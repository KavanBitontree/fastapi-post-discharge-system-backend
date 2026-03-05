"""
LLM Prescription Validator  —  LangChain/Groq-backed gap-filler
------------------------------------------------------
Takes the raw PDF text and the Stage-1 :class:`ParsedPrescription` from
``parsers.prescription_parser`` and asks the LLM to fill every ``None`` field,
handle synonym labels, and parse free-text medication instructions like
"take 1 paracetamol after lunch for 12 days".

Usage::

    from parsers.prescription_parser import parse_prescription_pdf, extract_raw_text
    from llm_validators.llm_prescription_validator import validate_prescription

    raw   = extract_raw_text("rx.pdf")
    rough = parse_prescription_pdf("rx.pdf")
    final = validate_prescription(raw, rough)    # ParsedPrescription, all fields populated
"""

import json
from datetime import date, datetime
from typing import Optional

from langsmith import traceable
from langchain_core.messages import SystemMessage, HumanMessage

from core.config import settings  # noqa: F401 — sets LangSmith os.environ vars
from core.llm_init import llm
from parsers.prescription_parser import (
    ParsedPrescription,
    MedicationData,
    RecurrenceData,
    ScheduleData,
)
from core.enums import MedicineForm

# LLM bound to JSON mode — guarantees the response is a JSON object
_json_llm = llm.bind(response_format={"type": "json_object"})


def _parse_json(content: str) -> dict:
    """Strip optional markdown code fences then parse JSON."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        content = content.rsplit("```", 1)[0]
    return json.loads(content.strip())

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """You are a clinical pharmacist and medical-data extraction specialist.
You are given raw text from a hospital prescription PDF and a partial JSON object that
a regex parser already extracted.  Your task is to return a COMPLETE JSON object by:

1. Filling every null / missing field by reading the raw text.
2. Resolving common label synonyms:
   - "Patient" can also appear as: Victim, Client, Member, Beneficiary, Insured, Patient Name
   - "Doctor" can also appear as: Prescribing Physician, Physician, Prescriber, Consulting Doctor, Attending Physician
   - "Prescription #" can also appear as: Rx No, Rx #, Ref #, Prescription Number, Script No
   - "Prescription Date" can also appear as: Rx Date, Date Issued, Date of Prescription, Issue Date
   - "Speciality" / "Specialty" can also appear as: Department, Specialization, Field
3. Parsing FREE-TEXT medication instructions such as:
   "take 1 paracetamol after lunch for 12 days"
   → drug_name: Paracetamol, dosage: "1 tab", after_lunch: true, dosing_days: 12, form: "tablet"
4. Mapping timing to schedule booleans:
   - "before breakfast" / "empty stomach" / "fasting" → before_breakfast: true
   - "after breakfast" / "with breakfast"              → after_breakfast: true
   - "before lunch"                                    → before_lunch: true
   - "after lunch" / "with lunch"                      → after_lunch: true
   - "before dinner"                                   → before_dinner: true
   - "after dinner" / "with dinner" / "bedtime" / "before bed" / "before sleep" / "at night" / "before bedtime" → after_dinner: true
5. Inferring form_of_medicine from drug name / free text if not stated.
   ONLY use one of: tablet, capsule, syrup, injection, drops, cream, ointment, inhaler, powder, other
6. Inferring recurrence from instructions:
   - "daily" / "every day" / "once a day" etc.  → type: "daily"
   - "every N days"                              → type: "every_n_days", every_n_days: N
   - "Mon-Fri" / "weekdays" / "5 days a week"   → type: "cyclic", cycle_take_days: 5, cycle_skip_days: 2
   - default to "daily" when unclear
7. Setting any field to null if you genuinely cannot find the information.

Return ONLY the JSON object described below — no markdown, no explanation.

