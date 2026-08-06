"""
SMS delivery via Eskiz.uz (a Uzbekistan SMS gateway), for follow-up and
medication reminders.

Requires ESKIZ_EMAIL and ESKIZ_PASSWORD env vars. Without them, send_sms()
logs and no-ops instead of failing - reminders/notes are never lost, they
just don't go out over SMS until real credentials are configured.

NOTE: field names below (mobile_phone/message/from) follow Eskiz's commonly
documented REST pattern as of this writing - verify against your own Eskiz
dashboard/docs before relying on this in production, API details can change.
"""

import logging
import os
import time

import requests

logger = logging.getLogger("bluum.sms")

ESKIZ_BASE_URL = "https://notify.eskiz.uz/api"

_token = None
_token_fetched_at = 0
_TOKEN_TTL_SECONDS = 25 * 24 * 60 * 60  # Eskiz tokens are valid ~30 days


def _get_token():
    global _token, _token_fetched_at

    email = os.environ.get("ESKIZ_EMAIL")
    password = os.environ.get("ESKIZ_PASSWORD")
    if not email or not password:
        return None

    if _token and (time.time() - _token_fetched_at) < _TOKEN_TTL_SECONDS:
        return _token

    resp = requests.post(
        f"{ESKIZ_BASE_URL}/auth/login",
        data={"email": email, "password": password},
        timeout=10,
    )
    resp.raise_for_status()
    _token = resp.json()["data"]["token"]
    _token_fetched_at = time.time()
    return _token


def send_sms(phone: str, message: str) -> bool:
    """Returns True if the SMS was actually sent, False if it was skipped or failed."""
    try:
        token = _get_token()
    except Exception as e:
        logger.warning("Eskiz auth failed, SMS not sent: %s", e)
        return False

    if not token:
        logger.info("ESKIZ_EMAIL/PASSWORD not set - skipping SMS to %s: %s", phone, message)
        return False

    try:
        resp = requests.post(
            f"{ESKIZ_BASE_URL}/message/sms/send",
            headers={"Authorization": f"Bearer {token}"},
            data={"mobile_phone": phone.lstrip("+"), "message": message, "from": "4546"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning("SMS send failed to %s: %s", phone, e)
        return False
