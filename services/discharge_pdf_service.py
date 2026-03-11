"""
services/discharge_pdf_service.py
-----------------------------------
Service layer for fetching discharge PDF URLs from the database.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from models.discharge_history import DischargeHistory


class DischargePdfService:

    @staticmethod
    def get_by_id(db: Session, discharge_id: int) -> Optional[DischargeHistory]:
        """Return a DischargeHistory row by primary key, or None if not found."""
        return (
            db.query(DischargeHistory)
            .filter(DischargeHistory.id == discharge_id)
            .first()
        )

    @staticmethod
    def get_latest_for_patient(db: Session, patient_id: int) -> Optional[DischargeHistory]:
        """Return the most recent DischargeHistory for a given patient, or None."""
        return (
            db.query(DischargeHistory)
            .filter(DischargeHistory.patient_id == patient_id)
            .order_by(DischargeHistory.created_at.desc())
            .first()
        )
