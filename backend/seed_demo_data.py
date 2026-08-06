"""One-off script: seed realistic demo data across every feature for the main
demo patient (token TmdRczwZXpQ). Safe to re-run — skips what already exists
where it would create duplicates."""

import io
import os
from datetime import date, datetime, timedelta

from app import create_app
from models import (
    Appointment, AppointmentSummary, CheckIn, Document, Habit, HabitCheckIn,
    Medication, Prescription, SleepLog, Staff, StaffNote, TestResult, db,
)

TOKEN = "TmdRczwZXpQ"

app = create_app()
with app.app_context():
    # ---------------------------------------------------------------- staff account
    staff = Staff.query.filter_by(email="demo@bluum.uz").first()
    if not staff:
        staff = Staff(full_name="Dr. Nodira Yusupova", email="demo@bluum.uz", hospital_name="Tashkent City Clinic")
        staff.set_password("bluum1234")
        db.session.add(staff)
        db.session.commit()
        print("staff: created demo@bluum.uz / bluum1234")
    else:
        print("staff: already exists")

    # ---------------------------------------------------------------- extra habits + streak history
    existing_names = {h.name for h in Habit.query.filter_by(patient_token=TOKEN).all()}
    new_habits = []
    if "Quit alcohol" not in existing_names:
        new_habits.append(Habit(patient_token=TOKEN, name="Quit alcohol", kind="alcohol"))
    if "Morning walk" not in existing_names:
        new_habits.append(Habit(patient_token=TOKEN, name="Morning walk", kind="custom"))
    for h in new_habits:
        db.session.add(h)
    db.session.commit()

    # Give every active habit a believable multi-day streak ending today.
    today = date.today()
    for h in Habit.query.filter_by(patient_token=TOKEN, active=True).all():
        have = {c.checkin_date for c in HabitCheckIn.query.filter_by(habit_id=h.id).all()}
        span = 6 if h.name == "Quit smoking" else 4 if h.name == "Quit alcohol" else 2
        for i in range(span):
            d = today - timedelta(days=i)
            if d not in have:
                db.session.add(HabitCheckIn(habit_id=h.id, checkin_date=d))
    db.session.commit()
    print("habits: seeded streak history for", Habit.query.filter_by(patient_token=TOKEN).count(), "habits")

    # ---------------------------------------------------------------- sleep history
    have_sleep = {r.log_date for r in SleepLog.query.filter_by(patient_token=TOKEN).all()}
    sleep_plan = [("23:30", "07:00", 7.5), ("00:15", "07:30", 7.25), ("23:00", "06:45", 7.75),
                  ("23:45", "07:15", 7.5), ("00:30", "07:00", 6.5)]
    for i, (sleep_t, wake_t, hours) in enumerate(sleep_plan):
        d = today - timedelta(days=i)
        if d not in have_sleep:
            db.session.add(SleepLog(patient_token=TOKEN, log_date=d, sleep_time=sleep_t, wake_time=wake_t, hours=hours))
    db.session.commit()
    print("sleep_logs:", SleepLog.query.filter_by(patient_token=TOKEN).count(), "nights")

    # ---------------------------------------------------------------- check-in log
    if CheckIn.query.filter_by(patient_token=TOKEN).count() == 0:
        db.session.add(CheckIn(patient_token=TOKEN, staff_id=staff.id, created_at=datetime.utcnow() - timedelta(days=3)))
        db.session.commit()
    print("check_ins:", CheckIn.query.filter_by(patient_token=TOKEN).count())

    # ---------------------------------------------------------------- appointments
    if Appointment.query.filter_by(patient_token=TOKEN).count() == 0:
        db.session.add_all([
            Appointment(patient_token=TOKEN, department="Cardiology",
                        requested_at=datetime.utcnow() + timedelta(days=5), status="confirmed"),
            Appointment(patient_token=TOKEN, department="Dermatology",
                        requested_at=datetime.utcnow() + timedelta(days=12), status="requested"),
        ])
        db.session.commit()
    print("appointments:", Appointment.query.filter_by(patient_token=TOKEN).count())

    # ---------------------------------------------------------------- documents (real small files on disk)
    if Document.query.filter_by(patient_token=TOKEN).count() == 0:
        upload_dir = os.path.join(os.path.dirname(__file__), "uploads", TOKEN)
        os.makedirs(upload_dir, exist_ok=True)
        docs = [("referral_cardiology.txt", "referral", "Referral letter to Cardiology — Dr. Yusupova, 2026-08-01."),
                ("insurance_card.txt", "insurance", "State Health Insurance Fund — Policy #UZ-2291-4471.")]
        for stored_name, category, content in docs:
            with open(os.path.join(upload_dir, stored_name), "w") as f:
                f.write(content)
            db.session.add(Document(patient_token=TOKEN, category=category, filename=stored_name, original_filename=stored_name))
        db.session.commit()
    print("documents:", Document.query.filter_by(patient_token=TOKEN).count())

    # ---------------------------------------------------------------- staff notes
    if StaffNote.query.filter_by(patient_token=TOKEN).count() == 0:
        db.session.add(StaffNote(patient_token=TOKEN, staff_id=staff.id,
                                  note="Patient adherent to medication schedule. Discussed smoking cessation progress — 6 days smoke-free, encouraged to continue."))
        db.session.commit()
    print("staff_notes:", StaffNote.query.filter_by(patient_token=TOKEN).count())

print("\ndone.")
