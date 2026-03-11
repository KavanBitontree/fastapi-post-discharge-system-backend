from pydantic import BaseModel
from typing import Optional, List


# ── Profile ────────────────────────────────────────────────────────────────────

class PatientProfileResponse(BaseModel):
    id: int
    full_name: str
    email: Optional[str]
    phone_number: Optional[str]
    dob: Optional[str]
    gender: Optional[str]
    address: Optional[str]
    created_at: Optional[str]


# ── Dashboard ──────────────────────────────────────────────────────────────────

class PatientStats(BaseModel):
    discharge_count: int
    active_medications: int
    total_reports: int
    is_discharged: bool


class LatestDischarge(BaseModel):
    discharge_id: int
    discharge_date: Optional[str]
    processed_reports: int
    processed_bills: int
    processed_prescriptions: int


class PatientInfo(BaseModel):
    id: int
    full_name: str
    email: Optional[str]
    phone_number: Optional[str]
    dob: Optional[str]
    gender: Optional[str]
    address: Optional[str]


class PatientDashboardResponse(BaseModel):
    patient: PatientInfo
    stats: PatientStats
    latest_discharge: Optional[LatestDischarge]


# ── Discharge history ──────────────────────────────────────────────────────────

class PatientDischargeHistoryItem(BaseModel):
    discharge_id: int
    discharge_date: Optional[str]
    created_at: Optional[str]
    processed_reports: int
    processed_bills: int
    processed_prescriptions: int
    discharge_summary_url: Optional[str]
    patient_friendly_summary_url: Optional[str]
    insurance_ready_url: Optional[str]


class PatientDischargeHistoryResponse(BaseModel):
    items: List[PatientDischargeHistoryItem]
    total: int
    page: int
    size: int


# ── Discharge documents ────────────────────────────────────────────────────────

class ReportItem(BaseModel):
    id: int
    report_name: str
    report_date: Optional[str]
    specimen_type: Optional[str]
    status: Optional[str]
    report_url: Optional[str]


class BillItem(BaseModel):
    id: int
    invoice_number: str
    invoice_date: Optional[str]
    total_amount: float
    bill_url: Optional[str]


class MedicationItem(BaseModel):
    id: int
    drug_name: str
    dosage: str
    strength: Optional[str]
    form_of_medicine: Optional[str]
    frequency_of_dose_per_day: int
    is_active: bool


class PatientDischargeDocumentsResponse(BaseModel):
    discharge_id: int
    discharge_date: Optional[str]
    status: str
    reports: List[ReportItem]
    bills: List[BillItem]
    medications: List[MedicationItem]


# ── Discharge PDFs ─────────────────────────────────────────────────────────────

class PatientDischargePdfsResponse(BaseModel):
    discharge_id: int
    discharge_date: Optional[str]
    status: str
    discharge_summary_url: Optional[str]
    patient_friendly_summary_url: Optional[str]
    insurance_ready_url: Optional[str]
