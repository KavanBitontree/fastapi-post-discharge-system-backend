"""
Utility Services
----------------
Helper utilities for document processing.
"""

from .pdf_detector import (
    PDFTypeDetector,
    is_scanned_pdf,
    analyze_pdf,
    get_extraction_strategy,
)

__all__ = [
    "PDFTypeDetector",
    "is_scanned_pdf",
    "analyze_pdf",
    "get_extraction_strategy",
]
