"""One-time schema migration for the subscription/premium feature: adds
is_premium and premium_since to patients. Safe to re-run - every statement is
idempotent.
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
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS premium_since TIMESTAMP",
]

with engine.begin() as conn:
    for stmt in statements:
        conn.execute(text(stmt))
        print(f"ran: {stmt}")

print("done")
