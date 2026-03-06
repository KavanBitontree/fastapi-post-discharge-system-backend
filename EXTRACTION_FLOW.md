# Unified PDF Extraction Flow

This document describes the unified extraction flow for reports, bills, and prescriptions with dynamic chunking based on model limits.

## Overview

All three document types (reports, bills, prescriptions) now use the same extraction pipeline:

1. **Text Extraction** - Extract text from PDF using pdfplumber with page markers
2. **Dynamic Chunking** - Calculate optimal chunk size based on model limits
3. **LLM Extraction** - Process each chunk with structured output
4. **Result Merging** - Combine results from all chunks

## Model Configuration

Current model: **openai/gpt-oss-120b**

Limits:
- Context Window: 131,072 tokens
- Max Output: 65,536 tokens
- TPM (Tokens Per Minute): 250,000
- RPM (Requests Per Minute): 1,000
- Cost: $0.15/1M input, $0.60/1M output

## Dynamic Chunking

The chunking system automatically adjusts based on:
- Document size (pages and characters)
- Model context window
- Expected output size
- Rate limits (TPM/RPM)

### Chunking Strategy Calculation

```python
from core.chunking import calculate_chunking_strategy

strategy = calculate_chunking_strategy(
    total_pages=200,
    avg_chars_per_page=2000,
    model_name="openai/gpt-oss-120b"
)

print(f"Pages per chunk: {strategy.pages_per_chunk}")
print(f"Total chunks: {strategy.estimated_total_chunks}")
print(f"Estimated cost: ${strategy.estimated_cost:.4f}")
```

### Example Scenarios

| Document Size | Pages/Chunk | Total Chunks | Est. Cost |
|--------------|-------------|--------------|-----------|
| 10 pages     | 10          | 1            | $0.0015   |
| 50 pages     | 25          | 2            | $0.0075   |
| 200 pages    | 50          | 4            | $0.0300   |
| 500 pages    | 50          | 10           | $0.0750   |

## Architecture

### Core Components

```
core/
├── chunking.py          # Dynamic chunking logic
├── llm_init.py          # LLM initialization with model config
└── config.py            # Application settings

services/
├── parsers/
│   ├── unified_pdf_parser.py      # Unified extraction engine
│   ├── report_parser.py           # Report-specific wrapper
│   ├── bill_parser.py             # Bill-specific wrapper
│   └── prescription_parser.py     # Prescription-specific wrapper
└── llm_validators/
    ├── report_llm_validator.py              # Report extraction & merging
    ├── llm_bill_validator.py                # Bill extraction & merging
    └── llm_prescription_validator_chunked.py # Prescription extraction & merging
```

### Flow Diagram

```
PDF File
   ↓
[unified_pdf_parser.extract_text_from_pdf]
   ↓
Raw Text with Page Markers
   ↓
[chunking.calculate_chunking_strategy]
   ↓
Chunking Strategy (pages/chunk, total chunks, cost)
   ↓
[chunking.chunk_text_by_pages]
   ↓
Text Chunks (List[str])
   ↓
[For each chunk: extraction_function(chunk, index, total)]
   ↓
Chunk Results (List[ValidatedData])
   ↓
[merge_function(results)]
   ↓
Final Merged Result
```

## Usage Examples

### Reports

```python
from services.parsers.report_parser import parse_pdf, get_report_chunking_info

# Analyze before processing
info = get_report_chunking_info("report.pdf")
print(f"Will process in {info['estimated_total_chunks']} chunks")
print(f"Estimated cost: ${info['estimated_cost_usd']}")

# Extract
validated_report = parse_pdf("report.pdf")
print(f"Extracted {len(validated_report.test_results)} tests")
```

### Bills

```python
from services.parsers.bill_parser import parse_bill_pdf, get_bill_chunking_info

# Analyze
info = get_bill_chunking_info("bill.pdf")

# Extract
parsed_bill = parse_bill_pdf("bill.pdf")
print(f"Extracted {len(parsed_bill.line_items)} line items")
```

### Prescriptions

```python
from services.parsers.prescription_parser import parse_prescription_pdf, get_prescription_chunking_info

# Analyze
info = get_prescription_chunking_info("prescription.pdf")

# Extract
parsed_rx = parse_prescription_pdf("prescription.pdf")
print(f"Extracted {len(parsed_rx.medications)} medications")
```

## Changing Models

To use a different model:

1. Update `core/llm_init.py`:
```python
MODEL_NAME = "your-new-model"
```

2. Add model config to `core/chunking.py`:
```python
MODEL_CONFIGS = {
    "your-new-model": ModelConfig(
        name="your-new-model",
        context_window=128_000,
        max_output_tokens=4_096,
        tpm=100_000,
        rpm=500,
        input_cost_per_1m=0.50,
        output_cost_per_1m=1.50,
    ),
    # ... existing configs
}
```

The chunking system will automatically adjust based on the new model's limits.

## Benefits

1. **Unified Flow** - Same extraction logic for all document types
2. **Automatic Scaling** - Handles documents of any size
3. **Cost Optimization** - Calculates optimal chunk size to minimize API calls
4. **Rate Limit Compliance** - Respects TPM/RPM limits
5. **Error Recovery** - Continues processing if individual chunks fail
6. **Progress Tracking** - Shows chunk-by-chunk progress
7. **Model Flexibility** - Easy to switch models with automatic reconfiguration

## Performance Characteristics

### Small Documents (1-10 pages)
- Single chunk processing
- Fast response (~2-5 seconds)
- Minimal cost (~$0.001-0.002)

### Medium Documents (10-50 pages)
- 2-3 chunks
- Moderate response time (~10-20 seconds)
- Low cost (~$0.005-0.015)

### Large Documents (50-200 pages)
- 4-10 chunks
- Longer processing (~30-90 seconds)
- Moderate cost (~$0.020-0.080)

### Very Large Documents (200+ pages)
- 10+ chunks
- Extended processing (2-5 minutes)
- Higher cost (~$0.080-0.200)

## Error Handling

The system includes multiple levels of error handling:

1. **Chunk-level recovery** - If a chunk fails, processing continues with other chunks
2. **Partial results** - Returns data from successful chunks even if some fail
3. **Fallback strategies** - Uses simplified extraction if structured output fails
4. **Detailed logging** - Tracks progress and errors for debugging

## Future Enhancements

Planned improvements:

1. **Vision Support** - Add back image-based extraction for scanned documents
2. **Parallel Processing** - Process multiple chunks simultaneously
3. **Caching** - Cache extracted data to avoid reprocessing
4. **Streaming** - Stream results as chunks complete
5. **Quality Metrics** - Track extraction confidence scores
6. **Adaptive Chunking** - Adjust chunk size based on content complexity
