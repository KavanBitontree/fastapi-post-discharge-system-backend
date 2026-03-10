"""
store_prescription.py  —  Orchestrator
----------------------------------------
Pipeline:
  1. parse_prescription_pdf  — Extract prescription using unified LLM extraction with chunking
  2. store_parsed_prescription — insert doctor, medications, schedules, etc. into DB

Usage::

    python store_prescription.py                              # uses default PDF path
    python store_prescription.py path/to/prescription.pdf

NOTE: This is a standalone CLI script. The API uses routes/prescription_routes.py instead.
"""
import sys
import os
from typing import Optional

from sqlalchemy.orm import Session

from services.parsers.prescription_parser import parse_prescription_pdf, ParsedPrescription


# ---------------------------------------------------------------------------
# New: store prescription linked to a discharge record (used by discharge service)
# ---------------------------------------------------------------------------

def store_prescription_for_discharge(
    db: Session,
    parsed: ParsedPrescription,
    discharge_id: int,
) -> dict:
    """
    Persist a ParsedPrescription into the database, linked to a discharge record.

    Does NOT open or commit the session — caller controls the transaction.
    """
    from models.doctor import Doctor
    from models.patient_doctor import PatientDoctor
    from models.recurrence_type import RecurrenceType
    from models.medication import Medication
    from models.medication_schedule import MedicationSchedule

    # ── Find or create doctor ────────────────────────────────────────────
    doctor = None
    if parsed.doctor_email:
        doctor = db.query(Doctor).filter(Doctor.email == parsed.doctor_email).first()
    if doctor is None and parsed.doctor_name:
        doctor = Doctor(
            full_name=parsed.doctor_name,
            email=parsed.doctor_email or f"unknown_{parsed.doctor_name.replace(' ', '_')}@hospital.org",
            speciality=parsed.doctor_speciality,
        )
        db.add(doctor)
        db.flush()

    # ── Link discharge ↔ doctor ──────────────────────────────────────────
    if doctor:
        existing_link = db.query(PatientDoctor).filter(
            PatientDoctor.discharge_id == discharge_id,
            PatientDoctor.doctor_id == doctor.id,
        ).first()
        if not existing_link:
            db.add(PatientDoctor(discharge_id=discharge_id, doctor_id=doctor.id))
            db.flush()

    # ── Medications ──────────────────────────────────────────────────────
    med_count = 0
    sched_count = 0
    recurrence_cache: dict = {}

    for med_data in parsed.medications:
        r = med_data.recurrence
        cache_key = (r.type, r.every_n_days, r.cycle_take_days, r.cycle_skip_days)

        if cache_key not in recurrence_cache:
            query = db.query(RecurrenceType).filter(RecurrenceType.type == r.type)
            if r.every_n_days is not None:
                query = query.filter(RecurrenceType.every_n_days == r.every_n_days)
            if r.cycle_take_days is not None:
                query = query.filter(RecurrenceType.cycle_take_days == r.cycle_take_days)
            if r.cycle_skip_days is not None:
                query = query.filter(RecurrenceType.cycle_skip_days == r.cycle_skip_days)
            existing_rec = query.first()

            if existing_rec:
                recurrence_cache[cache_key] = existing_rec
            else:
                new_rec = RecurrenceType(
                    type=r.type,
                    every_n_days=r.every_n_days,
                    start_date_for_every_n_days=r.start_date_for_every_n_days,
                    cycle_take_days=r.cycle_take_days,
                    cycle_skip_days=r.cycle_skip_days,
                )
                db.add(new_rec)
                db.flush()
                recurrence_cache[cache_key] = new_rec

        recurrence_obj = recurrence_cache[cache_key]

        # Skip duplicate: same discharge + drug + date
        existing_med = db.query(Medication).filter(
            Medication.discharge_id == discharge_id,
            Medication.drug_name == med_data.drug_name,
            Medication.prescription_date == med_data.prescription_date,
        ).first()
        if existing_med:
            continue

        med = Medication(
            discharge_id=discharge_id,
            drug_name=med_data.drug_name,
            dosage=med_data.dosage,
            frequency_of_dose_per_day=med_data.frequency_of_dose_per_day,
            dosing_days=med_data.dosing_days,
            recurrence_id=recurrence_obj.id,
            is_active=True,
            strength=med_data.strength,
            form_of_medicine=med_data.form_of_medicine,
            doctor_id=doctor.id if doctor else None,
            prescription_date=med_data.prescription_date,
        )
        db.add(med)
        db.flush()
        med_count += 1

        s = med_data.schedule
        db.add(MedicationSchedule(
            medication_id=med.id,
            before_breakfast=s.before_breakfast,
            after_breakfast=s.after_breakfast,
            before_lunch=s.before_lunch,
            after_lunch=s.after_lunch,
            before_dinner=s.before_dinner,
            after_dinner=s.after_dinner,
        ))
        sched_count += 1

    return {
        "doctor_id": doctor.id if doctor else None,
        "medications_inserted": med_count,
        "schedules_inserted": sched_count,
    }
