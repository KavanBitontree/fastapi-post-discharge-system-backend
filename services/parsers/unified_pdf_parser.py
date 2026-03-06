"""
Unified PDF Parser
------------------
Handles both text-based and scanned PDFs with automatic detection.

Routes to appropriate extraction method:
- Text-based PDFs → text extraction with pdfplumber
- Scanned PDFs → vision extraction with HuggingFace
"""

from pathlib import Path
from typing import Callable, TypeVar, Union, BinaryIO
import pdfplumber
from io import BytesIO

from core.chunking import calculate_chunking_strategy, get_model_config
from services.utils.pdf_detector import PDFTypeDetector

# Type variable for generic return types
T = TypeVar('T')


def analyze_pdf_for_chunking(pdf_path: str) -> dict:
    """
    Analyze PDF and determine chunking strategy.
    
    Works for both text-based and scanned PDFs.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
        
    Returns
    -------
    dict
        Chunking information including strategy, cost estimate, etc.
    """
    # Detect PDF type
    is_scanned, detection_info = PDFTypeDetector.is_scanned(pdf_path, verbose=True)
    
    if is_scanned:
        # For scanned PDFs, estimate based on image tokens
        from core.img_to_txt_llm_init import load_input
        images = load_input(pdf_path)
        total_pages = len(images)
        avg_tokens_per_page = 1500  # Vision models use ~1000-2000 tokens per image
        
        chunk_info = calculate_chunk_size(
            total_pages=total_pages,
            avg_tokens_per_page=avg_tokens_per_page,
            model_name=MODEL_ID
        )
        
        return {
            "pdf_type": "scanned",
            "total_pages": total_pages,
            "pages_per_chunk": chunk_info["pages_per_chunk"],
            "total_chunks": chunk_info["total_chunks"],
            "estimated_tokens_per_chunk": chunk_info["estimated_tokens_per_chunk"],
            "estimated_cost": chunk_info["estimated_cost"],
            "model": MODEL_ID,
            "extraction_type": "vision",
            "detection_info": detection_info,
        }
    else:
        # For text-based PDFs
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            
            # Sample first 3 pages to estimate tokens
            sample_pages = min(3, total_pages)
            total_chars = 0
            
            for page in pdf.pages[:sample_pages]:
                text = page.extract_text() or ""
                total_chars += len(text)
            
            avg_chars_per_page = total_chars / sample_pages if sample_pages > 0 else 0
            avg_tokens_per_page = avg_chars_per_page / 4  # ~4 chars per token
            
            chunk_strategy = calculate_chunking_strategy(
                total_pages=total_pages,
                avg_chars_per_page=int(avg_chars_per_page),
                model_name="openai/gpt-oss-120b"
            )
            
            return {
                "pdf_type": "text",
                "total_pages": total_pages,
                "pages_per_chunk": chunk_strategy.pages_per_chunk,
                "total_chunks": chunk_strategy.estimated_total_chunks,
                "estimated_tokens_per_chunk": chunk_strategy.estimated_tokens_per_chunk,
                "estimated_cost": chunk_strategy.estimated_cost,
                "model": "openai/gpt-oss-120b",
                "extraction_type": "text",
                "detection_info": detection_info,
            }


