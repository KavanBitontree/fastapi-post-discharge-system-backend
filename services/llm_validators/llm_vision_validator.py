"""
Vision-Based LLM Validator
---------------------------
Direct structured extraction from scanned PDFs and images.

This module does BOTH:
1. OCR (image → text)
2. Structured extraction (text → JSON)

In a SINGLE LLM call to save time and cost.

Uses UNIFIED chunking system from core.chunking for consistency.
"""

from typing import List, Optional
from pathlib import Path
import math

from PIL import Image
from tqdm import tqdm

from core.img_to_txt_llm_init import (
    HFInferenceChatModel,
    load_input,
    image_to_data_uri,
    HF_TOKEN,
    MODEL_ID,
)
from core.chunking import get_model_config, calculate_chunking_strategy
from langchain_core.messages import HumanMessage

# Import schemas for structured output
from schemas.report_schemas import ValidatedReport, ReportHeader, TestResult
from schemas.bill_schemas import ValidatedBill, BillHeader, PatientInfo, BillLineItem
from schemas.prescription_schemas import ValidatedPrescription, PrescriptionHeader, Medication

# Import merge functions from text validators
from services.llm_validators.llm_report_validator import merge_report_results
from services.llm_validators.llm_bill_validator import merge_bill_results
from services.llm_validators.llm_prescription_validator import merge_prescription_results

# Get vision model config (use same model name for consistency)
VISION_MODEL_CONFIG = get_model_config(MODEL_ID)

# Pages per chunk for vision extraction (will be calculated dynamically)
PAGES_PER_CHUNK = 5  # Default, overridden by chunking system


# ══════════════════════════════════════════════════════════════════════════════
# REPORT EXTRACTION FROM VISION
# ══════════════════════════════════════════════════════════════════════════════

_REPORT_VISION_PROMPT = """You are a medical laboratory report data extraction system.
Extract structured data from this medical lab report IMAGE and return it in JSON format.

HEADER FIELDS:
- report_name: Full report title (REQUIRED)
- report_date: Date in DD/MM/YYYY HH:MM format
- collection_date: Sample collection date
- received_date: Sample received date
- specimen_type: Type of specimen
- status: Report status

TEST RESULTS - Extract EVERY test with:
- test_name: Test name (REQUIRED)
- section: Section/category
- normal_result: Value when no flag
- abnormal_result: Value when flagged
- flag: "H"=High, "L"=Low, "*"=Abnormal
- units: Unit of measurement
- reference_range_low: Lower bound
- reference_range_high: Upper bound

CRITICAL: Extract ALL tests from ALL visible pages. Return ONLY valid JSON with these exact keys:
{
  "header": { ... },
  "test_results": [ ... ]
}"""


