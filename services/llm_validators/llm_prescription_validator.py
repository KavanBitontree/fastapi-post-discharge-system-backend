"""
LLM Prescription Validator (Chunked)
-------------------------------------
Simplified prescription extraction with chunking support.
"""

from typing import Optional, List
from datetime import date

from core.llm_init import llm
from services.parsers.prescription_parser import (
    ParsedPrescription,
    MedicationData,
    RecurrenceData,
    ScheduleData,
)
from core.enums import MedicineForm
from schemas.prescription_schemas import (
    MedicationSchedule,
    MedicationRecurrence,
    Medication,
    PrescriptionHeader,
    ValidatedPrescription,
)


# ── Prompts ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a prescription data extraction system.
Extract structured data from medical prescriptions and return it in JSON format.

HEADER FIELDS:
- rx_number: Prescription number
- rx_date: Prescription date in YYYY-MM-DD format
- patient_phone: Patient phone number
- doctor_name: Prescribing doctor name
- doctor_email: Doctor email
- doctor_speciality: Doctor specialization

MEDICATIONS - Extract EVERY medication with:
- drug_name: Medication name (REQUIRED)
- strength: Dose with unit (e.g., "5 mg", "10 mg")
- form_of_medicine: tablet, capsule, syrup, injection, drops, cream, ointment, inhaler, powder, other
- dosage: Amount per dose (e.g., "1", "2")
- frequency_of_dose_per_day: Number of times per day (count all timings)
- dosing_days: Duration in days
- prescription_date: Date in YYYY-MM-DD format

RECURRENCE:
- type: "daily" (default), "every_n_days", or "cyclic"
- For "Alternate" or "Every 2 Days": type="every_n_days", every_n_days=2
- For "Mon–Fri Only": type="cyclic", cycle_take_days=5, cycle_skip_days=2

SCHEDULE (set true when mentioned):
- before_breakfast, after_breakfast, before_lunch, after_lunch, before_dinner, after_dinner
- "After Lunch After Dinner" → after_lunch=true, after_dinner=true, frequency=2
- "Before Bedtime" → after_dinner=true

CRITICAL: Extract ALL medications. Do not skip any."""


def extract_prescription_from_chunk(
    text_chunk: str,
    chunk_index: int,
    total_chunks: int,
) -> ValidatedPrescription:
    """
    Extract prescription data from a text chunk.
    """
    # Use temperature=0 for more deterministic structured output
    from core.llm_init import llm as base_llm
    deterministic_llm = base_llm.bind(temperature=0)
    structured_llm = deterministic_llm.with_structured_output(ValidatedPrescription)
    
    if chunk_index == 0:
        prompt = f"""Extract the complete header and all medications from this prescription.

This is chunk 1 of {total_chunks}.

{text_chunk}

Return complete header information and all medications found in this chunk."""
    else:
        prompt = f"""Extract ONLY medications from this prescription chunk. Use minimal header.

This is chunk {chunk_index + 1} of {total_chunks}.

{text_chunk}

