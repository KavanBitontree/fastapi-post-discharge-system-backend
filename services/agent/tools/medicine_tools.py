"""
services/agent/tools/medicine_tools.py
----------------------------------------
SQLAlchemy-based tools for the Medicine & Reminder specialist node.
"""

from __future__ import annotations
from datetime import datetime, date
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from sqlalchemy.orm import Session, joinedload

from models.medication import Medication
from models.medication_schedule import MedicationSchedule
from models.recurrence_type import RecurrenceType
from services.reminder.reminder_service import (
    MEAL_SLOTS,
    SLOT_LABELS,
    _is_active_today,
    _dosing_complete,
    _days_remaining,
    _compute_next_notify_at,
)

TIMEZONE = ZoneInfo("Asia/Kolkata")


def _recurrence_str(rec: RecurrenceType | None) -> str:
    """Render all RecurrenceType columns as a human-readable string."""
    if rec is None:
        return "daily"
    detail = rec.type
    if rec.every_n_days:
        start = rec.start_date_for_every_n_days or "N/A"
        detail = f"every {rec.every_n_days} days (starting {start})"
    elif rec.cycle_take_days and rec.cycle_skip_days:
        detail = f"cyclic — take {rec.cycle_take_days} days, skip {rec.cycle_skip_days} days"
    return detail


def _schedule_str(sched: MedicationSchedule | None) -> str:
    """Render all MedicationSchedule slot flags as a human-readable string."""
    if sched is None:
        return "Not configured"
    active_slots = [
        SLOT_LABELS[flag]
        for flag, _, _ in MEAL_SLOTS
        if getattr(sched, flag, False)
    ]
    return ", ".join(active_slots) if active_slots else "No slots configured"


def _med_header(m: Medication, today: date) -> str:
    """Render all Medication columns including doctor and status."""
    form = m.form_of_medicine.value.title() if m.form_of_medicine else "N/A"
    status = "Active" if m.is_active else "Inactive"
    days_left = _days_remaining(m, today)
    days_str = str(days_left) if days_left is not None else "ongoing"
    doctor_name = m.doctor.full_name if m.doctor else "Not on record"
    return (
        f"Medication: {m.drug_name} [{status}]\n"
        f"  Strength      : {m.strength or 'N/A'}\n"
        f"  Form          : {form}\n"
        f"  Dosage        : {m.dosage}\n"
        f"  Frequency     : {m.frequency_of_dose_per_day}x per day\n"
        f"  Dosing days   : {m.dosing_days or 'ongoing'}\n"
        f"  Days remaining: {days_str}\n"
        f"  Recurrence    : {_recurrence_str(m.recurrence)}\n"
        f"  Schedule      : {_schedule_str(m.schedule)}\n"
        f"  Prescribed by : {doctor_name}\n"
        f"  Prescribed on : {m.prescription_date or 'N/A'}"
    )


