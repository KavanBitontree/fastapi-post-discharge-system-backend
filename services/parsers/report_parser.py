"""
report_parser.py
----------------
Handles PDF text extraction and regex-based parsing.
Pure parsing logic - no database, no LLM.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

import pypdf


# Date formats found in PDFs
_DATE_FMT_WITH_TIME = "%m/%d/%Y %H:%M"
_DATE_FMT_DATE_ONLY = "%m/%d/%Y"


def extract_raw_text(pdf_path: str) -> str:
    """
    Extract raw text from PDF preserving layout.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
        
    Returns
    -------
    str
        Raw extracted text
        
    Raises
    ------
    FileNotFoundError
        If PDF file doesn't exist
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = pypdf.PdfReader(str(path))
    pages: List[str] = []
    for page in reader.pages:
        pages.append(page.extract_text(extraction_mode="layout") or "")

    return "\n".join(pages)


def _parse_datetime(value: str) -> Optional[datetime]:
    """Try both datetime formats; return None on failure."""
    for fmt in (_DATE_FMT_WITH_TIME, _DATE_FMT_DATE_ONLY):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _find(pattern: str, text: str, group: int = 1, flags: int = re.IGNORECASE) -> Optional[str]:
    """Return the first capture-group match or None."""
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None


def parse_header(raw_text: str) -> Dict[str, any]:
    """
    Extract report header metadata using regex.
    
    Parameters
    ----------
    raw_text : str
        Raw text extracted from PDF
        
    Returns
    -------
    dict
        Header fields: report_name, report_date, collection_date, 
        received_date, specimen_type, status, patient_email
    """
    report_name = None
    lines = raw_text.split('\n')[:15]
    
    # Pattern 1: Look for "LABORATORY REPORT"
    for line in lines:
        if 'LABORATORY REPORT' in line.upper() or 'LAB REPORT' in line.upper():
            match = re.search(r'([A-Z][A-Z &()\-/]+?)\s*[—–-]\s*LABORATORY REPORT', line, re.IGNORECASE)
            if match:
                report_name = match.group(1).strip()
                break
            if line.strip() and not any(x in line.upper() for x in ['HOSPITAL', 'DEPARTMENT', 'PHONE', 'CLIA']):
                report_name = line.strip()
                break
    
    # Pattern 2: Look for "PANEL"
    if not report_name:
        for line in lines:
            if 'PANEL' in line.upper() and len(line.strip()) > 10:
                match = re.search(r'([A-Z][A-Z &()\-/]*PANEL[A-Z &()\-/]*)', line)
                if match:
                    report_name = match.group(1).strip()
                    break
    
    # Pattern 3: Common report types
    if not report_name:
        common_reports = [
            r'Complete Blood Count\s*\(CBC\)',
            r'Lipid Panel',
            r'Metabolic Panel',
            r'Diabetes Panel',
            r'Cardiovascular Panel',
            r'Thyroid Panel',
            r'Liver Function Test',
            r'Kidney Function Test',
            r'Hypertension.*Panel'
        ]
        for pattern in common_reports:
            match = re.search(pattern, raw_text[:1000], re.IGNORECASE)
            if match:
                report_name = match.group(0).strip()
                break
    
    # Pattern 4: ALL-CAPS title line
    if not report_name:
        for line in lines:
            line = line.strip()
            if (line and line.isupper() and 20 < len(line) < 100 and
                not any(keyword in line for keyword in ['HOSPITAL', 'DEPARTMENT', 'PHONE', 'CLIA', 'SUITE', 'BLVD', 'STREET', 'AVENUE'])):
                report_name = line
                break
    
    # Extract dates
    report_date_str = _find(r"Report\s+Date(?:/Time)?[:：]\s*([\d/]+ [\d:]+)", raw_text)
    collection_date_str = _find(r"Collection\s+Date(?:/Time)?[:：]\s*([\d/]+ [\d:]+)", raw_text)
    received_date_str = _find(r"Received\s+Date(?:/Time)?[:：]\s*([\d/]+ [\d:]+)", raw_text)
    
    # Extract specimen type
    specimen_type = _find(r"Specimen\s+Type[:：]\s*([^\r\n]+)", raw_text)
    if not specimen_type:
        specimen_type = _find(r"Sample\s+Type[:：]\s*([^\r\n]+)", raw_text)
    
    # Extract status
    status = _find(r"Status[:：]\s*([A-Z]+(?:\s+[A-Z]+)?)", raw_text)
    report_status_footer = _find(r"Report\s+Status[:：]\s*([A-Z]+)", raw_text)
    
    # Extract patient email
    patient_email = _find(r"Patient\s+(?:e-?mail|email)[:：]\s*([^\s]+@[^\s]+)", raw_text)
    if not patient_email:
        patient_email = _find(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", raw_text)

    return {
        "report_name": report_name,
        "report_date": _parse_datetime(report_date_str) if report_date_str else None,
        "collection_date": _parse_datetime(collection_date_str) if collection_date_str else None,
        "received_date": _parse_datetime(received_date_str) if received_date_str else None,
        "specimen_type": specimen_type,
        "status": report_status_footer or status,
        "patient_email": patient_email,
    }


# Regex patterns for test rows
_SECTION_HEADING = re.compile(r"^[A-Z][A-Z &()\-/]+$")
_SKIP_LINE = re.compile(r"Test\s+Name\s+Normal\s+Result", re.IGNORECASE)
_SIMPLE_ROW = re.compile(
    r"^\s{0,10}"
    r"(?P<test_name>[A-Za-z][^\d]*?)"
    r"\s{3,}"
    r"(?P<col1>[<>]?\s*\d[\d.,\s/<>]*)"
    r"(?:\s{2,}(?P<col2>[<>]?\s*\d[\d.,\s/<>]*))?"
    r"(?:\s{2,}(?P<flag>[HL*]{1,2}))?"
    r"(?:\s{2,}(?P<units>[^\s].+?))?"
    r"(?:\s{2,}(?P<ref_range>[\d.<>\s\-–/]+))?$"
)


def _parse_reference_range(ref_str: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split reference range into low and high values."""
    if not ref_str:
        return None, None
    ref_str = ref_str.strip()
    m = re.match(r"^([\d.<>]+)\s*[-–]\s*([\d.<>/\w]+)$", ref_str)
    if m:
        return m.group(1), m.group(2)
    parts = re.split(r"\s*[-–]\s*", ref_str)
    if len(parts) == 2:
        return parts[0].strip() or None, parts[1].strip() or None
    return None, None


def _current_section(line: str, current: str) -> str:
    """Return updated section name if line looks like a heading."""
    stripped = line.strip()
    if stripped and _SECTION_HEADING.match(stripped) and len(stripped) > 5:
        if not _SKIP_LINE.search(stripped):
            return stripped
    return current


def parse_test_rows(raw_text: str) -> List[Dict[str, any]]:
    """
    Extract test results from PDF text using regex.
    
    Parameters
    ----------
    raw_text : str
        Raw text extracted from PDF
        
    Returns
    -------
    list of dict
        Test results with keys: section, test_name, normal_result, 
        abnormal_result, flag, units, reference_range_low, reference_range_high
    """
    results: List[Dict[str, any]] = []
    current_section = "UNKNOWN"

    for line in raw_text.splitlines():
        if not line.strip():
            continue
        if _SKIP_LINE.search(line):
            continue
        
        current_section = _current_section(line, current_section)
        if current_section == line.strip():
            continue
        
        if len(line.strip()) < 10:
            continue
        if re.search(r"CONFIDENTIAL|Flag\s+Key|Critical\s+Result|Verified\s+By|END\s+OF\s+REPORT", line, re.IGNORECASE):
            continue
        if re.search(
            r"\b(Patient\s+Name|Date\s+of\s+Birth|Age/Sex|Ordering\s+Physician|"
            r"Diagnosis|ICD-10|Specimen\s+ID|Patient\s+email|Report\s+Date|"
            r"Collection\s+Date|Received\s+Date|Specimen\s+Type)\b",
            line, re.IGNORECASE
        ):
            continue
        
        m = _SIMPLE_ROW.match(line)
        if not m:
            continue
        
        test_name = (m.group("test_name") or "").strip()
        if not test_name or len(test_name) < 3:
            continue
        
        col1 = (m.group("col1") or "").strip() or None
        col2 = (m.group("col2") or "").strip() or None
        flag = (m.group("flag") or "").strip() or None
        units = (m.group("units") or "").strip() or None
        ref_range = (m.group("ref_range") or "").strip() or None
        
        if flag and col1 and not col2:
            normal_result = None
            abnormal_result = col1
        elif col1 and col2:
            normal_result = col1
            abnormal_result = col2
        else:
            normal_result = col1
            abnormal_result = None
        
        ref_low, ref_high = _parse_reference_range(ref_range)
        
        results.append({
            "section": current_section,
            "test_name": test_name,
            "normal_result": normal_result,
            "abnormal_result": abnormal_result,
            "flag": flag,
            "units": units,
            "reference_range_low": ref_low,
            "reference_range_high": ref_high,
        })
    
    return results
