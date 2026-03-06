# Naming Convention Standardization

## Summary

All LLM validator files now follow a consistent naming pattern for better code organization and maintainability.

## Changes Made

### Before (Inconsistent)
```
services/llm_validators/
├── report_llm_validator.py              ❌ Inconsistent (prefix at end)
├── llm_bill_validator.py                ✅ Correct
└── llm_prescription_validator_chunked.py ❌ Inconsistent (extra suffix)
```

### After (Consistent)
```
services/llm_validators/
├── llm_report_validator.py       ✅ Standardized
├── llm_bill_validator.py         ✅ Already correct
└── llm_prescription_validator.py ✅ Standardized
```

## Naming Pattern

**Pattern**: `llm_{document_type}_validator.py`

- `llm_` prefix indicates LLM-based extraction
- `{document_type}` is the document type (report, bill, prescription)
- `_validator` suffix indicates validation/extraction logic

## Files Renamed

1. `report_llm_validator.py` → `llm_report_validator.py`
2. `llm_prescription_validator_chunked.py` → `llm_prescription_validator.py`

## Import Updates

All imports were automatically updated by `smartRelocate`:

### `services/parsers/report_parser.py`
```python
# Before
from services.llm_validators.report_llm_validator import (...)

# After
from services.llm_validators.llm_report_validator import (...)
```

### `services/parsers/prescription_parser.py`
```python
# Before
from services.llm_validators.llm_prescription_validator_chunked import (...)

# After
from services.llm_validators.llm_prescription_validator import (...)
```

### `routes/prescription_routes.py`
```python
# Before
from services.llm_validators.llm_prescription_validator_chunked import (...)

# After
from services.llm_validators.llm_prescription_validator import (...)
```

## Benefits

1. **Consistency**: All validators follow the same naming pattern
2. **Clarity**: Clear indication that files are LLM-based validators
3. **Maintainability**: Easier to locate and understand file purposes
4. **Scalability**: Easy to add new document types following the same pattern

## Adding New Document Types

When adding a new document type, follow this pattern:

```
services/llm_validators/llm_{new_type}_validator.py
```

Example:
- Invoice: `llm_invoice_validator.py`
- Receipt: `llm_receipt_validator.py`
- Lab Order: `llm_lab_order_validator.py`

## Verification

All files compile without errors:
```bash
✅ services/llm_validators/llm_report_validator.py
✅ services/llm_validators/llm_bill_validator.py
✅ services/llm_validators/llm_prescription_validator.py
✅ services/parsers/report_parser.py
✅ services/parsers/prescription_parser.py
✅ routes/prescription_routes.py
```
