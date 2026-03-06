from sqlalchemy.orm import Session
from passlib.context import CryptContext
from models.patient import Patient
from schemas.register import RegisterRequest

# Argon2 setup
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

class RegisterService:
    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def get_patient_by_email(db: Session, email: str):
        return db.query(Patient).filter(Patient.email == email).first()

    @staticmethod
    def create_new_patient(db: Session, data: RegisterRequest):
        hashed_pwd = RegisterService.hash_password(data.password)
        new_patient = Patient(
            full_name=data.full_name,
            email=data.email,
            dob=data.dob,
            gender=data.gender,
            password_hash=hashed_pwd 
        )
        db.add(new_patient)
        db.commit()
        db.refresh(new_patient)
        return new_patient