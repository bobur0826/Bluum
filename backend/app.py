import io
import json
import os
from datetime import date, datetime, timedelta

import qrcode
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from prompts import (
    SummaryGenerationError,
    check_medication_interactions,
    generate_prep_questions,
    generate_summary,
    generate_chat_reply,
    generate_test_result_explanation,
)
from auth import StaffUser, login_manager
from models import (
    OTP_TTL_MINUTES,
    Appointment,
    AppointmentSummary,
    CheckIn,
    DailyLog,
    Document,
    FoodLog,
    GOAL_TARGETS,
    Habit,
    HabitCheckIn,
    Medication,
    Patient,
    Prescription,
    SleepLog,
    Staff,
    StaffNote,
    TestResult,
    db,
)
from share_card import generate_streak_card
from sms import send_sms
from symptom_model import predict_diseases
from nutrition import analyze_food_photo, generate_calories_burned, generate_food_estimate
from telegram_auth import verify_init_data
from translations import t as translate
from uploads import save_upload, upload_path


def create_app():
    app = Flask(__name__)

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        if os.environ.get("FLASK_DEBUG", "1") != "1":
            raise RuntimeError("SECRET_KEY must be set in production (see .env.example)")
        secret_key = "dev-secret-change-me"  # local dev only, never used when FLASK_DEBUG=0
    app.config["SECRET_KEY"] = secret_key

    # Bot token from @BotFather - required for /telegram/auth to verify Mini App
    # launches. Unset is fine outside the Telegram flow (rest of the app works either way).
    app.config["TELEGRAM_BOT_TOKEN"] = os.environ.get("TELEGRAM_BOT_TOKEN")

    # Falls back to local SQLite for dev; set DATABASE_URL (e.g. postgresql://...) in production.
    database_url = os.environ.get("DATABASE_URL", "sqlite:///bluum.db")
    # Force the pure-Python pg8000 driver instead of psycopg2's C extension: psycopg2(-binary)
    # needs the system libpq shared library, which isn't reliably present in every deploy
    # environment (e.g. it's missing on Railway's build image) - pg8000 has no such dependency.
    if database_url.startswith("postgres://"):
        database_url = "postgresql+pg8000://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+pg8000://" + database_url[len("postgresql://"):]
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Cookies only over HTTPS once actually deployed (FLASK_DEBUG=0); allows plain HTTP for local dev.
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_DEBUG", "1") != "1"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Trust X-Forwarded-* headers from the Nginx reverse proxy in front of this app,
    # so Flask sees the real client scheme (https) instead of the internal http hop.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()

    def get_patient_or_404(token):
        return Patient.query.filter_by(token=token).first_or_404()

    @app.before_request
    def _strip_stray_trailing_backslash():
        # Some Telegram clients (observed on Desktop) append a literal trailing
        # backslash to the Mini App URL when loading it, e.g. "/telegram\" instead
        # of "/telegram" - a client-side quirk, not something a URL can be typed
        # to avoid. Redirect it to the clean path rather than 404ing on it.
        if request.path.endswith("\\"):
            clean_path = request.path.rstrip("\\") or "/"
            qs = request.query_string.decode()
            return redirect(clean_path + (f"?{qs}" if qs else ""), code=308)

    @app.context_processor
    def inject_lang():
        lang = session.get("lang", "en")
        return {"current_lang": lang, "t": lambda key: translate(key, lang)}

    @app.get("/set-lang/<lang>")
    def set_lang(lang):
        if lang in ("en", "uz", "ru"):
            session["lang"] = lang
        return redirect(request.referrer or url_for("home"))

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
        # Straight into signup/login - no more "I'm a patient / I'm hospital
        # staff" chooser landing page. Staff can still reach their login
        # directly at /staff/login if needed for a hospital-side demo.
        return render_template("onboarding.html")

    @app.get("/patient/new")
    def patient_onboarding():
        return render_template("onboarding.html")

    @app.get("/patient/new/form")
    def patient_form():
        return render_template("patient_form.html")

    def _send_otp_and_redirect(patient, next_mode):
        code = patient.generate_otp()
        db.session.commit()
        sent = send_sms(patient.phone, f"Your Bluum verification code is {code}. It expires in {OTP_TTL_MINUTES} minutes.")
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

    # ---------------------------------------------------------------- Telegram Mini App login

    @app.get("/telegram")
    def telegram_launch():
        """Entry point opened by the bot's Web App button. Renders a near-blank page
        whose only job is to hand Telegram's initData to /telegram/auth and then jump
        straight to the real dashboard - the user never sees this page render."""
        return render_template("telegram_launch.html")

    @app.post("/telegram/auth")
    def telegram_auth_submit():
        bot_token = app.config.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return jsonify(error="Telegram login is not configured on this server"), 503

        init_data = request.form.get("init_data", "")
        tg_user = verify_init_data(init_data, bot_token)
        if not tg_user:
            return jsonify(error="Could not verify Telegram identity"), 401

        telegram_user_id = tg_user.get("id")
        if not telegram_user_id:
            return jsonify(error="Malformed Telegram user data"), 400

        patient = Patient.query.filter_by(telegram_user_id=telegram_user_id).first()
        if not patient:
            display_name = " ".join(
                part for part in (tg_user.get("first_name"), tg_user.get("last_name")) if part
            ).strip() or tg_user.get("username") or "Bluum user"
            patient = Patient(
                full_name=display_name,
                telegram_user_id=telegram_user_id,
                telegram_username=tg_user.get("username"),
                phone_verified=True,  # Telegram's own signature is the verification here
            )
            db.session.add(patient)
            db.session.commit()

        session["patient_token"] = patient.token
        return jsonify(redirect=url_for("patient_dashboard", token=patient.token))

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
        habits = Habit.query.filter_by(patient_token=token, active=True).order_by(Habit.created_at).all()
        sleep_streak = SleepLog.current_streak_for(token)
        today_log = DailyLog.today_for(token)

        hour = datetime.now().hour
        greeting = "good_morning" if hour < 12 else "good_afternoon" if hour < 18 else "good_evening"

        plan = [
            {
                "label": "steps", "icon": "👟", "value": today_log.steps if today_log and today_log.steps else 0,
                "target": DailyLog.STEPS_TARGET, "unit": "steps", "tag": "today",
            },
            {
                "label": "water", "icon": "💧", "value": today_log.water_cups if today_log and today_log.water_cups else 0,
                "target": DailyLog.WATER_TARGET, "unit": "cups", "tag": "today",
            },
            {
                "label": "active_minutes", "icon": "⏱", "value": today_log.active_minutes if today_log and today_log.active_minutes else 0,
                "target": DailyLog.ACTIVE_MINUTES_TARGET, "unit": "min", "tag": "today",
            },
        ]
        for p in plan:
            p["pct"] = min(round(p["value"] / p["target"] * 100), 100) if p["target"] else 0

        return render_template(
            "patient_dashboard.html", patient=patient, habits=habits, sleep_streak=sleep_streak,
            greeting=greeting, plan=plan,
        )

    @app.get("/patients/<token>/records")
    def records_hub(token):
        patient = get_patient_or_404(token)
        medications = Medication.query.filter_by(patient_token=token, active=True).order_by(Medication.created_at).all()
        prescriptions = Prescription.query.filter_by(patient_token=token).order_by(Prescription.created_at.desc()).all()
        results = TestResult.query.filter_by(patient_token=token).order_by(TestResult.uploaded_at.desc()).all()
        documents = Document.query.filter_by(patient_token=token).order_by(Document.uploaded_at.desc()).all()
        return render_template(
            "records_hub.html", patient=patient, medications=medications, prescriptions=prescriptions,
            results=results, documents=documents,
        )

    @app.get("/patients/<token>/visits")
    def visits_hub(token):
        patient = get_patient_or_404(token)
        return render_template("visits_hub.html", patient=patient, **_visits_hub_context(token))

    @app.get("/patients/<token>/history")
    def patient_history(token):
        patient = get_patient_or_404(token)
        query = AppointmentSummary.query.filter_by(patient_token=token)
        if not current_user.is_authenticated:
            query = query.filter_by(status="approved")
        summaries = query.order_by(AppointmentSummary.created_at.desc()).all()
        return render_template("history.html", patient=patient, summaries=summaries)

    # ---------------------------------------------------------------- progressive profile

    def _translated_progressive_question(patient):
        field, question = patient.next_progressive_question()
        if field:
            question = translate(f"progressive_q_{field}", session.get("lang", "en"))
        return field, question

    @app.get("/patients/<token>/profile")
    def profile_overview(token):
        patient = get_patient_or_404(token)
        field, question = _translated_progressive_question(patient)
        habits = Habit.query.filter_by(patient_token=token, active=True).order_by(Habit.created_at).all()
        sleep_streak = SleepLog.current_streak_for(token)
        total_streak_days = sum(h.current_streak() for h in habits) + sleep_streak
        return render_template(
            "profile_overview.html", patient=patient, next_question=question, habits=habits,
            sleep_streak=sleep_streak, total_streak_days=total_streak_days,
        )

    @app.get("/patients/<token>/profile/next-question")
    def profile_next_question(token):
        patient = get_patient_or_404(token)
        field, question = _translated_progressive_question(patient)
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
        if patient.phone:
            send_sms(patient.phone, "Bluum: your visit summary is ready. Open the app to see what your doctor said.")
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
        return redirect(url_for("records_hub", token=token))

    @app.post("/patients/<token>/medications/<int:med_id>/delete")
    def delete_medication(token, med_id):
        med = Medication.query.filter_by(id=med_id, patient_token=token).first_or_404()
        med.active = False
        db.session.commit()
        return redirect(url_for("records_hub", token=token))

    # ---------------------------------------------------------------- habit streaks

    @app.get("/patients/<token>/habits")
    def list_habits(token):
        patient = get_patient_or_404(token)
        habits = Habit.query.filter_by(patient_token=token, active=True).order_by(Habit.created_at).all()

        # Aggregate week strip: a day counts as "active" if any habit or sleep was logged.
        habit_days = {c.checkin_date for h in habits for c in h.checkins}
        sleep_days = {r.log_date for r in SleepLog.query.filter_by(patient_token=token).all()}
        active_days = habit_days | sleep_days
        today = date.today()
        week = [
            {"date": d, "dow": d.strftime("%a")[0], "day": d.day, "hit": d in active_days, "today": d == today}
            for d in (today - timedelta(days=i) for i in range(6, -1, -1))
        ]

        sleep_streak = SleepLog.current_streak_for(token)
        habit_streaks_list = [h.current_streak() for h in habits]
        best_habit_streak = max(habit_streaks_list) if habit_streaks_list else 0
        best_streak = max(habit_streaks_list + [sleep_streak]) if habit_streaks_list else sleep_streak
        checked_in_today = sum(1 for h in habits if h.checked_in_today())

        last_sleep = SleepLog.query.filter_by(patient_token=token).order_by(SleepLog.log_date.desc()).first()
        today_log = DailyLog.today_for(token)
        today_food = FoodLog.today_totals(token)

        return render_template(
            "habits.html", patient=patient, week=week, best_streak=best_streak,
            checked_in_today=checked_in_today, total_habits=len(habits), sleep_streak=sleep_streak,
            last_sleep=last_sleep, today_log=today_log, DailyLog=DailyLog, best_habit_streak=best_habit_streak,
            today_food=today_food,
        )

    @app.get("/patients/<token>/day/<day>")
    def day_detail(token, day):
        patient = get_patient_or_404(token)
        try:
            d = date.fromisoformat(day)
        except ValueError:
            abort(404)
        habits = Habit.query.filter_by(patient_token=token, active=True).all()
        done_habits = [h for h in habits if any(c.checkin_date == d for c in h.checkins)]
        sleep = SleepLog.query.filter_by(patient_token=token, log_date=d).first()
        daily = DailyLog.query.filter_by(patient_token=token, log_date=d).first()
        return render_template(
            "day_detail.html", patient=patient, day=d, done_habits=done_habits, sleep=sleep, daily=daily
        )

    @app.post("/patients/<token>/daily-log")
    def log_daily_activity(token):
        get_patient_or_404(token)

        def _int(name):
            val = request.form.get(name, "").strip()
            return int(val) if val.isdigit() else None

        today_log = DailyLog.today_for(token)
        if not today_log:
            today_log = DailyLog(patient_token=token)
            db.session.add(today_log)
        for field in ("steps", "active_calories", "active_minutes", "water_cups"):
            value = _int(field)
            if value is not None:
                setattr(today_log, field, value)
        db.session.commit()
        return redirect(url_for("list_habits", token=token))

    @app.get("/patients/<token>/habits/streaks")
    def habit_streaks(token):
        patient = get_patient_or_404(token)
        habits = Habit.query.filter_by(patient_token=token, active=True).order_by(Habit.created_at).all()
        return render_template("habit_streaks.html", patient=patient, habits=habits)

    @app.post("/patients/<token>/habits")
    def add_habit(token):
        patient = get_patient_or_404(token)
        name = request.form.get("name", "").strip()
        if not name:
            abort(400, "name is required")
        db.session.add(Habit(patient_token=token, name=name, kind=request.form.get("kind", "custom")))
        db.session.commit()
        return redirect(url_for("habit_streaks", token=token))

    @app.post("/patients/<token>/habits/<int:habit_id>/checkin")
    def checkin_habit(token, habit_id):
        habit = Habit.query.filter_by(id=habit_id, patient_token=token).first_or_404()
        if not habit.checked_in_today():
            db.session.add(HabitCheckIn(habit_id=habit.id))
            db.session.commit()
        return redirect(url_for("habit_streaks", token=token))

    @app.post("/patients/<token>/habits/<int:habit_id>/edit")
    def edit_habit(token, habit_id):
        habit = Habit.query.filter_by(id=habit_id, patient_token=token).first_or_404()
        name = request.form.get("name", "").strip()
        if name:
            habit.name = name
        habit.kind = request.form.get("kind", habit.kind)
        db.session.commit()
        return redirect(url_for("habit_streaks", token=token))

    @app.post("/patients/<token>/habits/<int:habit_id>/delete")
    def delete_habit(token, habit_id):
        # A real, permanent delete (not just deactivating) - the button this
        # is wired to says "Delete" and confirms first, so it should mean it.
        habit = Habit.query.filter_by(id=habit_id, patient_token=token).first_or_404()
        HabitCheckIn.query.filter_by(habit_id=habit.id).delete()
        db.session.delete(habit)
        db.session.commit()
        return redirect(url_for("habit_streaks", token=token))

    @app.get("/patients/<token>/habits/<int:habit_id>/card.png")
    def habit_share_card(token, habit_id):
        habit = Habit.query.filter_by(id=habit_id, patient_token=token).first_or_404()
        buf = generate_streak_card(habit.name, habit.current_streak(), subtitle="on Bluum")
        return send_file(buf, mimetype="image/png")

    # ---------------------------------------------------------------- nutrition
    # Calorie/macro tracking from a food photo, and a daily calories-burned
    # figure. Both are SIMULATED for now (see nutrition.py) - no real vision
    # model or wearable integration wired up yet.

    @app.get("/patients/<token>/nutrition")
    def nutrition_page(token):
        patient = get_patient_or_404(token)
        today = date.today()
        logs = FoodLog.query.filter_by(patient_token=token, log_date=today).order_by(FoodLog.created_at.desc()).all()
        totals = FoodLog.today_totals(token)
        targets = GOAL_TARGETS.get(patient.fitness_goal, GOAL_TARGETS["staying_in_shape"])
        burned = generate_calories_burned(token, today)
        return render_template(
            "nutrition.html", patient=patient, logs=logs, totals=totals, targets=targets,
            burned=burned, net_calories=totals["calories"] - burned,
        )

    @app.post("/patients/<token>/nutrition/goal")
    def set_fitness_goal(token):
        patient = get_patient_or_404(token)
        goal = request.form.get("goal")
        if goal in GOAL_TARGETS:
            patient.fitness_goal = goal
            db.session.commit()
        return redirect(url_for("nutrition_page", token=token))

    @app.post("/patients/<token>/nutrition/log")
    def add_food_log(token):
        get_patient_or_404(token)
        photo = request.files.get("photo")
        stored_filename = None
        estimate = None
        if photo and photo.filename:
            image_bytes = photo.read()
            photo.seek(0)
            estimate = analyze_food_photo(image_bytes)
            stored_filename, _original = save_upload(photo, token)
        if estimate is None:
            # No photo, or the real vision call wasn't available/failed -
            # fall back to a plausible generated placeholder rather than a
            # blank log or a hard error.
            seed = stored_filename or f"{token}:{datetime.utcnow().isoformat()}"
            estimate = generate_food_estimate(seed)
        db.session.add(FoodLog(
            patient_token=token,
            description=estimate["description"],
            photo_filename=stored_filename,
            calories=estimate["calories"],
            protein_g=estimate["protein_g"],
            fat_g=estimate["fat_g"],
            carbs_g=estimate["carbs_g"],
        ))
        db.session.commit()
        return redirect(url_for("nutrition_page", token=token))

    @app.post("/patients/<token>/nutrition/log/<int:log_id>/delete")
    def delete_food_log(token, log_id):
        entry = FoodLog.query.filter_by(id=log_id, patient_token=token).first_or_404()
        db.session.delete(entry)
        db.session.commit()
        return redirect(url_for("nutrition_page", token=token))

    @app.get("/patients/<token>/nutrition/log/<int:log_id>/photo")
    def food_log_photo(token, log_id):
        entry = FoodLog.query.filter_by(id=log_id, patient_token=token).first_or_404()
        if not entry.photo_filename:
            abort(404)
        return send_file(upload_path(token, entry.photo_filename))

    # ---------------------------------------------------------------- sleep streaks

    @app.get("/patients/<token>/sleep")
    def sleep_log(token):
        patient = get_patient_or_404(token)
        logs = SleepLog.query.filter_by(patient_token=token).order_by(SleepLog.log_date.desc()).limit(14).all()
        streak = SleepLog.current_streak_for(token)
        logged_today = any(l.log_date == date.today() for l in logs)
        week = SleepLog.week_strip_for(token)
        return render_template(
            "sleep.html", patient=patient, logs=logs, streak=streak, logged_today=logged_today, week=week
        )

    @app.post("/patients/<token>/sleep")
    def add_sleep_log(token):
        get_patient_or_404(token)
        sleep_time = request.form.get("sleep_time") or None
        wake_time = request.form.get("wake_time") or None
        hours = None
        if sleep_time and wake_time:
            try:
                s_h, s_m = (int(x) for x in sleep_time.split(":"))
                w_h, w_m = (int(x) for x in wake_time.split(":"))
                mins = (w_h * 60 + w_m) - (s_h * 60 + s_m)
                if mins <= 0:
                    mins += 24 * 60
                hours = round(mins / 60, 1)
            except ValueError:
                hours = None
        existing = SleepLog.query.filter_by(patient_token=token, log_date=date.today()).first()
        if existing:
            existing.sleep_time, existing.wake_time, existing.hours = sleep_time, wake_time, hours
        else:
            db.session.add(SleepLog(patient_token=token, sleep_time=sleep_time, wake_time=wake_time, hours=hours))
        db.session.commit()
        return redirect(url_for("list_habits", token=token))

    @app.get("/patients/<token>/sleep/card.png")
    def sleep_share_card(token):
        get_patient_or_404(token)
        streak = SleepLog.current_streak_for(token)
        buf = generate_streak_card("Sleep schedule", streak, subtitle="on Bluum")
        return send_file(buf, mimetype="image/png")

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
        return redirect(url_for("records_hub", token=token))

    @app.get("/patients/<token>/documents/<int:doc_id>/download")
    def download_document(token, doc_id):
        doc = Document.query.filter_by(id=doc_id, patient_token=token).first_or_404()
        return send_file(upload_path(token, doc.filename), download_name=doc.original_filename, as_attachment=True)

    # ---------------------------------------------------------------- symptom checker

    EXAMPLE_SYMPTOM_QUESTIONS = [
        "I have a headache and a slight fever",
        "My stomach hurts after eating",
        "I've had a persistent cough for a week",
        "Sharp pain in my lower back",
    ]

    def _chat_key(token):
        return f"symptom_chat_{token}"

    @app.get("/patients/<token>/symptom-checker")
    def symptom_checker_form(token):
        patient = get_patient_or_404(token)
        chat = session.get(_chat_key(token), [])
        return render_template(
            "symptom_checker.html", patient=patient, chat=chat, examples=EXAMPLE_SYMPTOM_QUESTIONS
        )

    def build_chat_context(patient, token):
        habits = Habit.query.filter_by(patient_token=token, active=True).all()
        habit_lines = [f"{h.name} (day {h.current_streak()} of their streak)" for h in habits] or None

        last_sleep = SleepLog.query.filter_by(patient_token=token).order_by(SleepLog.log_date.desc()).first()
        sleep_text = f"{last_sleep.hours}h last night" if last_sleep and last_sleep.hours else None

        today_log = DailyLog.today_for(token)
        today_bits = []
        if today_log:
            if today_log.steps:
                today_bits.append(f"{today_log.steps} steps")
            if today_log.active_calories:
                today_bits.append(f"{today_log.active_calories} active calories burned")
            if today_log.water_cups:
                today_bits.append(f"{today_log.water_cups} cups of water")
        today_text = ", ".join(today_bits) or None

        rx = Prescription.query.filter_by(patient_token=token).order_by(Prescription.created_at.desc()).limit(5).all()
        rx_text = "; ".join(f"{r.drug_name} {r.dosage}" for r in rx) or None

        results = TestResult.query.filter_by(patient_token=token).order_by(TestResult.uploaded_at.desc()).limit(3).all()
        results_text = "; ".join(f"{r.risk_level or 'routine'} result from {r.uploaded_at.strftime('%Y-%m-%d')}" for r in results) or None

        return {
            "allergies": patient.allergies,
            "chronic_conditions": patient.chronic_conditions,
            "current_medications": patient.current_medications,
            "prescriptions": rx_text,
            "habits": "; ".join(habit_lines) if habit_lines else None,
            "last_sleep": sleep_text,
            "today_activity": today_text,
            "recent_results": results_text,
        }

    @app.post("/patients/<token>/symptom-checker")
    def symptom_checker_submit(token):
        patient = get_patient_or_404(token)
        symptoms = request.form.get("symptoms", "").strip()
        if not symptoms:
            return jsonify({"error": "Message is empty"}), 400

        chat = session.get(_chat_key(token), [])
        history = [
            {"role": "Patient" if m["role"] == "user" else "Bluum",
             "text": m.get("text") or m.get("explanation_en") or ""}
            for m in chat
        ]
        chat.append({"role": "user", "text": symptoms})
        try:
            result = generate_chat_reply(symptoms, history, build_chat_context(patient, token))
            predictions = predict_diseases(symptoms) if result["is_symptom_report"] else []
            bot_msg = {
                "role": "bot", "is_symptom_report": result["is_symptom_report"],
                "urgency": result["urgency"], "specialist": result["specialist"],
                "explanation_uz": result["explanation_uz"], "explanation_ru": result["explanation_ru"],
                "explanation_en": result["explanation_en"], "predictions": predictions,
            }
            chat.append(bot_msg)
            session[_chat_key(token)] = chat
            return jsonify(bot_msg)
        except SummaryGenerationError as e:
            bot_msg = {"role": "bot", "error": str(e)}
            chat.append(bot_msg)
            session[_chat_key(token)] = chat
            return jsonify(bot_msg), 502

    @app.post("/patients/<token>/symptom-checker/clear")
    def symptom_checker_clear(token):
        session.pop(_chat_key(token), None)
        return redirect(url_for("symptom_checker_form", token=token))

    # ---------------------------------------------------------------- appointment prep

    @app.get("/patients/<token>/appointments/prepare")
    def prep_form(token):
        return redirect(url_for("visits_hub", token=token))

    def _visits_hub_context(token):
        appointments = Appointment.query.filter_by(patient_token=token).order_by(Appointment.requested_at).all()
        summaries = AppointmentSummary.query.filter_by(patient_token=token, status="approved").order_by(
            AppointmentSummary.created_at.desc()
        ).all()
        return {"appointments": appointments, "summaries": summaries}

    @app.post("/patients/<token>/appointments/prepare")
    def prep_submit(token):
        patient = get_patient_or_404(token)
        reason = request.form.get("reason", "").strip()
        if not reason:
            abort(400, "reason is required")
        try:
            ai = generate_prep_questions(reason, patient.chronic_conditions, patient.current_medications)
        except SummaryGenerationError as e:
            return render_template(
                "visits_hub.html", patient=patient, error=str(e), reason=reason, **_visits_hub_context(token)
            ), 502
        questions_uz = json.loads(ai["questions_uz"])
        questions_ru = json.loads(ai["questions_ru"])
        return render_template(
            "visits_hub.html", patient=patient, reason=reason, questions_uz=questions_uz, questions_ru=questions_ru,
            **_visits_hub_context(token)
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
        return redirect(url_for("visits_hub", token=token))

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
                if not patient or not patient.phone:
                    continue
                send_sms(patient.phone, f"Bluum: time to take {med.name} ({med.dosage or 'as prescribed'}).")
                med.last_reminder_sent = now
            db.session.commit()

    def send_follow_up_reminders():
        with app.app_context():
            tomorrow = date.today() + timedelta(days=1)
            due = AppointmentSummary.query.filter_by(follow_up_date=tomorrow, follow_up_sms_sent=False).all()
            for summary in due:
                patient = Patient.query.filter_by(token=summary.patient_token).first()
                if not patient or not patient.phone:
                    continue
                send_sms(patient.phone, "Bluum: reminder — you have a follow-up appointment tomorrow.")
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
    app.run(host="0.0.0.0", port=5001, debug=os.environ.get("FLASK_DEBUG", "1") == "1")
