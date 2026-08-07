"""One-off script: creates Bobur, Izzat, and Bekzod as demo patients with 2
weeks of realistic habit/sleep/activity history. Safe to re-run - looks each
patient up by name first and skips creating a duplicate.

  Bobur  - running every morning + quitting sugar
  Izzat  - quitting smoking (with a realistic slip mid-way, not a perfect streak)
  Bekzod - building a boxing habit, 3x/week

Run from backend/: .venv/bin/python3 seed_three_users.py
"""

from datetime import date, timedelta

from app import create_app
from models import DailyLog, Habit, HabitCheckIn, Patient, SleepLog, db

app = create_app()
today = date.today()


def get_or_create_patient(full_name, avatar_filename=None, fitness_goal=None):
    patient = Patient.query.filter_by(full_name=full_name).first()
    if patient:
        print(f"{full_name}: already exists (token {patient.token})")
        return patient
    patient = Patient(
        full_name=full_name,
        phone_verified=True,
        avatar_filename=avatar_filename,
        fitness_goal=fitness_goal,
    )
    db.session.add(patient)
    db.session.commit()
    print(f"{full_name}: created (token {patient.token})")
    return patient


def get_or_create_habit(patient, name, kind):
    habit = Habit.query.filter_by(patient_token=patient.token, name=name).first()
    if habit:
        return habit
    habit = Habit(patient_token=patient.token, name=name, kind=kind)
    db.session.add(habit)
    db.session.commit()
    return habit


def seed_checkins(habit, days_ago_list):
    have = {c.checkin_date for c in HabitCheckIn.query.filter_by(habit_id=habit.id).all()}
    added = 0
    for days_ago in days_ago_list:
        d = today - timedelta(days=days_ago)
        if d not in have:
            db.session.add(HabitCheckIn(habit_id=habit.id, checkin_date=d))
            added += 1
    db.session.commit()
    return added


def seed_sleep(patient, pattern):
    """pattern: list of (days_ago, sleep_time, wake_time, hours)."""
    have = {r.log_date for r in SleepLog.query.filter_by(patient_token=patient.token).all()}
    added = 0
    for days_ago, sleep_t, wake_t, hours in pattern:
        d = today - timedelta(days=days_ago)
        if d not in have:
            db.session.add(SleepLog(patient_token=patient.token, log_date=d, sleep_time=sleep_t, wake_time=wake_t, hours=hours))
            added += 1
    db.session.commit()
    return added


def seed_daily_logs(patient, pattern):
    """pattern: list of (days_ago, steps, active_minutes, active_calories, water_cups)."""
    have = {r.log_date for r in DailyLog.query.filter_by(patient_token=patient.token).all()}
    added = 0
    for days_ago, steps, minutes, cals, water in pattern:
        d = today - timedelta(days=days_ago)
        if d not in have:
            db.session.add(DailyLog(patient_token=patient.token, log_date=d, steps=steps,
                                     active_minutes=minutes, active_calories=cals, water_cups=water))
            added += 1
    db.session.commit()
    return added


with app.app_context():
    # ---------------------------------------------------------------- Bobur
    bobur = get_or_create_patient("Bobur", avatar_filename=None, fitness_goal="staying_in_shape")
    run_habit = get_or_create_habit(bobur, "Morning run", "running")
    sugar_habit = get_or_create_habit(bobur, "Quit sugar", "custom")

    # Ran most mornings, missed 2 early days when the streak was just starting -
    # current streak ends up at 9 straight days, which reads as genuinely earned.
    run_days = [d for d in range(14) if d not in (11, 13)]
    n = seed_checkins(run_habit, run_days)
    print(f"Bobur / Morning run: +{n} check-ins, current streak {run_habit.current_streak()}d")

    sugar_days = list(range(10))  # solid, more recent 10-day streak
    n = seed_checkins(sugar_habit, sugar_days)
    print(f"Bobur / Quit sugar: +{n} check-ins, current streak {sugar_habit.current_streak()}d")

    sleep_pattern = [
        (0, "23:10", "06:30", 7.3), (1, "23:00", "06:30", 7.5), (2, "23:40", "06:30", 6.8),
        (3, "23:15", "06:30", 7.25), (4, "00:05", "06:45", 6.7), (5, "23:30", "07:00", 7.5),
        (6, "23:20", "06:30", 7.2), (7, "23:00", "06:30", 7.5), (8, "23:45", "06:45", 7.0),
        (9, "23:10", "06:30", 7.3), (10, "23:30", "06:45", 7.25), (11, "00:20", "07:00", 6.7),
        (12, "23:15", "06:30", 7.25), (13, "23:00", "06:30", 7.5),
    ]
    n = seed_sleep(bobur, sleep_pattern)
    print(f"Bobur / sleep logs: +{n}")

    daily_pattern = [(d, 7800 + (d * 37) % 3200, 28 + (d % 5) * 6, 380 + (d % 4) * 60, 6 + d % 3) for d in range(14)]
    n = seed_daily_logs(bobur, daily_pattern)
    print(f"Bobur / daily logs: +{n}")

    # ---------------------------------------------------------------- Izzat
    izzat = get_or_create_patient("Izzat", avatar_filename="izzat_character.png")
    smoking_habit = get_or_create_habit(izzat, "Quit smoking", "smoking")

    # 14 days, one real slip on day 7 (a week in - realistic), consistent since.
    smoking_days = [d for d in range(14) if d != 7]
    n = seed_checkins(smoking_habit, smoking_days)
    print(f"Izzat / Quit smoking: +{n} check-ins, current streak {smoking_habit.current_streak()}d")

    sleep_pattern = [
        (0, "00:30", "07:30", 7.0), (1, "23:50", "07:15", 7.4), (2, "01:00", "08:00", 7.0),
        (4, "23:40", "07:00", 7.3), (5, "00:15", "07:30", 7.25), (7, "01:20", "07:45", 6.4),
        (8, "23:55", "07:15", 7.3), (10, "00:10", "07:30", 7.3), (12, "23:45", "07:00", 7.25),
    ]
    n = seed_sleep(izzat, sleep_pattern)
    print(f"Izzat / sleep logs: +{n}")

    # ---------------------------------------------------------------- Bekzod
    bekzod = get_or_create_patient("Bekzod", avatar_filename="bekzod_character.png", fitness_goal="staying_in_shape")
    boxing_habit = get_or_create_habit(bekzod, "Boxing", "custom")

    # 3x/week for 2 weeks = 6 sessions, Mon/Wed/Fri-style spacing.
    boxing_days = [0, 2, 4, 7, 9, 11]
    n = seed_checkins(boxing_habit, boxing_days)
    print(f"Bekzod / Boxing: +{n} check-ins, current streak {boxing_habit.current_streak()}d")

    daily_pattern = [(d, 5200 + (d * 53) % 4500, (45 if d in boxing_days else 15), (520 if d in boxing_days else 220), 5 + d % 4) for d in range(14)]
    n = seed_daily_logs(bekzod, daily_pattern)
    print(f"Bekzod / daily logs: +{n}")

    tokens = {"Bobur": bobur.token, "Izzat": izzat.token, "Bekzod": bekzod.token}

print("\ndone.")
for name, token in tokens.items():
    print(f"{name} token: {token}")
