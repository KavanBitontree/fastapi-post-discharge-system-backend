from pydantic import BaseModel
from typing import Optional, List


# ── Dashboard ──────────────────────────────────────────────────────────────────

class RecentDischargeItem(BaseModel):
    discharge_id: int
    patient_id: int
    patient_name: str
    patient_email: str
    discharge_date: Optional[str]
    processed_reports: int
    processed_bills: int
    processed_prescriptions: int


class DashboardStatsResponse(BaseModel):
    total_patients: int
    active_patients: int
    discharged_patients: int
    total_discharges: int
    recent_discharges: List[RecentDischargeItem]


# ── Patient list (admin view) ──────────────────────────────────────────────────

class PatientListItem(BaseModel):
    id: int
    full_name: str
    email: Optional[str]
    phone_number: Optional[str]
    dob: Optional[str]
    gender: Optional[str]
    address: Optional[str]
    is_active: bool
    discharge_date: Optional[str]


class PatientListResponse(BaseModel):
    items: List[PatientListItem]
    total: int
    page: int
    size: int


# ── Discharge history (admin view) ────────────────────────────────────────────

class DischargeHistoryItem(BaseModel):
    discharge_id: int
    patient_id: int
    patient_name: str
    patient_email: str
    discharge_date: Optional[str]
    created_at: Optional[str]
    processed_reports: int
    processed_bills: int
    processed_prescriptions: int


class DischargeHistoryResponse(BaseModel):
    items: List[DischargeHistoryItem]
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


class DischargeDocumentsResponse(BaseModel):
    discharge_id: int
    patient_id: int
    patient_name: str
    patient_email: str
    discharge_date: Optional[str]
    status: str
    reports: List[ReportItem]
    bills: List[BillItem]
    medications: List[MedicationItem]
