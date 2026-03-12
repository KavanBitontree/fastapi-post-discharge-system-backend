"""
store_report.py
------------------
Database storage operations for medical reports.
Handles patient lookup, duplicate checking, and data persistence.

NOTE: Date string → datetime parsing now lives here, since the parser
no longer returns datetime objects (LLM returns ISO/MM-DD-YYYY strings).
"""

from typing import Optional, Dict, List
from sqlalchemy.orm import Session
from datetime import datetime


# ── Date Parsing ──────────────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%d/%m/%Y %H:%M",    # DD/MM/YYYY HH:MM (Asian/EU format - try first)
    "%m/%d/%Y %H:%M",    # MM/DD/YYYY HH:MM (US format)
    "%d/%m/%Y",          # DD/MM/YYYY
    "%m/%d/%Y",          # MM/DD/YYYY
    "%Y-%m-%dT%H:%M:%S", # ISO with T
    "%Y-%m-%d %H:%M:%S", # ISO with space
    "%Y-%m-%d",          # ISO date only
    "%d-%m-%Y %H:%M",    # DD-MM-YYYY HH:MM
    "%d-%m-%Y",          # DD-MM-YYYY
]


def parse_date(value: Optional[str]) -> Optional[datetime]:
    """
    Parse a date string returned by the LLM into a datetime object.

    Tries multiple common formats. Returns None if parsing fails or
    value is None/empty.

    Parameters
    ----------
    value : str or None
        Date string from LLM output.

    Returns
    -------
    datetime or None
    """
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    print(f"[store_db] Warning: could not parse date '{value}' — storing as None.")
    return None


# ── Patient Lookups ───────────────────────────────────────────────────────────

def get_patient_by_email(db: Session, email: str):
    """
    Look up a patient by email address.

    Parameters
    ----------
    db : Session
        Database session
    email : str
        Patient email address

    Returns
    -------
    Patient or None
    """
    from models.patient import Patient
    return db.query(Patient).filter(Patient.email == email).first()


def get_patient_by_id(db: Session, patient_id: int):
    """
    Look up a patient by ID.

    Parameters
    ----------
    db : Session
        Database session
    patient_id : int
        Patient ID

    Returns
    -------
    Patient or None
    """
    from models.patient import Patient
    return db.query(Patient).filter(Patient.id == patient_id).first()


# ── Duplicate Check ───────────────────────────────────────────────────────────

def check_duplicate_report(
    db: Session,
    discharge_id: int,
    report_name: str,
    report_date: datetime,
) -> bool:
    """
    Check if a report already exists for this discharge.
    """
    from models.report import Report

    existing = db.query(Report).filter(
        Report.discharge_id == discharge_id,
        Report.report_name == report_name,
        Report.report_date == report_date,
    ).first()

    return existing is not None


# ── Store Report ──────────────────────────────────────────────────────────────

def store_report(
    db: Session,
    validated_report,
    discharge_id: int,
    report_url: Optional[str] = None,
) -> object:
    """
    Store a validated report and its test results in the database.

    Accepts a ValidatedReport Pydantic object directly — no need for
    callers to manually unpack header dicts or row lists.

    Parameters
    ----------
    db : Session
    validated_report : ValidatedReport
        Structured report from LLM extraction.
    patient_id : int
    report_url : str, optional
        URL to stored PDF file.

    Returns
    -------
    Report
        Created Report ORM object with populated ID.

    Raises
    ------
    ValueError
        If report_name is missing.
    """
    from models.report import Report
    from models.report_description import ReportDescription

    header = validated_report.header
    rows = validated_report.test_results

    if not header.report_name:
        raise ValueError("report_name is required but not found in extracted header.")

    # Create Report row
    report = Report(
        discharge_id=discharge_id,
        report_name=header.report_name,
        report_date=parse_date(header.report_date),
        collection_date=parse_date(header.collection_date),
        received_date=parse_date(header.received_date),
        specimen_type=header.specimen_type,
        status=header.status,
        report_url=report_url,
    )
    db.add(report)
    db.flush()  # Populate report.id

    # Create ReportDescription rows
    descriptions = [
        ReportDescription(
            report_id=report.id,
            discharge_id=discharge_id,
            test_name=row.test_name,
            section=row.section,
            normal_result=row.normal_result,
            abnormal_result=row.abnormal_result,
            flag=row.flag,
            units=row.units,
            reference_range_low=row.reference_range_low,
            reference_range_high=row.reference_range_high,
        )
        for row in rows
    ]
    db.bulk_save_objects(descriptions)
    db.commit()
    db.refresh(report)

    return report
