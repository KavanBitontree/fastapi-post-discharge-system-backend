# Quick Start Guide: Dynamic Chunking for PDF Extraction

## TL;DR

All PDF extraction (reports, bills, prescriptions) now uses smart chunking that automatically handles documents of any size based on your model's limits.

## Current Setup

- **Model**: openai/gpt-oss-120b
- **Max Document Size**: Unlimited (automatically chunked)
- **Chunk Size**: 50 pages per chunk
- **Cost**: ~$0.0055 per 50 pages

## Basic Usage

### 1. Extract a Report
```python
from services.parsers.report_parser import parse_pdf

report = parse_pdf("lab_report.pdf")
print(f"Found {len(report.test_results)} tests")
```

### 2. Extract a Bill
```python
from services.parsers.bill_parser import parse_bill_pdf

bill = parse_bill_pdf("hospital_bill.pdf")
print(f"Total: ${bill.bill.total_amount}")
print(f"Line items: {len(bill.line_items)}")
```

### 3. Extract a Prescription
```python
from services.parsers.prescription_parser import parse_prescription_pdf

rx = parse_prescription_pdf("prescription.pdf")
print(f"Medications: {len(rx.medications)}")
```

## Check Cost Before Processing

```python
from services.parsers.report_parser import get_report_chunking_info

info = get_report_chunking_info("large_report.pdf")
print(f"Pages: {info['total_pages']}")
print(f"Chunks: {info['estimated_total_chunks']}")
print(f"Cost: ${info['estimated_cost_usd']:.4f}")
print(f"Time: {info['recommendation']}")
```

## What Changed?

### Before (Old System)
- ❌ Failed on large documents (>40 pages)
- ❌ Manual text truncation
- ❌ Lost data from truncation
- ❌ No cost visibility
- ❌ Different logic for each document type

### After (New System)
- ✅ Handles unlimited document size
- ✅ Automatic smart chunking
- ✅ No data loss
- ✅ Cost estimation before processing
- ✅ Unified logic for all document types

## How It Works

```
Large PDF (200 pages)
        ↓
[Analyze] → "Need 4 chunks, ~$0.02"
        ↓
[Chunk 1: Pages 1-50]   → Extract data
[Chunk 2: Pages 51-100] → Extract data
[Chunk 3: Pages 101-150] → Extract data
[Chunk 4: Pages 151-200] → Extract data
        ↓
[Merge Results] → Complete data
```

## Performance Guide

| Document Size | Processing Time | Cost    |
|--------------|-----------------|---------|
| 1-50 pages   | 2-5 seconds     | $0.0055 |
| 100 pages    | 10-15 seconds   | $0.0110 |
| 200 pages    | 30-45 seconds   | $0.0219 |
| 500 pages    | 1-2 minutes     | $0.0548 |

## Changing Models

If you switch to a different LLM:

1. Update `core/llm_init.py`:
```python
MODEL_NAME = "your-new-model"
```

2. Add config to `core/chunking.py`:
```python
MODEL_CONFIGS["your-new-model"] = ModelConfig(
    name="your-new-model",
    context_window=128000,  # Your model's context
    max_output_tokens=4096,  # Your model's max output
    tpm=100000,              # Tokens per minute limit
    rpm=500,                 # Requests per minute limit
    input_cost_per_1m=0.50,  # Cost per 1M input tokens
    output_cost_per_1m=1.50, # Cost per 1M output tokens
)
```

The system automatically recalculates optimal chunk sizes!

## Testing

Test the chunking system:
```bash
python test_chunking.py
```

This shows:
- Chunking strategies for different document sizes
- Cost estimates
- Performance characteristics

## API Routes

The existing API routes work without changes:

### Reports
```
POST /api/reports/upload
- patient_id: int
- file: PDF file
- strategy: "text" (default)
```

### Bills
```
POST /api/bills/upload
- patient_id: int
- file: PDF file
- use_llm: bool (default: true)
```

### Prescriptions
```
POST /api/prescriptions/upload
- patient_id: int
- file: PDF file
```

## Troubleshooting

### "PDF too large" error
- This shouldn't happen anymore! The system handles any size.
- If you see this, check that you're using the new parsers.

### Slow processing
- Normal for large documents (200+ pages)
- Check estimated time with `get_*_chunking_info()`
- Consider processing in background for very large files

### High costs
- Check document size first
- Use `get_*_chunking_info()` to see cost before processing
- Typical cost: ~$0.01 per 100 pages

## Need Help?

- See `EXTRACTION_FLOW.md` for detailed architecture
- See `IMPLEMENTATION_SUMMARY.md` for complete changes
- Run `python test_chunking.py` to test the system
