"""Proactive Telegram messages + inline-button actions, so common actions
(checking in) happen with one tap on a push notification instead of opening
the Mini App. Separate from telegram_auth.py, which only verifies Mini App
launches - this is the Bot API side (sendMessage/editMessageText/webhook).

Every call here is best-effort: a failed Telegram API request (bot blocked
by the user, transient network issue, etc.) is logged and swallowed rather
than raised, so one bad send never breaks the reminder job it's part of.
"""

import logging
import os

import requests

logger = logging.getLogger("bluum.telegram_bot")

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def _call(method: str, payload: dict) -> dict | None:
    token = _token()
    if not token:
        return None
    try:
        resp = requests.post(API_BASE.format(token=token, method=method), json=payload, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram API %s failed: %s", method, data)
            return None
        return data.get("result")
    except Exception as e:
        logger.warning("Telegram API %s request failed: %s", method, e)
        return None


def send_message(chat_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict | None:
    """buttons: rows of (label, callback_data) tuples for an inline keyboard."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": label, "callback_data": data} for label, data in row] for row in buttons
            ]
        }
    return _call("sendMessage", payload)


def edit_message_text(chat_id: int, message_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict | None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if buttons is not None:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": label, "callback_data": data} for label, data in row] for row in buttons
            ]
        }
    return _call("editMessageText", payload)


def answer_callback_query(callback_query_id: str, text: str = "") -> dict | None:
    return _call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


def set_webhook(url: str) -> dict | None:
    return _call("setWebhook", {"url": url, "allowed_updates": ["message", "callback_query"]})
