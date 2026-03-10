"""
chunking.py
-----------
Utilities for chunking large documents for LLM processing.
"""

from typing import List, Dict
import re


def estimate_tokens(text: str, model: str = "openai/gpt-oss-120b") -> int:
    """
    Estimate token count for text.
    
    Rough approximation: 1 token ≈ 3.5 characters for English text.
    """
    return int(len(text) / 3.5)


def chunk_text_by_size(
    text: str,
    max_chars_per_chunk: int = 3500,
    overlap_chars: int = 300
) -> List[str]:
    """
    Split text into chunks of approximately max_chars_per_chunk.
    
    Parameters
    ----------
    text : str
        Text to chunk
    max_chars_per_chunk : int
        Maximum characters per chunk
    overlap_chars : int
        Number of characters to overlap between chunks
    
    Returns
    -------
    List[str]
        List of text chunks
    """
    
    if len(text) <= max_chars_per_chunk:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        # Find end position
        end = start + max_chars_per_chunk
        
        # If not at end of text, try to break at sentence boundary
        if end < len(text):
            # Look for period, newline, or other sentence breaks
            last_period = text.rfind('.', start, end)
            last_newline = text.rfind('\n', start, end)
            
            # Use the latest sentence break found
            break_pos = max(last_period, last_newline)
            
            if break_pos > start + (max_chars_per_chunk * 0.7):  # At least 70% of chunk
                end = break_pos + 1
        
        # Extract chunk
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # Move start position (with overlap)
        start = end - overlap_chars
    
    return chunks


def calculate_chunking_strategy(
    text_length: int,
    estimated_tokens: int
) -> Dict:
    """
    Determine if chunking is needed and what strategy to use.
    
    Parameters
    ----------
    text_length : int
        Length of text in characters
    estimated_tokens : int
        Estimated token count
    
    Returns
    -------
    Dict
        Strategy information
    """
    
    # With 8K TPM limit, be conservative
    # Max ~3000 tokens for single pass (leaves room for prompt + output)
    
    if estimated_tokens < 3000:
        return {
            "strategy": "single_pass",
            "requires_chunking": False,
            "estimated_tokens": estimated_tokens
        }
    else:
        # Calculate chunks needed
        chunk_size = 1000  # tokens per chunk
        num_chunks = (estimated_tokens + chunk_size - 1) // chunk_size
        
        return {
            "strategy": "chunking",
            "requires_chunking": True,
            "estimated_tokens": estimated_tokens,
            "num_chunks": num_chunks,
            "tokens_per_chunk": chunk_size
        }


def get_model_config(model_name: str) -> Dict:
    """
    Get configuration for a specific model.
    
    Parameters
    ----------
    model_name : str
        Model identifier
    
    Returns
    -------
    Dict
        Model configuration with pricing
    """
    
    configs = {
        "openai/gpt-oss-120b": {
            "input_cost_per_1m": 0.60,
            "output_cost_per_1m": 0.60,
            "max_tokens": 4096,
            "context_window": 8192
        },
        "openai/gpt-oss-20b": {
            "input_cost_per_1m": 0.27,
            "output_cost_per_1m": 0.81,
            "max_tokens": 4096,
            "context_window": 8192
        }
    }
    
    return configs.get(model_name, configs["openai/gpt-oss-120b"])
