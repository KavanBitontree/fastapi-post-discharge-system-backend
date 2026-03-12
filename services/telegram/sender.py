"""
services/telegram/sender.py
-----------------------------
Thin wrapper around the Telegram Bot API (sync, httpx).
Used by the webhook handler and reminder cron.
"""

from __future__ import annotations

import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_BASE = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


def send_placeholder(chat_id: str | int, text: str = "...") -> int | None:
    """
    Send an immediate placeholder message (e.g. ...) and return its message_id.
    Returns None on failure.
    """
    try:
        r = httpx.post(
            f"{_BASE}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["result"]["message_id"]
    except Exception as exc:
        logger.warning("send_placeholder failed: %s", exc)
        return None


def edit_message(chat_id: str | int, message_id: int, text: str, parse_mode: str = "HTML") -> bool:
    """
    Edit an existing message in-place (replaces the placeholder with the real answer).
    Falls back gracefully if the message can't be edited.
    """
    try:
        r = httpx.post(
            f"{_BASE}/editMessageText",
            json={
                "chat_id":    chat_id,
                "message_id": message_id,
                "text":       text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("edit_message failed (chat=%s, msg=%s): %s", chat_id, message_id, exc)
        return False


def send_message(chat_id: str | int, text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a text message to a Telegram chat.
    parse_mode: "HTML" (default) or "MarkdownV2"
    Returns True on success.
    """
    try:
        r = httpx.post(
            f"{_BASE}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        r.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Telegram sendMessage failed → chat_id=%s : %s | response: %s",
            chat_id, exc, exc.response.text,
        )
        return False
    except Exception as exc:
        logger.error("Telegram sendMessage failed → chat_id=%s : %s", chat_id, exc)
        return False


# ── Webhook management ────────────────────────────────────────────────────────

def set_webhook(url: str, secret_token: str = "") -> bool:
    """
    Register a Telegram webhook.  Call once on startup (or via a one-off script).
    `url` must be HTTPS.  `secret_token` is sent back by Telegram in the
    X-Telegram-Bot-Api-Secret-Token header so our endpoint can verify origin.
    """
    payload: dict = {
        "url": url,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    }
    if secret_token:
        payload["secret_token"] = secret_token
    try:
        r = httpx.post(f"{_BASE}/setWebhook", json=payload, timeout=10)
        r.raise_for_status()
        ok = r.json().get("result", False)
        logger.info("setWebhook → %s  (url=%s)", ok, url)
        return bool(ok)
    except Exception as exc:
        logger.error("setWebhook failed: %s", exc)
        return False


def delete_webhook(drop_pending: bool = True) -> bool:
    """Remove the current webhook (useful for switching back to polling locally)."""
    try:
        r = httpx.post(
            f"{_BASE}/deleteWebhook",
            json={"drop_pending_updates": drop_pending},
            timeout=10,
        )
        r.raise_for_status()
        ok = r.json().get("result", False)
        logger.info("deleteWebhook → %s", ok)
        return bool(ok)
    except Exception as exc:
        logger.error("deleteWebhook failed: %s", exc)
        return False


def set_my_commands() -> None:
    """Register bot commands so they appear in the Telegram menu."""
    commands = [
        {"command": "start",   "description": "Start / re-register"},
        {"command": "resend",  "description": "Resend OTP"},
        {"command": "restart", "description": "Reset and start over"},
        {"command": "help",    "description": "Show help"},
    ]
    try:
        httpx.post(f"{_BASE}/setMyCommands", json={"commands": commands}, timeout=10)
    except Exception as exc:
        logger.warning("setMyCommands failed: %s", exc)