def extract_report_from_vision(
    image_path: str,
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> ValidatedReport:
    """
    Extract structured report data directly from scanned PDF/image.
    
    Does BOTH OCR + structured extraction in ONE call.
    
    Parameters
    ----------
    image_path : str
        Path to scanned PDF or image
    chunk_index : int
        Current chunk index
    total_chunks : int
        Total number of chunks
        
    Returns
    -------
    ValidatedReport
        Structured report data
    """
    # Load images
    images = load_input(image_path)
    
    # For chunking, take subset
    if total_chunks > 1:
        start = chunk_index * PAGES_PER_CHUNK
        end = min(start + PAGES_PER_CHUNK, len(images))
        images = images[start:end]
    
    # Build multimodal message
    content = []
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_uri(img)},
        })
    
    # Add extraction prompt
    if chunk_index == 0:
        prompt = f"""Extract the complete header and all test results from this medical report.

This is chunk 1 of {total_chunks}.

{_REPORT_VISION_PROMPT}"""
    else:
        prompt = f"""Extract ONLY test results from this medical report chunk.

This is chunk {chunk_index + 1} of {total_chunks}.

{_REPORT_VISION_PROMPT}

Use minimal header (report_name="Chunk {chunk_index + 1}")."""
    
    content.append({"type": "text", "text": prompt})
    
    # Call vision LLM with structured output
    llm = HFInferenceChatModel(model_id=MODEL_ID, hf_token=HF_TOKEN)
    
    # Note: HuggingFace InferenceClient doesn't support structured output directly
    # So we need to parse JSON from response
    response = llm.invoke([HumanMessage(content=content)])
    
    # Parse JSON response
    import json
    try:
        # Try to extract JSON from response
        text = response.content.strip()
        
        # Remove markdown code fences if present
        if text.startswith("```json"):
            text = text.split("\n", 1)[1]
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if "```" in text:
            text = text.split("```")[0]
        
        data = json.loads(text.strip())
        
        # Convert to ValidatedReport
        header = ReportHeader(**data.get("header", {}))
        test_results = [TestResult(**t) for t in data.get("test_results", [])]
        
        result = ValidatedReport(header=header, test_results=test_results)
        print(f"[vision] Chunk {chunk_index + 1}: extracted {len(result.test_results)} tests")
        return result
        
    except Exception as e:
        print(f"[vision] Chunk {chunk_index + 1}: extraction failed - {e}")
        # Return minimal valid result
        if chunk_index == 0:
            return ValidatedReport(
                header=ReportHeader(report_name="Unknown Report"),
                test_results=[]
            )
        else:
            return ValidatedReport(
                header=ReportHeader(report_name=f"Chunk {chunk_index + 1}"),
                test_results=[]
            )


# ══════════════════════════════════════════════════════════════════════════════
# BILL EXTRACTION FROM VISION
# ══════════════════════════════════════════════════════════════════════════════

_BILL_VISION_PROMPT = """You are a medical billing data extraction system.
Extract structured data from this hospital bill IMAGE and return it in JSON format.

BILL HEADER:
- invoice_number: Invoice/bill number (REQUIRED)
- invoice_date: Date in YYYY-MM-DD
- due_date: Due date in YYYY-MM-DD
- initial_amount: Initial charges (number)
- discount_amount: Discount (number)
- tax_amount: Tax (number)
- total_amount: Total due (REQUIRED, number)

PATIENT INFO:
- full_name, phone_number, dob, gender, discharge_date

LINE ITEMS - Extract EVERY service:
- cpt_code, description (REQUIRED), qty, unit_price, total_price

CRITICAL: Extract ALL line items. Return ONLY valid JSON with these exact keys:
{
  "bill": { ... },
  "patient": { ... },
  "line_items": [ ... ]
}"""


def extract_bill_from_vision(
    image_path: str,
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> ValidatedBill:
    """
    Extract structured bill data directly from scanned PDF/image.
    
    Does BOTH OCR + structured extraction in ONE call.
    """
    images = load_input(image_path)
    
    if total_chunks > 1:
        start = chunk_index * PAGES_PER_CHUNK
        end = min(start + PAGES_PER_CHUNK, len(images))
        images = images[start:end]
    
    content = []
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_uri(img)},
        })
    
    if chunk_index == 0:
        prompt = f"""Extract complete bill information from this document.

This is chunk 1 of {total_chunks}.

{_BILL_VISION_PROMPT}"""
    else:
        prompt = f"""Extract ONLY line items from this bill chunk.

This is chunk {chunk_index + 1} of {total_chunks}.

{_BILL_VISION_PROMPT}"""
    
    content.append({"type": "text", "text": prompt})
    
    llm = HFInferenceChatModel(model_id=MODEL_ID, hf_token=HF_TOKEN)
    response = llm.invoke([HumanMessage(content=content)])
    
    import json
    try:
        text = response.content.strip()
        
        # Debug: print raw response (more characters to see full JSON)
        print(f"[vision] Raw LLM response (first 1000 chars): {text[:1000]}")
        
        if text.startswith("```json"):
            text = text.split("\n", 1)[1]
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if "```" in text:
            text = text.split("```")[0]
        
        data = json.loads(text.strip())
        
        # Handle both uppercase and lowercase keys for flexibility
        bill_data = data.get("bill", data.get("BILL_HEADER", {}))
        patient_data = data.get("patient", data.get("PATIENT_INFO", {}))
        line_items_data = data.get("line_items", data.get("LINE_ITEMS", []))
        
        bill = BillHeader(**bill_data)
        patient = PatientInfo(**patient_data)
        line_items = [BillLineItem(**item) for item in line_items_data]
        
        result = ValidatedBill(bill=bill, patient=patient, line_items=line_items)
        print(f"[vision] Chunk {chunk_index + 1}: extracted {len(result.line_items)} line items")
        return result
        
    except Exception as e:
        print(f"[vision] Chunk {chunk_index + 1}: extraction failed - {e}")
        print(f"[vision] Response text: {text if 'text' in locals() else 'N/A'}")
        return ValidatedBill(
            bill=BillHeader(invoice_number=f"Chunk {chunk_index + 1}" if chunk_index > 0 else None),
            patient=PatientInfo(),
            line_items=[],
        )


