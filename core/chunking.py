"""
Dynamic PDF Chunking System
----------------------------
Intelligent chunking based on model token limits and rate limits.
Automatically adjusts chunk size based on the configured LLM model.

Model Configuration:
- Model: openai/gpt-oss-120b
- Context: 131,072 tokens
- Output: 65,536 tokens
- TPM (Tokens Per Minute): 250,000
- RPM (Requests Per Minute): 1,000
- Cost: $0.15/1M input, $0.60/1M output
"""

from typing import List, Dict, Tuple
from dataclasses import dataclass
import math


@dataclass
class ModelConfig:
    """Configuration for LLM model limits."""
    name: str
    context_window: int  # Total context tokens
    max_output_tokens: int  # Max output tokens
    tpm: int  # Tokens per minute
    rpm: int  # Requests per minute
    input_cost_per_1m: float  # Cost per 1M input tokens
    output_cost_per_1m: float  # Cost per 1M output tokens


# Model configurations
MODEL_CONFIGS = {
    "openai/gpt-oss-120b": ModelConfig(
        name="openai/gpt-oss-120b",
        context_window=131_072,
        max_output_tokens=65_536,
        tpm=8_000,  # Actual limit for on_demand tier
        rpm=1_000,
        input_cost_per_1m=0.15,
        output_cost_per_1m=0.60,
    ),
    # Add more models as needed
    "default": ModelConfig(
        name="default",
        context_window=128_000,
        max_output_tokens=4_096,
        tpm=100_000,
        rpm=500,
        input_cost_per_1m=0.50,
        output_cost_per_1m=1.50,
    ),
}


@dataclass
class ChunkingStrategy:
    """Chunking strategy calculated based on model limits."""
    pages_per_chunk: int
    max_chars_per_chunk: int
    estimated_tokens_per_chunk: int
    max_chunks_per_batch: int
    estimated_total_chunks: int
    estimated_cost: float
    model_name: str


def get_model_config(model_name: str) -> ModelConfig:
    """Get model configuration by name."""
    return MODEL_CONFIGS.get(model_name, MODEL_CONFIGS["default"])


