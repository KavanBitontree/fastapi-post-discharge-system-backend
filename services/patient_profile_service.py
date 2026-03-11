from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, asc
from models.patient import Patient
from models.discharge_history import DischargeHistory
from models.medication import Medication
from models.report import Report
from typing import Optional


def _get_discharge_pdfs_for_patient(db: Session, patient_id: int, discharge_id: int):
    """Return discharge PDF URLs for a patient-owned discharge record."""
    discharge = (
        db.query(DischargeHistory)
        .filter(
            DischargeHistory.id == discharge_id,
            DischargeHistory.patient_id == patient_id,
            DischargeHistory.status == "completed",
        )
        .first()
    )
    if not discharge:
        return None
    return {
        "discharge_id": discharge.id,
        "discharge_date": str(discharge.discharge_date) if discharge.discharge_date else None,
        "status": discharge.status,
        "discharge_summary_url": discharge.discharge_summary_url,
        "patient_friendly_summary_url": discharge.patient_friendly_summary_url,
        "insurance_ready_url": discharge.insurance_ready_url,
    }


class PatientProfileService:

    @staticmethod
    def get_profile(db: Session, patient_id: int):
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return None
        return {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone_number": patient.phone_number,
            "dob": str(patient.dob) if patient.dob else None,
            "gender": patient.gender,
            "address": patient.address,
            "created_at": (
                patient.created_at.isoformat() if patient.created_at else None
            ),
        }

    @staticmethod
    def update_profile(db: Session, patient_id: int, data):
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(patient, key, value)
        db.commit()
        db.refresh(patient)
        return {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone_number": patient.phone_number,
            "dob": str(patient.dob) if patient.dob else None,
            "gender": patient.gender,
            "address": patient.address,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
        }

    @staticmethod
    def get_dashboard(db: Session, patient_id: int):
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return None

        latest_discharge = (
            db.query(DischargeHistory)
            .filter(
                DischargeHistory.patient_id == patient_id,
                DischargeHistory.status == "completed",
            )
            .order_by(desc(DischargeHistory.discharge_date))
            .first()
        )

        discharge_count = (
            db.query(DischargeHistory)
            .filter(
                DischargeHistory.patient_id == patient_id,
                DischargeHistory.status == "completed",
            )
            .count()
        )

        active_meds = (
            db.query(Medication)
            .join(DischargeHistory, Medication.discharge_id == DischargeHistory.id)
            .filter(
                DischargeHistory.patient_id == patient_id,
                Medication.is_active == True,
            )
            .count()
        )

        total_reports = (
            db.query(Report)
            .join(DischargeHistory, Report.discharge_id == DischargeHistory.id)
            .filter(DischargeHistory.patient_id == patient_id)
            .count()
        )

        return {
            "patient": {
                "id": patient.id,
                "full_name": patient.full_name,
                "email": patient.email,
                "phone_number": patient.phone_number,
                "dob": str(patient.dob) if patient.dob else None,
                "gender": patient.gender,
                "address": patient.address,
            },
            "stats": {
                "discharge_count": discharge_count,
                "active_medications": active_meds,
                "total_reports": total_reports,
                "is_discharged": discharge_count > 0,
            },
            "latest_discharge": {
                "discharge_id": latest_discharge.id,
                "discharge_date": (
                    str(latest_discharge.discharge_date)
                    if latest_discharge.discharge_date
                    else None
                ),
                "processed_reports": latest_discharge.processed_reports,
                "processed_bills": latest_discharge.processed_bills,
                "processed_prescriptions": latest_discharge.processed_prescriptions,
            }
            if latest_discharge
            else None,
        }

    @staticmethod
    def get_discharge_history(
        db: Session, patient_id: int, page: int, size: int, sort: str
    ):
        query = db.query(DischargeHistory).filter(
            DischargeHistory.patient_id == patient_id,
            DischargeHistory.status == "completed",
        )
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
                "discharge_date": (
                    str(d.discharge_date) if d.discharge_date else None
                ),
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "processed_reports": d.processed_reports,
                "processed_bills": d.processed_bills,
                "processed_prescriptions": d.processed_prescriptions,
                "discharge_summary_url": d.discharge_summary_url,
                "patient_friendly_summary_url": d.patient_friendly_summary_url,
                "insurance_ready_url": d.insurance_ready_url,
            }
            for d in items
        ]
        return {"items": result, "total": total, "page": page, "size": size}

    @staticmethod
    def get_discharge_documents(db: Session, patient_id: int, discharge_id: int):
        discharge = (
            db.query(DischargeHistory)
            .options(
                joinedload(DischargeHistory.reports),
                joinedload(DischargeHistory.bills),
                joinedload(DischargeHistory.medications),
            )
            .filter(
                DischargeHistory.id == discharge_id,
                DischargeHistory.patient_id == patient_id,
                DischargeHistory.status == "completed",
            )
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

        return {
            "discharge_id": discharge.id,
            "discharge_date": (
                str(discharge.discharge_date) if discharge.discharge_date else None
            ),
            "status": discharge.status,
            "reports": reports,
            "bills": bills,
            "medications": medications,
        }

    @staticmethod
    def get_discharge_pdfs(db: Session, patient_id: int, discharge_id: int):
        """Return PDF Cloudinary URLs for a patient-owned discharge record."""
        discharge = (
            db.query(DischargeHistory)
            .filter(
                DischargeHistory.id == discharge_id,
                DischargeHistory.patient_id == patient_id,
                DischargeHistory.status == "completed",
            )
            .first()
        )
        if not discharge:
            return None
        return {
            "discharge_id": discharge.id,
            "discharge_date": (
                str(discharge.discharge_date) if discharge.discharge_date else None
            ),
            "status": discharge.status,
            "discharge_summary_url": discharge.discharge_summary_url,
            "patient_friendly_summary_url": discharge.patient_friendly_summary_url,
            "insurance_ready_url": discharge.insurance_ready_url,
        }

    @staticmethod
    def get_latest_discharge_pdfs(db: Session, patient_id: int):
        """Return PDF URLs for the patient's most recent completed discharge."""
        discharge = (
            db.query(DischargeHistory)
            .filter(
                DischargeHistory.patient_id == patient_id,
                DischargeHistory.status == "completed",
            )
            .order_by(desc(DischargeHistory.created_at))
            .first()
        )
        if not discharge:
            return None
        return {
            "discharge_id": discharge.id,
            "discharge_date": (
                str(discharge.discharge_date) if discharge.discharge_date else None
            ),
            "status": discharge.status,
            "discharge_summary_url": discharge.discharge_summary_url,
            "patient_friendly_summary_url": discharge.patient_friendly_summary_url,
            "insurance_ready_url": discharge.insurance_ready_url,
        }
