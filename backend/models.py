import secrets
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def generate_token():
    return secrets.token_urlsafe(8)


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(16), unique=True, nullable=False, default=generate_token)

    full_name = db.Column(db.String(120), nullable=False)
    dob = db.Column(db.String(20), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    blood_type = db.Column(db.String(10), nullable=True)

    allergies = db.Column(db.Text, nullable=True)
    chronic_conditions = db.Column(db.Text, nullable=True)
    current_medications = db.Column(db.Text, nullable=True)

    emergency_contact_name = db.Column(db.String(120), nullable=True)
    emergency_contact_phone = db.Column(db.String(30), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppointmentSummary(db.Model):
    __tablename__ = "appointment_summaries"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    doctor_notes = db.Column(db.Text, nullable=False)

    # Plain-language explanation, generated per language.
    diagnosis_uz = db.Column(db.Text, nullable=True)
    medications_uz = db.Column(db.Text, nullable=True)
    next_steps_uz = db.Column(db.Text, nullable=True)
    follow_up_uz = db.Column(db.Text, nullable=True)

    diagnosis_ru = db.Column(db.Text, nullable=True)
    medications_ru = db.Column(db.Text, nullable=True)
    next_steps_ru = db.Column(db.Text, nullable=True)
    follow_up_ru = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