import os
from typing import Optional

from services.parsers.prescription_parser import parse_prescription_pdf, ParsedPrescription


# ---------------------------------------------------------------------------
# DB store (moved here from test_prescription_parse.py — identical logic)
# ---------------------------------------------------------------------------

def store_parsed_prescription(parsed: ParsedPrescription) -> dict:
    """
    Persist a :class:`ParsedPrescription` into the database.

    Steps
    -----
    1. Look up patient by email or phone.
    2. Find or create doctor.
    3. Link patient ↔ doctor in patient_doctor (if not already linked).
    4. For each medication:
       a. Find or create a matching RecurrenceType.
       b. Insert a Medication row (skip duplicates).
       c. Insert a MedicationSchedule row.

    Returns
    -------
    dict with counts of rows inserted.
    """
    from core.database import SessionLocal
    from models.patient import Patient
    from models.doctor import Doctor
    from models.patient_doctor import PatientDoctor
    from models.recurrence_type import RecurrenceType
    from models.medication import Medication
    from models.medication_schedule import MedicationSchedule

    db = SessionLocal()
    try:
        # ── 1. Find patient ──────────────────────────────────────────────
        patient = None
        if hasattr(parsed, 'patient_id') and parsed.patient_id:
            patient = db.query(Patient).filter(
                Patient.id == parsed.patient_id
            ).first()
        elif parsed.patient_email:
            patient = db.query(Patient).filter(
                Patient.email == parsed.patient_email
            ).first()
        if patient is None and parsed.patient_phone:
            patient = db.query(Patient).filter(
                Patient.phone_number == parsed.patient_phone
            ).first()
        if patient is None:
            raise ValueError(
                f"Patient not found in DB for id={getattr(parsed, 'patient_id', None)} "
                f"/ email={parsed.patient_email} / phone={parsed.patient_phone}. "
                "Please store the patient first."
            )
        print(f"  [~] Found patient    id={patient.id}  name={patient.full_name}")

        # ── 2. Find or create doctor ─────────────────────────────────────
        doctor = None
        if parsed.doctor_email:
            doctor = db.query(Doctor).filter(
                Doctor.email == parsed.doctor_email
            ).first()
        if doctor is None and parsed.doctor_name:
            doctor = Doctor(
                full_name=parsed.doctor_name,
                email=parsed.doctor_email or f"unknown_{parsed.doctor_name.replace(' ', '_')}@hospital.org",
                speciality=parsed.doctor_speciality,
            )
            db.add(doctor)
            db.flush()
            print(f"  [+] Created doctor   id={doctor.id}  name={doctor.full_name}")
        elif doctor:
            print(f"  [~] Found doctor     id={doctor.id}  name={doctor.full_name}")

        # ── 3. Link patient ↔ doctor ─────────────────────────────────────
        if doctor:
            existing_link = db.query(PatientDoctor).filter(
                PatientDoctor.patient_id == patient.id,
                PatientDoctor.doctor_id == doctor.id,
            ).first()
            if existing_link is None:
                db.add(PatientDoctor(patient_id=patient.id, doctor_id=doctor.id))
                db.flush()
                print(f"  [+] Linked patient id={patient.id} ↔ doctor id={doctor.id}")
            else:
                print("  [~] patient_doctor link already exists")

        # ── 4. Medications ───────────────────────────────────────────────
        med_count = 0
        sched_count = 0
        recurrence_cache: dict = {}

        for med_data in parsed.medications:

            # a) Find or create RecurrenceType
            r = med_data.recurrence
            cache_key = (r.type, r.every_n_days, r.cycle_take_days, r.cycle_skip_days)

            if cache_key not in recurrence_cache:
                query = db.query(RecurrenceType).filter(RecurrenceType.type == r.type)
                if r.every_n_days is not None:
                    query = query.filter(RecurrenceType.every_n_days == r.every_n_days)
                if r.cycle_take_days is not None:
                    query = query.filter(RecurrenceType.cycle_take_days == r.cycle_take_days)
                if r.cycle_skip_days is not None:
                    query = query.filter(RecurrenceType.cycle_skip_days == r.cycle_skip_days)
                existing_rec = query.first()

                if existing_rec:
                    recurrence_cache[cache_key] = existing_rec
                    print(f"  [~] Reused recurrence  id={existing_rec.id}  type={existing_rec.type}")
                else:
                    new_rec = RecurrenceType(
                        type=r.type,
                        every_n_days=r.every_n_days,
                        start_date_for_every_n_days=r.start_date_for_every_n_days,
                        cycle_take_days=r.cycle_take_days,
                        cycle_skip_days=r.cycle_skip_days,
                    )
                    db.add(new_rec)
                    db.flush()
                    recurrence_cache[cache_key] = new_rec
                    print(f"  [+] Created recurrence id={new_rec.id}  type={new_rec.type}")

            recurrence_obj = recurrence_cache[cache_key]

            # b) Insert Medication (skip duplicate: same patient + drug + date)
            existing_med = db.query(Medication).filter(
                Medication.patient_id == patient.id,
                Medication.drug_name == med_data.drug_name,
                Medication.prescription_date == med_data.prescription_date,
            ).first()

            if existing_med:
                print(f"  [!] Skipping duplicate medication '{med_data.drug_name}'  id={existing_med.id}")
                continue

            med = Medication(
                patient_id=patient.id,
                drug_name=med_data.drug_name,
                dosage=med_data.dosage,
                frequency_of_dose_per_day=med_data.frequency_of_dose_per_day,
                dosing_days=med_data.dosing_days,
                recurrence_id=recurrence_obj.id,
                is_active=True,
                strength=med_data.strength,
                form_of_medicine=med_data.form_of_medicine,
                doctor_id=doctor.id if doctor else None,
                prescription_date=med_data.prescription_date,
            )
            db.add(med)
            db.flush()
            med_count += 1

            # c) Insert MedicationSchedule
            s = med_data.schedule
            db.add(MedicationSchedule(
                medication_id=med.id,
                before_breakfast=s.before_breakfast,
                after_breakfast=s.after_breakfast,
                before_lunch=s.before_lunch,
                after_lunch=s.after_lunch,
                before_dinner=s.before_dinner,
                after_dinner=s.after_dinner,
            ))
            sched_count += 1

        db.commit()
        return {
            "patient_id": patient.id,
            "doctor_id": doctor.id if doctor else None,
            "medications_inserted": med_count,
            "schedules_inserted": sched_count,
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Public pipeline entry-point
# ---------------------------------------------------------------------------

def process_prescription_pdf(pdf_path: str, patient_id: int) -> dict:
    """
    Full pipeline: extract → parse with LLM → store.

    Parameters
    ----------
    pdf_path : str
        Path to the prescription PDF file.
    patient_id : int
        ID of the patient (provided manually, not extracted from PDF).

    Returns
    -------
    dict with ``patient_id``, ``doctor_id``, ``medications_inserted``,
    ``schedules_inserted``.
    """
    print("Step 1/2  Extracting with LLM (unified chunked extraction) …")
    parsed = parse_prescription_pdf(pdf_path)
    
    # Set patient_id (not extracted from PDF)
    parsed.patient_id = patient_id
    print(f"          Found {len(parsed.medications)} medications")

    print("Step 2/2  Storing to DB …")
    return store_parsed_prescription(parsed)


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
    _DEFAULT_PDF = os.path.join(_PROJECT_ROOT, "public", "Medicare_Prescription_BP (1).pdf")
    PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(_DEFAULT_PDF)

    print(f"\nProcessing prescription PDF: {PDF_PATH}\n")
    result = process_prescription_pdf(PDF_PATH)

    print()
    print("Done!")
    print(f"  patient_id           : {result['patient_id']}")
    print(f"  doctor_id            : {result['doctor_id']}")
    print(f"  medications_inserted : {result['medications_inserted']}")
    print(f"  schedules_inserted   : {result['schedules_inserted']}")
