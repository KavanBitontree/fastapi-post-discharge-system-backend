"""
llm_discharge_summary_converter.py
-----------------------------------
Converts complex medical discharge summaries into patient-friendly reports.
Uses chunking for large documents (15-16 pages).
"""

from typing import List
from core.llm_init import llm
from core.chunking import (
    calculate_chunking_strategy,
    chunk_text_by_size,
    estimate_tokens
)
from schemas.patient_friendly_report_schemas import PatientFriendlyReportResponse

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a medical communication expert who converts complex medical discharge summaries into patient-friendly language.

Your goal: Create a clear, concise 1-page summary that patients can understand without medical training.

CRITICAL REQUIREMENTS - DO NOT OMIT:
- INCLUDE ALL MEDICATIONS with dosage and timing (e.g., "Aspirin 75mg daily")
- INCLUDE ALL LAB VALUES with simple explanations (e.g., "blood count improved from 6.2 to 9.4")
- INCLUDE blood transfusions, IV treatments, and major procedures
- INCLUDE dietary restrictions (low-sodium, DASH diet, NSAID avoidance)
- INCLUDE specific follow-up timelines (not vague - e.g., "2 weeks" not "1-2 weeks")
- INCLUDE test results that explain the diagnosis (hemoglobin, cholesterol, kidney function, etc.)
- INCLUDE any special monitoring needed

GUIDELINES:
- Use simple, everyday language (avoid medical jargon)
- When medical terms are necessary, explain them in parentheses
- Be empathetic and reassuring in tone
- Focus on what matters to the patient: their condition, treatment, and next steps
- Include specific numbers and values (e.g., "blood count improved from 6.2 to 9.4")
- Keep the summary to approximately 500-700 words (1 page)

STRUCTURE YOUR RESPONSE AS JSON:
{
  "summary": "Main patient-friendly narrative (500-700 words) - MUST include all medications, lab values, procedures, and dietary instructions",
  "key_points": ["3-5 most important takeaways - include specific test results"],
  "medications": ["COMPLETE list of ALL medications with dosage and timing"],
  "follow_up_instructions": "Specific timeline and actions - include dietary restrictions, activity level, monitoring instructions",
  "warning_signs": ["When to seek immediate medical attention"]
}

TONE: Warm, clear, and supportive. Write as if explaining to a family member.

IMPORTANT: Do NOT omit any medications, lab values, or important medical details. Include everything."""

_CHUNK_SUMMARY_PROMPT = """Extract and simplify the key medical information from this section of a discharge summary.

This is chunk {chunk_index} of {total_chunks}.

CRITICAL: Extract ALL of the following if present:
- ALL medications (with dosage and timing)
- ALL lab values and test results (with numbers)
- Blood transfusions or IV treatments
- Procedures performed
- Dietary restrictions
- Follow-up appointments and timelines
- Monitoring instructions

Focus on:
- Patient's condition and diagnosis
- Treatments received
- Medications (COMPLETE list)
- Test results (in simple terms with specific numbers)
- Follow-up care needed (specific timelines)
- Warning signs
- Dietary and lifestyle changes

DISCHARGE SUMMARY SECTION:
{text_chunk}

Return simplified information in JSON format. DO NOT OMIT any medications, lab values, or important details."""

_FINAL_SYNTHESIS_PROMPT = """You have received simplified information from {num_chunks} sections of a discharge summary.

Now create a cohesive, patient-friendly 1-page report that combines ALL this information.

CRITICAL: Include EVERYTHING:
- ALL medications (with dosage and timing)
- ALL lab values (with specific numbers and what they mean)
- Blood transfusions and IV treatments
- Dietary restrictions and lifestyle changes
- Specific follow-up timelines
- All test results that explain the diagnosis

SIMPLIFIED SECTIONS:
{combined_summaries}

