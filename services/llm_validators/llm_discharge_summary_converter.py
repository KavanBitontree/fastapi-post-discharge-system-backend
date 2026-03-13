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

Your goal: Create a clear, concise 1-page summary (300-400 words) that patients can understand without medical training.

CRITICAL REQUIREMENTS - ACCURACY IS ESSENTIAL:

BLOOD PRESSURE & VITAL SIGNS:
- Use DISCHARGE BP (final BP at discharge), NOT admission BP
- Example: If admission BP was 168/104 but discharge BP was 148/88, use 148/88 in key points
- Always specify which BP reading you're using (discharge, current, etc.)

MEDICATION EXTRACTION - MUST BE COMPLETE AND EXACT:
- Extract EVERY medication from the discharge prescription list
- For each medication, include: name, EXACT dose, EXACT timing (all times if multiple daily doses)
- Example: "Losartan 50mg after lunch AND after dinner" (not just lunch)
- Include ALL special instructions: "do not crush", "take with food", "every other day", etc.
- Common medications to check for: Losartan, Spironolactone, Omega-3, Folic Acid, Deferoxamine, Aspirin, etc.
- If a medication appears in discharge but not in your list, you missed it - go back and find it

MEDICATION DESCRIPTIONS - CLINICAL ACCURACY:
- Deferoxamine: "to prevent iron overload risk after blood transfusion" (not "to remove excess iron")
- Spironolactone: Include "do not crush" instruction
- Omega-3: Include exact dose (e.g., "1000mg daily")
- Folic Acid: Include exact dose (e.g., "5mg daily")

LAB VALUES & VITAL SIGNS:
- Use DISCHARGE values, not admission values
- Include exact numbers (e.g., "blood count improved from 6.2 to 9.4")
- For key points, use discharge BP (e.g., 148/88), not admission BP

FOLLOW-UP TIMELINES - MUST BE EXACT:
- Use EXACT timelines from discharge (e.g., "2 weeks" not "4-6 weeks")
- If discharge says "2 weeks for eGFR, K+, creatinine recheck", use "2 weeks"
- Do not round or estimate timelines

DIETARY RESTRICTIONS:
- Use EXACT values from discharge (e.g., "< 2,300 mg sodium per day" not "< 2g")
- Include all restrictions: low-sodium, DASH diet, NSAID avoidance, etc.

PRECAUTIONS & WARNINGS - MUST BE COMPLETE:
- Extract ALL precautions from discharge (avoid NSAIDs, avoid alcohol, avoid strenuous activity, etc.)
- Include activity restrictions with specific details
- Include medication interactions to avoid
- Include symptoms that require immediate attention
- Organize by urgency: critical warnings first, then important precautions

GUIDELINES:
- Use simple, everyday language (avoid medical jargon)
- When medical terms are necessary, explain them in parentheses
- Be empathetic and reassuring in tone
- Focus on what matters to the patient: their condition, treatment, and next steps
- Keep the summary to approximately 300-400 words (fits on 1 page)
- Use bullet points and short sentences for clarity
- Organize information logically: condition → treatment → follow-up
- DO NOT duplicate medication information between summary and medications list

STRUCTURE YOUR RESPONSE AS JSON:
{
  "summary": "Main patient-friendly narrative (300-400 words) - Include condition, treatment received, DISCHARGE lab values, dietary restrictions, and follow-up timeline. DO NOT list medications here - they go in the medications list only.",
  "key_points": ["2-3 most important takeaways - use DISCHARGE BP and lab values, not admission values"],
  "medications": ["COMPLETE list of ALL medications from discharge prescription - include EXACT dosage, timing (all times if multiple daily), and special instructions. Examples: 'Losartan 50mg after lunch AND after dinner', 'Spironolactone 25mg every other day (do not crush)', 'Omega-3 1000mg daily', 'Folic Acid 5mg daily'"],
  "precautions": ["COMPLETE list of ALL precautions and restrictions - include activity restrictions, medication interactions to avoid, dietary restrictions, and lifestyle changes. Examples: 'Avoid NSAIDs (pain relievers like ibuprofen)', 'No strenuous exercise for 4 weeks', 'Avoid alcohol with this medication', 'Do not take with dairy products'"],
  "follow_up_instructions": "Specific timeline and actions - include EXACT dietary restrictions (e.g., '< 2,300 mg sodium per day'), activity level, monitoring instructions, and EXACT follow-up appointment timelines (e.g., 'eGFR, K+, creatinine recheck in 2 weeks')",
  "warning_signs": ["When to seek immediate medical attention - max 5 items - include specific symptoms like chest pain, severe shortness of breath, etc."]
}

