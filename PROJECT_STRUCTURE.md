# Project Structure

## Complete Directory Layout

```
fastapi-post-discharge-system-backend/
│
├── core/                           # Core configuration and utilities
│   ├── chunking.py                # Dynamic chunking based on model TPM limits
│   ├── config.py                  # Application settings (env vars, database)
│   ├── database.py                # SQLAlchemy session management
│   ├── enums.py                   # Enumerations (MedicineForm, etc.)
│   └── llm_init.py                # LLM initialization (Groq client)
│
├── models/                         # SQLAlchemy ORM models
│   ├── bill.py                    # Bill model
│   ├── bill_description.py        # BillDescription model
│   ├── doctor.py                  # Doctor model
│   ├── medication.py              # Medication model
│   ├── medication_schedule.py     # MedicationSchedule model
│   ├── patient.py                 # Patient model
│   ├── patient_doctor.py          # PatientDoctor (many-to-many)
│   ├── recurrence_type.py         # RecurrenceType model
│   ├── refresh_token.py           # RefreshToken model
│   ├── report.py                  # Report model
│   ├── report_description.py      # ReportDescription model
│   └── __init__.py                # Model exports
│
├── schemas/                        # Pydantic validation schemas
│   ├── bill_schemas.py            # Bill extraction schemas
│   ├── prescription_schemas.py    # Prescription extraction schemas
│   ├── report_schemas.py          # Report extraction schemas
│   └── __init__.py                # Schema exports
│
├── services/                       # Business logic layer
│   │
│   ├── parsers/                   # PDF parsing and extraction
│   │   ├── unified_pdf_parser.py  # Main extraction engine (chunking)
│   │   ├── bill_parser.py         # Bill-specific parsing logic
│   │   ├── prescription_parser.py # Prescription-specific parsing logic
│   │   ├── report_parser.py       # Report-specific parsing logic
│   │   └── __init__.py
│   │
│   ├── llm_validators/            # LLM-based extraction
│   │   ├── llm_bill_validator.py         # Bill LLM extraction
│   │   ├── llm_prescription_validator.py # Prescription LLM extraction
│   │   ├── llm_report_validator.py       # Report LLM extraction
│   │   └── __init__.py
│   │
│   └── db_store/                  # Database storage services
│       ├── store_bill.py          # Bill storage logic
│       ├── store_prescription.py  # Prescription storage logic
│       ├── report_store_db.py     # Report storage logic
│       └── __init__.py
│
├── routes/                         # FastAPI route handlers
│   ├── bill_routes.py             # Bill API endpoints
│   ├── prescription_routes.py     # Prescription API endpoints
│   └── report_routes.py           # Report API endpoints
│
├── alembic/                        # Database migrations
│   ├── versions/                  # Migration scripts
│   ├── env.py                     # Alembic environment config
│   └── script.py.mako             # Migration template
│
├── public/                         # Static files
│   ├── pdfs/                      # Uploaded PDF storage
│   └── favicon.ico
│
├── middlewares/                    # Custom middleware (empty for now)
│
├── tests/                          # Test files (empty for now)
│
├── main.py                         # FastAPI application entry point
├── requirements.txt                # Python dependencies
├── pyproject.toml                  # Project metadata
├── alembic.ini                     # Alembic configuration
├── .env                            # Environment variables (not in git)
├── .gitignore                      # Git ignore rules
│
└── Documentation/
    ├── README.md                   # Main project documentation
    ├── ARCHITECTURE_DIAGRAM.md     # System architecture
    ├── EXTRACTION_FLOW.md          # Extraction flow details
    ├── QUICK_START.md              # Quick start guide
    ├── CLEANUP_SUMMARY.md          # Cleanup and reorganization summary
    ├── NAMING_CONVENTION.md        # Naming convention standards
    └── PROJECT_STRUCTURE.md        # This file
```

## Module Responsibilities

### Core (`core/`)
- **chunking.py**: Calculates optimal chunk sizes based on model TPM limits
- **config.py**: Loads environment variables and application settings
- **database.py**: Provides database session management
- **enums.py**: Defines enumerations used across the application
- **llm_init.py**: Initializes and configures the LLM client (Groq)

