"""
routes/reminder_routes.py
--------------------------
Manual trigger endpoints — useful for testing without waiting for cron.

POST /reminders/trigger/{slot}                  → fire a slot for all verified Telegram patients
POST /reminders/trigger/{slot}/{patient_id}     → fire a slot for one specific patient
GET  /reminders/slots                           → list valid slot names
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.enums import SessionStatus
from services.reminder.reminder_service import (
    MEAL_SLOTS,
    collect_due_medications,
    build_telegram_message,
    run_reminder_for_slot,
    send_telegram_message,
    update_schedule_after_send,
)
from models.patient import Patient
from models.telegram_session import TelegramSession
from datetime import datetime
from zoneinfo import ZoneInfo

router = APIRouter(prefix="/reminders", tags=["Reminders"])

VALID_SLOTS = {flag for flag, _, _ in MEAL_SLOTS}
TIMEZONE    = ZoneInfo("Asia/Kolkata")


@router.post("/trigger/{slot}")
def trigger_slot(slot: str, db: Session = Depends(get_db)):
    """Fire the reminder job for a specific slot across all verified Telegram patients."""
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid slot '{slot}'. Valid: {sorted(VALID_SLOTS)}",
        )
    run_reminder_for_slot(db, slot)
    return {"message": f"Reminder job for slot '{slot}' completed."}


@router.post("/trigger/{slot}/{patient_id}")
def trigger_slot_for_patient(
    slot: str,
    patient_id: int,
    db: Session = Depends(get_db),
):
    """Fire the reminder for a specific slot + patient (handy for testing)."""
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid slot '{slot}'. Valid: {sorted(VALID_SLOTS)}",
        )

    patient: Patient | None = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient id={patient_id} not found")

    # Resolve Telegram chat_id from verified session
    tg_session: TelegramSession | None = (
        db.query(TelegramSession)
        .filter(
            TelegramSession.patient_id == patient_id,
            TelegramSession.session_status == SessionStatus.VERIFIED,
        )
        .first()
    )
    if not tg_session:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Patient id={patient_id} has no verified Telegram session. "
                "Ask them to start the bot and complete verification first."
            ),
        )

    now = datetime.now(TIMEZONE)
    due = collect_due_medications(db, patient_id, slot, now)

    if not due:
        return {
            "message": f"No medications due for patient id={patient_id} at slot '{slot}'.",
            "sent": False,
        }

    message = build_telegram_message(patient, due, now)
    success = send_telegram_message(tg_session.telegram_id, message)

    if success:
        for item in due:
            sched = item["medication"].schedule
            if sched:
                update_schedule_after_send(db, sched, now)

    return {
        "message": "Reminder sent via Telegram." if success else "Send failed — check logs.",
        "sent": success,
        "patient": patient.full_name,
        "telegram_chat_id": tg_session.telegram_id,
        "slot": slot,
        "medications": [item["medication"].drug_name for item in due],
        "preview": message,
    }


@router.get("/slots")
def list_slots():
    """List all valid meal slot names."""
    return [
        {"flag": flag, "label": label, "fire_hour": f"{hour:02d}:00"}
        for flag, label, hour in MEAL_SLOTS
    ]
