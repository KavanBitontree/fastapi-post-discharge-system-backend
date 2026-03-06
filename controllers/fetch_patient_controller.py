from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from services.fetch_patient_service import FetchPatientService

class FetchPatientController:
    @staticmethod
    def list_patients(db: Session, search: str, page: int, size: int, sort: str):
        skip = (page - 1) * size 
        
        patients, total = FetchPatientService.get_filtered_patients(
            db=db, 
            search=search, 
            skip=skip, 
            limit=size, 
            sort_order=sort
        )
        
        return {
            "items": patients,
            "total": total,
            "page": page,
            "size": size
        }

    @staticmethod
    def get_details(db: Session, patient_id: int):
        patient = FetchPatientService.get_patient_by_id(db, patient_id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient with ID {patient_id} not found"
            )
        return patient