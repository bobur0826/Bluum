"""One-time migration: copy every row from local SQLite into the Postgres
(Supabase) database pointed to by DATABASE_URL in .env. Never prints the
connection string or any credential."""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker

load_dotenv()

import models  # noqa: E402 (needs load_dotenv() first, unused import warning is fine)

pg_url = os.environ.get("DATABASE_URL")
if not pg_url:
    raise SystemExit("DATABASE_URL not set in .env")

sqlite_engine = create_engine("sqlite:///instance/medpass.db")
pg_engine = create_engine(pg_url)

# Create all tables on Postgres (safe to re-run - only creates what's missing).
models.db.metadata.create_all(pg_engine)

SqliteSession = sessionmaker(bind=sqlite_engine)
PgSession = sessionmaker(bind=pg_engine)
sqlite_session = SqliteSession()
pg_session = PgSession()

# Order matters: parents before children (foreign keys).
tables_in_order = [
    models.Patient.__table__,
    models.Staff.__table__,
    models.CheckIn.__table__,
    models.AppointmentSummary.__table__,
    models.TestResult.__table__,
    models.Medication.__table__,
    models.Document.__table__,
    models.Appointment.__table__,
    models.Prescription.__table__,
    models.StaffNote.__table__,
]

for table in tables_in_order:
    rows = sqlite_session.execute(table.select()).mappings().all()
    if not rows:
        print(f"{table.name}: 0 rows, skipped")
        continue
    pg_session.execute(insert(table), [dict(r) for r in rows])
    pg_session.commit()
    print(f"{table.name}: copied {len(rows)} rows")

print("done")
