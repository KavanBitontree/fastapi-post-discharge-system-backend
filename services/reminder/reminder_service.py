"""
services/reminder_service.py
------------------------------
WhatsApp Medication Reminder — rewritten against real DB data.

Real data findings (discharge_id=3, 8 medications):
  - after_breakfast : Amlodipine, Furosemide, Aspirin, Folic Acid  → ONE grouped msg
  - after_lunch     : Losartan, Spironolactone                      → ONE grouped msg
  - after_dinner    : Losartan, Aspirin, Omega-3                    → ONE grouped msg
  - Rosuvastatin (id=53) has ALL schedule flags = false → logged as warning

Cron flow:
  1. Fires at each slot time (07/08/12/13/19/20)
  2. Checks next_notify_at per schedule row — only sends if now >= next_notify_at
     (or next_notify_at is NULL = never sent yet)
  3. Groups ALL due medications for a patient into ONE WhatsApp message
  4. After send: updates latest_notified_at = now, next_notify_at = next slot time
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, joinedload

from models.discharge_history import DischargeHistory
from models.medication import Medication
from models.medication_schedule import MedicationSchedule
from models.patient import Patient
from core.enums import MedicineForm

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

TIMEZONE = ZoneInfo("Asia/Kolkata")

# (schedule_column_flag, display_label, cron_hour)
MEAL_SLOTS: list[tuple[str, str, int]] = [
    ("before_breakfast", "Before Breakfast", 7),
    ("after_breakfast",  "After Breakfast",  8),
    ("before_lunch",     "Before Lunch",     11),
    ("after_lunch",      "After Lunch",      12),
    ("before_dinner",    "Before Dinner",    18),
    ("after_dinner",     "After Dinner",     21),
]

SLOT_LABELS: dict[str, str] = {f: l for f, l, _ in MEAL_SLOTS}
SLOT_ORDER:  list[str]      = [f for f, _, _ in MEAL_SLOTS]

FORM_EMOJI: dict[str, str] = {
    MedicineForm.TABLET:    "💊",
    MedicineForm.CAPSULE:   "💊",
    MedicineForm.SYRUP:     "🍶",
    MedicineForm.INJECTION: "💉",
    MedicineForm.DROPS:     "💧",
    MedicineForm.CREAM:     "🧴",
    MedicineForm.OINTMENT:  "🧴",
    MedicineForm.INHALER:   "💨",
    MedicineForm.POWDER:    "🫙",
    MedicineForm.OTHER:     "💊",
}


# ─── Recurrence ───────────────────────────────────────────────────────────────

def _is_active_today(med: Medication, today: date) -> bool:
    rec = med.recurrence

    if rec is None:
        return True

    rtype = rec.type.lower().strip()

    if rtype == "daily":
        return True

    if rtype == "every_n_days":
        n = rec.every_n_days or 1
        start = rec.start_date_for_every_n_days or med.created_at.date()
        delta = (today - start).days
        return delta >= 0 and delta % n == 0

    if rtype == "cyclic":
        take = rec.cycle_take_days or 1
        skip = rec.cycle_skip_days or 0
        anchor = med.prescription_date or med.created_at.date()
        delta = (today - anchor).days
        if delta < 0:
            return False
        return (delta % (take + skip)) < take

    logger.warning("Unknown recurrence type '%s' on med id=%s — treating as daily", rec.type, med.id)
    return True


def _dosing_complete(med: Medication, today: date) -> bool:
    if med.dosing_days is None:
        return False
    anchor = med.prescription_date or med.created_at.date()
    return (today - anchor).days >= med.dosing_days


def _days_remaining(med: Medication, today: date) -> Optional[int]:
    if med.dosing_days is None:
        return None
    anchor = med.prescription_date or med.created_at.date()
    return max(0, med.dosing_days - (today - anchor).days)


# ─── next_notify_at logic ────────────────────────────────────────────────────

def _compute_next_notify_at(schedule: MedicationSchedule, after: datetime) -> Optional[datetime]:
    """
    Look at which slot flags are True on this schedule,
    then return the datetime of the next one AFTER *after*.

    Example: schedule has after_lunch=True, after_dinner=True
      - If called at 13:01 → returns today 20:00
      - If called at 20:01 → returns tomorrow 13:00
    """
    today = after.date()
    tomorrow = today + timedelta(days=1)

    # Check remaining slots today
    for flag, _, hour in MEAL_SLOTS:
        if not getattr(schedule, flag, False):
            continue
        candidate = datetime(today.year, today.month, today.day, hour, 0, tzinfo=TIMEZONE)
        if candidate > after:
            return candidate

    # Wrap to tomorrow — find first active slot
    for flag, _, hour in MEAL_SLOTS:
        if not getattr(schedule, flag, False):
            continue
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, 0, tzinfo=TIMEZONE)

    # No slots set at all (e.g. Rosuvastatin with all false)
    return None


# ─── Should we send NOW? ──────────────────────────────────────────────────────

def _is_due_now(schedule: MedicationSchedule, slot: str, now: datetime) -> bool:
    """
    Two-gate check:
    1. The slot flag must be True on this schedule row
    2. next_notify_at must be NULL (never sent) OR <= now
       → prevents double-firing if cron runs slightly early/late
    """
    if not getattr(schedule, slot, False):
        return False

    if schedule.next_notify_at is None:
        return True  # never sent yet → send now

    # Normalize to aware datetime for comparison
    nna = schedule.next_notify_at
    if nna.tzinfo is None:
        nna = nna.replace(tzinfo=TIMEZONE)

    return now >= nna


# ─── Telegram message builder ────────────────────────────────────────────────

def build_telegram_message(
    patient: Patient,
    due_items: list[dict],   # [{"medication": Medication, "slot": str}]
    now: datetime,
) -> str:
    """
    Builds ONE grouped Telegram message (HTML) for ALL medications due at this slot.
    """
    today      = now.date()
    slot       = due_items[0]["slot"]
    slot_label = SLOT_LABELS.get(slot, "Scheduled Time")
    time_str   = now.strftime("%I:%M %p")
    count      = len(due_items)

    lines: list[str] = [
        f"👋 Hello <b>{patient.full_name}</b>!",
        f"🕐 It's <b>{time_str}</b> — time for your <b>{slot_label}</b> medicine{'s' if count > 1 else ''}.\n",
    ]

    for idx, item in enumerate(due_items, 1):
        med: Medication = item["medication"]

        emoji    = FORM_EMOJI.get(med.form_of_medicine, "💊") if med.form_of_medicine else "💊"
        form_str = f" ({med.form_of_medicine.value.title()})" if med.form_of_medicine else ""
        strength = f" {med.strength}" if med.strength else ""
        days_left = _days_remaining(med, today)

        lines.append(f"{emoji} <b>{idx}. {med.drug_name}{strength}{form_str}</b>")
        lines.append(f"   • Dose      : {med.dosage}")
        if days_left is not None:
            lines.append(f"   • Days left : {days_left} day(s)")
        lines.append("")

    lines += [
        "─────────────────────────",
        "✅ Take all medicines as prescribed.",
        "❓ You can ask me any question about your medication.",
    ]

    return "\n".join(lines)


def send_telegram_message(chat_id: str, body: str) -> bool:
    """Send a reminder message via the Telegram bot."""
    try:
        from services.telegram.sender import send_message
        return send_message(chat_id, body, parse_mode="HTML")
    except Exception as exc:
        logger.error("Telegram reminder send failed → chat_id=%s : %s", chat_id, exc)
        return False


# ─── Stale discharge purge ────────────────────────────────────────────────────

def purge_stale_discharges(db: Session) -> int:
    """
    Delete discharge_history rows stuck in 'pending' or 'failed' for > 24 hours.
    Returns the number of rows deleted.
    """
    from models.discharge_history import DischargeHistory

    try:
        cutoff = datetime.now(TIMEZONE) - timedelta(hours=24)
        deleted = (
            db.query(DischargeHistory)
            .filter(
                DischargeHistory.status.in_(["pending", "failed"]),
                DischargeHistory.created_at <= cutoff,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        if deleted:
            logger.info("Purged %d stale discharge record(s) older than 24 h", deleted)
        return deleted
    except Exception as exc:
        db.rollback()
        logger.error("Stale discharge purge failed: %s", exc, exc_info=True)
        return 0


# ─── Core query ───────────────────────────────────────────────────────────────

def collect_due_medications(
    db: Session,
    discharge_id: int,
    slot: str,
    now: datetime,
) -> list[dict]:
    """
    Returns list of {"medication": Medication, "slot": str}
    for every medication due at *slot* right now.

    Uses next_notify_at to avoid double-sending.
    """
    today = now.date()

    meds: list[Medication] = (
        db.query(Medication)
        .options(
            joinedload(Medication.schedule),
            joinedload(Medication.recurrence),
        )
        .filter(
            Medication.discharge_id == discharge_id,
            Medication.is_active == True,
        )
        .all()
    )

    due = []
    for med in meds:
        # Gate 1: dosing course complete?
        if _dosing_complete(med, today):
            logger.debug("med id=%s dosing complete — skip", med.id)
            continue

        # Gate 2: recurrence says skip today?
        if not _is_active_today(med, today):
            continue

        sched: Optional[MedicationSchedule] = med.schedule
        if sched is None:
            logger.warning("med id=%s '%s' has no schedule row — skip", med.id, med.drug_name)
            continue

        # Gate 3: is this slot active AND is it time to send?
        if not _is_due_now(sched, slot, now):
            # Log specifically if ALL flags are false (data issue like Rosuvastatin id=53)
            if not any(getattr(sched, f, False) for f, _, _ in MEAL_SLOTS):
                logger.warning(
                    "med id=%s '%s' has ALL schedule flags=false — will never be reminded!",
                    med.id, med.drug_name
                )
            continue

        due.append({"medication": med, "slot": slot})

    return due


# ─── DB updater ───────────────────────────────────────────────────────────────

def update_schedule_after_send(
    db: Session,
    schedule: MedicationSchedule,
    sent_at: datetime,
) -> None:
    """
    After a successful send:
      latest_notified_at = sent_at
      next_notify_at     = next slot time for THIS schedule's active flags
    """
    next_dt = _compute_next_notify_at(schedule, sent_at)

    schedule.latest_notified_at = sent_at
    schedule.next_notify_at = next_dt
    db.commit()

    next_str = next_dt.isoformat() if next_dt else "None (no active slots!)"
    logger.info(
        "Schedule id=%s updated → latest_notified_at=%s | next_notify_at=%s",
        schedule.id, sent_at.isoformat(), next_str,
    )


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def run_reminder_for_slot(db: Session, slot: str) -> None:
    """
    Called by cron at each meal slot.
    Sends Telegram reminders only to patients with a VERIFIED TelegramSession.
    Groups all due meds per patient into ONE message.
    """
    from models.telegram_session import TelegramSession
    from core.enums import SessionStatus

    now = datetime.now(TIMEZONE)
    logger.info("\u25b6 Reminder job \u2014 slot='%s'  time=%s", slot, now.strftime("%H:%M"))

    # Only patients with a verified Telegram session receive reminders
    verified = (
        db.query(TelegramSession)
        .filter(TelegramSession.session_status == SessionStatus.VERIFIED)
        .all()
    )

    if not verified:
        logger.info("No verified Telegram patients \u2014 slot '%s' skipped", slot)
        return

    did_to_chat: dict[int, str] = {
        s.discharge_id: s.telegram_id
        for s in verified
        if s.discharge_id
    }

    discharges: list[DischargeHistory] = (
        db.query(DischargeHistory)
        .options(joinedload(DischargeHistory.patient))
        .filter(
            DischargeHistory.id.in_(list(did_to_chat.keys())),
        )
        .all()
    )

    sent_count = 0
    for discharge in discharges:
        patient = discharge.patient
        if not patient or not patient.is_active:
            continue

        chat_id = did_to_chat.get(discharge.id)
        if not chat_id:
            continue

        due = collect_due_medications(db, discharge.id, slot, now)
        if not due:
            continue

        message = build_telegram_message(patient, due, now)
        success = send_telegram_message(chat_id, message)

        if success:
            sent_count += 1
            for item in due:
                sched = item["medication"].schedule
                if sched:
                    update_schedule_after_send(db, sched, now)

    logger.info("\u2714 Slot '%s' done \u2014 %d patient(s) notified via Telegram", slot, sent_count)


# ─── Single cron orchestrator (all slots, window-based) ──────────────────────

def run_all_due_reminders(db: Session, window_minutes: int = 20) -> dict:
    """
    Called by a single external cron endpoint (POST /cron/reminders).

    For every verified Telegram patient, collects all medications whose
    next_notify_at falls within:
        next_notify_at  <=  now  <=  next_notify_at + window_minutes

    This ensures a late cron hit (e.g. 8:20 for an 8:00 notification) still
    delivers the reminder, while stale notifications (older than the window)
    are skipped to avoid confusing double-sends.
    """
    from models.telegram_session import TelegramSession
    from core.enums import SessionStatus

    now    = datetime.now(TIMEZONE)
    window = timedelta(minutes=window_minutes)

    logger.info(
        "\u25b6 Cron reminder job \u2014 time=%s  window=%d min",
        now.strftime("%H:%M"), window_minutes,
    )

    verified = (
        db.query(TelegramSession)
        .filter(TelegramSession.session_status == SessionStatus.VERIFIED)
        .all()
    )

    if not verified:
        logger.info("No verified Telegram patients \u2014 cron skipped")
        return {"notified": 0, "skipped": 0}

    did_to_chat: dict[int, str] = {
        s.discharge_id: s.telegram_id
        for s in verified
        if s.discharge_id
    }

    discharges: list[DischargeHistory] = (
        db.query(DischargeHistory)
        .options(joinedload(DischargeHistory.patient))
        .filter(
            DischargeHistory.id.in_(list(did_to_chat.keys())),
        )
        .all()
    )

    # hour → schedule flag, e.g. 20 → "after_dinner"
    hour_to_flag: dict[int, str] = {hour: flag for flag, _, hour in MEAL_SLOTS}

    sent_count = 0
    skip_count = 0

    for discharge in discharges:
        patient = discharge.patient
        if not patient or not patient.is_active:
            skip_count += 1
            continue

        chat_id = did_to_chat.get(discharge.id)
        if not chat_id:
            skip_count += 1
            continue

        today = now.date()

        meds: list[Medication] = (
            db.query(Medication)
            .options(
                joinedload(Medication.schedule),
                joinedload(Medication.recurrence),
            )
            .filter(
                Medication.discharge_id == discharge.id,
                Medication.is_active == True,
            )
            .all()
        )

        due: list[dict] = []

        for med in meds:
            if _dosing_complete(med, today):
                continue
            if not _is_active_today(med, today):
                continue

            sched = med.schedule
            if not sched or sched.next_notify_at is None:
                continue

            nna = sched.next_notify_at
            if nna.tzinfo is None:
                nna = nna.replace(tzinfo=TIMEZONE)

            # Window check: due in the past ≤ window_minutes ago
            if not (nna <= now <= nna + window):
                continue

            # Map notify hour → slot flag
            slot = hour_to_flag.get(nna.hour)
            if not slot:
                logger.warning(
                    "med id=%s: next_notify_at hour=%d doesn't match any slot",
                    med.id, nna.hour,
                )
                continue

            # Confirm the slot flag is actually enabled on the schedule
            if not getattr(sched, slot, False):
                continue

            due.append({"medication": med, "slot": slot})

        if not due:
            skip_count += 1
            continue

        message = build_telegram_message(patient, due, now)
        success = send_telegram_message(chat_id, message)

        if success:
            sent_count += 1
            for item in due:
                s = item["medication"].schedule
                if s:
                    update_schedule_after_send(db, s, now)
        else:
            skip_count += 1

    logger.info(
        "\u2714 Cron reminder done \u2014 %d notified, %d skipped",
        sent_count, skip_count,
    )
    return {"notified": sent_count, "skipped": skip_count}