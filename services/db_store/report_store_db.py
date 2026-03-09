"""
report_store_db.py
------------------
Stores validated report data to Neon DB.

Design principles:
  - Trusts LLM-extracted + Pydantic-validated values directly (no regex re-parsing).
  - Pre-store validation guarantees data integrity before any DB write.
  - Bulk-inserts all ReportDescription rows in a single transaction.
  - All helpers are pure string/float operations - no regex.
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from models.report import Report
from models.report_description import ReportDescription
from services.llm_validators.report_llm_validator import ExtractedReport, TestResult


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ReportStoreError(ValueError):
    """Raised when data fails pre-store validation."""
    pass


# ---------------------------------------------------------------------------
# Pre-store validation
# ---------------------------------------------------------------------------

def pre_store_validate(extracted: ExtractedReport) -> None:
    """
    Validate extracted report data before writing to DB.
    Raises ReportStoreError with a descriptive message on failure.

    Checks:
      - header.report_name is present and non-empty
      - at least one test result exists
      - each result has test_name + at least one result value
    """
    h = extracted.header

    if not h.report_name or not h.report_name.strip():
        raise ReportStoreError("report_name is missing from the extracted report header.")

    if not extracted.test_results:
        raise ReportStoreError("No test results were extracted from this report.")

    invalid_rows: List[str] = []
    for i, t in enumerate(extracted.test_results):
        if not t.test_name or not t.test_name.strip():
            invalid_rows.append(f"Row {i}: empty test_name")
        elif not t.normal_result and not t.abnormal_result:
            invalid_rows.append(f"Row {i} ({t.test_name!r}): no result value")

    if invalid_rows:
        summary = "; ".join(invalid_rows[:5])
        raise ReportStoreError(
            f"{len(invalid_rows)} invalid row(s) in extracted report: {summary}"
        )


# ---------------------------------------------------------------------------
# Duplicate check
# ---------------------------------------------------------------------------

def check_duplicate_report(
    db: Session,
    patient_id: int,
    report_name: str,
    report_date: Optional[str],
) -> bool:
    """Return True if this exact report already exists for the patient."""
    from models.report import Report as ReportModel

    query = db.query(ReportModel).filter(
        ReportModel.patient_id  == patient_id,
        ReportModel.report_name == report_name,
    )
    if report_date:
        parsed = _parse_iso_date(report_date)
        if parsed:
            query = query.filter(ReportModel.report_date == parsed)

    return query.first() is not None


# ---------------------------------------------------------------------------
# Main store function
# ---------------------------------------------------------------------------

def store_report(
    db: Session,
    extracted: ExtractedReport,
    patient_id: int,
    report_url: str,
) -> Report:
    """
    Persist a validated report to Neon DB.

    Creates one Report row + bulk-inserts all ReportDescription rows
    in a single transaction.

    The LLM + Pydantic validators already normalised every field:
      - flag         -> None / "H" / "L" / "**"
      - units        -> clean unit string or None
      - ref_low/high -> plain numeric string or None
      - normal/abnormal -> correctly assigned based on flag

    Parameters
    ----------
    db          : SQLAlchemy session
    extracted   : ExtractedReport already passed through validate_extracted_report()
    patient_id  : patient this report belongs to
    report_url  : path/URL to the stored PDF

    Returns
    -------
    Report ORM object with id populated.
    """
    h = extracted.header

    report = Report(
        patient_id      = patient_id,
        report_name     = _safe_str(h.report_name) or "Unknown Report",
        report_date     = _parse_iso_date(h.report_date),
        collection_date = _parse_iso_date(h.collection_date),
        received_date   = _parse_iso_date(h.received_date),
        specimen_type   = _safe_str(h.specimen_type),
        status          = _safe_str(h.status),
        report_url      = report_url,
    )
    db.add(report)
    db.flush()  # Populate report.id before bulk insert

    descriptions = []
    for t in extracted.test_results:
        descriptions.append(
            ReportDescription(
                report_id            = report.id,
                patient_id           = patient_id,
                test_name            = _safe_str(t.test_name),
                section              = _safe_str(t.section),
                normal_result        = _safe_str(t.normal_result),
                abnormal_result      = _safe_str(t.abnormal_result),
                flag                 = _safe_str(t.flag),
                units                = _safe_str(t.units),
                reference_range_low  = _safe_numeric_str(t.reference_range_low),
                reference_range_high = _safe_numeric_str(t.reference_range_high),
            )
        )

    db.bulk_save_objects(descriptions)
    db.commit()
    db.refresh(report)
    return report


# ---------------------------------------------------------------------------
# Private helpers (no regex)
# ---------------------------------------------------------------------------

def _safe_str(value: Optional[str]) -> Optional[str]:
    """Strip whitespace; return None for empty strings."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _safe_numeric_str(value: Optional[str]) -> Optional[str]:
    """
    Accept only a value that can be parsed as a float.
    Strips whitespace. Returns None if not a valid number.
    This guards against the LLM accidentally storing unit strings
    in reference_range_low/high despite Pydantic validation.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        float(s)
        return s
    except ValueError:
        return None


def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 string into datetime. Returns None on failure."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