def build_medicine_tools(discharge_id: int, db: Session) -> list:

    @tool
    def get_all_medications() -> str:
        """
        Get all active medications prescribed to the patient.
        Use when patient asks 'what medicines am I taking?' or 'my prescriptions'.
        """
        meds = (
            db.query(Medication)
            .options(
                joinedload(Medication.schedule),
                joinedload(Medication.recurrence),
                joinedload(Medication.doctor),
            )
            .filter(Medication.discharge_id == discharge_id, Medication.is_active == True)
            .all()
        )
        if not meds:
            return "No active medications found."

        today = date.today()
        lines = ["Active medications:"]
        for m in meds:
            lines.append("")
            lines.append(_med_header(m, today))
        return "\n".join(lines)

    @tool
    def get_medication_schedule() -> str:
        """
        Get the full schedule showing when each medicine should be taken (before/after meals).
        Use when patient asks 'when do I take my medicines?' or 'my medication schedule'.
        """
        meds = (
            db.query(Medication)
            .options(joinedload(Medication.schedule))
            .filter(Medication.discharge_id == discharge_id, Medication.is_active == True)
            .all()
        )
        if not meds:
            return "No active medications found."

        lines = ["Medication schedule:"]
        for m in meds:
            slot_str = _schedule_str(m.schedule)
            lines.append(f"  • {m.drug_name} {m.strength or ''}: {slot_str}")

        return "\n".join(lines)

    @tool
    def get_medication_details(drug_name: str) -> str:
        """
        Get complete details about a specific medication.
        Use when patient asks about a specific drug like 'tell me about Amlodipine'.

        Args:
            drug_name: Name or partial name of the drug (e.g. 'Amlodipine', 'aspirin')
        """
        med = (
            db.query(Medication)
            .options(
                joinedload(Medication.schedule),
                joinedload(Medication.recurrence),
                joinedload(Medication.doctor),
            )
            .filter(
                Medication.discharge_id == discharge_id,
                Medication.drug_name.ilike(f"%{drug_name}%"),
                Medication.is_active == True,
            )
            .first()
        )
        if not med:
            return f"No active medication matching '{drug_name}' found."

        return _med_header(med, date.today())

    @tool
    def get_last_reminder() -> str:
        """
        Get when the last medication reminder was sent.
        Use when patient asks 'when was my last reminder?' or 'did I get a reminder today?'
        """
        meds = (
            db.query(Medication)
            .options(joinedload(Medication.schedule))
            .filter(Medication.discharge_id == discharge_id, Medication.is_active == True)
            .all()
        )
        results = []
        for m in meds:
            sched = m.schedule
            if sched and sched.latest_notified_at:
                lna = sched.latest_notified_at
                if lna.tzinfo is None:
                    lna = lna.replace(tzinfo=TIMEZONE)
                results.append((m.drug_name, lna))

        if not results:
            return "No reminders have been sent yet."

        results.sort(key=lambda x: x[1], reverse=True)
        lines = ["Last reminders sent:"]
        for drug, dt in results:
            lines.append(f"  • {drug}: {dt.strftime('%d %b %Y at %I:%M %p')}")
        return "\n".join(lines)

    @tool
    def get_next_reminder() -> str:
        """
        Get when the next medication reminder is scheduled.
        Use when patient asks 'when is my next reminder?' or 'when will I be reminded?'
        """
        meds = (
            db.query(Medication)
            .options(joinedload(Medication.schedule))
            .filter(Medication.discharge_id == discharge_id, Medication.is_active == True)
            .all()
        )
        now = datetime.now(TIMEZONE)
        results = []
        for m in meds:
            sched = m.schedule
            if not sched:
                continue
            nna = sched.next_notify_at
            if nna:
                if nna.tzinfo is None:
                    nna = nna.replace(tzinfo=TIMEZONE)
                if nna > now:
                    results.append((m.drug_name, nna))
            else:
                computed = _compute_next_notify_at(sched, now)
                if computed:
                    results.append((m.drug_name, computed))

        if not results:
            return "No upcoming reminders found. Check if medications have schedule slots configured."

        results.sort(key=lambda x: x[1])
        lines = ["Upcoming reminders:"]
        for drug, dt in results:
            lines.append(f"  • {drug}: {dt.strftime('%d %b %Y at %I:%M %p')}")
        return "\n".join(lines)

    @tool
    def get_todays_medications() -> str:
        """
        Get which medications are due today and at what times.
        Use when patient asks 'what do I take today?' or 'today's medicines'.
        """
        today = date.today()
        meds = (
            db.query(Medication)
            .options(joinedload(Medication.schedule), joinedload(Medication.recurrence))
            .filter(Medication.discharge_id == discharge_id, Medication.is_active == True)
            .all()
        )

        due_by_slot: dict[str, list[str]] = {flag: [] for flag, _, _ in MEAL_SLOTS}

        for m in meds:
            if _dosing_complete(m, today) or not _is_active_today(m, today):
                continue
            sched = m.schedule
            if not sched:
                continue
            for flag, _, _ in MEAL_SLOTS:
                if getattr(sched, flag, False):
                    due_by_slot[flag].append(f"{m.drug_name} {m.strength or ''}")

        lines = [f"Today's medication plan ({today.strftime('%d %b %Y')}):"]
        any_due = False
        for flag, label, _ in MEAL_SLOTS:
            if due_by_slot[flag]:
                any_due = True
                lines.append(f"\n  {label}:")
                for drug in due_by_slot[flag]:
                    lines.append(f"    • {drug}")

        if not any_due:
            return "No medications due today."
        return "\n".join(lines)

    @tool
    def get_all_medication_data() -> str:
        """
        Get the COMPLETE medication history for the patient — all medications (active and inactive)
        with full schedule, recurrence pattern, and dosing details.
        Use this for a comprehensive overview of all prescriptions and medication history.
        """
        meds = (
            db.query(Medication)
            .options(
                joinedload(Medication.schedule),
                joinedload(Medication.recurrence),
                joinedload(Medication.doctor),
            )
            .filter(Medication.discharge_id == discharge_id)
            .order_by(Medication.prescription_date.desc().nullslast(), Medication.created_at.desc())
            .all()
        )
        if not meds:
            return "No medication records found for this patient."

        today_date = date.today()
        sections = [_med_header(m, today_date) for m in meds]
        return "=== Complete Medication History ===\n\n" + "\n\n".join(sections)

    return [
        get_all_medications,
        get_medication_schedule,
        get_medication_details,
        get_last_reminder,
        get_next_reminder,
        get_todays_medications,
        get_all_medication_data,
    ]