Create a complete patient-friendly report following the JSON structure.
Keep the main summary to 500-700 words (approximately 1 page when printed).
DO NOT OMIT any medications, lab values, or important medical details."""


# ── Core Conversion Functions ─────────────────────────────────────────────────

def convert_discharge_summary_to_patient_friendly(
    discharge_text: str,
    model_name: str = "openai/gpt-oss-120b"
) -> dict:
    """
    Convert a complex discharge summary into a patient-friendly 1-page report.
    
    Uses intelligent chunking for large documents (15-16 pages).
    
    Parameters
    ----------
    discharge_text : str
        Full text of the discharge summary
    model_name : str
        LLM model to use
    
    Returns
    -------
    dict
        Patient-friendly report with summary, key points, medications, etc.
    """
    print(f"[converter] Starting conversion of {len(discharge_text)} character document")
    
    # Calculate if we need chunking
    estimated_tokens = estimate_tokens(discharge_text)
    print(f"[converter] Estimated tokens: {estimated_tokens}")
    
    # With 8K TPM limit, we need to be very conservative
    # Use chunking for anything over 3000 tokens (to stay well under 8K with prompt + output)
    if estimated_tokens < 3000:  # Very conservative for 8K TPM limit
        print("[converter] Document small enough for single-pass processing")
        return _convert_single_pass(discharge_text)
    
    # For large documents, use chunking strategy
    print("[converter] Document requires chunking")
    return _convert_with_chunking(discharge_text, model_name)


def _convert_single_pass(discharge_text: str) -> dict:
    """Convert discharge summary in a single LLM call."""
    
    import json
    import re
    
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"""Convert this discharge summary into a patient-friendly 1-page report.

CRITICAL: Include ALL medications, ALL lab values, blood transfusions, dietary restrictions, and specific follow-up timelines.

{discharge_text}

Return ONLY valid JSON (no markdown, no extra text) with these exact fields:
{{
  "summary": "Main patient-friendly narrative (500-700 words) - MUST include all medications, lab values, procedures, and dietary instructions",
  "key_points": ["3-5 most important takeaways - include specific test results"],
  "medications": ["COMPLETE list of ALL medications with dosage and timing"],
  "follow_up_instructions": "Specific timeline and actions - include dietary restrictions, activity level, monitoring instructions",
  "warning_signs": ["When to seek immediate medical attention"]
}}"""}
    ]
    
    try:
        # Use regular LLM to get JSON text, then parse it
        response = llm.invoke(messages)
        response_text = response.content
        
        # Look for JSON in the response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            result_dict = json.loads(json_str)
            print(f"[converter] Single-pass conversion successful")
            return result_dict
        else:
            raise ValueError("No JSON found in response")
            
    except Exception as e:
        print(f"[converter] Single-pass conversion failed: {e}")
        raise ValueError(f"Failed to convert discharge summary: {str(e)}")


def _convert_with_chunking(discharge_text: str, model_name: str) -> dict:
    """
    Convert large discharge summary using chunking strategy.
    
    Process:
    1. Split document into manageable chunks
    2. Simplify each chunk separately
    3. Synthesize all simplified chunks into final 1-page report
    """
    
    # For 8K TPM limit, use very small chunks
    # Target: ~2000 tokens per chunk (including prompt + output)
    # Input should be ~1000 tokens max
    max_input_tokens = 1000
    max_chars_per_chunk = int(max_input_tokens * 3.5)  # ~3500 chars
    
    print(f"[converter] Using aggressive chunking for 8K TPM limit")
    print(f"[converter] Max chars per chunk: {max_chars_per_chunk}")
    
    # Split text into chunks
    chunks = chunk_text_by_size(
        text=discharge_text,
        max_chars_per_chunk=max_chars_per_chunk,
        overlap_chars=300  # Reduced overlap
    )
    
    print(f"[converter] Created {len(chunks)} chunks")
    
    # Process each chunk to extract simplified information
    simplified_chunks = []
    for i, chunk in enumerate(chunks):
        print(f"[converter] Processing chunk {i+1}/{len(chunks)}")
        
        # Add delay between chunks to avoid rate limit (8K TPM = ~133 tokens/second)
        # Wait 10 seconds between chunks to be safe
        if i > 0:
            import time
            print(f"[converter] Waiting 10 seconds to avoid rate limit...")
            time.sleep(10)
        
        # Use a very simple prompt to stay under token limit
        simple_prompt = f"""Summarize this medical text in simple language. Focus on key facts only.Text:
        {chunk}
        Provide a brief summary in simple terms."""
        
        messages = [
            {"role": "user", "content": simple_prompt}
        ]
        
        try:
            # Use regular LLM (not structured output) to save tokens
            response = llm.invoke(messages)
            simplified_chunks.append(response.content)
            print(f"[converter] Chunk {i+1} processed successfully")
        except Exception as e:
            print(f"[converter] Warning: Chunk {i+1} processing failed: {e}")
            # Continue with other chunks
            simplified_chunks.append(f"[Section {i+1} - processing error]")
    
    # Synthesize all chunks into final patient-friendly report
    print("[converter] Synthesizing final report from all chunks")
    
    combined_summaries = "\n\n---\n\n".join([
        f"SECTION {i+1}:\n{summary}"
        for i, summary in enumerate(simplified_chunks)
    ])
    
    # Truncate combined summaries if too long
    max_synthesis_chars = 8000  # Keep synthesis input small
    if len(combined_summaries) > max_synthesis_chars:
        print(f"[converter] Truncating combined summaries from {len(combined_summaries)} to {max_synthesis_chars} chars")
        combined_summaries = combined_summaries[:max_synthesis_chars] + "\n\n[Additional sections truncated for length]"
    
    synthesis_messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"""Create a patient-friendly 1-page report from these simplified sections.

