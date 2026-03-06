from sqlalchemy.orm import Session
from models.patient import Patient
from sqlalchemy import func, or_, asc, desc 

class FetchPatientService:
    @staticmethod
    def get_filtered_patients(db: Session, search: str = None, skip: int = 0, limit: int = 10, sort_order: str = "asc"):
        """Fetches patients with optional search, pagination, and sorting"""
        query = db.query(Patient).filter(Patient.id != 0)
        
        if search:
            search_param = f"%{search}%"
            query = query.filter(
                or_(
                    Patient.full_name.ilike(search_param),
                    Patient.email.ilike(search_param)
                )
            )

        # Sorting logic
        sort_col = func.lower(Patient.full_name)
        query = query.order_by(desc(sort_col)) if sort_order == "desc" else query.order_by(asc(sort_col))

        total_count = query.count()
        patients = query.offset(skip).limit(limit).all()

        return patients, total_count
    
    @staticmethod
    def get_patient_by_id(db: Session, patient_id: int):
        """Fetches a single patient by their ID"""
        return db.query(Patient).filter(Patient.id == patient_id).first()