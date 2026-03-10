"""
services/telegram/bot.py
--------------------------
Telegram bot — long-polling state machine.

Verification flow
─────────────────
1. Any message from unknown user
       → create TelegramSession (AWAIT_MOBILE) + send welcome/ask-for-number msg

2. AWAIT_MOBILE state
       • /start or /help → ask for number again
       • text looks like a phone number
            – found in patients table  → generate OTP, SMS it, AWAIT_OTP
            – not found               → "number not in our records, try again"
       • anything else → "we need your number first"

3. AWAIT_OTP state
       • /resend   → new OTP, reset expiry, SMS again
       • /restart  → reset session → AWAIT_MOBILE
       • /start    → remind user they're in OTP step
       • 6-digit sequence found in text
            – matches DB OTP and not expired → VERIFIED
            – expired                        → "expired, use /resend"
            – wrong, attempts > 0            → "wrong OTP, N left"
            – wrong, attempts = 0            → "too many attempts, /restart"
       • no 6 digits found → "invalid format"

4. VERIFIED state
       • /start or /help  → "already verified, ask away"
       • anything else    → routed to LangGraph agent
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.enums import SessionStatus
from models.discharge_history import DischargeHistory
from models.patient import Patient
from models.telegram_session import TelegramSession
from services.telegram.otp import generate_otp, send_otp_sms
from services.telegram.sender import get_updates, send_message, send_placeholder, edit_message, set_my_commands

logger = logging.getLogger(__name__)

TIMEZONE           = ZoneInfo("Asia/Kolkata")
OTP_EXPIRY_MINUTES = 5
MAX_ATTEMPTS       = 3

# ── Bot reply templates (HTML) ────────────────────────────────────────────────

_WELCOME = (
    "👋 Welcome to <b>Medicare Bot</b>!\n\n"
    "I can help you with:\n"
    "  💊 Medication reminders &amp; queries\n"
    "  🧪 Lab report results\n"
    "  🧾 Billing information\n"
    "  👨‍⚕️ Doctor contact details\n\n"
    "To get started, please send your <b>registered mobile number</b> with country code.\n"
    "Example: <code>+919876543210</code>"
)

_ASK_MOBILE = (
    "📱 Please send your <b>registered mobile number</b> with country code.\n"
    "Example: <code>+919876543210</code>"
)

_INVALID_MOBILE = (
    "❌ That doesn't look like a valid phone number.\n\n"
    "Please include the country code.\n"
    "Example: <code>+919876543210</code>"
)

_NOT_FOUND = (
    "❌ No patient found with that number in our records.\n\n"
    "Please double-check and try again, or contact the hospital."
)

_OTP_SENT = (
    "✅ Number matched!\n\n"
    "Welcome, <b>{name}</b>! 🎉\n\n"
    "We have sent a 6-digit OTP to your number ending with <b>****{last4}</b>.\n"
    "Please enter the OTP to complete verification.\n\n"
    "Type /resend if you didn't receive it."
)

_INVALID_OTP_FORMAT = (
    "⚠️ I couldn't find a 6-digit OTP in your message.\n"
    "Please send <b>only the 6-digit code</b>.\n"
    "Example: <code>123456</code>"
)

_WRONG_OTP = "❌ Incorrect OTP. You have <b>{attempts}</b> attempt(s) remaining."

_OTP_EXPIRED = (
    "⏰ Your OTP has expired.\n\n"
    "Type /resend to receive a new OTP."
)

_TOO_MANY = (
    "🚫 Too many failed attempts. Your session has been reset.\n\n"
    "Type /restart to begin again."
)

_VERIFIED = (
    "🎉 <b>Verification successful!</b>\n\n"
    "You're all set, <b>{name}</b>!\n\n"
    "You'll receive medication reminders here, and you can ask me anything about:\n"
    "  • Your medicines &amp; schedule\n"
    "  • Lab report results\n"
    "  • Your bills\n"
    "  • Your doctors\n\n"
    "Go ahead — ask your first question! 😊"
)

_ALREADY_VERIFIED = (
    "✅ You're already verified, <b>{name}</b>!\n\n"
    "Ask me anything about your health records."
)

_IN_VERIFICATION = (
    "🔐 You're in the middle of OTP verification.\n\n"
    "Please enter your <b>6-digit OTP</b>, or:\n"
    "  /resend  — to get a new OTP\n"
    "  /restart — to start over"
)

_NEED_MOBILE = (
    "📱 I need your mobile number before we can continue.\n\n"
    "Please send your registered number with country code.\n"
    "Example: <code>+919876543210</code>"
)

_AGENT_ERROR = (
    "😔 I'm having trouble processing your request right now.\n"
    "Please try again in a moment."
)

_HELP = (
    "<b>Post-Discharge Care Bot \u2014 Help</b>\n\n"
    "Commands:\n"
    "  /start   \u2014 show welcome message\n"
    "  /resend  \u2014 resend your OTP (during verification)\n"
    "  /restart \u2014 reset your session and start over\n"
    "  /help    \u2014 show this message\n\n"
    "Once verified, just type your question naturally:\n"
    "  \u2022 What medicines do I take today?\n"
    "  \u2022 Show my latest blood test results\n"
    "  \u2022 How much is my outstanding bill?"
)

# ── Phone helpers ─────────────────────────────────────────────────────────────

_PHONE_RE = re.compile(r'^\+?\d[\d\s\-]{6,}\d$')


def _extract_phone(text: str) -> str | None:
    """
    Return the phone string (+ kept, spaces/dashes stripped) if it looks like
    a phone number, otherwise None.
    """
    cleaned = text.strip()
    if not _PHONE_RE.match(cleaned):
        return None
    return re.sub(r'[\s\-]', '', cleaned)


def _digits_only(s: str) -> str:
    return re.sub(r'\D', '', s)


def _phone_matches(stored: str | None, user_input: str) -> bool:
    """
    Match by last 10 digits so +919876543210 matches 9876543210 and vice-versa.
    """
    if not stored:
        return False
    sd = _digits_only(stored)
    ud = _digits_only(user_input)
    # Both must have at least 10 digits for a meaningful last-10 comparison
    if len(sd) >= 10 and len(ud) >= 10:
        return sd[-10:] == ud[-10:]
    return sd == ud  # fallback: exact digit match


def _extract_otp(text: str) -> str | None:
    """Find the first standalone 6-digit sequence in the text."""
    m = re.search(r'\b(\d{6})\b', text.strip())
    return m.group(1) if m else None


# ── Session helpers ───────────────────────────────────────────────────────────

def _get_or_create_session(db: Session, chat_id: str) -> tuple[TelegramSession, bool]:
    """Returns (session, is_new). Commits if new row created."""
    sess = (
        db.query(TelegramSession)
        .filter(TelegramSession.telegram_id == chat_id)
        .first()
    )
    if sess:
        return sess, False
    sess = TelegramSession(
        telegram_id=chat_id,
        session_status=SessionStatus.AWAIT_MOBILE,
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess, True


def _issue_otp(db: Session, sess: TelegramSession, patient: Patient) -> bool:
    """Generate OTP, store in DB (5-min expiry), dispatch SMS. Returns SMS success."""
    otp = generate_otp()
    now = datetime.now(TIMEZONE)
    exp = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

    # Find the most recent discharge for this patient
    discharge = (
        db.query(DischargeHistory)
        .filter(DischargeHistory.patient_id == patient.id)
        .order_by(DischargeHistory.created_at.desc())
        .first()
    )

    sess.otp            = otp
    sess.otp_created_at = now
    sess.otp_expires_at = exp
    sess.attempts       = MAX_ATTEMPTS
    sess.phone_number   = patient.phone_number
    sess.discharge_id   = discharge.id if discharge else None
    sess.session_status = SessionStatus.AWAIT_OTP
    db.commit()

    return send_otp_sms(patient.phone_number or "", otp)


# ── State handlers ────────────────────────────────────────────────────────────

def _handle_await_mobile(db: Session, sess: TelegramSession, chat_id: str, text: str) -> None:
    cmd = text.split()[0].lower().split("@")[0] if text else ""

    if cmd in ("/start", "/help"):
        send_message(chat_id, _HELP if cmd == "/help" else _WELCOME)
        return

    phone = _extract_phone(text)
    if not phone:
        send_message(chat_id, _INVALID_MOBILE)
        return

    # Lookup patient by phone (last-10-digit normalisation)
    candidates = (
        db.query(Patient)
        .filter(Patient.is_active == True, Patient.phone_number.isnot(None))
        .all()
    )
    patient = next((p for p in candidates if _phone_matches(p.phone_number, phone)), None)

    if not patient:
        send_message(chat_id, _NOT_FOUND)
        return

    _issue_otp(db, sess, patient)
    last4 = _digits_only(phone)[-4:]
    send_message(chat_id, _OTP_SENT.format(name=patient.full_name, last4=last4))


def _handle_await_otp(db: Session, sess: TelegramSession, chat_id: str, text: str) -> None:
    cmd = text.split()[0].lower().split("@")[0] if text else ""

    if cmd == "/restart":
        sess.session_status = SessionStatus.AWAIT_MOBILE
        sess.otp            = None
        sess.discharge_id   = None
        db.commit()
        send_message(chat_id, _ASK_MOBILE)
        return

    if cmd == "/resend":
        discharge = sess.discharge_id and db.query(DischargeHistory).filter(DischargeHistory.id == sess.discharge_id).first()
        patient = discharge.patient if discharge else None
        if patient:
            _issue_otp(db, sess, patient)
            last4 = _digits_only(patient.phone_number or "")[-4:]
            send_message(chat_id, f"🔄 New OTP sent to number ending <b>****{last4}</b>.")
        else:
            send_message(chat_id, "❌ Session error. Type /restart to begin again.")
        return

    if cmd in ("/start", "/help"):
        send_message(chat_id, _IN_VERIFICATION)
        return

    otp = _extract_otp(text)
    if not otp:
        send_message(chat_id, _INVALID_OTP_FORMAT)
        return

    # Expiry check
    now = datetime.now(TIMEZONE)
    exp = sess.otp_expires_at
    if exp:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=TIMEZONE)
        if now > exp:
            send_message(chat_id, _OTP_EXPIRED)
            return

    # OTP match check
    if otp != sess.otp:
        sess.attempts = max(0, sess.attempts - 1)
        db.commit()
        if sess.attempts <= 0:
            # Reset so they can /restart
            sess.session_status = SessionStatus.AWAIT_MOBILE
            sess.otp            = None
            sess.discharge_id   = None
            db.commit()
            send_message(chat_id, _TOO_MANY)
        else:
            send_message(chat_id, _WRONG_OTP.format(attempts=sess.attempts))
        return

    # ── Correct OTP → mark VERIFIED ──────────────────────────────────────────
    discharge = db.query(DischargeHistory).filter(DischargeHistory.id == sess.discharge_id).first()
    patient = discharge.patient if discharge else None
    sess.session_status = SessionStatus.VERIFIED
    sess.verified_at    = now
    sess.otp            = None       # clear after use
    db.commit()

    name = patient.full_name if patient else "Patient"
    send_message(chat_id, _VERIFIED.format(name=name))


def _handle_verified(db: Session, sess: TelegramSession, chat_id: str, text: str) -> None:
    """Route message to LangGraph agent and reply with AI response."""
    cmd = text.split()[0].lower().split("@")[0] if text else ""

    if cmd in ("/start", "/help"):
        discharge = db.query(DischargeHistory).filter(DischargeHistory.id == sess.discharge_id).first()
        name = discharge.patient.full_name if discharge and discharge.patient else "Patient"
        send_message(chat_id, _ALREADY_VERIFIED.format(name=name) if cmd == "/start" else _HELP)
        return

    discharge_id = sess.discharge_id
    if not discharge_id:
        send_message(chat_id, _AGENT_ERROR)
        return

    placeholder_id: int | None = None
    try:
        # Import here to avoid circular imports at module load time
        from services.agent.graph import build_agent_graph
        from services.agent.chat_history_service import fetch_last_10, save_turn
        from services.agent.state import AgentState

        # Show animated thinking dots in the placeholder bubble (•  →  ••  →  •••)
        placeholder_id = send_placeholder(chat_id, "•")
        _typing_stop = threading.Event()
        _DOT_FRAMES = ("•", "••", "•••")

        def _animate():
            frame = 1  # placeholder already shows frame 0 ("•")
            while not _typing_stop.is_set():
                _typing_stop.wait(0.7)  # ≤1 edit/s keeps us under Telegram's rate limit
                if _typing_stop.is_set():
                    break
                edit_message(chat_id, placeholder_id, _DOT_FRAMES[frame % 3])
                frame += 1

        typing_thread = threading.Thread(target=_animate, daemon=True)
        typing_thread.start()

        try:
            history  = fetch_last_10(discharge_id, db)
            now_str  = datetime.now(TIMEZONE).strftime("%A, %d %b %Y, %I:%M %p IST")
            initial_state: AgentState = {
                "discharge_id":     discharge_id,
                "user_msg":         text.strip(),
                "current_datetime": now_str,
                "chat_history":     history,
                "intents":          [],
                "pending_intents":  [],
                "node_responses":   {},
                "final_answer":     None,
                "call_counts":      {},
                "total_calls":      0,
                "error":            None,
            }

            graph  = build_agent_graph(discharge_id, db)
            result: AgentState = graph.invoke(initial_state)
        finally:
            _typing_stop.set()
            typing_thread.join(timeout=2)  # wait for any in-flight edit to finish

        answer = result.get("final_answer") or (
            "I'm sorry, that's outside my scope. "
            "I can help with reports, bills, medications, and doctors."
        )
        save_turn(discharge_id, text, answer, db)

        chunks = _split_message(answer)

        if placeholder_id is not None:
            # Replace the • bubble with the real answer in-place
            if not edit_message(chat_id, placeholder_id, chunks[0]):
                logger.warning("edit_message failed for chat=%s; answer may not have shown", chat_id)
            for chunk in chunks[1:]:
                send_message(chat_id, chunk)
        else:
            # Placeholder send failed — just send all chunks normally
            for chunk in chunks:
                send_message(chat_id, chunk)

    except Exception as exc:
        logger.error("LangGraph error for Telegram discharge %s: %s", discharge_id, exc, exc_info=True)
        # Replace placeholder with error message so it never stays stuck
        if placeholder_id is not None and not edit_message(chat_id, placeholder_id, _AGENT_ERROR):
            send_message(chat_id, _AGENT_ERROR)
        elif placeholder_id is None:
            send_message(chat_id, _AGENT_ERROR)


def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Split long text into ≤4000-char chunks at newline boundaries."""
    if len(text) <= limit:
        return [text]
    chunks, buf = [], []
    for line in text.splitlines(keepends=True):
        if sum(len(l) for l in buf) + len(line) > limit:
            chunks.append("".join(buf))
            buf = []
        buf.append(line)
    if buf:
        chunks.append("".join(buf))
    return chunks


