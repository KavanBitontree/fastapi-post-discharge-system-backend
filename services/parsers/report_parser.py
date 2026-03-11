"""
report_parser.py
----------------
LLM-first PDF extraction with dynamic chunking.

Strategy:
  1. Text extraction with pdfplumber
  2. Dynamic chunking based on model limits
  3. LLM extraction with automatic chunk processing
  4. Result merging
"""

from pathlib import Path
from typing import Optional, BinaryIO

from services.parsers.unified_pdf_parser import extract_with_chunking, analyze_pdf_for_chunking, extract_with_chunking_from_memory
from services.llm_validators.llm_report_validator import (
    ValidatedReport,
    extract_structured_report_from_chunk,
    merge_report_results,
)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_pdf_from_memory(pdf_buffer: BinaryIO, filename: str, strategy: str = "auto") -> ValidatedReport:
    """
    Parse a medical PDF report from memory into structured data (for Vercel deployment).

    Parameters
    ----------
    pdf_buffer : BinaryIO
        PDF content in memory
    filename : str
        Original filename for logging
    strategy : str
        "auto" – auto-detect PDF type (default)
        "text" – force text-based extraction
        "vision" – force vision extraction

    Returns
    -------
    ValidatedReport
        Fully structured report with header and test results.

    Raises
    ------
    ValueError
        If extraction fails.
    """
    print(f"[parser] Extracting report from memory: {filename}")
    
    return extract_with_chunking_from_memory(
        pdf_buffer=pdf_buffer,
        filename=filename,
        extraction_function=extract_structured_report_from_chunk,
        merge_function=merge_report_results,
        strategy=strategy,
    )


def get_report_chunking_info(pdf_path: str) -> dict:
    """
    Analyze PDF and return chunking strategy without processing.
    
    Useful for showing estimated cost and processing time.
    """
    return analyze_pdf_for_chunking(pdf_path)



def parse_pdf(pdf_path: str, strategy: str = "auto") -> ValidatedReport:
    """
    Parse a medical PDF report into structured data (backward compatibility).

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.
    strategy : str
        "auto" – auto-detect PDF type (default)
        "text" – force text-based extraction
        "vision" – force vision extraction

    Returns
    -------
    ValidatedReport
        Fully structured report with header and test results.

    Raises
    ------
    FileNotFoundError
        If the PDF does not exist.
    ValueError
        If extraction fails.
    """
    from pathlib import Path
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"[parser] Extracting report: {path.name}")
    
    return extract_with_chunking(
        pdf_path=str(path),
        extraction_function=extract_structured_report_from_chunk,
        merge_function=merge_report_results,
        strategy=strategy,
    )