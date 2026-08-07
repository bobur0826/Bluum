"""One-time schema migration: adds patients.avatar_filename, patients.fitness_goal,
and creates the food_logs table. Safe to re-run - every statement is idempotent."""

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
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS avatar_filename VARCHAR(120)",
    "ALTER TABLE patients ADD COLUMN IF NOT EXISTS fitness_goal VARCHAR(20)",
    """
    CREATE TABLE IF NOT EXISTS food_logs (
        id SERIAL PRIMARY KEY,
        patient_token VARCHAR(16) NOT NULL REFERENCES patients(token),
        log_date DATE NOT NULL,
        description VARCHAR(160),
        photo_filename VARCHAR(255),
        calories INTEGER NOT NULL DEFAULT 0,
        protein_g INTEGER NOT NULL DEFAULT 0,
        fat_g INTEGER NOT NULL DEFAULT 0,
        carbs_g INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_food_logs_patient_token ON food_logs (patient_token)",
    "CREATE INDEX IF NOT EXISTS ix_food_logs_created_at ON food_logs (created_at)",
]

with engine.begin() as conn:
    for stmt in statements:
        conn.execute(text(stmt))
        print(f"ran: {stmt.strip().splitlines()[0]}...")

print("done")