# ── Main dispatcher ───────────────────────────────────────────────────────────

def handle_update(update: dict) -> None:
    """Process one Telegram Update object."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = str(message["chat"]["id"])
    text    = (message.get("text") or "").strip()
    if not text:
        return  # ignore photos, stickers, voice, etc.

    db: Session = SessionLocal()
    try:
        sess, is_new = _get_or_create_session(db, chat_id)

        if is_new:
            # Brand-new user — welcome message already covers asking for number
            send_message(chat_id, _WELCOME)
            return

        status = sess.session_status
        if status == SessionStatus.AWAIT_MOBILE:
            _handle_await_mobile(db, sess, chat_id, text)
        elif status == SessionStatus.AWAIT_OTP:
            _handle_await_otp(db, sess, chat_id, text)
        elif status == SessionStatus.VERIFIED:
            _handle_verified(db, sess, chat_id, text)
        else:
            logger.warning("Unknown session status '%s' for chat_id=%s", status, chat_id)
            send_message(chat_id, _ASK_MOBILE)

    except Exception as exc:
        logger.error("handle_update error chat_id=%s: %s", chat_id, exc, exc_info=True)
        try:
            send_message(chat_id, "⚠️ Something went wrong. Please try again.")
        except Exception:
            pass
    finally:
        db.close()


# ── Long-polling loop ─────────────────────────────────────────────────────────

_stop_event = threading.Event()
_bot_thread: threading.Thread | None = None


def _polling_loop() -> None:
    logger.info("🤖 Telegram bot polling started")
    set_my_commands()

    # Drain any updates that accumulated while the server was offline so we
    # never replay stale messages from a previous session on restart.
    pending = get_updates(offset=0, timeout=0)
    if pending:
        offset = pending[-1]["update_id"] + 1
        logger.info("Skipped %d stale update(s) from previous session (offset → %d)", len(pending), offset)
    else:
        offset = 0

    _conflict_warned = False

    while not _stop_event.is_set():
        try:
            updates = get_updates(offset, timeout=20)
            if updates is None:
                # 409 — a previous crashed instance left an open poll at Telegram.
                # Telegram holds it for up to 20s. Back off and retry silently.
                if not _conflict_warned:
                    logger.warning(
                        "Telegram 409 Conflict: a previous session is still open at Telegram. "
                        "Will retry every 30s until it clears automatically."
                    )
                    _conflict_warned = True
                _stop_event.wait(30)
                continue
            _conflict_warned = False
            for upd in updates:
                try:
                    handle_update(upd)
                except Exception as exc:
                    logger.error("Error handling update %s: %s", upd.get("update_id"), exc)
                offset = upd["update_id"] + 1
        except Exception as exc:
            logger.error("Polling loop fatal error: %s", exc)
            time.sleep(5)  # back off before retry

    logger.info("🛑 Telegram bot polling stopped")


def start_polling() -> None:
    """Start the bot in a daemon background thread."""
    global _bot_thread
    _stop_event.clear()
    _bot_thread = threading.Thread(
        target=_polling_loop,
        name="telegram-bot",
        daemon=True,
    )
    _bot_thread.start()
    logger.info("✅ Telegram bot thread started")


def stop_polling() -> None:
    """Signal the polling loop to stop and wait for the thread to join."""
    _stop_event.set()
    if _bot_thread and _bot_thread.is_alive():
        _bot_thread.join(timeout=30)
    logger.info("Telegram bot thread stopped")