# ══════════════════════════════════════════════════════════════════════════════
# PRESCRIPTION EXTRACTION FROM VISION
# ══════════════════════════════════════════════════════════════════════════════

_PRESCRIPTION_VISION_PROMPT = """You are a prescription data extraction system.
Extract structured data from this prescription IMAGE and return it in JSON format.

HEADER:
- rx_number, rx_date (YYYY-MM-DD), patient_phone, doctor_name, doctor_email, doctor_speciality

MEDICATIONS - Extract EVERY medication:
- drug_name (REQUIRED)
- strength (e.g., "5 mg")
- form_of_medicine: tablet, capsule, syrup, injection, drops, cream, ointment, inhaler, powder, other
- dosage (e.g., "1", "2")
- frequency_of_dose_per_day (count all timings)
- dosing_days (duration in days)
- recurrence: {type: "daily"/"every_n_days"/"cyclic", every_n_days, cycle_take_days, cycle_skip_days}
- schedule: {before_breakfast, after_breakfast, before_lunch, after_lunch, before_dinner, after_dinner}

CRITICAL: Extract ALL medications. Return ONLY valid JSON with these exact keys:
{
  "header": { ... },
  "medications": [ ... ]
}"""


def extract_prescription_from_vision(
    image_path: str,
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> ValidatedPrescription:
    """
    Extract structured prescription data directly from scanned PDF/image.
    
    Does BOTH OCR + structured extraction in ONE call.
    """
    images = load_input(image_path)
    
    if total_chunks > 1:
        start = chunk_index * PAGES_PER_CHUNK
        end = min(start + PAGES_PER_CHUNK, len(images))
        images = images[start:end]
    
    content = []
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_uri(img)},
        })
    
    if chunk_index == 0:
        prompt = f"""Extract the complete header and all medications from this prescription.

This is chunk 1 of {total_chunks}.

{_PRESCRIPTION_VISION_PROMPT}"""
    else:
        prompt = f"""Extract ONLY medications from this prescription chunk.

This is chunk {chunk_index + 1} of {total_chunks}.

{_PRESCRIPTION_VISION_PROMPT}"""
    
    content.append({"type": "text", "text": prompt})
    
    llm = HFInferenceChatModel(model_id=MODEL_ID, hf_token=HF_TOKEN)
    response = llm.invoke([HumanMessage(content=content)])
    
    import json
    try:
        text = response.content.strip()
        if text.startswith("```json"):
            text = text.split("\n", 1)[1]
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if "```" in text:
            text = text.split("```")[0]
        
        data = json.loads(text.strip())
        
        header = PrescriptionHeader(**data.get("header", {}))
        medications = [Medication(**m) for m in data.get("medications", [])]
        
        result = ValidatedPrescription(header=header, medications=medications)
        print(f"[vision] Chunk {chunk_index + 1}: extracted {len(result.medications)} medications")
        return result
        
    except Exception as e:
        print(f"[vision] Chunk {chunk_index + 1}: extraction failed - {e}")
        return ValidatedPrescription(
            header=PrescriptionHeader(rx_number=f"Chunk {chunk_index + 1}" if chunk_index > 0 else None),
            medications=[],
        )
