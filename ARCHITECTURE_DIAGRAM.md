# Architecture Diagram: Unified PDF Extraction with Dynamic Chunking

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PDF Upload (Any Size)                        │
│                    Reports | Bills | Prescriptions                   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Unified PDF Parser                                │
│                 (unified_pdf_parser.py)                              │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  1. Extract Text with pdfplumber                             │   │
│  │     - Tables → Structured TSV format                         │   │
│  │     - Text → Plain text with page markers                    │   │
│  │     - Output: "--- Page 1 ---\n[Table 1]\n..."              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Dynamic Chunking Engine                           │
│                      (core/chunking.py)                              │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  2. Calculate Optimal Strategy                               │   │
│  │     Input:                                                    │   │
│  │       - Total pages: 200                                     │   │
│  │       - Avg chars/page: 2000                                 │   │
│  │       - Model: openai/gpt-oss-120b                           │   │
│  │                                                               │   │
│  │     Model Limits:                                            │   │
│  │       - Context: 131,072 tokens                              │   │
│  │       - Output: 65,536 tokens                                │   │
│  │       - TPM: 250,000                                         │   │
│  │       - RPM: 1,000                                           │   │
│  │                                                               │   │
│  │     Calculation:                                             │   │
│  │       - Available tokens = 131,072 - 500 (system)           │   │
│  │                          - 2,000 (output)                    │   │
│  │                          - 20% safety margin                 │   │
│  │       - Tokens/page ≈ 2000 chars / 3.5 = 571 tokens         │   │
│  │       - Pages/chunk = Available / Tokens per page            │   │
│  │       - Max 50 pages/chunk (for progress tracking)           │   │
│  │                                                               │   │
│  │     Output Strategy:                                         │   │
│  │       ✓ Pages per chunk: 50                                  │   │
│  │       ✓ Total chunks: 4                                      │   │
│  │       ✓ Tokens per chunk: ~28,550                            │   │
│  │       ✓ Cost estimate: $0.0219                               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  3. Split Text into Chunks                                   │   │
│  │     - Split by page markers: "--- Page N ---"                │   │
│  │     - Group pages: [1-50], [51-100], [101-150], [151-200]   │   │
│  │     - Maintain context with page numbers                     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LLM Extraction (Per Chunk)                        │
│                                                                       │
│  ┌──────────────────────┐  ┌──────────────────────┐                │
│  │   Chunk 1 (Pages 1-50)│  │  Chunk 2 (Pages 51-100)│              │
│  │         ↓             │  │         ↓             │                │
│  │  [LLM Extraction]     │  │  [LLM Extraction]     │  ...          │
│  │         ↓             │  │         ↓             │                │
│  │  Structured Output    │  │  Structured Output    │                │
│  │  - Header (if first)  │  │  - Tests/Items only   │                │
│  │  - Tests/Items        │  │  - Tests/Items        │                │
│  └──────────────────────┘  └──────────────────────┘                │
│                                                                       │
│  Document-Specific Validators:                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Reports: report_llm_validator.py                            │   │
│  │    - extract_structured_report_from_chunk()                  │   │
│  │    - Returns: ValidatedReport(header, test_results)          │   │
│  │                                                               │   │
│  │  Bills: llm_bill_validator.py                                │   │
│  │    - extract_bill_from_chunk()                               │   │
│  │    - Returns: ValidatedBill(bill, patient, line_items)       │   │
│  │                                                               │   │
│  │  Prescriptions: llm_prescription_validator_chunked.py        │   │
│  │    - extract_prescription_from_chunk()                       │   │
│  │    - Returns: ValidatedPrescription(header, medications)     │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Result Merging                                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  4. Merge Chunk Results                                      │   │
│  │                                                               │   │
│  │  Strategy:                                                    │   │
│  │    - Take header from first chunk                            │   │
│  │    - Combine all tests/items/medications from all chunks     │   │
│  │    - Filter out None results (failed chunks)                 │   │
│  │    - Deduplicate if needed                                   │   │
│  │                                                               │   │
│  │  Example (Report):                                           │   │
│  │    Chunk 1: header + 50 tests                                │   │
│  │    Chunk 2: 50 tests                                         │   │
│  │    Chunk 3: 50 tests                                         │   │
│  │    Chunk 4: 30 tests                                         │   │
│  │    ────────────────────────                                  │   │
│  │    Result: header + 180 tests                                │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Final Structured Output                           │
│                                                                       │
│  Reports:        ValidatedReport                                     │
│    - header: ReportHeader                                            │
│    - test_results: List[TestResult]                                  │
│                                                                       │
│  Bills:          ParsedBill                                          │
│    - bill: BillData                                                  │
│    - patient info                                                    │
│    - line_items: List[BillDescriptionItem]                           │
│                                                                       │
│  Prescriptions:  ParsedPrescription                                  │
│    - header info                                                     │
│    - medications: List[MedicationData]                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow Example: 200-Page Report

