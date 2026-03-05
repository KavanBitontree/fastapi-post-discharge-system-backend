"""
report_store_db.py
------------------
Database storage operations for medical reports.
Handles patient lookup, duplicate checking, and data persistence.
"""

from typing import Optional, Dict, List
from sqlalchemy.orm import Session
from datetime import datetime


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
        Patient object if found, None otherwise
    """
    from models.patient import Patient
    return db.query(Patient).filter(Patient.email == email).first()


def check_duplicate_report(db: Session, patient_id: int, report_name: str, report_date: datetime) -> bool:
    """
    Check if a report already exists for this patient.
    
    Parameters
    ----------
    db : Session
        Database session
    patient_id : int
        Patient ID
    report_name : str
        Report name/title
    report_date : datetime
        Report date
        
    Returns
    -------
    bool
        True if duplicate exists, False otherwise
    """
    from models.report import Report
    
    existing = db.query(Report).filter(
        Report.patient_id == patient_id,
        Report.report_name == report_name,
        Report.report_date == report_date
    ).first()
    
    return existing is not None


def store_report(
    db: Session,
    header: Dict,
    rows: List[Dict],
    patient_id: int,
    report_url: Optional[str] = None,
):
    """
    Store report and test results in database.
    
    Parameters
    ----------
    db : Session
        Database session
    header : dict
        Report header data
    rows : list of dict
        Test results data
    patient_id : int
        Patient ID
    report_url : str, optional
        URL to stored PDF file
        
    Returns
    -------
    Report
        Created Report object with populated ID
        
    Raises
    ------
    ValueError
        If required fields are missing
    """
    from models.report import Report
    from models.report_description import ReportDescription
    
    # Validate required fields
    if not header.get("report_name"):
        raise ValueError("report_name is required but not found in header")
    
    # Create Report
    report = Report(
        patient_id=patient_id,
        report_name=header.get("report_name"),
        report_date=header.get("report_date"),
        collection_date=header.get("collection_date"),
        received_date=header.get("received_date"),
        specimen_type=header.get("specimen_type"),
        status=header.get("status"),
        report_url=report_url,
    )
    db.add(report)
    db.flush()  # Get report.id
    
    # Create ReportDescription rows
    descriptions = [
        ReportDescription(
            report_id=report.id,
            patient_id=patient_id,
            test_name=row["test_name"],
            section=row.get("section"),
            normal_result=row.get("normal_result"),
            abnormal_result=row.get("abnormal_result"),
            flag=row.get("flag"),
            units=row.get("units"),
            reference_range_low=row.get("reference_range_low"),
            reference_range_high=row.get("reference_range_high"),
        )
        for row in rows
    ]
    db.bulk_save_objects(descriptions)
    db.commit()
    db.refresh(report)
    
    return report
