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
from collections import deque
from fastapi import APIRouter, Request, HTTPException

from core.config import settings
from services.telegram.bot import handle_update_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["Telegram Webhook"])

# Deduplication buffer: stores last 100 processed update_ids
# Telegram retries webhooks if handler takes >30s, this prevents duplicate processing
_PROCESSED_UPDATES: deque = deque(maxlen=100)


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Telegram Bot API webhook receiver.

    Telegram will include the ``X-Telegram-Bot-Api-Secret-Token`` header if we
    set ``secret_token`` when registering the webhook.  We reject requests
    without a matching token to prevent spoofed payloads.
    
    Spawns handle_update_async as a background task and returns immediately.
    Includes deduplication to prevent processing the same update twice if Telegram retries.
    """
    print("📨 [WEBHOOK] Received Telegram update")
    
    # ── Verify secret token ───────────────────────────────────────────────
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if expected:
        incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if incoming != expected:
            print("❌ [WEBHOOK] Invalid secret token")
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    update: dict = await request.json()
    
    print(f"📬 [WEBHOOK] Update ID: {update.get('update_id')}")
    message = update.get("message") or update.get("edited_message")
    if message:
        text = message.get("text", "")
        print(f"💬 [WEBHOOK] Message text: {text[:100]}")

    # ── Deduplication: prevent processing same update twice ───────────────
    # Telegram retries the same update_id if handler takes >30 seconds
    update_id = update.get("update_id")
    if update_id:
        if update_id in _PROCESSED_UPDATES:
            logger.info("Skipping duplicate update_id=%s (Telegram retry)", update_id)
            print(f"⏭️ [WEBHOOK] Skipping duplicate update_id={update_id}")
            return {"ok": True}
        # Mark as processed
        _PROCESSED_UPDATES.append(update_id)

    try:
        # Spawn async task — don't wait, return 200 immediately to Telegram
        print("🚀 [WEBHOOK] Spawning async handler")
        asyncio.create_task(handle_update_async(update))
    except Exception as exc:
        # Log spawn error but still return 200 to avoid Telegram retries
        logger.error("Webhook task spawn error: %s", exc, exc_info=True)
        print(f"❌ [WEBHOOK] Error spawning task: {exc}")

    print("✅ [WEBHOOK] Returning OK to Telegram")
    return {"ok": True}
