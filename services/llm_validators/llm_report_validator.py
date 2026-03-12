"""
llm_report_validator.py
-----------------------
Pure LLM-based extraction of medical report data.
No regex. Handles any PDF layout via vision or text strategies.

Supports:
  - Multimodal (vision) input: PDF pages as base64 JPEG images
  - Text input: raw text extracted by pdfplumber
"""

from typing import Optional, List, Dict
from core.llm_init import llm
from schemas.report_schemas import TestResult, ReportHeader, ValidatedReport


# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a medical laboratory report data extraction system.
Extract structured data from medical lab reports and return it in JSON format.

HEADER FIELDS:
- report_name: Full report title (REQUIRED)
- report_date: Date in DD/MM/YYYY HH:MM format (e.g., "29/10/2021 21:26")
- collection_date: Sample collection date in DD/MM/YYYY HH:MM format
- received_date: Sample received date in DD/MM/YYYY HH:MM format
- specimen_type: Type of specimen (e.g., "Whole Blood", "Serum")
- status: Report status (e.g., "FINAL", "ROUTINE")

TEST RESULTS - Extract EVERY test with:
- test_name: Test name (REQUIRED)
- section: Section/category heading
- normal_result: Result value when no abnormal flag is present
- abnormal_result: Result value when an explicit H/L/* flag is printed next to it
- flag: "H"=High, "L"=Low, "*"=Abnormal — copy exactly as printed in the PDF
- units: Unit of measurement
- reference_range_low: Lower bound of reference range
- reference_range_high: Upper bound of reference range

CRITICAL RULES:
- Extract ALL tests from ALL pages - do not skip any
- Keep values concise (no extra text)
- Split ranges: "90-120" → low="90", high="120"
- Use null for missing fields
- Dates must be DD/MM/YYYY HH:MM format"""

_USER_PROMPT_TEXT = """Extract structured data from this medical lab report.

{raw_text}

Return complete header and all test results in the schema."""

_USER_PROMPT_VISION = """Extract all structured data from this medical laboratory report.

The report is provided as {n_pages} page image(s). Read every page carefully.

Extract the complete report header and every single test result. Return in the structured schema."""


# ── Core Extraction Function ──────────────────────────────────────────────────

def extract_structured_report_from_chunk(
    text_chunk: str,
    chunk_index: int,
    total_chunks: int,
) -> ValidatedReport:
    """
    Extract structured data from a chunk of a medical report.

    Parameters
    ----------
    text_chunk : str
        Text chunk from PDF
    chunk_index : int
        Index of current chunk (0-based)
    total_chunks : int
        Total number of chunks

    Returns
    -------
    ValidatedReport
        Structured report data from this chunk
    """
    structured_llm = llm.with_structured_output(ValidatedReport)
    
    # For first chunk, extract header + tests
    # For subsequent chunks, extract only tests
    if chunk_index == 0:
        prompt = f"""Extract the complete header and all test results from this medical report chunk.

This is chunk 1 of {total_chunks}.

{text_chunk}

Return complete header information and all test results found in this chunk."""
    else:
        prompt = f"""Extract ONLY test results from this medical report chunk. Use minimal header.

This is chunk {chunk_index + 1} of {total_chunks}.

{text_chunk}

Return a ValidatedReport with minimal header (report_name="Chunk {chunk_index + 1}") and all test_results from this chunk."""
    
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    
    try:
        result = structured_llm.invoke(messages)
        print(f"[llm] Chunk {chunk_index + 1}: extracted {len(result.test_results)} tests")
        return result
    except Exception as e:
        print(f"[llm] Chunk {chunk_index + 1}: extraction failed, attempting recovery")
        try:
            recovered = _handle_extraction_error(e, messages, structured_llm)
            print(f"[llm] Chunk {chunk_index + 1}: recovered {len(recovered.test_results)} tests")
            return recovered
        except Exception as recovery_error:
            print(f"[llm] Chunk {chunk_index + 1}: recovery also failed - {str(recovery_error)[:100]}")
            # Return minimal valid result instead of failing completely
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


def merge_report_results(results: List[Optional[ValidatedReport]]) -> ValidatedReport:
    """
    Merge results from multiple chunks into a single ValidatedReport.
    
    Takes header from first chunk and combines all test results.
    """
    # Filter out None results
    valid_results = [r for r in results if r is not None]
    
    if not valid_results:
        raise ValueError("No valid results to merge")
    
    # Use header from first chunk
    header = valid_results[0].header
    
    # Combine all test results
    all_tests = []
    for result in valid_results:
        all_tests.extend(result.test_results)
    
    print(f"[llm] Merged {len(valid_results)} chunks: {len(all_tests)} total tests")
    
    return ValidatedReport(header=header, test_results=all_tests)


# ── Backward Compatibility (deprecated) ───────────────────────────────────────

def extract_structured_report(
    page_images: Optional[List[str]] = None,
    raw_text: Optional[str] = None,
) -> ValidatedReport:
    """
    DEPRECATED: Use extract_structured_report_from_chunk with unified_pdf_parser instead.
    
    Legacy function for backward compatibility.
    """
    if page_images is not None:
        raise NotImplementedError("Vision extraction is deprecated. Use text extraction with chunking.")
    
    if raw_text is None:
        raise ValueError("raw_text must be provided")
    
    # Simple single-chunk extraction for backward compatibility
    return extract_structured_report_from_chunk(raw_text, 0, 1)


def _extract_with_chunking(raw_text: str, structured_llm) -> ValidatedReport:
    """
    DEPRECATED: Old chunking implementation. Use unified_pdf_parser instead.
    """
    print("[llm] Starting chunked extraction...")
    
    # Extract header from first part
    header_text = raw_text[:5000]
    header_prompt = f"""Extract ONLY the header information from this medical report:

{header_text}

Return the header with report_name, dates, specimen_type, and status. Set test_results to empty array []."""
    
    header_messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": header_prompt},
    ]
    
    try:
        result = structured_llm.invoke(header_messages)
        header = result.header
        print(f"[llm] Extracted header: {header.report_name}")
    except Exception as header_err:
        print(f"[llm] Header extraction failed: {header_err}, using defaults")
        header = ReportHeader(
            report_name="Laboratory Report",
            report_date=None,
            collection_date=None,
            received_date=None,
            specimen_type=None,
            status=None
        )
    
    all_tests = []
    
    # Split text by page markers
    pages = raw_text.split("--- Page")
    print(f"[llm] Found {len(pages)} pages to process")
    
    for i, page_text in enumerate(pages):
        if not page_text.strip() or len(page_text) < 100:
            continue
        
        # Limit page text to avoid token limits (keep first 10k chars per page)
        page_text = page_text[:10000]
        
        # Extract tests from this page
        page_prompt = f"""Extract ONLY the test results from this page. Ignore header information.

Page content:
{page_text}

Return a ValidatedReport with minimal header (just report_name="Page {i+1}") and all test_results from this page."""
        
        page_messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": page_prompt},
        ]
        
        try:
            page_result = structured_llm.invoke(page_messages)
            page_tests = page_result.test_results
            all_tests.extend(page_tests)
            print(f"[llm] Page {i+1}: extracted {len(page_tests)} tests (total: {len(all_tests)})")
        except Exception as page_err:
            print(f"[llm] Page {i+1}: extraction failed - {str(page_err)[:100]}")
            # Try recovery for this page
            try:
                recovered = _handle_extraction_error(page_err, page_messages, structured_llm)
                page_tests = recovered.test_results
                all_tests.extend(page_tests)
                print(f"[llm] Page {i+1}: recovered {len(page_tests)} tests (total: {len(all_tests)})")
            except Exception:
                print(f"[llm] Page {i+1}: recovery also failed, skipping")
                continue
    
    print(f"[llm] Chunked extraction complete: {len(all_tests)} total tests")
    return ValidatedReport(header=header, test_results=all_tests)


def _build_text_messages(raw_text: str) -> List[Dict]:
    """Build LLM messages for text-based extraction."""
    # Truncate to avoid context limit — 40k chars to stay well within Groq limits
    truncated = raw_text[:40_000]
    if len(raw_text) > 40_000:
        print(f"[llm] Warning: text truncated from {len(raw_text)} to 40,000 chars.")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT_TEXT.format(raw_text=truncated)},
    ]


def _build_vision_messages(page_images: List[str]) -> List[Dict]:
    """
    Build LLM messages for vision-based extraction.

    Constructs a multimodal message with one image block per page.
    Compatible with OpenAI-style vision API (GPT-4o, Claude, etc.)
    """
    content = [
        {
            "type": "text",
            "text": _USER_PROMPT_VISION.format(n_pages=len(page_images)),
        }
    ]

    for i, b64_image in enumerate(page_images):
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64_image}",
                "detail": "high",  # Use "high" for medical data accuracy
            },
        })

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


# ── Error Recovery ────────────────────────────────────────────────────────────

def _handle_extraction_error(error: Exception, messages: List[Dict], structured_llm) -> ValidatedReport:
    """
    Attempt recovery from LLM extraction errors.

    Common failure mode: response truncated due to large number of test results
    causing the structured output parser to fail. We attempt to recover
    the partial JSON from the error message.
    """
    import re
    import json

    error_msg = str(error)

    # Groq/LangChain truncation error pattern
    if "tool_use_failed" in error_msg or "failed_generation" in error_msg:
        print("[llm] Response truncated. Attempting partial recovery...")

        # Try multiple patterns to extract the partial JSON
        patterns = [
            r"'failed_generation': '(.+?)'[,}]",
            r'"failed_generation": "(.+?)"[,}]',
            r"'failed_generation':\s*'(.+)'",
            r'"failed_generation":\s*"(.+)"',
        ]
        
        partial_json = None
        for pattern in patterns:
            match = re.search(pattern, error_msg, re.DOTALL)
            if match:
                partial_json = match.group(1)
                break
        
        if partial_json:
            try:
                # Clean up escape sequences
                partial_json = partial_json.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")
                
                print(f"[llm] Raw partial JSON length: {len(partial_json)}")

                # Check if it's wrapped in Groq's tool call format
                if '"name": "ValidatedReport"' in partial_json or "'name': 'ValidatedReport'" in partial_json:
                    # Extract the arguments object
                    args_match = re.search(r'"arguments":\s*({.+)', partial_json, re.DOTALL)
                    if args_match:
                        partial_json = args_match.group(1)
                        print("[llm] Extracted arguments from Groq tool call wrapper")

                # Remove any incomplete field at the end (truncated mid-field)
                # Look for patterns like: "field_name": "incomplete_val
                partial_json = re.sub(r',\s*"[^"]+"\s*:\s*"[^"]*$', '', partial_json)
                partial_json = re.sub(r',\s*"[^"]+"\s*:\s*[^,}\]]*$', '', partial_json)
                
                # Remove trailing incomplete objects in test_results array
                # Pattern: incomplete test object at end of array
                partial_json = re.sub(r',\s*{\s*"[^}]*$', '', partial_json)

                print(f"[llm] Cleaned partial JSON length: {len(partial_json)}")

                # Attempt to close open JSON arrays/objects with various suffixes
                suffixes = [
                    '}]}}',   # Close test object, test_results array, and root
                    ']}}',    # Close test_results array and root
                    '}}',     # Close root object
                ]
                
                for suffix in suffixes:
                    try:
                        test_json = partial_json + suffix
                        data = json.loads(test_json)
                        
                        # Extract header
                        if "header" in data:
                            header = ReportHeader(**data["header"])
                        else:
                            # Try to extract header from partial data
                            header = ReportHeader(
                                report_name=data.get("report_name", "Unknown Report"),
                                report_date=data.get("report_date"),
                                collection_date=data.get("collection_date"),
                                received_date=data.get("received_date"),
                                specimen_type=data.get("specimen_type"),
                                status=data.get("status"),
                            )
                        
                        # Extract test results
                        tests = []
                        if "test_results" in data:
                            for t in data.get("test_results", []):
                                try:
                                    tests.append(TestResult(**t))
                                except Exception as test_err:
                                    print(f"[llm] Skipping invalid test: {test_err}")
                                    continue
                        
                        if tests:  # Only return if we got some tests
                            print(f"[llm] Successfully recovered {len(tests)} tests from truncated response.")
                            return ValidatedReport(header=header, test_results=tests)
                    except (json.JSONDecodeError, KeyError, TypeError) as parse_err:
                        # Try next suffix
                        continue
                        
                print("[llm] All suffix attempts failed")
            except Exception as parse_err:
                print(f"[llm] Recovery failed with error: {parse_err}")

    # If recovery fails, raise the original error
    raise error


# ── Standalone Fallback ───────────────────────────────────────────────────────

def extract_report_name_only(raw_text: str) -> str:
    """
    Lightweight LLM call to extract just the report name.
    Used as a last-resort fallback if full extraction fails.

    Parameters
    ----------
    raw_text : str
        Raw text from PDF (first ~2000 chars is enough).

    Returns
    -------
    str
        The report title.
    """
    prompt = (
        "Extract the report name/title from this medical laboratory report. "
        "Return ONLY the title, nothing else.\n\n"
        f"{raw_text[:2000]}"
    )
    response = llm.invoke(prompt)
    return response.content.strip()
