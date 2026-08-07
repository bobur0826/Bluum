"""One-time schema migration for the Telegram Mini App login: makes patients.phone
and patients.dob nullable (Telegram signups don't collect either up front) and adds
telegram_user_id / telegram_username. Safe to re-run - every statement is idempotent.

`db.create_all()` never alters existing tables, only creates missing ones, so this
had to be a real migration rather than something that happens automatically on deploy.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

pg_url = os.environ.get("DATABASE_URL")
if not pg_url:
    raise SystemExit("DATABASE_URL not set in .env")

engine = create_engine(pg_url)

statements = [
    "ALTER TABLE patients ALTER COLUMN dob DROP NOT NULL",
    "ALTER TABLE patients ALTER COLUMN phone DROP NOT NULL",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS telegram_username VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_patients_telegram_user_id "
    "ON patients (telegram_user_id) WHERE telegram_user_id IS NOT NULL",
]

with engine.begin() as conn:
    for stmt in statements:
        conn.execute(text(stmt))
        print(f"ran: {stmt}")

print("done")