def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text.
    
    Rule of thumb: ~4 characters per token for English text.
    Medical documents tend to be denser, so we use 3.5 chars/token.
    """
    return int(len(text) / 3.5)


def calculate_chunking_strategy(
    total_pages: int,
    avg_chars_per_page: int,
    model_name: str = "openai/gpt-oss-120b",
    system_prompt_tokens: int = 400,  # Increased to account for actual prompt size
    expected_output_tokens: int = 1500,  # Increased for structured output overhead
) -> ChunkingStrategy:
    """
    Calculate optimal chunking strategy based on model limits.
    
    Parameters
    ----------
    total_pages : int
        Total number of pages in the document
    avg_chars_per_page : int
        Average characters per page
    model_name : str
        Name of the LLM model
    system_prompt_tokens : int
        Estimated tokens for system prompt
    expected_output_tokens : int
        Expected tokens for output per chunk
    
    Returns
    -------
    ChunkingStrategy
        Calculated chunking parameters
    """
    config = get_model_config(model_name)
    
    # Calculate available tokens for input content
    # Reserve space for: system prompt + output + safety margin (50% for very tight limits)
    safety_margin = 0.50  # Increased from 0.40 for very tight TPM limits
    reserved_tokens = system_prompt_tokens + expected_output_tokens
    available_input_tokens = int(
        (config.context_window - reserved_tokens) * (1 - safety_margin)
    )
    
    # Estimate tokens per page
    tokens_per_page = estimate_tokens("x" * avg_chars_per_page)
    
    # Calculate pages per chunk
    pages_per_chunk = max(1, int(available_input_tokens / tokens_per_page))
    
    # For very large documents, limit chunk size to avoid extremely long processing
    # With tight TPM limits (8K), use smaller chunks for better rate limit compliance
    if config.tpm <= 10_000:
        # Tight limits: max 3 pages per chunk (reduced from 5)
        pages_per_chunk = min(pages_per_chunk, 3)
    elif config.tpm <= 50_000:
        # Medium limits: max 10 pages per chunk
        pages_per_chunk = min(pages_per_chunk, 10)
    else:
        # High limits: max 50 pages per chunk
        pages_per_chunk = min(pages_per_chunk, 50)
    
    # Calculate actual tokens and chars per chunk
    estimated_tokens_per_chunk = pages_per_chunk * tokens_per_page
    max_chars_per_chunk = pages_per_chunk * avg_chars_per_page
    
    # Calculate total chunks needed
    estimated_total_chunks = math.ceil(total_pages / pages_per_chunk)
    
    # Calculate max chunks per batch based on TPM limit
    # Each chunk uses: input_tokens + output_tokens
    tokens_per_request = estimated_tokens_per_chunk + expected_output_tokens
    max_chunks_per_batch = min(
        config.rpm,  # Don't exceed RPM
        int(config.tpm / tokens_per_request)  # Don't exceed TPM
    )
    max_chunks_per_batch = max(1, max_chunks_per_batch)
    
    # Estimate cost
    total_input_tokens = estimated_total_chunks * estimated_tokens_per_chunk
    total_output_tokens = estimated_total_chunks * expected_output_tokens
    estimated_cost = (
        (total_input_tokens / 1_000_000) * config.input_cost_per_1m +
        (total_output_tokens / 1_000_000) * config.output_cost_per_1m
    )
    
    return ChunkingStrategy(
        pages_per_chunk=pages_per_chunk,
        max_chars_per_chunk=max_chars_per_chunk,
        estimated_tokens_per_chunk=estimated_tokens_per_chunk,
        max_chunks_per_batch=max_chunks_per_batch,
        estimated_total_chunks=estimated_total_chunks,
        estimated_cost=estimated_cost,
        model_name=config.name,
    )


def chunk_text_by_pages(
    text: str,
    pages_per_chunk: int,
    page_delimiter: str = "--- Page"
) -> List[str]:
    """
    Split text into chunks based on page markers.
    
    Parameters
    ----------
    text : str
        Full text with page markers
    pages_per_chunk : int
        Number of pages per chunk
    page_delimiter : str
        Delimiter marking page boundaries
    
    Returns
    -------
    List[str]
        List of text chunks
    """
    # Split by page markers
    pages = text.split(page_delimiter)
    
    # Filter out empty pages
    pages = [p.strip() for p in pages if p.strip() and len(p.strip()) > 50]
    
    # Group pages into chunks
    chunks = []
    for i in range(0, len(pages), pages_per_chunk):
        chunk_pages = pages[i:i + pages_per_chunk]
        chunk_text = f"\n\n{page_delimiter}".join(chunk_pages)
        chunks.append(chunk_text)
    
    return chunks


def chunk_text_by_size(
    text: str,
    max_chars_per_chunk: int,
    overlap_chars: int = 500
) -> List[str]:
    """
    Split text into chunks by character count with overlap.
    
    Used when page markers are not available.
    
    Parameters
    ----------
    text : str
        Full text to chunk
    max_chars_per_chunk : int
        Maximum characters per chunk
    overlap_chars : int
        Number of characters to overlap between chunks
    
    Returns
    -------
    List[str]
        List of text chunks
    """
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + max_chars_per_chunk
        
        # If not the last chunk, try to break at a natural boundary
        if end < text_len:
            # Look for paragraph break
            break_point = text.rfind("\n\n", start, end)
            if break_point == -1:
                # Look for line break
                break_point = text.rfind("\n", start, end)
            if break_point != -1 and break_point > start + (max_chars_per_chunk * 0.7):
                end = break_point
        
        chunks.append(text[start:end].strip())
        
        # Move start position with overlap
        start = end - overlap_chars if end < text_len else text_len
    
    return chunks


def get_chunking_info(
    total_pages: int,
    total_chars: int,
    model_name: str = "openai/gpt-oss-120b"
) -> Dict:
    """
    Get chunking information for a document.
    
    Returns a dictionary with chunking strategy and recommendations.
    """
    avg_chars_per_page = total_chars // max(total_pages, 1)
    
    strategy = calculate_chunking_strategy(
        total_pages=total_pages,
        avg_chars_per_page=avg_chars_per_page,
        model_name=model_name,
    )
    
    return {
        "model": strategy.model_name,
        "total_pages": total_pages,
        "total_chars": total_chars,
        "avg_chars_per_page": avg_chars_per_page,
        "pages_per_chunk": strategy.pages_per_chunk,
        "max_chars_per_chunk": strategy.max_chars_per_chunk,
        "estimated_tokens_per_chunk": strategy.estimated_tokens_per_chunk,
        "estimated_total_chunks": strategy.estimated_total_chunks,
        "max_chunks_per_batch": strategy.max_chunks_per_batch,
        "estimated_cost_usd": round(strategy.estimated_cost, 4),
        "recommendation": _get_recommendation(strategy),
    }


def _get_recommendation(strategy: ChunkingStrategy) -> str:
    """Generate recommendation based on chunking strategy."""
    if strategy.estimated_total_chunks == 1:
        return "Document is small enough to process in a single request."
    elif strategy.estimated_total_chunks <= 5:
        return f"Document will be processed in {strategy.estimated_total_chunks} chunks. Processing should be fast."
    elif strategy.estimated_total_chunks <= 20:
        return f"Document will be processed in {strategy.estimated_total_chunks} chunks. May take 1-2 minutes."
    else:
        return f"Large document: {strategy.estimated_total_chunks} chunks. Processing may take several minutes. Consider batch processing."
