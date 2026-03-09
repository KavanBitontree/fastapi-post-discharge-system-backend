"""
services/telegram/otp.py
--------------------------
6-digit OTP generation + SMS dispatch stub.

Wire in your SMS provider inside send_otp_sms() below.
Until then, the OTP is printed to the console / logs clearly so you can test
the full flow without an SMS gateway.
"""

from __future__ import annotations

import logging
import secrets
from twilio.rest import Client
from core.config import settings

logger = logging.getLogger(__name__)


def generate_otp(length: int = 6) -> str:
    """Return a cryptographically random N-digit OTP string."""
    # secrets.randbelow gives a uniform random int; zero-pad to ensure length
    upper = 10 ** length
    return str(secrets.randbelow(upper)).zfill(length)


def send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send OTP to `phone` via SMS.

    Uncomment ONE of the provider blocks below and add keys to .env / core/config.py. """


    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(
        to=phone,
        from_=settings.TWILIO_FROM_NUMBER,
        body=f"Your Post-Discharge Care OTP is: {otp}. Valid for 5 minutes.",
    )
    
    try:
        # ── STUB (remove once SMS provider is wired) ───────────────────────────
        logger.info("📲 [STUB OTP] SMS → %s  |  OTP: %s", phone, otp)
        print(f"\n{'=' * 50}")
        print(f"  [OTP DEBUG]  Phone: {phone}  →  OTP: {otp}")
        print(f"{'=' * 50}\n")
        return True
        # ───────────────────────────────────────────────────────────────────────

    except Exception as exc:
        logger.error("SMS send failed → %s : %s", phone, exc)
        return False
