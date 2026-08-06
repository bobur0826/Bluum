import random
import secrets
from datetime import date, datetime, timedelta

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

OTP_TTL_MINUTES = 10


def generate_token():
    return secrets.token_urlsafe(8)


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(16), unique=True, nullable=False, default=generate_token)

    full_name = db.Column(db.String(120), nullable=False)
    dob = db.Column(db.String(20), nullable=False)
    phone = db.Column(db.String(30), nullable=False, unique=True)
    blood_type = db.Column(db.String(10), nullable=True)

    allergies = db.Column(db.Text, nullable=True)
    chronic_conditions = db.Column(db.Text, nullable=True)
    current_medications = db.Column(db.Text, nullable=True)

    emergency_contact_name = db.Column(db.String(120), nullable=True)
    emergency_contact_phone = db.Column(db.String(30), nullable=True)

    # "simple" = everyday language, "medical" = clinical terminology kept intact.
    language_register = db.Column(db.String(16), nullable=False, default="simple")

    # Progressive profile: one of these is asked at a time, at check-in, until complete.
    # Safety-relevant fields first, "nice to have" fields last.
    height_cm = db.Column(db.Integer, nullable=True)
    weight_kg = db.Column(db.Integer, nullable=True)
    smoking_status = db.Column(db.String(32), nullable=True)
    occupation = db.Column(db.String(120), nullable=True)
    family_history = db.Column(db.Text, nullable=True)

    # Phone verification (SMS OTP is the only login method - no password).
    phone_verified = db.Column(db.Boolean, nullable=False, default=False)
    otp_code = db.Column(db.String(6), nullable=True)
    otp_expires_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    PROGRESSIVE_FIELDS = [
        ("allergies", "Do you have any allergies? (write 'none' if not)"),
        ("chronic_conditions", "Any chronic conditions, like asthma or diabetes? (write 'none' if not)"),
        ("current_medications", "Are you currently taking any medications? (write 'none' if not)"),
        ("emergency_contact_name", "Who should we contact in an emergency? (name)"),
        ("emergency_contact_phone", "Their phone number?"),
        ("blood_type", "What is your blood type, if you know it?"),
        ("height_cm", "What is your height (cm)?"),
        ("weight_kg", "What is your weight (kg)?"),
        ("smoking_status", "Do you smoke? (never / former / current)"),
        ("occupation", "What is your occupation?"),
        ("family_history", "Any major illnesses in your immediate family?"),
    ]

    def next_progressive_question(self):
        for field, question in self.PROGRESSIVE_FIELDS:
            if not getattr(self, field):
                return field, question
        return None, None

    def generate_otp(self):
        code = f"{random.randint(0, 999999):06d}"
        self.otp_code = code
        self.otp_expires_at = datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
        return code

    def verify_otp(self, code):
        if not self.otp_code or not self.otp_expires_at:
            return False
        if datetime.utcnow() > self.otp_expires_at:
            return False
        if code != self.otp_code:
            return False
        self.phone_verified = True
        self.otp_code = None
        self.otp_expires_at = None
        return True


class Staff(db.Model):
    __tablename__ = "staff"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    hospital_name = db.Column(db.String(160), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class CheckIn(db.Model):
    __tablename__ = "check_ins"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class AppointmentSummary(db.Model):
    __tablename__ = "appointment_summaries"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    doctor_notes = db.Column(db.Text, nullable=False)

    # Plain-language explanation, generated per language.
    diagnosis_uz = db.Column(db.Text, nullable=True)
    medications_uz = db.Column(db.Text, nullable=True)
    next_steps_uz = db.Column(db.Text, nullable=True)
    follow_up_uz = db.Column(db.Text, nullable=True)
    daily_steps_uz = db.Column(db.Text, nullable=True)  # JSON list of short steps

    diagnosis_ru = db.Column(db.Text, nullable=True)
    medications_ru = db.Column(db.Text, nullable=True)
    next_steps_ru = db.Column(db.Text, nullable=True)
    follow_up_ru = db.Column(db.Text, nullable=True)
    daily_steps_ru = db.Column(db.Text, nullable=True)

    # pending_review -> awaiting doctor approval, not visible to patient yet.
    # approved -> patient can see it.
    status = db.Column(db.String(20), nullable=False, default="pending_review")
    follow_up_date = db.Column(db.Date, nullable=True)
    follow_up_sms_sent = db.Column(db.Boolean, nullable=False, default=False)
    patient_viewed = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class TestResult(db.Model):
    __tablename__ = "test_results"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)

    risk_level = db.Column(db.String(16), nullable=True)  # "urgent" or "routine"
    explanation_uz = db.Column(db.Text, nullable=True)
    explanation_ru = db.Column(db.Text, nullable=True)

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class Medication(db.Model):
    __tablename__ = "medications"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    dosage = db.Column(db.String(120), nullable=True)
    schedule_times = db.Column(db.String(120), nullable=True)  # comma-separated "08:00,20:00"
    active = db.Column(db.Boolean, nullable=False, default=True)
    last_reminder_sent = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    category = db.Column(db.String(32), nullable=False)  # prescription / referral / insurance / lab
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    department = db.Column(db.String(120), nullable=False)
    requested_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="requested")  # requested / confirmed / cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Prescription(db.Model):
    __tablename__ = "prescriptions"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    drug_name = db.Column(db.String(160), nullable=False)
    dosage = db.Column(db.String(120), nullable=False)
    instructions = db.Column(db.Text, nullable=True)
    duration = db.Column(db.String(80), nullable=True)
    interaction_warning = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class StaffNote(db.Model):
    __tablename__ = "staff_notes"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)
    note = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


