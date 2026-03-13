"""
Scanned PDF / Image → Text Extraction
--------------------------------------
Inference : HuggingFace InferenceClient (HF picks the provider automatically)
Model     : Qwen/Qwen2.5-VL-72B-Instruct (vision-language model)
Stack     : huggingface_hub + langchain + pymupdf (zero system deps)

This module provides vision-capable LLM for processing:
- Scanned PDFs (converted to images)
- Direct image uploads (JPG, PNG, etc.)

Install:
    pip install pymupdf langchain langchain-core huggingface_hub pillow tqdm
"""

import os
import math
import base64
import time
import logging
from pathlib import Path
from io import BytesIO
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

import fitz  # pymupdf — no poppler, no system deps
from PIL import Image
from tqdm import tqdm

from huggingface_hub import InferenceClient

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration

from core.config import settings

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

HF_TOKEN        = settings.HF_TOKEN
MODEL_ID        = "Qwen/Qwen2.5-VL-72B-Instruct:hyperbolic"
PAGES_PER_CHUNK = 2
DPI             = 150   # 150 DPI renders faster and stays within 1400px after thumbnail
MAX_IMG_DIM     = 1400  # smaller JPEG payload → faster HF inference, avoids 504


# ══════════════════════════════════════════════════════════════════════════════
# LANGCHAIN WRAPPER around HuggingFace InferenceClient
# ══════════════════════════════════════════════════════════════════════════════

class HFInferenceChatModel(BaseChatModel):
    """
    LangChain ChatModel wrapper over huggingface_hub.InferenceClient.
    HF automatically selects the inference provider — no explicit config needed.
    """

    model_id:    str
    hf_token:    str
    max_tokens:  int   = 2048  # lower → faster inference, avoids 504 gateway timeouts
    temperature: float = 0.0
    _client:     Any   = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client = InferenceClient(api_key=self.hf_token)

    @property
    def _llm_type(self) -> str:
        return "hf-inference-client"

    def _convert_messages(self, messages: List[BaseMessage]) -> List[dict]:
        """Convert LangChain messages → HF InferenceClient message dicts."""
        result = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                # content can be plain string OR multimodal list
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                result.append({"role": "assistant", "content": msg.content})
        return result

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs,
    ) -> ChatResult:
        hf_messages = self._convert_messages(messages)
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=self.model_id,
                    messages=hf_messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                text = response.choices[0].message.content
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                if any(code in err_str for code in ("502", "503", "504")):
                    wait = 15 * (attempt + 1)  # 15 s, 30 s, 45 s
                    logger.warning(
                        "HF inference transient error (attempt %d/3) — retrying in %ds: %s",
                        attempt + 1, wait, err_str[:120],
                    )
                    time.sleep(wait)
                    continue
                raise
        raise last_exc  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════════════
# PDF / IMAGE → LIST OF PIL IMAGES
# Uses pymupdf (fitz) — pure Python, zero system dependencies, works everywhere
# ══════════════════════════════════════════════════════════════════════════════

def load_input(input_path: str) -> List[Image.Image]:
    """
    Load a scanned PDF or image file into a list of PIL Images.

    PDF  → rendered via pymupdf (no poppler / no system install needed)
    Image → opened directly with Pillow
    """
    p = Path(input_path)

    if p.suffix.lower() == ".pdf":
        print(f"[load] Rendering PDF at {DPI} DPI via pymupdf ...")
        images = []
        doc = fitz.open(str(p))

        for page_num, page in enumerate(doc):
            # fitz baseline is 72 DPI — matrix scales to target DPI
            mat = fitz.Matrix(DPI / 72, DPI / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
            print(f"  page {page_num + 1}/{len(doc)} rendered  "
                  f"({pix.width}×{pix.height}px)")

        doc.close()
        print(f"[load] {len(images)} page(s) ready.")
        return images

    elif p.suffix.lower() in {".jpg", ".jpeg", ".png",
                               ".tiff", ".tif", ".bmp", ".webp"}:
        print(f"[load] Opening image '{p.name}' ...")
        return [Image.open(p).convert("RGB")]

    else:
        raise ValueError(f"Unsupported file format: {p.suffix}")


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE → BASE64 DATA-URI
# ══════════════════════════════════════════════════════════════════════════════

def image_to_data_uri(img: Image.Image) -> str:
    """Resize to MAX_IMG_DIM on longest edge, encode as JPEG base64 data-URI."""
    img = img.convert("RGB")
    img.thumbnail((MAX_IMG_DIM, MAX_IMG_DIM), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACT ONE CHUNK → TEXT (single API call)
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = (
    "You are an expert OCR engine and document parser. "
    "Transcribe ALL visible text exactly as it appears. "
    "Preserve tables (pipe-delimited), headers, and indentation. "
    "Mark illegible text as [ILLEGIBLE]. "
    "Output transcribed content only — no commentary."
)

def extract_chunk(llm: HFInferenceChatModel, images: List[Image.Image]) -> str:
    """
    Build a multimodal HumanMessage (images + prompt) and call the LLM.
    Returns the extracted text for this chunk.
    """
    content = []

    # Add one image block per page in the chunk
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_uri(img)},
        })

    # Add the OCR instruction
    content.append({"type": "text", "text": SYSTEM_PROMPT})

    response = llm.invoke([HumanMessage(content=content)])
    return response.content.strip()


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API FOR INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

