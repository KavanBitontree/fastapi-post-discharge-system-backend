"""
Vision Parser
-------------
Unified parser for scanned PDFs and images using vision models.

Uses the same chunking system as text-based extraction for consistency.
"""

from pathlib import Path
from typing import Tuple, List
import math

from core.img_to_txt_llm_init import load_input
from core.chunking import calculate_chunking_strategy, get_model_config

# Import validators
from services.llm_validators.llm_vision_validator import (
    extract_report_from_vision,
    extract_bill_from_vision,
    extract_prescription_from_vision,
)

# Import merge functions
from services.llm_validators.llm_report_validator import merge_report_results
from services.llm_validators.llm_bill_validator import merge_bill_results
from services.llm_validators.llm_prescription_validator import merge_prescription_results

# Import result types
from schemas.report_schemas import ValidatedReport
from schemas.bill_schemas import ValidatedBill
from schemas.prescription_schemas import ValidatedPrescription
from services.parsers.bill_parser import ParsedBill
from services.parsers.prescription_parser import ParsedPrescription


def analyze_vision_pdf_for_chunking(pdf_path: str) -> dict:
    """
    Analyze scanned PDF and determine chunking strategy.
    
    Uses unified chunking system from core.chunking.
    
    Parameters
    ----------
    pdf_path : str
        Path to scanned PDF or image
        
    Returns
    -------
    dict
        Chunking information
    """
    # Load images to get page count
    images = load_input(pdf_path)
    total_pages = len(images)
    
    # Get model config
    config = get_model_config("openai/gpt-oss-120b")
    
    # For vision, estimate tokens per page (images are token-heavy)
    # Vision models typically use ~1000-2000 tokens per image
    avg_tokens_per_page = 1500
    
    # Calculate chunk size using unified system
    chunk_strategy = calculate_chunking_strategy(
        total_pages=total_pages,
        avg_chars_per_page=avg_tokens_per_page * 4,  # Convert tokens to chars estimate
        model_name="openai/gpt-oss-120b"
    )
    
    return {
        "total_pages": total_pages,
        "pages_per_chunk": chunk_strategy.pages_per_chunk,
        "total_chunks": chunk_strategy.estimated_total_chunks,
        "estimated_tokens_per_chunk": chunk_strategy.estimated_tokens_per_chunk,
        "estimated_cost": chunk_strategy.estimated_cost,
        "model": "openai/gpt-oss-120b",
        "extraction_type": "vision",
    }


def parse_report_vision(pdf_path: str) -> ValidatedReport:
    """
    Parse scanned report PDF using vision model with unified chunking.
    
    Parameters
    ----------
    pdf_path : str
        Path to scanned PDF or image
        
    Returns
    -------
    ValidatedReport
        Parsed report data
    """
    # Analyze for chunking
    chunk_info = analyze_vision_pdf_for_chunking(pdf_path)
    
    print(f"[vision-parser] Extracting report: {Path(pdf_path).name}")
    print(f"[vision-parser] PDF: {chunk_info['total_pages']} pages")
    print(f"[vision-parser] Strategy: {chunk_info['pages_per_chunk']} pages/chunk, "
          f"{chunk_info['total_chunks']} chunks, ~${chunk_info['estimated_cost']:.4f}")
    
    # Load all images
    images = load_input(pdf_path)
    pages_per_chunk = chunk_info["pages_per_chunk"]
    total_chunks = chunk_info["total_chunks"]
    
    if total_chunks == 1:
        print(f"[vision-parser] Processing in single chunk")
        result = extract_report_from_vision(pdf_path, 0, 1)
        # Convert ValidatedReport to ParsedReport
        # (This conversion is handled by merge_report_results)
        return result
    else:
        print(f"[vision-parser] Created {total_chunks} chunks")
        results = []
        
        for i in range(total_chunks):
            start = i * pages_per_chunk
            end = min(start + pages_per_chunk, len(images))
            
            print(f"[vision-parser] Processing chunk {i+1}/{total_chunks} "
                  f"(pages {start+1}-{end})")
            
            # Extract from chunk
            result = extract_report_from_vision(pdf_path, i, total_chunks)
            results.append(result)
            
            print(f"[vision-parser] Chunk {i+1} complete")
        
        print(f"[vision-parser] Merging results...")
        # Merge using same function as text extraction
        merged = merge_report_results(results)
        return merged