def compute_streak(dates_desc):
    """Given a list of `date` objects (any order, may include gaps), return the
    current streak length: consecutive days ending today (or yesterday, so a
    streak doesn't visually reset before the user has had a chance to log
    today)."""
    days = sorted(set(dates_desc), reverse=True)
    if not days:
        return 0
    today = date.today()
    if days[0] not in (today, today - timedelta(days=1)):
        return 0
    streak = 1
    cursor = days[0]
    for d in days[1:]:
        if cursor - d == timedelta(days=1):
            streak += 1
            cursor = d
        elif d == cursor:
            continue
        else:
            break
    return streak


class Habit(db.Model):
    __tablename__ = "habits"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)  # e.g. "Quit smoking"
    kind = db.Column(db.String(32), nullable=False, default="custom")  # smoking / alcohol / custom
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def current_streak(self):
        days = [c.checkin_date for c in self.checkins]
        return compute_streak(days)

    def checked_in_today(self):
        return any(c.checkin_date == date.today() for c in self.checkins)

    def week_strip(self):
        """Last 7 days (oldest first) as [{date, dow, hit, today}, ...] for the
        week-view UI."""
        hit_days = {c.checkin_date for c in self.checkins}
        today = date.today()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        return [
            {
                "date": d,
                "dow": d.strftime("%a")[0],
                "hit": d in hit_days,
                "today": d == today,
            }
            for d in days
        ]


class HabitCheckIn(db.Model):
    __tablename__ = "habit_checkins"

    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey("habits.id"), nullable=False, index=True)
    checkin_date = db.Column(db.Date, nullable=False, default=date.today)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    habit = db.relationship("Habit", backref=db.backref("checkins", lazy="joined"))

    __table_args__ = (db.UniqueConstraint("habit_id", "checkin_date", name="uq_habit_date"),)


class SleepLog(db.Model):
    __tablename__ = "sleep_logs"

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    log_date = db.Column(db.Date, nullable=False, default=date.today)
    sleep_time = db.Column(db.String(5), nullable=True)  # "23:30"
    wake_time = db.Column(db.String(5), nullable=True)  # "07:00"
    hours = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("patient_token", "log_date", name="uq_sleep_date"),)

    @staticmethod
    def current_streak_for(patient_token):
        days = [
            r.log_date
            for r in SleepLog.query.filter_by(patient_token=patient_token).all()
        ]
        return compute_streak(days)

    @staticmethod
    def week_strip_for(patient_token):
        hit_days = {
            r.log_date
            for r in SleepLog.query.filter_by(patient_token=patient_token).all()
        }
        today = date.today()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        return [
            {
                "date": d,
                "dow": d.strftime("%a")[0],
                "hit": d in hit_days,
                "today": d == today,
            }
            for d in days
        ]


class DailyLog(db.Model):
    """Manually-logged daily activity — steps, active minutes, active calories,
    water — one row per patient per day. Not sensor data (no wearable
    integration yet); the patient enters it themselves."""

    __tablename__ = "daily_logs"

    STEPS_TARGET = 8000
    ACTIVE_MINUTES_TARGET = 30
    WATER_TARGET = 8

    id = db.Column(db.Integer, primary_key=True)
    patient_token = db.Column(db.String(16), db.ForeignKey("patients.token"), nullable=False, index=True)
    log_date = db.Column(db.Date, nullable=False, default=date.today)
    steps = db.Column(db.Integer, nullable=True)
    active_calories = db.Column(db.Integer, nullable=True)
    active_minutes = db.Column(db.Integer, nullable=True)
    water_cups = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("patient_token", "log_date", name="uq_daily_log_date"),)

    @staticmethod
    def today_for(patient_token):
        return DailyLog.query.filter_by(patient_token=patient_token, log_date=date.today()).first()