def extract_with_chunking(
    pdf_path: str,
    extraction_function: Callable,
    merge_function: Callable,
    strategy: str = "auto"
) -> T:
    """
    Extract structured data from PDF with automatic chunking.
    
    Automatically detects PDF type and routes to appropriate extraction method.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    extraction_function : Callable
        Function to extract from a single chunk (text-based)
    merge_function : Callable
        Function to merge results from multiple chunks
    strategy : str
        "auto" (default) - auto-detect PDF type
        "text" - force text extraction
        "vision" - force vision extraction
        
    Returns
    -------
    T
        Merged extraction result
    """
    # Determine extraction strategy
    if strategy == "auto":
        is_scanned, _ = PDFTypeDetector.is_scanned(pdf_path, verbose=True)
        actual_strategy = "vision" if is_scanned else "text"
    else:
        actual_strategy = strategy
    
    print(f"[unified-parser] Using {actual_strategy} extraction")
    
    if actual_strategy == "vision":
        # Route to vision parser
        # Import here to avoid circular dependency
        from services.parsers.vision_parser import (
            parse_report_vision,
            parse_bill_vision,
            parse_prescription_vision,
        )
        
        # Determine document type from extraction function name
        func_name = extraction_function.__name__
        
        if "report" in func_name.lower():
            return parse_report_vision(pdf_path)
        elif "bill" in func_name.lower():
            return parse_bill_vision(pdf_path)
        elif "prescription" in func_name.lower():
            return parse_prescription_vision(pdf_path)
        else:
            raise ValueError(f"Unknown document type for function: {func_name}")
    
    else:
        # Text-based extraction (existing logic)
        chunk_info = analyze_pdf_for_chunking(pdf_path)
        
        print(f"[unified-parser] PDF: {chunk_info['total_pages']} pages")
        print(f"[unified-parser] Strategy: {chunk_info['pages_per_chunk']} pages/chunk, "
              f"{chunk_info['total_chunks']} chunks, ~${chunk_info['estimated_cost']:.4f}")
        
        # Extract text from all pages
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n\n".join(
                page.extract_text() or "" for page in pdf.pages
            )
        
        pages_per_chunk = chunk_info["pages_per_chunk"]
        total_chunks = chunk_info["total_chunks"]
        
        if total_chunks == 1:
            print(f"[unified-parser] Processing in single chunk")
            result = extraction_function(full_text, 0, 1)
            return result
        else:
            print(f"[unified-parser] Created {total_chunks} chunks")
            
            # Split text into chunks
            with pdfplumber.open(pdf_path) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            
            results = []
            for i in range(total_chunks):
                start = i * pages_per_chunk
                end = min(start + pages_per_chunk, len(pages))
                chunk_text = "\n\n".join(pages[start:end])
                
                print(f"[unified-parser] Processing chunk {i+1}/{total_chunks} "
                      f"(pages {start+1}-{end})")
                
                result = extraction_function(chunk_text, i, total_chunks)
                results.append(result)
                
                print(f"[unified-parser] Chunk {i+1} complete")
            
            print(f"[unified-parser] Merging results...")
            merged = merge_function(results)
            return merged