### Models (`models/`)
SQLAlchemy ORM models representing database tables. Each model corresponds to a table and defines relationships.

### Schemas (`schemas/`)
Pydantic models for:
- LLM structured output validation
- API request/response validation
- Data transformation between layers

### Services (`services/`)

#### Parsers (`services/parsers/`)
- **unified_pdf_parser.py**: Core extraction engine with dynamic chunking
- **{type}_parser.py**: Document-specific parsing logic and dataclass definitions

#### LLM Validators (`services/llm_validators/`)
- **llm_{type}_validator.py**: LLM-based extraction with structured output
- Naming pattern: `llm_{document_type}_validator.py`

#### DB Store (`services/db_store/`)
- **store_{type}.py**: Database persistence logic for each document type

### Routes (`routes/`)
FastAPI route handlers for API endpoints. Each file handles one document type.

### Alembic (`alembic/`)
Database migration management using Alembic.

## Data Flow

```
1. PDF Upload (routes/)
   ↓
2. Save to public/pdfs/
   ↓
3. Extract text (parsers/unified_pdf_parser.py)
   ↓
4. Dynamic chunking (core/chunking.py)
   ↓
5. LLM extraction (llm_validators/llm_{type}_validator.py)
   ↓
6. Merge chunks (llm_validators/llm_{type}_validator.py)
   ↓
7. Convert to dataclass (parsers/{type}_parser.py)
   ↓
8. Store in database (db_store/store_{type}.py)
   ↓
9. Return response (routes/{type}_routes.py)
```

## Naming Conventions

### Files
- **Models**: `{entity}.py` (e.g., `patient.py`, `medication.py`)
- **Schemas**: `{type}_schemas.py` (e.g., `bill_schemas.py`)
- **Parsers**: `{type}_parser.py` (e.g., `report_parser.py`)
- **Validators**: `llm_{type}_validator.py` (e.g., `llm_bill_validator.py`)
- **Storage**: `store_{type}.py` (e.g., `store_prescription.py`)
- **Routes**: `{type}_routes.py` (e.g., `prescription_routes.py`)

### Functions
- **Extraction**: `extract_{type}_from_chunk()`
- **Merging**: `merge_{type}_results()`
- **Storage**: `store_parsed_{type}()`
- **Parsing**: `parse_{type}_pdf()`

### Classes
- **Pydantic**: `Validated{Type}` (e.g., `ValidatedBill`)
- **Dataclass**: `Parsed{Type}` (e.g., `ParsedPrescription`)
- **SQLAlchemy**: `{Entity}` (e.g., `Patient`, `Medication`)

## Configuration

### Environment Variables (`.env`)
```env
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
GROQ_API_KEY=your_groq_api_key
```

### Model Configuration (`core/chunking.py`)
```python
MODEL_CONFIGS = {
    "openai/gpt-oss-120b": {
        "tpm_limit": 8_000,
        "pages_per_chunk": 3,
        "safety_margin": 0.5,
    }
}
```

## Adding New Document Types

To add a new document type (e.g., "invoice"):

1. **Schema**: Create `schemas/invoice_schemas.py`
2. **Validator**: Create `services/llm_validators/llm_invoice_validator.py`
3. **Parser**: Create `services/parsers/invoice_parser.py`
4. **Model**: Create `models/invoice.py`
5. **Storage**: Create `services/db_store/store_invoice.py`
6. **Routes**: Create `routes/invoice_routes.py`
7. **Migration**: Run `alembic revision --autogenerate -m "add invoice table"`

## Best Practices

1. **Separation of Concerns**: Each layer has a specific responsibility
2. **Consistent Naming**: Follow established naming conventions
3. **Type Safety**: Use Pydantic for validation, dataclasses for internal data
4. **Error Handling**: Graceful degradation with recovery mechanisms
5. **Documentation**: Keep docs updated with code changes
6. **Testing**: Add tests for new features (future)

## Dependencies

Key dependencies:
- **FastAPI**: Web framework
- **SQLAlchemy**: ORM
- **Alembic**: Database migrations
- **Pydantic**: Data validation
- **LangChain**: LLM integration
- **Groq**: LLM provider
- **pdfplumber**: PDF text extraction
