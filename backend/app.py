import io
import json
import os
from datetime import date, datetime, timedelta

import qrcode
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

load_dotenv()

from prompts import (
    SummaryGenerationError,
    check_medication_interactions,
    generate_prep_questions,
    generate_summary,
    generate_symptom_check,
    generate_test_result_explanation,
)
from auth import StaffUser, login_manager
from models import (
    OTP_TTL_MINUTES,
    Appointment,
    AppointmentSummary,
    CheckIn,
    Document,
    Medication,
    Patient,
    Prescription,
    Staff,
    StaffNote,
    TestResult,
    db,
)
from sms import send_sms
from symptom_model import predict_diseases
from uploads import save_upload, upload_path


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///medpass.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "dev-secret-change-me"  # session signing; override in production
    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()

    def get_patient_or_404(token):
        return Patient.query.filter_by(token=token).first_or_404()

    @app.context_processor
    def inject_notifications():
        # Staff identity takes priority: a browser can hold both a patient session and a
        # staff login at once (e.g. a doctor who also registered as a patient), and whichever
        # role the current page is actually rendering for should win - staff pages always
        # authenticate via current_user, so check that first rather than a leftover session key.
        items = []
        if current_user.is_authenticated:
            pending = (
                AppointmentSummary.query.filter_by(status="pending_review")
                .order_by(AppointmentSummary.created_at.desc())
                .limit(5)
                .all()
            )
            names = {p.token: p.full_name for p in Patient.query.all()}
            items = [
                {
                    "text": f"{names.get(s.patient_token, 'Patient')} — awaiting review",
                    "url": url_for("review_summary", token=s.patient_token, summary_id=s.id),
                }
                for s in pending
            ]
        elif session.get("patient_token"):
            patient_token = session["patient_token"]
            unseen = (
                AppointmentSummary.query.filter_by(
                    patient_token=patient_token, status="approved", patient_viewed=False
                )
                .order_by(AppointmentSummary.created_at.desc())
                .limit(5)
                .all()
            )
            items = [
                {
                    "text": f"Visit summary ready — {s.created_at.strftime('%b %d')}",
                    "url": url_for("view_summary", token=patient_token, summary_id=s.id),
                }
                for s in unseen
            ]
        return dict(notification_items=items, notification_count=len(items))

    # ---------------------------------------------------------------- home / patient profile

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.get("/patient/new")
    def patient_form():
        return render_template("patient_form.html")

    def _send_otp_and_redirect(patient, next_mode):
        code = patient.generate_otp()
        db.session.commit()
        sent = send_sms(patient.phone, f"Your MedPass verification code is {code}. It expires in {OTP_TTL_MINUTES} minutes.")
        # If SMS isn't configured (no Eskiz creds), show the code directly so the flow
        # stays testable/demoable without real SMS delivery.
        dev_code = None if sent else code
        return redirect(url_for("patient_verify_form", phone=patient.phone, next=next_mode, dev_code=dev_code))

    @app.post("/patients")
    def create_patient():
        form = request.form
        if not form.get("full_name") or not form.get("dob") or not form.get("phone"):
            abort(400, "full_name, dob, and phone are required")
        if Patient.query.filter_by(phone=form["phone"]).first():
            return render_template(
                "patient_form.html", error="An account with that phone number already exists"
            ), 409

        patient = Patient(full_name=form["full_name"], dob=form["dob"], phone=form["phone"])
        db.session.add(patient)
        db.session.commit()
        return _send_otp_and_redirect(patient, "register")

    @app.get("/patient/login")
    def patient_login_form():
        return render_template("patient_login.html")

    @app.post("/patient/login")
    def patient_login():
        phone = request.form.get("phone", "").strip()
        patient = Patient.query.filter_by(phone=phone).first()
        if not patient:
            return render_template("patient_login.html", error="No account found for that phone number"), 404
        return _send_otp_and_redirect(patient, "login")

    @app.get("/patient/verify")
    def patient_verify_form():
        return render_template(
            "patient_verify.html",
            phone=request.args.get("phone"),
            next_mode=request.args.get("next"),
            dev_code=request.args.get("dev_code"),
        )

    @app.post("/patient/verify")
    def patient_verify_submit():
        phone = request.form.get("phone", "")
        code = request.form.get("code", "").strip()
        next_mode = request.form.get("next")
        patient = Patient.query.filter_by(phone=phone).first()

        if not patient or not patient.verify_otp(code):
            return render_template(
                "patient_verify.html", phone=phone, next_mode=next_mode, error="Invalid or expired code"
            ), 401

        db.session.commit()
        session["patient_token"] = patient.token
        if next_mode == "register":
            return redirect(url_for("show_qr", token=patient.token))
        return redirect(url_for("patient_dashboard", token=patient.token))

    @app.post("/patient/verify/resend")
    def patient_verify_resend():
        phone = request.form.get("phone", "")
        next_mode = request.form.get("next")
        patient = Patient.query.filter_by(phone=phone).first_or_404()
        return _send_otp_and_redirect(patient, next_mode)

    @app.get("/patient/logout")
    def patient_logout():
        session.pop("patient_token", None)
        return redirect(url_for("home"))

    @app.get("/patients/<token>/qr")
    def show_qr(token):
        patient = get_patient_or_404(token)
        return render_template("qr_result.html", patient=patient)

    @app.get("/patients/<token>/qr.png")
    def qr_image(token):
        patient = get_patient_or_404(token)
        reception_url = url_for("reception_view", token=patient.token, _external=True)
        img = qrcode.make(reception_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    @app.get("/patients/<token>/dashboard")
    def patient_dashboard(token):
        patient = get_patient_or_404(token)
        return render_template("patient_dashboard.html", patient=patient)

    @app.get("/patients/<token>/records")
    def records_hub(token):
        patient = get_patient_or_404(token)
        return render_template("records_hub.html", patient=patient)

    @app.get("/patients/<token>/visits")
    def visits_hub(token):
        patient = get_patient_or_404(token)
        return render_template("visits_hub.html", patient=patient)

    @app.get("/patients/<token>/history")
    def patient_history(token):
        patient = get_patient_or_404(token)
        query = AppointmentSummary.query.filter_by(patient_token=token)
        if not current_user.is_authenticated:
            query = query.filter_by(status="approved")
        summaries = query.order_by(AppointmentSummary.created_at.desc()).all()
        return render_template("history.html", patient=patient, summaries=summaries)

    # ---------------------------------------------------------------- progressive profile

    @app.get("/patients/<token>/profile")
    def profile_overview(token):
        patient = get_patient_or_404(token)
        field, question = patient.next_progressive_question()
        return render_template("profile_overview.html", patient=patient, next_question=question)

    @app.get("/patients/<token>/profile/next-question")
    def profile_next_question(token):
        patient = get_patient_or_404(token)
        field, question = patient.next_progressive_question()
        return render_template("profile_question.html", patient=patient, field=field, question=question)

    @app.post("/patients/<token>/profile/next-question")
    def profile_answer_question(token):
        patient = get_patient_or_404(token)
        field = request.form.get("field")
        valid_fields = {f for f, _ in Patient.PROGRESSIVE_FIELDS}
        if field not in valid_fields:
            abort(400, "unknown field")
        value = request.form.get("value", "").strip()
        if value:
            setattr(patient, field, value)
            db.session.commit()
        return redirect(url_for("profile_next_question", token=token))

    # ---------------------------------------------------------------- staff auth

    @app.get("/staff/register")
    def staff_register_form():
        return render_template("staff_register.html")

    @app.post("/staff/register")
    def staff_register():
        form = request.form
        if not form.get("full_name") or not form.get("email") or not form.get("password"):
            return render_template("staff_register.html", error="All fields are required"), 400
        if Staff.query.filter_by(email=form["email"]).first():
            return render_template("staff_register.html", error="An account with that email already exists"), 409

        staff = Staff(full_name=form["full_name"], email=form["email"], hospital_name=form.get("hospital_name"))
        staff.set_password(form["password"])
        db.session.add(staff)
        db.session.commit()
        login_user(StaffUser(staff))
        return redirect(url_for("staff_lookup"))

    @app.get("/staff/login")
    def staff_login_form():
        return render_template("staff_login.html")

    @app.post("/staff/login")
    def staff_login_submit():
        form = request.form
        staff = Staff.query.filter_by(email=form.get("email")).first()
        if not staff or not staff.check_password(form.get("password", "")):
            return render_template("staff_login.html", error="Invalid email or password"), 401
        login_user(StaffUser(staff))
        return redirect(url_for("staff_lookup"))

    @app.get("/staff/logout")
    @login_required
    def staff_logout():
        logout_user()
        return redirect(url_for("home"))

    # ---------------------------------------------------------------- staff lookup / reception

    @app.get("/staff")
    @login_required
    def staff_lookup():
        return render_template("staff.html")

    @app.post("/staff/lookup")
    @login_required
    def staff_lookup_submit():
        token = request.form.get("token", "").strip()
        if not Patient.query.filter_by(token=token).first():
            return render_template("staff.html", error="No patient found for that code"), 404
        db.session.add(CheckIn(patient_token=token, staff_id=int(current_user.id)))
        db.session.commit()
        return redirect(url_for("reception_view", token=token))

    @app.get("/reception/<token>")
    @login_required
    def reception_view(token):
        patient = get_patient_or_404(token)
        return render_template("reception_view.html", patient=patient)

    # ---------------------------------------------------------------- AI appointment summary

    @app.get("/patients/<token>/summary/new")
    @login_required
    def new_summary_form(token):
        patient = get_patient_or_404(token)
        return render_template("summary_form.html", patient=patient)

    @app.post("/patients/<token>/summary")
    @login_required
    def create_summary(token):
        patient = get_patient_or_404(token)
        notes = request.form.get("doctor_notes", "").strip()
        if not notes:
            abort(400, "doctor_notes is required")

        try:
            generated = generate_summary(
                notes=notes,
                allergies=patient.allergies,
                current_medications=patient.current_medications,
                chronic_conditions=patient.chronic_conditions,
                language_register=patient.language_register,
            )
        except SummaryGenerationError as e:
            return render_template("summary_form.html", patient=patient, error=str(e), notes=notes), 502

        follow_up_date = request.form.get("follow_up_date") or None
        summary = AppointmentSummary(
            patient_token=patient.token,
            staff_id=int(current_user.id),
            doctor_notes=notes,
            follow_up_date=datetime.strptime(follow_up_date, "%Y-%m-%d").date() if follow_up_date else None,
            **generated,
        )
        db.session.add(summary)
        db.session.commit()
        return redirect(url_for("review_summary", token=patient.token, summary_id=summary.id))

    @app.get("/patients/<token>/summary/<int:summary_id>/review")
    @login_required
    def review_summary(token, summary_id):
        patient = get_patient_or_404(token)
        summary = AppointmentSummary.query.filter_by(id=summary_id, patient_token=token).first_or_404()
        return render_template("summary_review.html", patient=patient, summary=summary)

    @app.post("/patients/<token>/summary/<int:summary_id>/approve")
    @login_required
    def approve_summary(token, summary_id):
        summary = AppointmentSummary.query.filter_by(id=summary_id, patient_token=token).first_or_404()
        summary.status = "approved"
        db.session.commit()
        patient = get_patient_or_404(token)
        send_sms(patient.phone, "MedPass: your visit summary is ready. Open the app to see what your doctor said.")
        return redirect(url_for("reception_view", token=token))

    @app.get("/patients/<token>/summary/<int:summary_id>")
    def view_summary(token, summary_id):
        patient = get_patient_or_404(token)
        summary = AppointmentSummary.query.filter_by(id=summary_id, patient_token=token).first_or_404()
        if summary.status != "approved" and not current_user.is_authenticated:
            return render_template("summary_pending.html", patient=patient), 403
        if summary.status == "approved" and not current_user.is_authenticated and not summary.patient_viewed:
            summary.patient_viewed = True
            db.session.commit()
        return render_template("summary_result.html", patient=patient, summary=summary)

    @app.get("/patients/<token>/summary/<int:summary_id>/discharge")
    def discharge_view(token, summary_id):
        patient = get_patient_or_404(token)
        summary = AppointmentSummary.query.filter_by(id=summary_id, patient_token=token).first_or_404()
        if summary.status != "approved" and not current_user.is_authenticated:
            return render_template("summary_pending.html", patient=patient), 403
        steps_uz = json.loads(summary.daily_steps_uz) if summary.daily_steps_uz else []
        steps_ru = json.loads(summary.daily_steps_ru) if summary.daily_steps_ru else []
        return render_template("discharge.html", patient=patient, summary=summary, steps_uz=steps_uz, steps_ru=steps_ru)

    # ---------------------------------------------------------------- test results

    @app.get("/patients/<token>/results")
    def list_results(token):
        patient = get_patient_or_404(token)
        results = TestResult.query.filter_by(patient_token=token).order_by(TestResult.uploaded_at.desc()).all()
        return render_template("results_list.html", patient=patient, results=results)

    @app.get("/patients/<token>/results/upload")
    def upload_result_form(token):
        patient = get_patient_or_404(token)
        return render_template("results_upload.html", patient=patient)

    @app.post("/patients/<token>/results/upload")
    def upload_result(token):
        patient = get_patient_or_404(token)
        description = request.form.get("description", "").strip()
        file = request.files.get("file")
        if not description and not file:
            return render_template(
                "results_upload.html", patient=patient, error="Add a file or describe the result"
            ), 400

        filename = original = None
        if file and file.filename:
            filename, original = save_upload(file, patient.token)

        try:
            ai = generate_test_result_explanation(
                result_text=description or f"See attached file: {original}",
                chronic_conditions=patient.chronic_conditions,
            )
        except SummaryGenerationError as e:
            return render_template("results_upload.html", patient=patient, error=str(e)), 502

        result = TestResult(
            patient_token=token,
            filename=filename or "",
            original_filename=original or "(no file)",
            risk_level=ai["risk_level"],
            explanation_uz=ai["explanation_uz"],
            explanation_ru=ai["explanation_ru"],
        )
        db.session.add(result)
        db.session.commit()
        return redirect(url_for("view_result", token=token, result_id=result.id))

    @app.get("/patients/<token>/results/<int:result_id>")
    def view_result(token, result_id):
        patient = get_patient_or_404(token)
        result = TestResult.query.filter_by(id=result_id, patient_token=token).first_or_404()
        return render_template("result_detail.html", patient=patient, result=result)

    # ---------------------------------------------------------------- medication tracker

    @app.get("/patients/<token>/medications")
    def list_medications(token):
        patient = get_patient_or_404(token)
        meds = Medication.query.filter_by(patient_token=token, active=True).order_by(Medication.created_at).all()
        return render_template("medications.html", patient=patient, medications=meds)

    @app.post("/patients/<token>/medications")
    def add_medication(token):
        patient = get_patient_or_404(token)
        name = request.form.get("name", "").strip()
        if not name:
            abort(400, "name is required")
        db.session.add(
            Medication(
                patient_token=token,
                name=name,
                dosage=request.form.get("dosage"),
                schedule_times=request.form.get("schedule_times"),
            )
        )
        db.session.commit()
        return redirect(url_for("list_medications", token=token))

    @app.post("/patients/<token>/medications/<int:med_id>/delete")
    def delete_medication(token, med_id):
        med = Medication.query.filter_by(id=med_id, patient_token=token).first_or_404()
        med.active = False
        db.session.commit()
        return redirect(url_for("list_medications", token=token))

    # ---------------------------------------------------------------- document storage

    @app.get("/patients/<token>/documents")
    def list_documents(token):
        patient = get_patient_or_404(token)
        docs = Document.query.filter_by(patient_token=token).order_by(Document.uploaded_at.desc()).all()
        return render_template("documents.html", patient=patient, documents=docs)

    @app.post("/patients/<token>/documents")
    def upload_document(token):
        patient = get_patient_or_404(token)
        file = request.files.get("file")
        category = request.form.get("category", "other")
        if not file or not file.filename:
            return render_template("documents.html", patient=patient, documents=[], error="Choose a file"), 400
        filename, original = save_upload(file, token)
        db.session.add(Document(patient_token=token, category=category, filename=filename, original_filename=original))
        db.session.commit()
        return redirect(url_for("list_documents", token=token))

    @app.get("/patients/<token>/documents/<int:doc_id>/download")
    def download_document(token, doc_id):
        doc = Document.query.filter_by(id=doc_id, patient_token=token).first_or_404()
        return send_file(upload_path(token, doc.filename), download_name=doc.original_filename, as_attachment=True)

    # ---------------------------------------------------------------- symptom checker

    @app.get("/patients/<token>/symptom-checker")
    def symptom_checker_form(token):
        patient = get_patient_or_404(token)
        return render_template("symptom_checker.html", patient=patient)

    @app.post("/patients/<token>/symptom-checker")
    def symptom_checker_submit(token):
        patient = get_patient_or_404(token)
        symptoms = request.form.get("symptoms", "").strip()
        if not symptoms:
            abort(400, "symptoms is required")
        try:
            result = generate_symptom_check(symptoms, patient.allergies, patient.chronic_conditions)
        except SummaryGenerationError as e:
            return render_template("symptom_checker.html", patient=patient, error=str(e), symptoms=symptoms), 502
        predictions = predict_diseases(symptoms)
        return render_template(
            "symptom_checker.html", patient=patient, result=result, symptoms=symptoms, predictions=predictions
        )

    # ---------------------------------------------------------------- appointment prep

    @app.get("/patients/<token>/appointments/prepare")
    def prep_form(token):
        patient = get_patient_or_404(token)
        return render_template("prep_questions.html", patient=patient)

    @app.post("/patients/<token>/appointments/prepare")
    def prep_submit(token):
        patient = get_patient_or_404(token)
        reason = request.form.get("reason", "").strip()
        if not reason:
            abort(400, "reason is required")
        try:
            ai = generate_prep_questions(reason, patient.chronic_conditions, patient.current_medications)
        except SummaryGenerationError as e:
            return render_template("prep_questions.html", patient=patient, error=str(e), reason=reason), 502
        questions_uz = json.loads(ai["questions_uz"])
        questions_ru = json.loads(ai["questions_ru"])
        return render_template(
            "prep_questions.html", patient=patient, reason=reason, questions_uz=questions_uz, questions_ru=questions_ru
        )

    # ---------------------------------------------------------------- appointment booking

    @app.get("/patients/<token>/appointments")
    def list_appointments(token):
        patient = get_patient_or_404(token)
        appts = Appointment.query.filter_by(patient_token=token).order_by(Appointment.requested_at).all()
        return render_template("appointments.html", patient=patient, appointments=appts)

    @app.post("/patients/<token>/appointments")
    def book_appointment(token):
        patient = get_patient_or_404(token)
        department = request.form.get("department", "").strip()
        requested_at = request.form.get("requested_at")
        if not department or not requested_at:
            abort(400, "department and requested_at are required")
        db.session.add(
            Appointment(
                patient_token=token,
                department=department,
                requested_at=datetime.strptime(requested_at, "%Y-%m-%dT%H:%M"),
            )
        )
        db.session.commit()
        return redirect(url_for("list_appointments", token=token))

    @app.get("/hospital/appointments")
    @login_required
    def hospital_appointments():
        appts = (
            Appointment.query.filter(Appointment.status == "requested")
            .order_by(Appointment.requested_at)
            .all()
        )
        patients_by_token = {p.token: p for p in Patient.query.all()}
        return render_template("hospital_appointments.html", appointments=appts, patients=patients_by_token)

    @app.post("/hospital/appointments/<int:appt_id>/confirm")
    @login_required
    def confirm_appointment(appt_id):
        appt = Appointment.query.get_or_404(appt_id)
        appt.status = "confirmed"
        db.session.commit()
        return redirect(url_for("hospital_appointments"))

    # ---------------------------------------------------------------- prescriptions

    @app.get("/patients/<token>/prescriptions")
    def list_prescriptions(token):
        patient = get_patient_or_404(token)
        rx = Prescription.query.filter_by(patient_token=token).order_by(Prescription.created_at.desc()).all()
        return render_template("prescriptions.html", patient=patient, prescriptions=rx)

    @app.get("/patients/<token>/prescriptions/new")
    @login_required
    def new_prescription_form(token):
        patient = get_patient_or_404(token)
        return render_template("prescription_form.html", patient=patient)

    @app.post("/patients/<token>/prescriptions")
    @login_required
    def create_prescription(token):
        patient = get_patient_or_404(token)
        drug_name = request.form.get("drug_name", "").strip()
        dosage = request.form.get("dosage", "").strip()
        if not drug_name or not dosage:
            abort(400, "drug_name and dosage are required")

        warning = None
        try:
            check = check_medication_interactions(
                drug_name, dosage, patient.current_medications, patient.allergies
            )
            if check["has_warning"]:
                warning = check["warning"]
        except SummaryGenerationError:
            pass  # interaction check is best-effort; missing API key shouldn't block prescribing

        db.session.add(
            Prescription(
                patient_token=token,
                staff_id=int(current_user.id),
                drug_name=drug_name,
                dosage=dosage,
                instructions=request.form.get("instructions"),
                duration=request.form.get("duration"),
                interaction_warning=warning,
            )
        )
        db.session.commit()
        return redirect(url_for("list_prescriptions", token=token))

    # ---------------------------------------------------------------- staff internal notes

    @app.get("/patients/<token>/notes")
    @login_required
    def list_staff_notes(token):
        patient = get_patient_or_404(token)
        notes = StaffNote.query.filter_by(patient_token=token).order_by(StaffNote.created_at.desc()).all()
        return render_template("staff_notes.html", patient=patient, notes=notes)

    @app.post("/patients/<token>/notes")
    @login_required
    def add_staff_note(token):
        note = request.form.get("note", "").strip()
        if not note:
            abort(400, "note is required")
        db.session.add(StaffNote(patient_token=token, staff_id=int(current_user.id), note=note))
        db.session.commit()
        return redirect(url_for("list_staff_notes", token=token))

    # ---------------------------------------------------------------- hospital dashboard

    @app.get("/hospital/dashboard")
    @login_required
    def hospital_dashboard():
        today_start = datetime.combine(date.today(), datetime.min.time())
        checkins_today = CheckIn.query.filter(CheckIn.created_at >= today_start).all()

        wait_times = []
        for c in checkins_today:
            first_summary = (
                AppointmentSummary.query.filter(
                    AppointmentSummary.patient_token == c.patient_token,
                    AppointmentSummary.created_at >= c.created_at,
                )
                .order_by(AppointmentSummary.created_at)
                .first()
            )
            if first_summary:
                wait_times.append((first_summary.created_at - c.created_at).total_seconds() / 60)

        avg_wait = round(sum(wait_times) / len(wait_times)) if wait_times else None
        bottleneck = None
        if wait_times and max(wait_times) > 45:
            bottleneck = f"{sum(1 for w in wait_times if w > 45)} patient(s) waited over 45 minutes today"

        return render_template(
            "dashboard.html",
            checkins_today=len(checkins_today),
            avg_wait=avg_wait,
            seen_today=len(wait_times),
            bottleneck=bottleneck,
        )

    # ---------------------------------------------------------------- background jobs

    def send_medication_reminders():
        with app.app_context():
            now = datetime.now()
            current_hhmm = now.strftime("%H:%M")
            meds = Medication.query.filter_by(active=True).all()
            for med in meds:
                if not med.schedule_times:
                    continue
                times = [t.strip() for t in med.schedule_times.split(",")]
                if current_hhmm not in times:
                    continue
                # avoid re-sending within the same minute if the job runs more than once
                if med.last_reminder_sent and med.last_reminder_sent.strftime("%Y-%m-%d %H:%M") == now.strftime("%Y-%m-%d %H:%M"):
                    continue
                patient = Patient.query.filter_by(token=med.patient_token).first()
                if not patient:
                    continue
                send_sms(patient.phone, f"MedPass: time to take {med.name} ({med.dosage or 'as prescribed'}).")
                med.last_reminder_sent = now
            db.session.commit()

    def send_follow_up_reminders():
        with app.app_context():
            tomorrow = date.today() + timedelta(days=1)
            due = AppointmentSummary.query.filter_by(follow_up_date=tomorrow, follow_up_sms_sent=False).all()
            for summary in due:
                patient = Patient.query.filter_by(token=summary.patient_token).first()
                if not patient:
                    continue
                send_sms(patient.phone, "MedPass: reminder — you have a follow-up appointment tomorrow.")
                summary.follow_up_sms_sent = True
            db.session.commit()

    # Guard against Flask's debug reloader starting two scheduler instances:
    # with the reloader, only the forked child process has WERKZEUG_RUN_MAIN set.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        scheduler = BackgroundScheduler()
        scheduler.add_job(send_medication_reminders, "interval", minutes=1, id="medication_reminders")
        scheduler.add_job(send_follow_up_reminders, "interval", hours=1, id="follow_up_reminders")
        scheduler.start()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
