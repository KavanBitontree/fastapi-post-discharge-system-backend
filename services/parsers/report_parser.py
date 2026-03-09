"""
report_parser.py
----------------
PDF text extraction using column-aware word bounding box reconstruction.

The core insight: lab report PDFs have consistent column positions for
TEST | RESULT | FLAG | UNIT | REFERENCE RANGE.

By bucketing each word into the correct column by its X position, we get
clean pipe-delimited output like:
    HAEMOGLOBIN | 14.6 |  | g/dL | ( 13.0- 18.0)
    Non-HDL-Cholesterol | 3.9 | * | mmol/L | (<3.4)

This makes it impossible for the LLM to confuse units with reference range.
"""

import io
import re
from collections import defaultdict
from pathlib import Path

import pdfplumber
import pypdf


# ---------------------------------------------------------------------------
# Column X boundaries (pixels) — measured from this PDF's header row:
#   TEST at x0=47, RESULT at x0=286, FLAG at x0=347, UNIT at x0=401, REF at x0=459
# These boundaries apply to Pantai Premier layout.
# For other labs, auto-detection falls back gracefully.
# ---------------------------------------------------------------------------
_COL_RESULT = 280
_COL_FLAG   = 345
_COL_UNIT   = 398
_COL_REF    = 453

# Lines longer than this in the TEST column are footer/legal noise
_MAX_TEST_LEN = 120


def extract_raw_text(pdf_source: str | bytes) -> str:
    """
    Extract clean pipe-delimited columnar text from a PDF.

    Output format per line:
        TEST_NAME | RESULT | FLAG | UNIT | REFERENCE_RANGE

    This explicit column separation prevents the LLM from ever merging
    units with reference range (the root cause of NULL reference_range_low/high).

    Falls back to pypdf plain text if pdfplumber yields nothing.

    Parameters
    ----------
    pdf_source : str | bytes
        File path string OR raw PDF bytes (e.g. from FastAPI UploadFile.read())

    Returns
    -------
    str
        Full structured text across all pages separated by PAGE BREAK markers.
    """
    pdf_bytes = _to_bytes(pdf_source)

    text = _extract_columnar(pdf_bytes)

    if len(text.strip()) < 100:
        text = _extract_with_pypdf(pdf_bytes)

    return text


def is_scanned_pdf(pdf_source: str | bytes) -> bool:
    """
    True if PDF appears to be a scanned image (OCR needed).
    """
    text = extract_raw_text(pdf_source)
    return len(text.strip()) < 100


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _to_bytes(pdf_source: str | bytes) -> bytes:
    if isinstance(pdf_source, str):
        path = Path(pdf_source)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_source}")
        return path.read_bytes()
    elif isinstance(pdf_source, bytes):
        return pdf_source
    raise ValueError(f"pdf_source must be str or bytes, got {type(pdf_source)}")


def _detect_column_boundaries(page) -> tuple[float, float, float, float]:
    """
    Auto-detect column positions from the header row (TEST/RESULT/FLAG/UNIT/REFERENCE).
    Falls back to hardcoded defaults if header not found.
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=2)
    col_map = {}
    for w in words:
        if w['text'] in ('RESULT', 'FLAG', 'UNIT', 'REFERENCE'):
            col_map[w['text']] = w['x0']

    if len(col_map) >= 3:
        result_x = col_map.get('RESULT', _COL_RESULT)
        flag_x   = col_map.get('FLAG',   _COL_FLAG)
        unit_x   = col_map.get('UNIT',   _COL_UNIT)
        ref_x    = col_map.get('REFERENCE', _COL_REF)
        # Use midpoints between columns as boundaries
        c_result = (result_x + flag_x) / 2 if 'FLAG' in col_map else result_x - 5
        c_flag   = (flag_x + unit_x) / 2   if 'UNIT' in col_map else flag_x - 5
        c_unit   = (unit_x + ref_x) / 2    if 'REFERENCE' in col_map else unit_x - 5
        c_ref    = ref_x - 5
        return c_result, c_flag, c_unit, c_ref

    return _COL_RESULT, _COL_FLAG, _COL_UNIT, _COL_REF


def _extract_page_columnar(page, y_tolerance: int = 2) -> str:
    """
    Extract one page using column-aware word bucketing.
    Emits pipe-delimited lines: TEST | RESULT | FLAG | UNIT | REFERENCE_RANGE
    """
    c_result, c_flag, c_unit, c_ref = _detect_column_boundaries(page)

    words = page.extract_words(
        x_tolerance=3,
        y_tolerance=y_tolerance,
        keep_blank_chars=False,
        use_text_flow=False,
    )
    if not words:
        return ""

    # Group words by Y position
    lines: dict[float, list] = defaultdict(list)
    for w in words:
        y_key = round(w['top'] / y_tolerance) * y_tolerance
        lines[y_key].append(w)

    result_lines = []
    for y_key in sorted(lines.keys()):
        line_words = sorted(lines[y_key], key=lambda w: w['x0'])

        test_parts, result_parts, flag_parts, unit_parts, ref_parts = [], [], [], [], []

        for w in line_words:
            x = w['x0']
            t = w['text']
            if x < c_result:
                test_parts.append(t)
            elif x < c_flag:
                result_parts.append(t)
            elif x < c_unit:
                flag_parts.append(t)
            elif x < c_ref:
                unit_parts.append(t)
            else:
                ref_parts.append(t)

        test = ' '.join(test_parts).strip()

        # Skip empty lines and long footer/legal noise
        if not test or len(test) > _MAX_TEST_LEN:
            continue

        result = ' '.join(result_parts).strip()
        flag   = ' '.join(flag_parts).strip()
        unit   = ' '.join(unit_parts).strip()
        ref    = ' '.join(ref_parts).strip()

        result_lines.append(f"{test} | {result} | {flag} | {unit} | {ref}")

    return '\n'.join(result_lines)


def _extract_columnar(pdf_bytes: bytes) -> str:
    """Extract all pages as pipe-delimited columnar text."""
    pages_text: list[str] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = _extract_page_columnar(page)
            pages_text.append(page_text)

    return "\n\n--- PAGE BREAK ---\n\n".join(pages_text)


def _extract_with_pypdf(pdf_bytes: bytes) -> str:
    """Fallback: pypdf layout extraction."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout") or ""
        pages_text.append(text)
    return "\n\n--- PAGE BREAK ---\n\n".join(pages_text)