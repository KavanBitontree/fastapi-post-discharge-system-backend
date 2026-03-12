"""
services/telegram/sender.py
-----------------------------
Thin wrapper around the Telegram Bot API (sync, httpx).
Works in background threads (reminder cron, bot polling).
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


def get_updates(offset: int = 0, timeout: int = 20) -> list[dict] | None:
    """
    Long-poll getUpdates. Blocks for `timeout` seconds.
    Returns list of Update objects, or None on 409 Conflict (another instance polling).
    """
    try:
        r = httpx.get(
            f"{_BASE}/getUpdates",
            params={
                "offset":          offset,
                "timeout":         timeout,
                "allowed_updates": ["message"],
            },
            timeout=timeout + 5,
        )
        r.raise_for_status()
        return r.json().get("result", [])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            return None  # signal conflict to caller — don't log here
        logger.error("getUpdates failed: %s", exc)
        return []
    except Exception as exc:
        logger.error("getUpdates failed: %s", exc)
        return []


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