def get_vision_llm() -> HFInferenceChatModel:
    """
    Get vision-capable LLM instance for scanned PDFs and images.
    
    Returns
    -------
    HFInferenceChatModel
        LangChain-compatible vision LLM
    """
    return HFInferenceChatModel(model_id=MODEL_ID, hf_token=HF_TOKEN)


def extract_text_from_scanned_pdf(pdf_path: str) -> str:
    """
    Extract text from scanned PDF using vision model.
    
    Parameters
    ----------
    pdf_path : str
        Path to scanned PDF file
        
    Returns
    -------
    str
        Extracted text from all pages
    """
    images = load_input(pdf_path)
    total  = len(images)
    chunks = math.ceil(total / PAGES_PER_CHUNK)

    print(f"\n[vision] {total} page(s) → {chunks} API call(s) | {MODEL_ID}\n")

    llm   = get_vision_llm()
    parts = []

    for i in tqdm(range(chunks), desc="Vision extraction"):
        start = i * PAGES_PER_CHUNK
        end   = min(start + PAGES_PER_CHUNK, total)
        label = (f"Page {start + 1}"
                 if end - start == 1
                 else f"Pages {start + 1}–{end}")

        text = extract_chunk(llm, images[start:end])
        parts.append(f"\n{'='*60}\n{label}\n{'='*60}\n{text}")
        print(f"  ✓ {label} — {len(text)} chars extracted")

    final = "\n".join(parts)
    print(f"\n[vision] Done. {len(final):,} chars total")
    return final


def extract_text_from_image(image_path: str) -> str:
    """
    Extract text from image file using vision model.
    
    Parameters
    ----------
    image_path : str
        Path to image file (JPG, PNG, etc.)
        
    Returns
    -------
    str
        Extracted text from image
    """
    images = load_input(image_path)
    llm = get_vision_llm()
    
    print(f"\n[vision] Extracting from image: {Path(image_path).name}")
    text = extract_chunk(llm, images)
    print(f"[vision] Done. {len(text)} chars extracted")
    
    return text


def is_scanned_pdf(pdf_path: str, threshold: int = 100) -> bool:
    """
    Detect if PDF is scanned (has minimal text content).
    
    Uses multiple heuristics:
    1. Text extraction character count
    2. Text-to-page ratio
    3. Image presence detection
    
    Parameters
    ----------
    pdf_path : str
        Path to PDF file
    threshold : int
        Minimum character count per page to consider as text-based PDF
        
    Returns
    -------
    bool
        True if PDF appears to be scanned (low text content)
    """
    try:
        import pdfplumber
        
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            pages_to_check = min(3, total_pages)  # Check first 3 pages or all if less
            
            total_chars = 0
            total_images = 0
            
            for i, page in enumerate(pdf.pages[:pages_to_check]):
                # Extract text
                text = page.extract_text() or ""
                total_chars += len(text.strip())
                
                # Count images
                images = page.images
                total_images += len(images)
            
            # Calculate metrics
            avg_chars_per_page = total_chars / pages_to_check if pages_to_check > 0 else 0
            has_many_images = total_images >= pages_to_check  # At least 1 image per page
            
            print(f"[detect] PDF Analysis:")
            print(f"  - Pages checked: {pages_to_check}/{total_pages}")
            print(f"  - Total chars: {total_chars}")
            print(f"  - Avg chars/page: {avg_chars_per_page:.0f}")
            print(f"  - Images found: {total_images}")
            
            # Decision logic:
            # 1. Very low text content → scanned
            if avg_chars_per_page < threshold:
                print(f"  → SCANNED (low text: {avg_chars_per_page:.0f} < {threshold})")
                return True
            
            # 2. Has images but very little text → likely scanned
            if has_many_images and avg_chars_per_page < threshold * 2:
                print(f"  → SCANNED (images + low text)")
                return True
            
            # 3. Sufficient text content → text-based
            print(f"  → TEXT-BASED (sufficient text: {avg_chars_per_page:.0f} chars/page)")
            return False
            
    except Exception as e:
        print(f"[detect] Error checking PDF: {e}")
        print(f"[detect] Assuming SCANNED (safe default)")
        return True


# ══════════════════════════════════════════════════════════════════════════════
# CLI FOR TESTING
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Scanned PDF / image → text | HF InferenceClient + LangChain + pymupdf"
    )
    ap.add_argument(
        "input",
        nargs="?",
        help="Path to scanned PDF or image file"
    )
    ap.add_argument(
        "--output",
        help="Output .txt file path (optional)"
    )
    args = ap.parse_args()

    if args.input:
        p = Path(args.input)
        if p.suffix.lower() == ".pdf":
            text = extract_text_from_scanned_pdf(args.input)
        else:
            text = extract_text_from_image(args.input)
        
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"\n[save] Saved to {args.output}")
        else:
            print(f"\n{'='*60}\nEXTRACTED TEXT\n{'='*60}\n{text}")
    else:
        print("Usage: python img_to_txt_llm_init.py <pdf_or_image_path> [--output output.txt]")