```
Input: lab_report.pdf (200 pages, 400,000 chars)
    ↓
[Analyze]
    Pages: 200
    Chars: 400,000
    Strategy: 4 chunks of 50 pages each
    Cost: $0.0219
    Time: ~30-45 seconds
    ↓
[Extract Text]
    --- Page 1 ---
    [Table 1]
    Test Name    Result    Reference
    Hemoglobin   14.5      13-17
    ...
    --- Page 2 ---
    ...
    ↓
[Chunk 1: Pages 1-50]
    → LLM: Extract header + tests
    → Result: header + 50 tests
    ↓
[Chunk 2: Pages 51-100]
    → LLM: Extract tests only
    → Result: 50 tests
    ↓
[Chunk 3: Pages 101-150]
    → LLM: Extract tests only
    → Result: 50 tests
    ↓
[Chunk 4: Pages 151-200]
    → LLM: Extract tests only
    → Result: 30 tests
    ↓
[Merge]
    header (from chunk 1)
    + 50 tests (chunk 1)
    + 50 tests (chunk 2)
    + 50 tests (chunk 3)
    + 30 tests (chunk 4)
    ────────────────────
    = header + 180 tests
    ↓
Output: ValidatedReport with 180 test results
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Chunk Processing with Recovery                    │
│                                                                       │
│  Chunk 1: ✓ Success → 50 tests                                      │
│  Chunk 2: ✗ Failed  → Skip, continue                                │
│  Chunk 3: ✓ Success → 50 tests                                      │
│  Chunk 4: ✓ Success → 30 tests                                      │
│                                                                       │
│  Result: Partial success with 130 tests (better than total failure) │
└─────────────────────────────────────────────────────────────────────┘
```

## Model Configuration Impact

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Model: openai/gpt-oss-120b                         │
│                                                                        │
│  Context Window: 131,072 tokens                                       │
│  ├─ System Prompt: ~500 tokens                                       │
│  ├─ Expected Output: ~2,000 tokens                                   │
│  ├─ Safety Margin (20%): ~25,714 tokens                              │
│  └─ Available for Input: ~102,858 tokens                             │
│                                                                        │
│  Calculation:                                                         │
│    102,858 tokens ÷ 571 tokens/page = 180 pages/chunk                │
│    Limited to 50 pages/chunk for better progress tracking            │
│                                                                        │
│  Result: 50 pages per chunk is optimal                               │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                    If Model Changes to Smaller Context                │
│                                                                        │
│  Example: Model with 32K context                                      │
│  Available: ~25,000 tokens                                            │
│  Pages/chunk: 25,000 ÷ 571 = ~43 pages                               │
│                                                                        │
│  System automatically adjusts:                                        │
│    - 200 page doc → 5 chunks instead of 4                            │
│    - More chunks = slightly higher cost                               │
│    - But still processes successfully!                                │
└──────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Page-Based Chunking
- ✓ Natural boundaries (pages)
- ✓ Easy to track progress
- ✓ Maintains context
- ✗ Alternative: Token-based (harder to track, may split mid-content)

### 2. First Chunk Gets Header
- ✓ Header usually on first page
- ✓ Reduces redundant extraction
- ✓ Simpler merging logic
- ✗ Alternative: Extract header from all chunks (wasteful)

### 3. 50 Page Chunk Limit
- ✓ Good progress granularity
- ✓ Better error recovery
- ✓ Reasonable processing time per chunk
- ✗ Alternative: Larger chunks (less progress visibility)

### 4. Continue on Chunk Failure
- ✓ Partial results better than nothing
- ✓ User can retry failed sections
- ✓ More resilient system
- ✗ Alternative: Fail entire document (poor UX)

## Performance Optimization

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Current: Sequential Processing                     │
│                                                                        │
│  Chunk 1 → Chunk 2 → Chunk 3 → Chunk 4                               │
│  (5s)      (5s)      (5s)      (5s)                                  │
│  Total: 20 seconds                                                    │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                    Future: Parallel Processing                        │
│                                                                        │
│  Chunk 1 ┐                                                            │
│  Chunk 2 ├─ Process in parallel                                      │
│  Chunk 3 │                                                            │
│  Chunk 4 ┘                                                            │
│  (5s max)                                                             │
│  Total: 5 seconds (4x faster!)                                       │
│                                                                        │
│  Limited by: RPM (1000 req/min) and TPM (250K tokens/min)           │
└──────────────────────────────────────────────────────────────────────┘
```