TONE: Warm, clear, and supportive. Write as if explaining to a family member.

CRITICAL: Accuracy over brevity. If you must choose between being concise and being accurate, choose accuracy. Every medication dose, timing, special instruction, vital sign, timeline, and precaution must match the discharge document exactly. Do not estimate or round values."""

_CHUNK_SUMMARY_PROMPT = """Extract and simplify the key medical information from this section of a discharge summary.

This is chunk {chunk_index} of {total_chunks}.

CRITICAL: Extract ALL of the following if present:
- ALL medications with EXACT dosages and timings (e.g., "Losartan 50mg after lunch AND after dinner")
- Special medication instructions (e.g., "do not crush", "every other day")
- ALL lab values and test results with exact numbers
- Blood transfusions or IV treatments
- Procedures performed
- Dietary restrictions with exact values (e.g., "< 2,300 mg sodium per day")
- Follow-up appointments and EXACT timelines (e.g., "2 weeks" not "4-6 weeks")
- Monitoring instructions
- DISCHARGE vital signs (BP, HR, etc.) - not admission values

Focus on:
- Patient's condition and diagnosis
- Treatments received
- ALL medications (COMPLETE list with exact dosages and timings)
- Test results (in simple terms with specific numbers)
- Follow-up care needed (EXACT timelines)
- Warning signs
- Dietary and lifestyle changes

DISCHARGE SUMMARY SECTION:
{text_chunk}

Return simplified information in JSON format. DO NOT OMIT any medications, lab values, or important details. Be thorough and complete."""

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

    # Estimate page count from text length (avg ~2000 chars/page for medical docs)
    avg_chars_per_page = 2000
    estimated_pages = max(1, len(discharge_text) // avg_chars_per_page)

    strategy = calculate_chunking_strategy(
        total_pages=estimated_pages,
        avg_chars_per_page=avg_chars_per_page,
        model_name=model_name,
    )

    print(f"[converter] Estimated tokens: {strategy.estimated_tokens_per_chunk * strategy.estimated_total_chunks}")
    print(f"[converter] Chunking strategy: {strategy.estimated_total_chunks} chunk(s), "
          f"{strategy.pages_per_chunk} pages/chunk, ~${strategy.estimated_cost:.4f}")

    if strategy.estimated_total_chunks == 1:
        print("[converter] Document small enough for single-pass processing")
        return _convert_single_pass(discharge_text)

    print("[converter] Document requires chunking")
    return _convert_with_chunking(discharge_text, strategy.max_chars_per_chunk)


def _convert_single_pass(discharge_text: str) -> dict:
    """Convert discharge summary in a single LLM call."""
    
    import json
    import re
    
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"""Convert this discharge summary into a patient-friendly 1-page report.

CRITICAL ACCURACY REQUIREMENTS:
1. Use DISCHARGE BP and lab values (not admission values) - Example: If admission BP was 168/104 but discharge BP was 148/88, use 148/88
2. Extract EVERY medication from the prescription list with EXACT dosage and timing
   - Losartan: Include BOTH lunch AND dinner doses if prescribed
   - Spironolactone: Include "do not crush" instruction
   - Include Omega-3, Folic Acid, and any other medications listed
3. Medication descriptions must be clinically accurate:
   - Deferoxamine: "to prevent iron overload risk after blood transfusion" (not "to remove excess iron")
4. Extract ALL precautions and restrictions:
   - Activity restrictions (e.g., "no strenuous exercise for 4 weeks")
   - Medication interactions to avoid (e.g., "avoid NSAIDs")
   - Dietary restrictions (e.g., "< 2,300 mg sodium per day")
   - Lifestyle changes (e.g., "avoid alcohol")
5. Follow-up timelines must be EXACT (e.g., "2 weeks" not "4-6 weeks")
6. DO NOT list medications in the summary narrative - put them ONLY in the medications list

Keep the summary to 300-400 words maximum. Use short sentences and bullet points for clarity.

{discharge_text}

