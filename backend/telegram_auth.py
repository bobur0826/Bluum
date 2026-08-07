"""Verifies Telegram Mini App `initData` so a patient's identity can be trusted
without a phone/OTP round-trip - Telegram itself already proved who they are.

Algorithm is Telegram's documented one for validating WebApp init data:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AUTH_AGE_SECONDS = 24 * 60 * 60  # reject stale/replayed init_data past this age


def verify_init_data(init_data: str, bot_token: str, max_age: int = MAX_AUTH_AGE_SECONDS) -> dict | None:
    """Returns the parsed Telegram `user` dict if `init_data` is genuinely signed by
    Telegram for this bot and not stale, else None. Never raises on malformed input."""
    if not init_data or not bot_token:
        return None

    try:
        pairs = parse_qsl(init_data, strict_parsing=True)
    except ValueError:
        return None

    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = data.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > max_age:
                return None
        except ValueError:
            return None

    user_raw = data.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except json.JSONDecodeError:
        return None
