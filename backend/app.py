import io

import qrcode
from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from ai_summary import SummaryGenerationError, generate_summary
from models import AppointmentSummary, Patient, db


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///medpass.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.get("/patient/new")
    def patient_form():
        return render_template("patient_form.html")

    @app.get("/staff")
    def staff_lookup():
        return render_template("staff.html")

    @app.post("/staff/lookup")
    def staff_lookup_submit():
        token = request.form.get("token", "").strip()
        if not Patient.query.filter_by(token=token).first():
            return render_template("staff.html", error="No patient found for that code"), 404
        return redirect(url_for("reception_view", token=token))

    @app.post("/patients")
    def create_patient():
        form = request.form
        if not form.get("full_name") or not form.get("dob") or not form.get("phone"):
            abort(400, "full_name, dob, and phone are required")

        patient = Patient(
            full_name=form["full_name"],
            dob=form["dob"],
            phone=form["phone"],
            blood_type=form.get("blood_type"),
            allergies=form.get("allergies"),
            chronic_conditions=form.get("chronic_conditions"),
            current_medications=form.get("current_medications"),
            emergency_contact_name=form.get("emergency_contact_name"),
            emergency_contact_phone=form.get("emergency_contact_phone"),
        )
        db.session.add(patient)
        db.session.commit()
        return redirect(url_for("show_qr", token=patient.token))

    @app.get("/patients/<token>/qr")
    def show_qr(token):
        patient = Patient.query.filter_by(token=token).first_or_404()
        return render_template("qr_result.html", patient=patient)

    @app.get("/patients/<token>/qr.png")
    def qr_image(token):
        patient = Patient.query.filter_by(token=token).first_or_404()
        reception_url = url_for("reception_view", token=patient.token, _external=True)
        img = qrcode.make(reception_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    @app.get("/reception/<token>")
    def reception_view(token):
        patient = Patient.query.filter_by(token=token).first_or_404()
        return render_template("reception_view.html", patient=patient)

    @app.get("/patients/<token>/summary/new")
    def new_summary_form(token):
        patient = Patient.query.filter_by(token=token).first_or_404()
        return render_template("summary_form.html", patient=patient)

    @app.post("/patients/<token>/summary")
    def create_summary(token):
        patient = Patient.query.filter_by(token=token).first_or_404()
        notes = request.form.get("doctor_notes", "").strip()
        if not notes:
            abort(400, "doctor_notes is required")

        try:
            generated = generate_summary(
                notes=notes,
                allergies=patient.allergies,
                current_medications=patient.current_medications,
                chronic_conditions=patient.chronic_conditions,
            )
        except SummaryGenerationError as e:
            return render_template("summary_form.html", patient=patient, error=str(e), notes=notes), 502

        summary = AppointmentSummary(patient_token=patient.token, doctor_notes=notes, **generated)
        db.session.add(summary)
        db.session.commit()
        return redirect(url_for("view_summary", token=patient.token, summary_id=summary.id))

    @app.get("/patients/<token>/summary/<int:summary_id>")
    def view_summary(token, summary_id):
        patient = Patient.query.filter_by(token=token).first_or_404()
        summary = AppointmentSummary.query.filter_by(id=summary_id, patient_token=token).first_or_404()
        return render_template("summary_result.html", patient=patient, summary=summary)

    @app.get("/patients/<token>/history")
    def patient_history(token):
        patient = Patient.query.filter_by(token=token).first_or_404()
        summaries = (
            AppointmentSummary.query.filter_by(patient_token=token)
            .order_by(AppointmentSummary.created_at.desc())
            .all()
        )
        return render_template("history.html", patient=patient, summaries=summaries)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
