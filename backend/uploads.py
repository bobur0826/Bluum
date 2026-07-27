import os
import secrets

from werkzeug.utils import secure_filename

UPLOAD_ROOT = os.path.join(os.path.dirname(__file__), "uploads")


def save_upload(file_storage, patient_token: str) -> tuple[str, str]:
    """Save an uploaded file under uploads/<token>/, return (stored_filename, original_filename)."""
    original = secure_filename(file_storage.filename or "file")
    stored = f"{secrets.token_hex(6)}_{original}"

    patient_dir = os.path.join(UPLOAD_ROOT, patient_token)
    os.makedirs(patient_dir, exist_ok=True)
    file_storage.save(os.path.join(patient_dir, stored))

    return stored, original


def upload_path(patient_token: str, filename: str) -> str:
    return os.path.join(UPLOAD_ROOT, patient_token, filename)
