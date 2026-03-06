"""
PDF Type Detection Utility
---------------------------
Detects whether a PDF is text-based or scanned/image-based.

Uses multiple heuristics:
1. Text extraction character count
2. Text density (chars per page)
3. Image presence and coverage
4. Font information
"""

from pathlib import Path
from typing import Tuple, Dict
import pdfplumber


class PDFTypeDetector:
    """Detect PDF type: text-based vs scanned."""
    
    # Thresholds for detection
    MIN_CHARS_PER_PAGE = 100  # Minimum chars/page for text-based PDF
    MIN_WORDS_PER_PAGE = 20   # Minimum words/page for text-based PDF
    MAX_IMAGE_RATIO = 0.7     # Max image coverage ratio for text-based PDF
    
    @classmethod
    def analyze_pdf(cls, pdf_path: str, max_pages: int = 3) -> Dict:
        """
        Analyze PDF and return detailed metrics.
        
        Parameters
        ----------
        pdf_path : str
            Path to PDF file
        max_pages : int
            Maximum pages to analyze (default: 3)
            
        Returns
        -------
        dict
            Analysis results with metrics
        """
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            pages_to_check = min(max_pages, total_pages)
            
            total_chars = 0
            total_words = 0
            total_images = 0
            has_fonts = False
            
            for page in pdf.pages[:pages_to_check]:
                # Text metrics
                text = page.extract_text() or ""
                total_chars += len(text.strip())
                total_words += len(text.split())
                
                # Image metrics
                images = page.images
                total_images += len(images)
                
                # Font detection (text-based PDFs have fonts)
                if not has_fonts and page.chars:
                    has_fonts = True
            
            # Calculate averages
            avg_chars = total_chars / pages_to_check if pages_to_check > 0 else 0
            avg_words = total_words / pages_to_check if pages_to_check > 0 else 0
            avg_images = total_images / pages_to_check if pages_to_check > 0 else 0
            
            return {
                "total_pages": total_pages,
                "pages_analyzed": pages_to_check,
                "total_chars": total_chars,
                "total_words": total_words,
                "total_images": total_images,
                "avg_chars_per_page": avg_chars,
                "avg_words_per_page": avg_words,
                "avg_images_per_page": avg_images,
                "has_fonts": has_fonts,
            }
    
    @classmethod
    def is_scanned(cls, pdf_path: str, verbose: bool = True) -> Tuple[bool, Dict]:
        """
        Detect if PDF is scanned.
        
        Parameters
        ----------
        pdf_path : str
            Path to PDF file
        verbose : bool
            Print detection details
            
        Returns
        -------
        tuple
            (is_scanned: bool, analysis: dict)
        """
        try:
            analysis = cls.analyze_pdf(pdf_path)
            
            # Decision logic
            is_scanned = False
            reason = ""
            
            # Check 1: Very low text content
            if analysis["avg_chars_per_page"] < cls.MIN_CHARS_PER_PAGE:
                is_scanned = True
                reason = f"Low text density ({analysis['avg_chars_per_page']:.0f} < {cls.MIN_CHARS_PER_PAGE} chars/page)"
            
            # Check 2: Very few words
            elif analysis["avg_words_per_page"] < cls.MIN_WORDS_PER_PAGE:
                is_scanned = True
                reason = f"Few words ({analysis['avg_words_per_page']:.0f} < {cls.MIN_WORDS_PER_PAGE} words/page)"
            
            # Check 3: Has images but minimal text
            elif analysis["avg_images_per_page"] >= 1 and analysis["avg_chars_per_page"] < cls.MIN_CHARS_PER_PAGE * 2:
                is_scanned = True
                reason = f"Images present with low text ({analysis['avg_chars_per_page']:.0f} chars/page)"
            
            # Check 4: No fonts detected (strong indicator of scanned)
            elif not analysis["has_fonts"] and analysis["total_chars"] < 50:
                is_scanned = True
                reason = "No fonts detected"
            
            else:
                reason = f"Sufficient text content ({analysis['avg_chars_per_page']:.0f} chars/page)"
            
            analysis["is_scanned"] = is_scanned
            analysis["reason"] = reason
            
            if verbose:
                print(f"\n[PDF Detection] {Path(pdf_path).name}")
                print(f"  Pages: {analysis['pages_analyzed']}/{analysis['total_pages']}")
                print(f"  Chars/page: {analysis['avg_chars_per_page']:.0f}")
                print(f"  Words/page: {analysis['avg_words_per_page']:.0f}")
                print(f"  Images/page: {analysis['avg_images_per_page']:.1f}")
                print(f"  Has fonts: {analysis['has_fonts']}")
                print(f"  Type: {'SCANNED' if is_scanned else 'TEXT-BASED'}")
                print(f"  Reason: {reason}\n")
            
            return is_scanned, analysis
            
        except Exception as e:
            if verbose:
                print(f"[PDF Detection] Error: {e}")
                print(f"[PDF Detection] Defaulting to SCANNED (safe choice)\n")
            
            return True, {
                "error": str(e),
                "is_scanned": True,
                "reason": "Error during detection, assuming scanned"
            }
    
    @classmethod
    def get_extraction_strategy(cls, pdf_path: str) -> str:
        """
        Determine the best extraction strategy for a PDF.
        
        Parameters
        ----------
        pdf_path : str
            Path to PDF file
            
        Returns
        -------
        str
            "vision" for scanned PDFs, "text" for text-based PDFs
        """
        is_scanned, _ = cls.is_scanned(pdf_path, verbose=False)
        return "vision" if is_scanned else "text"


# Convenience functions
def is_scanned_pdf(pdf_path: str, verbose: bool = True) -> bool:
    """
    Quick check if PDF is scanned.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    verbose : bool
        Print detection details
        
    Returns
    -------
    bool
        True if PDF is scanned
    """
    is_scanned, _ = PDFTypeDetector.is_scanned(pdf_path, verbose=verbose)
    return is_scanned


def analyze_pdf(pdf_path: str) -> Dict:
    """
    Get detailed PDF analysis.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
        
    Returns
    -------
    dict
        Analysis results
    """
    return PDFTypeDetector.analyze_pdf(pdf_path)


def get_extraction_strategy(pdf_path: str) -> str:
    """
    Get recommended extraction strategy.
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
        
    Returns
    -------
    str
        "vision" or "text"
    """
    return PDFTypeDetector.get_extraction_strategy(pdf_path)
