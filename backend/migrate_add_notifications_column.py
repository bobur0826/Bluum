"""One-time schema migration: adds notifications_enabled to patients, defaulted
to FALSE for everyone including existing rows - opt-in, not opt-out. Safe to
re-run.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

pg_url = os.environ.get("DATABASE_URL")
if not pg_url:
    raise SystemExit("DATABASE_URL not set in .env")
if pg_url.startswith("postgresql://"):
    pg_url = "postgresql+pg8000://" + pg_url[len("postgresql://"):]

engine = create_engine(pg_url)

statements = [
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN NOT NULL DEFAULT FALSE",
]

with engine.begin() as conn:
    for stmt in statements:
        conn.execute(text(stmt))
        print(f"ran: {stmt}")

print("done")