def parse_bill_vision(pdf_path: str) -> ParsedBill:
    """
    Parse scanned bill PDF using vision model with unified chunking.
    
    Parameters
    ----------
    pdf_path : str
        Path to scanned PDF or image
        
    Returns
    -------
    ParsedBill
        Parsed bill data
    """
    chunk_info = analyze_vision_pdf_for_chunking(pdf_path)
    
    print(f"[vision-parser] Extracting bill: {Path(pdf_path).name}")
    print(f"[vision-parser] PDF: {chunk_info['total_pages']} pages")
    print(f"[vision-parser] Strategy: {chunk_info['pages_per_chunk']} pages/chunk, "
          f"{chunk_info['total_chunks']} chunks")
    
    images = load_input(pdf_path)
    pages_per_chunk = chunk_info["pages_per_chunk"]
    total_chunks = chunk_info["total_chunks"]
    
    if total_chunks == 1:
        print(f"[vision-parser] Processing in single chunk")
        result = extract_bill_from_vision(pdf_path, 0, 1)
        # Convert to ParsedBill
        return merge_bill_results([result])
    else:
        print(f"[vision-parser] Created {total_chunks} chunks")
        results = []
        
        for i in range(total_chunks):
            print(f"[vision-parser] Processing chunk {i+1}/{total_chunks}")
            result = extract_bill_from_vision(pdf_path, i, total_chunks)
            results.append(result)
            print(f"[vision-parser] Chunk {i+1} complete")
        
        print(f"[vision-parser] Merging results...")
        merged = merge_bill_results(results)
        return merged


def parse_prescription_vision(pdf_path: str) -> ParsedPrescription:
    """
    Parse scanned prescription PDF using vision model with unified chunking.
    
    Parameters
    ----------
    pdf_path : str
        Path to scanned PDF or image
        
    Returns
    -------
    ParsedPrescription
        Parsed prescription data
    """
    chunk_info = analyze_vision_pdf_for_chunking(pdf_path)
    
    print(f"[vision-parser] Extracting prescription: {Path(pdf_path).name}")
    print(f"[vision-parser] PDF: {chunk_info['total_pages']} pages")
    print(f"[vision-parser] Strategy: {chunk_info['pages_per_chunk']} pages/chunk, "
          f"{chunk_info['total_chunks']} chunks")
    
    images = load_input(pdf_path)
    pages_per_chunk = chunk_info["pages_per_chunk"]
    total_chunks = chunk_info["total_chunks"]
    
    if total_chunks == 1:
        print(f"[vision-parser] Processing in single chunk")
        result = extract_prescription_from_vision(pdf_path, 0, 1)
        # Convert to ParsedPrescription
        return merge_prescription_results([result])
    else:
        print(f"[vision-parser] Created {total_chunks} chunks")
        results = []
        
        for i in range(total_chunks):
            print(f"[vision-parser] Processing chunk {i+1}/{total_chunks}")
            result = extract_prescription_from_vision(pdf_path, i, total_chunks)
            results.append(result)
            print(f"[vision-parser] Chunk {i+1} complete")
        
        print(f"[vision-parser] Merging results...")
        merged = merge_prescription_results(results)
        return merged


# ══════════════════════════════════════════════════════════════════════════════
# MEMORY-BASED FUNCTIONS FOR VERCEL DEPLOYMENT
# ══════════════════════════════════════════════════════════════════════════════

def parse_report_vision_from_memory(pdf_buffer, filename: str) -> ValidatedReport:
    """Parse scanned report PDF from memory (for Vercel deployment)."""
    from io import BytesIO
    import tempfile
    import os
    
    # Create temporary file for vision processing
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
        pdf_buffer.seek(0)
        temp_file.write(pdf_buffer.read())
        temp_path = temp_file.name
    
    try:
        result = parse_report_vision(temp_path)
        return result
    finally:
        # Clean up temporary file
        try:
            os.unlink(temp_path)
        except:
            pass


def parse_bill_vision_from_memory(pdf_buffer, filename: str) -> ParsedBill:
    """Parse scanned bill PDF from memory (for Vercel deployment)."""
    from io import BytesIO
    import tempfile
    import os
    
    # Create temporary file for vision processing
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
        pdf_buffer.seek(0)
        temp_file.write(pdf_buffer.read())
        temp_path = temp_file.name
    
    try:
        result = parse_bill_vision(temp_path)
        return result
    finally:
        # Clean up temporary file
        try:
            os.unlink(temp_path)
        except:
            pass


def parse_prescription_vision_from_memory(pdf_buffer, filename: str) -> ParsedPrescription:
    """Parse scanned prescription PDF from memory (for Vercel deployment)."""
    from io import BytesIO
    import tempfile
    import os
    
    # Create temporary file for vision processing
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
        pdf_buffer.seek(0)
        temp_file.write(pdf_buffer.read())
        temp_path = temp_file.name
    
    try:
        result = parse_prescription_vision(temp_path)
        return result
    finally:
        # Clean up temporary file
        try:
            os.unlink(temp_path)
        except:
            pass