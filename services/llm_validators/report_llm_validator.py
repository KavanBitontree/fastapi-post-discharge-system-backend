"""
report_llm_validator.py
-----------------------
LLM-based validation and enhancement of parsed report data.
Uses Groq API with LangSmith tracing.
"""

from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from core.config import settings
import os


# Set LangSmith environment variables for tracing
if settings.LANGSMITH_TRACING:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGSMITH_ENDPOINT or "https://api.smith.langchain.com"
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY or ""
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT or "Medicare"


# Initialize LLM with tracing
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=settings.GROQ_API_KEY,
    temperature=0.3,
)


class TestResult(BaseModel):
    """Individual test result from a medical report"""
    test_name: str = Field(description="Name of the test or measurement")
    section: Optional[str] = Field(None, description="Section or category of the test")
    normal_result: Optional[str] = Field(None, description="Result value when within normal range")
    abnormal_result: Optional[str] = Field(None, description="Result value when outside normal range")
    flag: Optional[str] = Field(None, description="Flag indicating abnormality: 'H' (High), 'L' (Low), '**' (Critical)")
    units: Optional[str] = Field(None, description="Unit of measurement")
    reference_range_low: Optional[str] = Field(None, description="Lower bound of reference range")
    reference_range_high: Optional[str] = Field(None, description="Upper bound of reference range")


class ReportHeader(BaseModel):
    """Header information from a medical report"""
    report_name: str = Field(description="Name/title of the report")
    patient_email: Optional[str] = Field(None, description="Patient's email address")
    report_date: Optional[str] = Field(None, description="Report date/time in format MM/DD/YYYY HH:MM or MM/DD/YYYY")
    collection_date: Optional[str] = Field(None, description="Sample collection date/time")
    received_date: Optional[str] = Field(None, description="Sample received date/time")
    specimen_type: Optional[str] = Field(None, description="Type of specimen")
    status: Optional[str] = Field(None, description="Report status")


class ValidatedReport(BaseModel):
    """Complete validated medical report"""
    header: ReportHeader
    test_results: List[TestResult]


def validate_with_llm(raw_text: str, regex_header: Dict, regex_rows: List[Dict]) -> ValidatedReport:
    """
    Validate and enhance parsed report data using LLM.
    
    This function sends the raw PDF text and regex parsing results to the LLM
    for validation and enhancement. The LLM ensures all required fields are
    extracted correctly and handles layout variations.
    
    Parameters
    ----------
    raw_text : str
        Raw text extracted from PDF
    regex_header : dict
        Header data from regex parsing
    regex_rows : list of dict
        Test results from regex parsing
        
    Returns
    -------
    ValidatedReport
        Validated and enhanced report data with all required fields
        
    Raises
    ------
    Exception
        If LLM validation fails
    """
    
    system_prompt = """You are an automated medical report data extraction system. Extract ALL required fields from medical laboratory reports and return them in structured format for database storage.

EXTRACTION REQUIREMENTS:

1. REPORT HEADER (ALL REQUIRED):
   - report_name: Full title of the report (e.g., "HYPERTENSION & CARDIOVASCULAR PANEL", "Complete Blood Count")
   - patient_email: Patient's email address
   - report_date: Report date/time (format: MM/DD/YYYY HH:MM or MM/DD/YYYY)
   - collection_date: Sample collection date/time
   - received_date: Sample received date/time
   - specimen_type: Type of specimen (e.g., "Whole Blood", "Serum", "Urine")
   - status: Report status (e.g., "ROUTINE", "FINAL", "PRELIMINARY")

2. TEST RESULTS (ALL TESTS IN THE REPORT):
   For each test, extract:
   - test_name: Name of the test (REQUIRED)
   - section: Category/section name
   - normal_result: Value when within normal range
   - abnormal_result: Value when outside normal range
   - flag: Abnormality indicator ("H" = High, "L" = Low, "**" = Critical)
   - units: Unit of measurement
   - reference_range_low: Lower bound of reference range
   - reference_range_high: Upper bound of reference range

FIELD SYNONYMS TO RECOGNIZE:
- "Patient email" = "Patient e-mail" = "Email"
- "Report Date" = "Report Date/Time" = "Date of Report"
- "Collection Date" = "Collection Date/Time" = "Sample Collection Date"
- "Received Date" = "Received Date/Time" = "Sample Received Date"
- "Specimen Type" = "Sample Type" = "Specimen"
- "Status" = "Report Status"

EXTRACTION RULES:
- Extract ALL test results from the report
- For tests with flags (H/L/**), the value goes in abnormal_result
- For tests without flags, the value goes in normal_result
- Split reference ranges: "90 - 120" → low: "90", high: "120"
- Preserve units exactly as shown in the report
- Group tests by their section headings"""

    extraction_prompt = f"""Extract all structured data from this medical laboratory report for database storage.

RAW TEXT FROM PDF:
{raw_text[:8000]}

REGEX PARSING HINTS (may be incomplete):
Header fields found: {list(regex_header.keys())}
Test results found: {len(regex_rows)} tests

Extract ALL required fields and return in structured format."""

    # Use structured output with LangSmith tracing
    structured_llm = llm.with_structured_output(ValidatedReport)
    
    result = structured_llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": extraction_prompt}
    ])
    
    return result


def extract_report_name_with_llm(raw_text: str) -> str:
    """
    Quick LLM call to extract just the report name/title.
    Used as a fallback if regex parsing fails.
    
    Parameters
    ----------
    raw_text : str
        Raw text extracted from PDF
        
    Returns
    -------
    str
        The report name/title
    """
    
    prompt = f"""Extract the report name/title from this medical laboratory report.

Look for the main title/heading, such as:
- "HYPERTENSION & CARDIOVASCULAR PANEL — LABORATORY REPORT"
- "Complete Blood Count (CBC)"
- "Lipid Panel"
- "Metabolic Panel"

Return ONLY the report name, nothing else.

RAW TEXT FROM PDF:
{raw_text[:2000]}"""
    
    response = llm.invoke(prompt)
    return response.content.strip()
