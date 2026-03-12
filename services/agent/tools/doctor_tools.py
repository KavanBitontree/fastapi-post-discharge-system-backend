"""
services/agent/tools/doctor_tools.py
--------------------------------------
SQLAlchemy-based tools for the Doctors specialist node.
All tools receive patient_id + db session via closure (injected at graph build time).
"""

from __future__ import annotations
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from models.patient_doctor import PatientDoctor
from models.doctor import Doctor


def _doctor_block(doc: Doctor) -> str:
    """Render all Doctor columns, always showing every field with fallback."""
    return (
        f"Doctor: {doc.full_name}\n"
        f"  Speciality : {doc.speciality or 'Not on record'}\n"
        f"  Email      : {doc.email or 'Not on record'}\n"
        f"  Phone      : {doc.phone_no or 'Not on record'}"
    )


def build_doctor_tools(discharge_id: int, db: Session) -> list:
    """
    Factory — returns tool list bound to this discharge's session.
    Called once per request when building the graph.
    """

    @tool
    def get_my_doctors() -> str:
        """
        Get the list of doctors assigned to this patient with full contact details.
        Use this when the patient asks 'who is my doctor?', 'what is my doctor's name?',
        'give me my doctor's email', 'contact my doctor', 'doctor details', etc.
        """
        rows = (
            db.query(PatientDoctor)
            .filter(PatientDoctor.discharge_id == discharge_id)
            .all()
        )
        if not rows:
            return "No doctors are currently assigned to you."

        sections = []
        for pd in rows:
            if pd.doctor:
                sections.append(_doctor_block(pd.doctor))

        if not sections:
            return "No doctor details available."
        return "Your assigned doctor(s):\n\n" + "\n\n".join(sections)

    @tool
    def get_doctor_by_name(name: str) -> str:
        """
        Get details of a specific doctor by name (partial match).
        Use when the patient mentions a doctor's name and wants their contact.

        Args:
            name: Full or partial name of the doctor (e.g. 'Ali', 'Dr Smith')
        """
        rows = (
            db.query(PatientDoctor)
            .join(Doctor, Doctor.id == PatientDoctor.doctor_id)
            .filter(
                PatientDoctor.discharge_id == discharge_id,
                Doctor.full_name.ilike(f"%{name}%"),
            )
            .all()
        )
        if not rows:
            return f"No doctor matching '{name}' found among your assigned doctors."

        sections = [_doctor_block(pd.doctor) for pd in rows if pd.doctor]
        return "\n\n".join(sections)

    @tool
    def get_all_doctor_data() -> str:
        """
        Get the COMPLETE list of all doctors assigned to the patient with full contact details.
        Use this for a comprehensive overview of all assigned doctors and their information.
        """
        rows = (
            db.query(PatientDoctor)
            .join(Doctor, Doctor.id == PatientDoctor.doctor_id)
            .filter(PatientDoctor.discharge_id == discharge_id)
            .all()
        )
        if not rows:
            return "No doctors are assigned to this patient."

        sections = [_doctor_block(pd.doctor) for pd in rows if pd.doctor]
        if not sections:
            return "No doctor details available."
        return "=== Assigned Doctors ===\n\n" + "\n\n".join(sections)

    return [get_my_doctors, get_doctor_by_name, get_all_doctor_data]