Return a ValidatedPrescription with minimal header (rx_number="Chunk {chunk_index + 1}") and all medications from this chunk."""
    
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    
    try:
        result = structured_llm.invoke(messages)
        print(f"[llm] Chunk {chunk_index + 1}: extracted {len(result.medications)} medications")
        return result
    except Exception as e:
        error_msg = str(e)
        print(f"[llm] Chunk {chunk_index + 1}: extraction failed, attempting recovery")
        
        # Try to recover from markdown-wrapped JSON or failed generation
        if "failed_generation" in error_msg or "tool_use_failed" in error_msg:
            try:
                import re
                import json
                
                # Extract the failed generation using multiple patterns
                patterns = [
                    r"'failed_generation': '(.+?)'(?:,|})",
                    r'"failed_generation": "(.+?)"(?:,|})',
                    r"'failed_generation':\s*'(.+)'",
                    r'"failed_generation":\s*"(.+)"',
                ]
                
                partial_json = None
                for pattern in patterns:
                    match = re.search(pattern, error_msg, re.DOTALL)
                    if match:
                        partial_json = match.group(1)
                        break
                
                if partial_json:
                    # Clean up escape sequences
                    partial_json = partial_json.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")
                    
                    print(f"[llm] Attempting to parse: {partial_json[:100]}...")
                    
                    # Check if LLM returned markdown text instead of JSON
                    if partial_json.startswith("**") or partial_json.startswith("##"):
                        print(f"[llm] LLM returned markdown text instead of JSON - cannot recover")
                        raise ValueError("LLM returned markdown text instead of structured JSON")
                    
                    # Remove markdown code fences if present
                    if partial_json.startswith("```json"):
                        partial_json = partial_json.split("\n", 1)[1] if "\n" in partial_json else partial_json
                    if partial_json.startswith("```"):
                        partial_json = partial_json.split("\n", 1)[1] if "\n" in partial_json else partial_json
                    if "```" in partial_json:
                        partial_json = partial_json.split("```")[0]
                    
                    # Check if it's wrapped in Groq's tool call format
                    if '"name": "ValidatedPrescription"' in partial_json or "'name': 'ValidatedPrescription'" in partial_json:
                        # Extract the arguments object
                        args_match = re.search(r'"arguments":\s*({.+)', partial_json, re.DOTALL)
                        if args_match:
                            partial_json = args_match.group(1)
                            print("[llm] Extracted arguments from Groq tool call wrapper")
                    
                    # Try to parse as JSON
                    try:
                        data = json.loads(partial_json.strip())
                        
                        # Convert to ValidatedPrescription
                        header = PrescriptionHeader(**data.get("header", {}))
                        medications = [Medication(**m) for m in data.get("medications", [])]
                        
                        result = ValidatedPrescription(header=header, medications=medications)
                        print(f"[llm] Chunk {chunk_index + 1}: recovered {len(result.medications)} medications")
                        return result
                    except (json.JSONDecodeError, KeyError, TypeError) as parse_err:
                        print(f"[llm] JSON recovery failed: {parse_err}")
            except Exception as recovery_err:
                print(f"[llm] Recovery failed: {recovery_err}")
        
        print(f"[llm] Chunk {chunk_index + 1}: returning empty result - {error_msg[:200]}")
        # Return minimal valid result instead of failing
        return ValidatedPrescription(
            header=PrescriptionHeader(
                rx_number=f"Chunk {chunk_index + 1}" if chunk_index > 0 else None
            ),
            medications=[],
        )


def merge_prescription_results(results: List[Optional[ValidatedPrescription]]) -> ParsedPrescription:
    """
    Merge results from multiple chunks into a single ParsedPrescription.
    """
    valid_results = [r for r in results if r is not None]
    
    if not valid_results:
        raise ValueError("No valid results to merge")
    
    first = valid_results[0]
    
    # Combine all medications
    all_meds = []
    for result in valid_results:
        all_meds.extend(result.medications)
    
    print(f"[llm] Merged {len(valid_results)} chunks: {len(all_meds)} total medications")
    
    # Convert to ParsedPrescription format
    def _to_date(val) -> Optional[date]:
        if not val:
            return None
        try:
            from datetime import datetime
            return datetime.strptime(str(val), "%Y-%m-%d").date()
        except ValueError:
            return None
    
    def _to_form(val: str) -> MedicineForm:
        mapping = {
            "tablet": MedicineForm.TABLET,
            "capsule": MedicineForm.CAPSULE,
            "syrup": MedicineForm.SYRUP,
            "injection": MedicineForm.INJECTION,
            "drops": MedicineForm.DROPS,
            "cream": MedicineForm.CREAM,
            "ointment": MedicineForm.OINTMENT,
            "inhaler": MedicineForm.INHALER,
            "powder": MedicineForm.POWDER,
        }
        return mapping.get((val or "").lower(), MedicineForm.OTHER)
    
    # Create ParsedPrescription (dataclass)
    parsed = ParsedPrescription()
    parsed.rx_number = first.header.rx_number
    parsed.rx_date = _to_date(first.header.rx_date)
    parsed.patient_phone = first.header.patient_phone
    parsed.doctor_name = first.header.doctor_name
    parsed.doctor_email = first.header.doctor_email
    parsed.doctor_speciality = first.header.doctor_speciality
    # patient_id and patient_email will be set by the route
    
    parsed.medications = [
        MedicationData(
            drug_name=med.drug_name,
            strength=med.strength,
            form_of_medicine=_to_form(med.form_of_medicine),
            dosage=med.dosage,
            frequency_of_dose_per_day=med.frequency_of_dose_per_day,
            dosing_days=med.dosing_days,
            prescription_date=_to_date(med.prescription_date),
            recurrence=RecurrenceData(
                type=med.recurrence.type,
                every_n_days=med.recurrence.every_n_days,
                start_date_for_every_n_days=_to_date(med.recurrence.start_date_for_every_n_days),
                cycle_take_days=med.recurrence.cycle_take_days,
                cycle_skip_days=med.recurrence.cycle_skip_days,
            ),
            schedule=ScheduleData(
                before_breakfast=med.schedule.before_breakfast,
                after_breakfast=med.schedule.after_breakfast,
                before_lunch=med.schedule.before_lunch,
                after_lunch=med.schedule.after_lunch,
                before_dinner=med.schedule.before_dinner,
                after_dinner=med.schedule.after_dinner,
            ),
        )
        for med in all_meds
    ]
    
    print(f"[llm] Created ParsedPrescription with {len(parsed.medications)} medications")
    print(f"[llm] Type check: {type(parsed).__name__}")
    
    return parsed


# Re-export for backward compatibility
def validate_prescription(raw_pdf_text: str, parsed: ParsedPrescription) -> ParsedPrescription:
    """
    DEPRECATED: Legacy function for backward compatibility.
    """
    result = extract_prescription_from_chunk(raw_pdf_text, 0, 1)
    
    # Merge with existing
    parsed.rx_number = result.header.rx_number or parsed.rx_number
    parsed.rx_date = _to_date(result.header.rx_date) or parsed.rx_date
    
    if result.medications:
        parsed.medications = merge_prescription_results([result]).medications
    
    return parsed


def _to_date(val) -> Optional[date]:
    if not val:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(str(val), "%Y-%m-%d").date()
    except ValueError:
        return None