def extract_with_chunking_from_memory(
    pdf_buffer: BinaryIO,
    filename: str,
    extraction_function: Callable,
    merge_function: Callable,
    strategy: str = "auto"
) -> T:
    """
    Extract structured data from PDF in memory (for Vercel deployment).
    
    Automatically detects PDF type and routes to appropriate extraction method.
    
    Parameters
    ----------
    pdf_buffer : BinaryIO
        PDF content in memory
    filename : str
        Original filename for logging
    extraction_function : Callable
        Function to extract from a single chunk (text-based)
    merge_function : Callable
        Function to merge results from multiple chunks
    strategy : str
        "auto" (default) - auto-detect PDF type
        "text" - force text extraction
        "vision" - force vision extraction
        
    Returns
    -------
    T
        Merged extraction result
    """
    # Create temporary file-like object for PDF detection
    pdf_buffer.seek(0)  # Reset to beginning
    temp_bytes = pdf_buffer.read()
    pdf_buffer.seek(0)  # Reset again
    
    # Write to temporary BytesIO for detection
    temp_buffer = BytesIO(temp_bytes)
    
    # Determine extraction strategy
    if strategy == "auto":
        # For memory-based detection, we need to use a different approach
        # Since PDFTypeDetector expects a file path, we'll use a simple heuristic
        try:
            with pdfplumber.open(temp_buffer) as pdf:
                total_pages = len(pdf.pages)
                sample_pages = min(3, total_pages)
                total_chars = 0
                
                for page in pdf.pages[:sample_pages]:
                    text = page.extract_text() or ""
                    total_chars += len(text.strip())
                
                avg_chars_per_page = total_chars / sample_pages if sample_pages > 0 else 0
                is_scanned = avg_chars_per_page < 100  # Same threshold as PDFTypeDetector
                
                print(f"[unified-parser] Memory detection: {avg_chars_per_page:.0f} chars/page")
                print(f"[unified-parser] Type: {'SCANNED' if is_scanned else 'TEXT-BASED'}")
                
                actual_strategy = "vision" if is_scanned else "text"
        except Exception as e:
            print(f"[unified-parser] Detection failed: {e}, defaulting to vision")
            actual_strategy = "vision"
    else:
        actual_strategy = strategy
    
    print(f"[unified-parser] Using {actual_strategy} extraction")
    
    if actual_strategy == "vision":
        # Route to vision parser (memory-based)
        from services.parsers.vision_parser import (
            parse_report_vision_from_memory,
            parse_bill_vision_from_memory,
            parse_prescription_vision_from_memory,
        )
        
        # Determine document type from extraction function name
        func_name = extraction_function.__name__
        
        if "report" in func_name.lower():
            return parse_report_vision_from_memory(pdf_buffer, filename)
        elif "bill" in func_name.lower():
            return parse_bill_vision_from_memory(pdf_buffer, filename)
        elif "prescription" in func_name.lower():
            return parse_prescription_vision_from_memory(pdf_buffer, filename)
        else:
            raise ValueError(f"Unknown document type for function: {func_name}")
    
    else:
        # Text-based extraction (memory-based)
        temp_buffer.seek(0)
        
        with pdfplumber.open(temp_buffer) as pdf:
            total_pages = len(pdf.pages)
            
            # Sample first 3 pages to estimate tokens
            sample_pages = min(3, total_pages)
            total_chars = 0
            
            for page in pdf.pages[:sample_pages]:
                text = page.extract_text() or ""
                total_chars += len(text)
            
            avg_chars_per_page = total_chars / sample_pages if sample_pages > 0 else 0
            avg_tokens_per_page = avg_chars_per_page / 4  # ~4 chars per token
            
            chunk_strategy = calculate_chunking_strategy(
                total_pages=total_pages,
                avg_chars_per_page=int(avg_chars_per_page),
                model_name="openai/gpt-oss-120b"
            )
            
            print(f"[unified-parser] PDF: {total_pages} pages")
            print(f"[unified-parser] Strategy: {chunk_strategy.pages_per_chunk} pages/chunk, "
                  f"{chunk_strategy.estimated_total_chunks} chunks, ~${chunk_strategy.estimated_cost:.4f}")
            
            # Extract text from all pages
            full_text = "\n\n".join(
                page.extract_text() or "" for page in pdf.pages
            )
            
            pages_per_chunk = chunk_strategy.pages_per_chunk
            total_chunks = chunk_strategy.estimated_total_chunks
            
            if total_chunks == 1:
                print(f"[unified-parser] Processing in single chunk")
                result = extraction_function(full_text, 0, 1)
                return result
            else:
                print(f"[unified-parser] Created {total_chunks} chunks")
                
                # Split text into chunks
                pages = [page.extract_text() or "" for page in pdf.pages]
                
                results = []
                for i in range(total_chunks):
                    start = i * pages_per_chunk
                    end = min(start + pages_per_chunk, len(pages))
                    chunk_text = "\n\n".join(pages[start:end])
                    
                    print(f"[unified-parser] Processing chunk {i+1}/{total_chunks} "
                          f"(pages {start+1}-{end})")
                    
                    result = extraction_function(chunk_text, i, total_chunks)
                    results.append(result)
                    
                    print(f"[unified-parser] Chunk {i+1} complete")
                
                print(f"[unified-parser] Merging results...")
                merged = merge_function(results)
                return merged