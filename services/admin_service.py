from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, desc, asc
from models.discharge_history import DischargeHistory
from models.patient import Patient
from datetime import date
from typing import Optional


class AdminService:

    @staticmethod
    def get_dashboard_stats(db: Session):
        total_patients = (
            db.query(Patient).filter(Patient.id != 0, Patient.is_active == True).count()
        )

        # Patient IDs that have at least one completed discharge
        discharged_subq = (
            db.query(DischargeHistory.patient_id)
            .filter(DischargeHistory.status == "completed")
            .distinct()
            .subquery()
        )
        discharged_patients = (
            db.query(Patient)
            .filter(Patient.id.in_(discharged_subq), Patient.id != 0)
            .count()
        )
        active_patients = total_patients - discharged_patients

        total_discharges = (
            db.query(DischargeHistory)
            .filter(DischargeHistory.status == "completed")
            .count()
        )

        # Recent 5 completed discharges
        recent = (
            db.query(DischargeHistory)
            .options(joinedload(DischargeHistory.patient))
            .filter(DischargeHistory.status == "completed")
            .order_by(desc(DischargeHistory.discharge_date))
            .limit(5)
            .all()
        )

        recent_list = [
            {
                "discharge_id": d.id,
                "patient_id": d.patient_id,
                "patient_name": d.patient.full_name if d.patient else "Unknown",
                "patient_email": d.patient.email if d.patient else "",
                "discharge_date": str(d.discharge_date) if d.discharge_date else None,
                "processed_reports": d.processed_reports,
                "processed_bills": d.processed_bills,
                "processed_prescriptions": d.processed_prescriptions,
            }
            for d in recent
        ]

        return {
            "total_patients": total_patients,
            "active_patients": active_patients,
            "discharged_patients": discharged_patients,
            "total_discharges": total_discharges,
            "recent_discharges": recent_list,
        }

    @staticmethod
    def get_discharge_history(
        db: Session,
        search: Optional[str],
        page: int,
        size: int,
        sort: str,
        date_from: Optional[date],
        date_to: Optional[date],
    ):
        query = (
            db.query(DischargeHistory)
            .join(Patient, DischargeHistory.patient_id == Patient.id)
            .options(joinedload(DischargeHistory.patient))
            .filter(DischargeHistory.status == "completed")
        )

        if search:
            query = query.filter(
                or_(
                    Patient.full_name.ilike(f"%{search}%"),
                    Patient.email.ilike(f"%{search}%"),
                )
            )

        if date_from:
            query = query.filter(DischargeHistory.discharge_date >= date_from)
        if date_to:
            query = query.filter(DischargeHistory.discharge_date <= date_to)

        total = query.count()
        order_col = (
            asc(DischargeHistory.discharge_date)
            if sort == "asc"
            else desc(DischargeHistory.discharge_date)
        )
        skip = (page - 1) * size
        items = query.order_by(order_col).offset(skip).limit(size).all()

        result = [
            {
                "discharge_id": d.id,
                "patient_id": d.patient_id,
                "patient_name": d.patient.full_name if d.patient else "Unknown",
                "patient_email": d.patient.email if d.patient else "",
                "discharge_date": str(d.discharge_date) if d.discharge_date else None,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "processed_reports": d.processed_reports,
                "processed_bills": d.processed_bills,
                "processed_prescriptions": d.processed_prescriptions,
            }
            for d in items
        ]

        return {"items": result, "total": total, "page": page, "size": size}

    @staticmethod
    def get_discharge_documents(db: Session, discharge_id: int):
        discharge = (
            db.query(DischargeHistory)
            .options(
                joinedload(DischargeHistory.patient),
                joinedload(DischargeHistory.reports),
                joinedload(DischargeHistory.bills),
                joinedload(DischargeHistory.medications),
            )
            .filter(DischargeHistory.id == discharge_id)
            .first()
        )

        if not discharge:
            return None

        reports = [
            {
                "id": r.id,
                "report_name": r.report_name,
                "report_date": r.report_date.isoformat() if r.report_date else None,
                "specimen_type": r.specimen_type,
                "status": r.status,
                "report_url": r.report_url,
            }
            for r in (discharge.reports or [])
        ]

        bills = [
            {
                "id": b.id,
                "invoice_number": b.invoice_number,
                "invoice_date": str(b.invoice_date) if b.invoice_date else None,
                "total_amount": float(b.total_amount) if b.total_amount else 0.0,
                "bill_url": b.bill_url,
            }
            for b in (discharge.bills or [])
        ]

        medications = [
            {
                "id": m.id,
                "drug_name": m.drug_name,
                "dosage": m.dosage,
                "strength": m.strength,
                "form_of_medicine": (
                    m.form_of_medicine.value if m.form_of_medicine else None
                ),
                "frequency_of_dose_per_day": m.frequency_of_dose_per_day,
                "is_active": m.is_active,
            }
            for m in (discharge.medications or [])
        ]

        patient = discharge.patient
        return {
            "discharge_id": discharge.id,
            "patient_id": discharge.patient_id,
            "patient_name": patient.full_name if patient else "Unknown",
            "patient_email": patient.email if patient else "",
            "discharge_date": (
                str(discharge.discharge_date) if discharge.discharge_date else None
            ),
            "status": discharge.status,
            "reports": reports,
            "bills": bills,
            "medications": medications,
        }

    @staticmethod
    def get_discharge_pdfs(db: Session, discharge_id: int):
        """Return all three PDF URLs for any discharge (admin use)."""
        discharge = (
            db.query(DischargeHistory)
            .options(joinedload(DischargeHistory.patient))
            .filter(
                DischargeHistory.id == discharge_id,
                DischargeHistory.status == "completed",
            )
            .first()
        )
        if not discharge:
            return None
        patient = discharge.patient
        return {
            "discharge_id": discharge.id,
            "patient_id": patient.id if patient else None,
            "patient_name": patient.full_name if patient else None,
            "discharge_date": (
                str(discharge.discharge_date) if discharge.discharge_date else None
            ),
            "status": discharge.status,
            "discharge_summary_url": discharge.discharge_summary_url,
            "patient_friendly_summary_url": discharge.patient_friendly_summary_url,
            "insurance_ready_url": discharge.insurance_ready_url,
        }