CRITICAL: Include ALL medications, ALL lab values, blood transfusions, dietary restrictions, and specific follow-up timelines.

{combined_summaries}

Return ONLY valid JSON (no markdown, no extra text) with these exact fields:
{{
  "summary": "Main patient-friendly narrative (500-700 words) - MUST include all medications, lab values, procedures, and dietary instructions",
  "key_points": ["3-5 most important takeaways - include specific test results"],
  "medications": ["COMPLETE list of ALL medications with dosage and timing"],
  "follow_up_instructions": "Specific timeline and actions - include dietary restrictions, activity level, monitoring instructions",
  "warning_signs": ["When to seek immediate medical attention"]
}}"""}
    ]
    
    try:
        # Use regular LLM to get JSON text, then parse it
        response = llm.invoke(synthesis_messages)
        response_text = response.content
        
        # Try to extract JSON from response
        import json
        import re
        
        # Look for JSON in the response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            result_dict = json.loads(json_str)
            print(f"[converter] Final synthesis successful")
            return result_dict
        else:
            raise ValueError("No JSON found in response")
            
    except Exception as e:
        print(f"[converter] Final synthesis failed: {e}")
        raise ValueError(f"Failed to synthesize final report: {str(e)}")


# ── Utility Functions ─────────────────────────────────────────────────────────

def estimate_conversion_cost(discharge_text: str, model_name: str = "openai/gpt-oss-120b") -> dict:
    """
    Estimate the cost and time for converting a discharge summary.
    
    Useful for showing users before processing.
    """
    from core.chunking import get_model_config
    
    estimated_tokens = estimate_tokens(discharge_text)
    config = get_model_config(model_name)
    
    # Estimate output tokens (summary is much shorter than input)
    estimated_output_tokens = 2000  # ~1 page of output
    
    # Calculate cost
    input_cost = (estimated_tokens / 1_000_000) * config.get("input_cost_per_1m", 0)
    output_cost = (estimated_output_tokens / 1_000_000) * config.get("output_cost_per_1m", 0)
    total_cost = input_cost + output_cost
    
    # Estimate time (rough approximation)
    # Groq processes ~100 tokens/second
    estimated_time_seconds = (estimated_tokens + estimated_output_tokens) / 100
    
    return {
        "estimated_input_tokens": estimated_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_cost_usd": round(total_cost, 4),
        "estimated_time_seconds": round(estimated_time_seconds, 1),
        "model": model_name,
        "requires_chunking": estimated_tokens > 20000,
    }
