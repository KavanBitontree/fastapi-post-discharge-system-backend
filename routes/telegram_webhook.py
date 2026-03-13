"""
routes/telegram_webhook.py
----------------------------
POST /telegram/webhook — receives Telegram updates via webhook (serverless-safe).

Telegram sends each update as a JSON POST.  We verify the secret token header
and hand off to ``handle_update()`` synchronously (Telegram retries on 5xx, so
we must return 200 promptly even if the handler spawns heavy work).
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Request, HTTPException

from core.config import settings
from services.telegram.bot import handle_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["Telegram Webhook"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Telegram Bot API webhook receiver.

    Telegram will include the ``X-Telegram-Bot-Api-Secret-Token`` header if we
    set ``secret_token`` when registering the webhook.  We reject requests
    without a matching token to prevent spoofed payloads.
    """
    # ── Verify secret token ───────────────────────────────────────────────
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if expected:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != expected:
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    update: dict = await request.json()

    try:
        handle_update(update)
    except Exception as exc:
        # Log but still return 200 — Telegram retries on non-2xx and we don't
        # want an infinite retry loop for a bad update.
        logger.error("Webhook handle_update error: %s", exc, exc_info=True)

    return {"ok": True}