JSON schema:
{
  "rx_number":        "string or null",
  "rx_date":          "YYYY-MM-DD or null",
  "patient_email":    "string or null",
  "patient_phone":    "string or null",
  "doctor_name":      "string or null",
  "doctor_email":     "string or null",
  "doctor_speciality": "string or null",
  "medications": [
    {
      "drug_name":                   "string",
      "strength":                    "string or null",
      "form_of_medicine":            "tablet|capsule|syrup|injection|drops|cream|ointment|inhaler|powder|other",
      "dosage":                      "string (e.g. '1 tab', '5ml', '2 puffs')",
      "frequency_of_dose_per_day":   integer (>=1),
      "dosing_days":                 integer or null,
      "prescription_date":           "YYYY-MM-DD or null",
      "recurrence": {
        "type":                      "daily|every_n_days|cyclic",
        "every_n_days":              integer or null,
        "start_date_for_every_n_days": "YYYY-MM-DD or null",
        "cycle_take_days":           integer or null,
        "cycle_skip_days":           integer or null
      },
      "schedule": {
        "before_breakfast": boolean,
        "after_breakfast":  boolean,
        "before_lunch":     boolean,
        "after_lunch":      boolean,
        "before_dinner":    boolean,
        "after_dinner":     boolean
      }
    }
  ]
}
"""


def _parsed_to_hint(parsed: ParsedPrescription) -> dict:
    return {
        "rx_number": parsed.rx_number,
        "rx_date": str(parsed.rx_date) if parsed.rx_date else None,
        "patient_email": parsed.patient_email,
        "patient_phone": parsed.patient_phone,
        "doctor_name": parsed.doctor_name,
        "doctor_email": parsed.doctor_email,
        "doctor_speciality": parsed.doctor_speciality,
        "medications": [
            {
                "drug_name": m.drug_name,
                "strength": m.strength,
                "form_of_medicine": m.form_of_medicine.value if m.form_of_medicine else None,
                "dosage": m.dosage,
                "frequency_of_dose_per_day": m.frequency_of_dose_per_day,
                "dosing_days": m.dosing_days,
                "prescription_date": str(m.prescription_date) if m.prescription_date else None,
                "recurrence": {
                    "type": m.recurrence.type,
                    "every_n_days": m.recurrence.every_n_days,
                    "start_date_for_every_n_days": str(m.recurrence.start_date_for_every_n_days)
                    if m.recurrence.start_date_for_every_n_days else None,
                    "cycle_take_days": m.recurrence.cycle_take_days,
                    "cycle_skip_days": m.recurrence.cycle_skip_days,
                },
                "schedule": {
                    "before_breakfast": m.schedule.before_breakfast,
                    "after_breakfast": m.schedule.after_breakfast,
                    "before_lunch": m.schedule.before_lunch,
                    "after_lunch": m.schedule.after_lunch,
                    "before_dinner": m.schedule.before_dinner,
                    "after_dinner": m.schedule.after_dinner,
                },
            }
            for m in parsed.medications
        ],
    }


def _user_prompt(raw_text: str, parsed: ParsedPrescription) -> str:
    return (
        "=== RAW PDF TEXT ===\n"
        + raw_text
        + "\n\n=== PARTIAL PARSE (fill in the nulls / improve accuracy) ===\n"
        + json.dumps(_parsed_to_hint(parsed), indent=2)
    )


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

_VALID_FORMS = {f.value for f in MedicineForm}


def _to_date(val) -> Optional[date]:
    if not val:
        return None
    try:
        return datetime.strptime(str(val), "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_form(val: str) -> MedicineForm:
    if val and val.lower() in _VALID_FORMS:
        return MedicineForm(val.lower())
    return MedicineForm.OTHER


def _build_medication(row: dict, rx_date: Optional[date]) -> MedicationData:
    rec_raw = row.get("recurrence", {})
    sch_raw = row.get("schedule", {})

    recurrence = RecurrenceData(
        type=rec_raw.get("type", "daily"),
        every_n_days=rec_raw.get("every_n_days"),
        start_date_for_every_n_days=_to_date(rec_raw.get("start_date_for_every_n_days")) or rx_date,
        cycle_take_days=rec_raw.get("cycle_take_days"),
        cycle_skip_days=rec_raw.get("cycle_skip_days"),
    )

    schedule = ScheduleData(
        before_breakfast=bool(sch_raw.get("before_breakfast", False)),
        after_breakfast=bool(sch_raw.get("after_breakfast", False)),
        before_lunch=bool(sch_raw.get("before_lunch", False)),
        after_lunch=bool(sch_raw.get("after_lunch", False)),
        before_dinner=bool(sch_raw.get("before_dinner", False)),
        after_dinner=bool(sch_raw.get("after_dinner", False)),
    )

    freq = row.get("frequency_of_dose_per_day") or sum([
        schedule.before_breakfast, schedule.after_breakfast,
        schedule.before_lunch, schedule.after_lunch,
        schedule.before_dinner, schedule.after_dinner,
    ]) or 1

    return MedicationData(
        drug_name=str(row.get("drug_name", "Unknown")),
        strength=row.get("strength"),
        form_of_medicine=_to_form(row.get("form_of_medicine", "")),
        dosage=str(row.get("dosage", "1")),
        frequency_of_dose_per_day=int(freq),
        dosing_days=row.get("dosing_days"),
        prescription_date=_to_date(row.get("prescription_date")) or rx_date,
        recurrence=recurrence,
        schedule=schedule,
    )


def _merge(original: ParsedPrescription, llm_data: dict) -> ParsedPrescription:
    def pick(current, llm_val):
        return current if current is not None else llm_val

    original.rx_number = pick(original.rx_number, llm_data.get("rx_number"))
    original.rx_date = pick(original.rx_date, _to_date(llm_data.get("rx_date")))
    original.patient_email = pick(original.patient_email, llm_data.get("patient_email"))
    original.patient_phone = pick(original.patient_phone, llm_data.get("patient_phone"))
    original.doctor_name = pick(original.doctor_name, llm_data.get("doctor_name"))
    original.doctor_email = pick(original.doctor_email, llm_data.get("doctor_email"))
    original.doctor_speciality = pick(original.doctor_speciality, llm_data.get("doctor_speciality"))

    llm_meds = llm_data.get("medications", [])
    if llm_meds and len(llm_meds) >= len(original.medications):
        original.medications = [_build_medication(m, original.rx_date) for m in llm_meds]
    elif llm_meds:
        for i, orig_med in enumerate(original.medications):
            if i < len(llm_meds):
                llm_med = llm_meds[i]
                if orig_med.strength is None:
                    orig_med.strength = llm_med.get("strength")
                if orig_med.form_of_medicine == MedicineForm.OTHER:
                    orig_med.form_of_medicine = _to_form(llm_med.get("form_of_medicine", ""))
                if orig_med.dosing_days is None:
                    orig_med.dosing_days = llm_med.get("dosing_days")
                if orig_med.prescription_date is None:
                    orig_med.prescription_date = _to_date(llm_med.get("prescription_date"))

    return original


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@traceable(name="validate_prescription", run_type="llm")
def validate_prescription(raw_pdf_text: str, parsed: ParsedPrescription) -> ParsedPrescription:
    """
    Stage-2 LLM validation.

    Sends *raw_pdf_text* plus the Stage-1 *parsed* result to the shared LLM
    and merges the response back into *parsed*, filling any ``None`` fields
    and resolving free-text medication instructions.

    Returns the mutated :class:`ParsedPrescription` object (same instance).
    """
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=_user_prompt(raw_pdf_text, parsed)),
    ]

    response = _json_llm.invoke(messages)
    llm_data = _parse_json(response.content)
    return _merge(parsed, llm_data)