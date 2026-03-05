"""
OCR Parser
----------
Extracts text from image-based PDFs using Tesseract OCR.
Falls back to regular PDF text extraction if OCR is not needed.
"""

import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from pathlib import Path
from typing import Optional
import pypdf

# Import OCR configuration
from core.ocr_config import pytesseract


def is_pdf_image_based(pdf_path: str, sample_pages: int = 2) -> bool:
    """
    Check if PDF is image-based (scanned) by checking if text extraction yields little content.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    sample_pages : int
        Number of pages to sample (default: 2)
        
    Returns
    -------
    bool
        True if PDF appears to be image-based, False otherwise
    """
    try:
        reader = pypdf.PdfReader(pdf_path)
        total_pages = len(reader.pages)
        pages_to_check = min(sample_pages, total_pages)
        
        total_chars = 0
        for i in range(pages_to_check):
            text = reader.pages[i].extract_text() or ""
            total_chars += len(text.strip())
        
        # If less than 100 characters per page on average, likely image-based
        avg_chars_per_page = total_chars / pages_to_check
        return avg_chars_per_page < 100
        
    except Exception:
        # If we can't read it, assume it might be image-based
        return True


def extract_text_with_ocr(pdf_path: str, dpi: int = 300) -> str:
    """
    Extract text from PDF using OCR (for scanned/image-based PDFs).
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    dpi : int
        DPI for image conversion (higher = better quality but slower)
        Default: 300 (good balance)
        
    Returns
    -------
    str
        Extracted text from all pages
        
    Raises
    ------
    RuntimeError
        If Tesseract is not installed or configured
    """
    try:
        # Convert PDF pages to images
        images = convert_from_path(pdf_path, dpi=dpi)
        
        # Extract text from each image
        text_parts = []
        for i, image in enumerate(images):
            print(f"  OCR processing page {i+1}/{len(images)}...")
            
            # Use pytesseract to extract text
            text = pytesseract.image_to_string(image, lang='eng')
            text_parts.append(text)
        
        return "\n\n".join(text_parts)
        
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract OCR is not installed or not found. "
            "Please install it:\n"
            "  Windows: choco install tesseract OR winget install UB-Mannheim.TesseractOCR\n"
            "  Mac: brew install tesseract\n"
            "  Linux: sudo apt-get install tesseract-ocr"
        )
    except Exception as e:
        raise RuntimeError(f"OCR extraction failed: {str(e)}")


def extract_text_smart(pdf_path: str, force_ocr: bool = False, dpi: int = 300) -> str:
    """
    Smart text extraction: automatically detects if PDF is image-based and uses OCR if needed.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    force_ocr : bool
        Force OCR even if PDF has extractable text (default: False)
    dpi : int
        DPI for OCR image conversion (default: 300)
        
    Returns
    -------
    str
        Extracted text
        
    Notes
    -----
    This function:
    1. Checks if PDF is image-based (scanned)
    2. Uses OCR if image-based or if force_ocr=True
    3. Falls back to regular text extraction for text-based PDFs
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    # Check if we need OCR
    needs_ocr = force_ocr or is_pdf_image_based(pdf_path)
    
    if needs_ocr:
        print(f"  📷 Image-based PDF detected, using OCR...")
        return extract_text_with_ocr(pdf_path, dpi=dpi)
    else:
        print(f"  📄 Text-based PDF detected, using standard extraction...")
        # Use regular pypdf extraction
        reader = pypdf.PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        return "\n".join(pages)


def extract_text_from_image(image_path: str) -> str:
    """
    Extract text from a single image file (JPG, PNG, etc.).
    
    Parameters
    ----------
    image_path : str
        Path to image file
        
    Returns
    -------
    str
        Extracted text
        
    Raises
    ------
    RuntimeError
        If Tesseract is not installed or configured
    """
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image, lang='eng')
        return text
        
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract OCR is not installed or not found. "
            "Please install it:\n"
            "  Windows: choco install tesseract OR winget install UB-Mannheim.TesseractOCR\n"
            "  Mac: brew install tesseract\n"
            "  Linux: sudo apt-get install tesseract-ocr"
        )
    except Exception as e:
        raise RuntimeError(f"Image text extraction failed: {str(e)}")