Return ONLY valid JSON (no markdown, no extra text) with these exact fields:
{{
  "summary": "Main patient-friendly narrative (300-400 words) - Include condition, treatment received, DISCHARGE lab values, dietary restrictions, and follow-up timeline. DO NOT list medications here.",
  "key_points": ["2-3 most important takeaways - use DISCHARGE BP and lab values, not admission values"],
  "medications": ["COMPLETE list of ALL medications from discharge prescription - include EXACT dosage, timing (all times if multiple daily), and special instructions. Examples: 'Losartan 50mg after lunch AND after dinner', 'Spironolactone 25mg every other day (do not crush)', 'Omega-3 1000mg daily', 'Folic Acid 5mg daily'"],
  "precautions": ["COMPLETE list of ALL precautions and restrictions - include activity restrictions, medication interactions to avoid, dietary restrictions, and lifestyle changes. Examples: 'Avoid NSAIDs (pain relievers like ibuprofen)', 'No strenuous exercise for 4 weeks', 'Avoid alcohol with this medication', 'Do not take with dairy products'"],
  "follow_up_instructions": "Specific timeline and actions - include EXACT dietary restrictions (e.g., '< 2,300 mg sodium per day'), activity level, monitoring instructions, and EXACT follow-up appointment timelines (e.g., 'eGFR, K+, creatinine recheck in 2 weeks')",
  "warning_signs": ["When to seek immediate medical attention - max 5 items - include specific symptoms like chest pain, severe shortness of breath, etc."]
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


def _convert_with_chunking(discharge_text: str, max_chars_per_chunk: int) -> dict:
    """
    Convert large discharge summary using chunking strategy.
    
    Process:
    1. Split document into manageable chunks
    2. Simplify each chunk separately
    3. Synthesize all simplified chunks into final 1-page report
    """
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

CRITICAL ACCURACY REQUIREMENTS:
1. Use DISCHARGE BP and lab values (not admission values) - Example: If admission BP was 168/104 but discharge BP was 148/88, use 148/88
2. Extract EVERY medication from the prescription list with EXACT dosage and timing
   - Losartan: Include BOTH lunch AND dinner doses if prescribed
   - Spironolactone: Include "do not crush" instruction
   - Include Omega-3, Folic Acid, and any other medications listed
3. Medication descriptions must be clinically accurate:
   - Deferoxamine: "to prevent iron overload risk after blood transfusion" (not "to remove excess iron")
4. Extract ALL precautions and restrictions:
   - Activity restrictions (e.g., "no strenuous exercise for 4 weeks")
   - Medication interactions to avoid (e.g., "avoid NSAIDs")
   - Dietary restrictions (e.g., "< 2,300 mg sodium per day")
   - Lifestyle changes (e.g., "avoid alcohol")
5. Follow-up timelines must be EXACT (e.g., "2 weeks" not "4-6 weeks")
6. DO NOT list medications in the summary narrative - put them ONLY in the medications list

Keep the summary to 300-400 words maximum. Use short sentences and bullet points for clarity.

{combined_summaries}

Return ONLY valid JSON (no markdown, no extra text) with these exact fields:
{{
  "summary": "Main patient-friendly narrative (300-400 words) - Include condition, treatment received, DISCHARGE lab values, dietary restrictions, and follow-up timeline. DO NOT list medications here.",
  "key_points": ["2-3 most important takeaways - use DISCHARGE BP and lab values, not admission values"],
  "medications": ["COMPLETE list of ALL medications from discharge prescription - include EXACT dosage, timing (all times if multiple daily), and special instructions. Examples: 'Losartan 50mg after lunch AND after dinner', 'Spironolactone 25mg every other day (do not crush)', 'Omega-3 1000mg daily', 'Folic Acid 5mg daily'"],
  "precautions": ["COMPLETE list of ALL precautions and restrictions - include activity restrictions, medication interactions to avoid, dietary restrictions, and lifestyle changes. Examples: 'Avoid NSAIDs (pain relievers like ibuprofen)', 'No strenuous exercise for 4 weeks', 'Avoid alcohol with this medication', 'Do not take with dairy products'"],
  "follow_up_instructions": "Specific timeline and actions - include EXACT dietary restrictions (e.g., '< 2,300 mg sodium per day'), activity level, monitoring instructions, and EXACT follow-up appointment timelines (e.g., 'eGFR, K+, creatinine recheck in 2 weeks')",
  "warning_signs": ["When to seek immediate medical attention - max 5 items - include specific symptoms like chest pain, severe shortness of breath, etc."]
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
    
    # Calculate cost using dataclass attributes
    input_cost = (estimated_tokens / 1_000_000) * config.input_cost_per_1m
    output_cost = (estimated_output_tokens / 1_000_000) * config.output_cost_per_1m
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
