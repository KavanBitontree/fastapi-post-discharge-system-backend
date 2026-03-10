"""
services/discharge_service.py
-------------------------------
Queue-based processor for discharge document uploads.

Processes files in order: reports → bills → prescriptions (sequential queue).

Each file is committed individually so that:
  - If file N fails, files 1…N-1 are already durably stored.
  - Admin can retry from file N without re-uploading already-stored docs.

Only when ALL jobs succeed is the discharge record marked `completed`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import Optional

from sqlalchemy.orm import Session

from models.discharge_history import DischargeHistory

logger = logging.getLogger(__name__)


# ── Job descriptor ─────────────────────────────────────────────────────────────

@dataclass
class FileJob:
    doc_type: str    # "report" | "bill" | "prescription"
    index: int       # 0-based within doc_type (used for resume tracking)
    filename: str
    content: bytes   # PDF bytes in memory
    strategy: str = "auto"


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclass
class DischargeResult:
    discharge_id: int
    status: str                        # "completed" | "failed"
    processed_reports: int
    processed_bills: int
    processed_prescriptions: int
    failed_at_type: Optional[str] = None
    failed_at_index: Optional[int] = None
    error: Optional[str] = None


# ── Per-type processors (sync — run inside a thread-pool endpoint) ─────────────

def _upload_to_cloudinary(content: bytes, filename: str, doc_type: str, patient_id: int) -> str:
    from services.storage.cloudinary_storage import upload_medical_pdf
    result = upload_medical_pdf(
        file=BytesIO(content),
        filename=filename,
        document_type=doc_type,
        patient_id=patient_id,
    )
    return result["secure_url"]


def _process_report(db: Session, discharge: DischargeHistory, job: FileJob) -> None:
    from services.parsers.report_parser import parse_pdf_from_memory
    from services.db_store.store_report import check_duplicate_report, store_report, parse_date

    url = _upload_to_cloudinary(job.content, job.filename, "report", discharge.patient_id)
    validated = parse_pdf_from_memory(BytesIO(job.content), job.filename, strategy=job.strategy)

    if not validated.header.report_name or not validated.test_results:
        raise ValueError(
            f"Report #{job.index + 1} ('{job.filename}') does not look like a medical report "
            f"— no report name or test results were extracted. Please upload a valid report PDF."
        )

    report_date = parse_date(validated.header.report_date)
    if check_duplicate_report(db, discharge.id, validated.header.report_name, report_date):
        raise ValueError(
            f"Report '{validated.header.report_name}' already exists for this discharge."
        )

    store_report(db, validated, discharge_id=discharge.id, report_url=url)


def _process_bill(db: Session, discharge: DischargeHistory, job: FileJob) -> None:
    from services.parsers.bill_parser import parse_bill_pdf_from_memory
    from services.db_store.store_bill import store_bill_for_discharge

    url = _upload_to_cloudinary(job.content, job.filename, "bill", discharge.patient_id)
    parsed = parse_bill_pdf_from_memory(BytesIO(job.content), job.filename, strategy=job.strategy)

    if not parsed.bill.invoice_number or not parsed.bill.total_amount or not parsed.line_items:
        raise ValueError(
            f"Bill #{job.index + 1} ('{job.filename}') does not look like a medical bill "
            f"— missing invoice number, total amount, or line items. Please upload a valid bill PDF."
        )

    store_bill_for_discharge(db, parsed, discharge_id=discharge.id, bill_url=url)


def _process_prescription(db: Session, discharge: DischargeHistory, job: FileJob) -> None:
    from services.parsers.prescription_parser import (
        parse_prescription_pdf_from_memory,
        ParsedPrescription, MedicationData, RecurrenceData, ScheduleData,
    )
    from services.db_store.store_prescription import store_prescription_for_discharge

    url = _upload_to_cloudinary(job.content, job.filename, "prescription", discharge.patient_id)
    parsed = parse_prescription_pdf_from_memory(BytesIO(job.content), job.filename, strategy=job.strategy)

    if not parsed.medications:
        raise ValueError(
            f"Prescription #{job.index + 1} ('{job.filename}') does not look like a prescription "
            f"— no medications were extracted. Please upload a valid prescription PDF."
        )

    # Normalise to ParsedPrescription if the parser returned a ValidatedPrescription
    if not hasattr(parsed, 'patient_id'):
        medications = [
            MedicationData(
                drug_name=m.drug_name,
                strength=m.strength,
                form_of_medicine=m.form_of_medicine,
                dosage=m.dosage,
                frequency_of_dose_per_day=m.frequency_of_dose_per_day,
                dosing_days=m.dosing_days,
                prescription_date=m.prescription_date,
                recurrence=RecurrenceData(
                    type=m.recurrence.type if m.recurrence else "daily",
                    every_n_days=m.recurrence.every_n_days if m.recurrence else None,
                    start_date_for_every_n_days=m.recurrence.start_date_for_every_n_days if m.recurrence else None,
                    cycle_take_days=m.recurrence.cycle_take_days if m.recurrence else None,
                    cycle_skip_days=m.recurrence.cycle_skip_days if m.recurrence else None,
                ),
                schedule=ScheduleData(
                    before_breakfast=m.schedule.before_breakfast if m.schedule else False,
                    after_breakfast=m.schedule.after_breakfast if m.schedule else False,
                    before_lunch=m.schedule.before_lunch if m.schedule else False,
                    after_lunch=m.schedule.after_lunch if m.schedule else False,
                    before_dinner=m.schedule.before_dinner if m.schedule else False,
                    after_dinner=m.schedule.after_dinner if m.schedule else False,
                ),
            )
            for m in parsed.medications
        ]
        parsed = ParsedPrescription(
            rx_number=parsed.header.rx_number,
            rx_date=parsed.header.rx_date,
            patient_id=discharge.patient_id,
            patient_email=None,
            patient_phone=getattr(parsed.header, "patient_phone", None),
            doctor_name=parsed.header.doctor_name,
            doctor_email=parsed.header.doctor_email,
            doctor_speciality=parsed.header.doctor_speciality,
            medications=medications,
        )
    else:
        parsed.patient_id = discharge.patient_id

    store_prescription_for_discharge(db, parsed, discharge_id=discharge.id)


_PROCESSORS = {
    "report":       _process_report,
    "bill":         _process_bill,
    "prescription": _process_prescription,
}

_PROGRESS_FIELD = {
    "report":       "processed_reports",
    "bill":         "processed_bills",
    "prescription": "processed_prescriptions",
}


# ── Public queue runner ────────────────────────────────────────────────────────

def run_discharge_queue(
    db: Session,
    discharge: DischargeHistory,
    jobs: list[FileJob],
) -> DischargeResult:
    """
    Process a sequential queue of FileJobs for a single discharge record.

    Each file is committed individually:
      ✓ success → increment progress counter, commit, continue
      ✗ failure → rollback current file, mark discharge as 'failed', stop

    Returns a DischargeResult. On failure the discharge_id is still valid and
    can be used to retry with the remaining files.
    """
    discharge.status = "processing"
    db.commit()

    for job in jobs:
        try:
            logger.info(
                "Discharge %d — processing %s #%d (%s)",
                discharge.id, job.doc_type, job.index + 1, job.filename,
            )
            _PROCESSORS[job.doc_type](db, discharge, job)

            # Atomically bump the progress counter and commit this file
            field = _PROGRESS_FIELD[job.doc_type]
            setattr(discharge, field, getattr(discharge, field) + 1)
            db.commit()

            logger.info("Discharge %d — %s #%d stored ✓", discharge.id, job.doc_type, job.index + 1)

        except Exception as exc:
            db.rollback()
            logger.error(
                "Discharge %d — %s #%d FAILED: %s",
                discharge.id, job.doc_type, job.index + 1, exc, exc_info=True,
            )
            discharge.status = "failed"
            db.commit()

            return DischargeResult(
                discharge_id=discharge.id,
                status="failed",
                processed_reports=discharge.processed_reports,
                processed_bills=discharge.processed_bills,
                processed_prescriptions=discharge.processed_prescriptions,
                failed_at_type=job.doc_type,
                failed_at_index=job.index,
                error=str(exc),
            )

    # ── All jobs completed ────────────────────────────────────────────────────
    discharge.discharge_date = date.today()
    discharge.status = "completed"
    db.commit()

    logger.info(
        "Discharge %d completed — reports=%d bills=%d prescriptions=%d",
        discharge.id,
        discharge.processed_reports,
        discharge.processed_bills,
        discharge.processed_prescriptions,
    )

    return DischargeResult(
        discharge_id=discharge.id,
        status="completed",
        processed_reports=discharge.processed_reports,
        processed_bills=discharge.processed_bills,
        processed_prescriptions=discharge.processed_prescriptions,
    )
