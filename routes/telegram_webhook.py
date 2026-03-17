"""
routes/telegram_webhook.py
----------------------------
POST /telegram/webhook — receives Telegram updates via webhook (serverless-safe).

Telegram sends each update as a JSON POST.  We verify the secret token header
and hand off to ``handle_update_async()`` spawned as a background task.
Webhook returns 200 immediately; heavy LangGraph work happens concurrently.
"""

from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException

from core.config import settings
from services.telegram.bot import handle_update_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["Telegram Webhook"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Telegram Bot API webhook receiver.

    Telegram will include the ``X-Telegram-Bot-Api-Secret-Token`` header if we
    set ``secret_token`` when registering the webhook.  We reject requests
    without a matching token to prevent spoofed payloads.
    
    Spawns handle_update_async as a background task and returns immediately.
    """
    # ── Verify secret token ───────────────────────────────────────────────
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if expected:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != expected:
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    update: dict = await request.json()

    try:
        # Spawn async task — don't wait, return 200 immediately to Telegram
        asyncio.create_task(handle_update_async(update))
    except Exception as exc:
        # Log spawn error but still return 200 to avoid Telegram retries
        logger.error("Webhook task spawn error: %s", exc, exc_info=True)

    return {"ok": True}
