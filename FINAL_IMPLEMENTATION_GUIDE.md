# Final Implementation Guide

## ✅ Completed Changes

### 1. Cloudinary Storage Service
**File**: `services/storage/cloudinary_storage.py`

- Cloud-based storage for PDFs and images
- Organized folder structure by document type
- Secure URL generation
- Easy file management

### 2. Vision Model Support (Production-Ready)
**File**: `core/img_to_txt_llm_init.py`

- Official HuggingFace implementation
- Zero system dependencies (uses pymupdf, not poppler)
- Supports scanned PDFs and images
- Automatic chunking for large documents
- Model: `Qwen/Qwen2.5-VL-72B-Instruct`

### 3. Text-to-Text LLM (Renamed)
**File**: `core/txt_to_txt_llm_init.py` (was `llm_init.py`)

- Groq-based text extraction
- Model: `openai/gpt-oss-120b`
- For text-based PDFs

### 4. Configuration Updates
**File**: `core/config.py`

Added environment variables:
- `HF_TOKEN` - HuggingFace API token
- `NOVITA_API_KEY` - Novita API key (optional, for future use)

## Environment Setup

### Required `.env` Variables

```env
# Database
NEON_DB_URL=postgresql://user:password@host/db

# Frontend
FRONTEND_URL=http://localhost:3000

# Cloudinary
CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# JWT
JWT_SECRET_KEY=your_secret_key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Cron
CRON_SECRET=your_cron_secret

# LLM Providers
GROQ_API_KEY=your_groq_api_key
HF_TOKEN=your_huggingface_token
NOVITA_API_KEY=your_novita_key  # Optional

# LangSmith (Optional)
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_PROJECT=your_project
LANGSMITH_ENDPOINT=https://api.smith.langchain.com

# Environment
ENV=development
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage Examples

### 1. Cloudinary Storage

```python
from services.storage import upload_medical_pdf, upload_medical_image

# Upload PDF
result = upload_medical_pdf(
    file=file_object,
    filename="report.pdf",
    document_type="report",  # or "bill", "prescription"
    patient_id=123
)

# Returns:
# {
#     "url": "http://...",
#     "secure_url": "https://...",
#     "public_id": "medical_documents/reports/patient_123/...",
#     "bytes": 12345,
#     "format": "pdf",
#     "resource_type": "raw"
# }

# Upload Image
result = upload_medical_image(
    file=image_object,
    filename="scan.jpg",
    document_type="bill",
    patient_id=456
)
```

### 2. Vision Model (Scanned PDFs)

```python
from core.img_to_txt_llm_init import (
    extract_text_from_scanned_pdf,
    extract_text_from_image,
    is_scanned_pdf
)

# Check if PDF is scanned
if is_scanned_pdf("document.pdf"):
    # Extract using vision model
    text = extract_text_from_scanned_pdf("document.pdf")
else:
    # Use regular text extraction
    from services.parsers.unified_pdf_parser import extract_text_from_pdf
    text, _, _ = extract_text_from_pdf("document.pdf")

# Extract from image
text = extract_text_from_image("scan.jpg")
```

### 3. Text-to-Text LLM (Regular PDFs)

```python
from core.txt_to_txt_llm_init import llm

# Use for text-based extraction
result = llm.invoke("Extract data from this text...")
```

## Integration Steps

### Step 1: Update Upload Routes

Modify `routes/report_routes.py`, `routes/bill_routes.py`, `routes/prescription_routes.py`:

```python
from pathlib import Path
from services.storage import upload_medical_pdf, upload_medical_image
from core.img_to_txt_llm_init import is_scanned_pdf, extract_text_from_scanned_pdf

@router.post("/upload")
async def upload_document(
    patient_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Detect file type
    file_ext = Path(file.filename).suffix.lower()
    
    if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
        # Image upload
        upload_result = upload_medical_image(
            file=file.file,
            filename=file.filename,
            document_type="report",  # or "bill", "prescription"
            patient_id=patient_id
        )
        
        # Extract using vision model
        from core.img_to_txt_llm_init import extract_text_from_image
        # Save to temp file first
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(await file.read())
        
        text = extract_text_from_image(temp_path)
        # Continue with extraction...
        
    elif file_ext == '.pdf':
        # Save temporarily to check if scanned
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(await file.read())
        
        # Upload to Cloudinary
        with open(temp_path, "rb") as f:
            upload_result = upload_medical_pdf(
                file=f,
                filename=file.filename,
                document_type="report",
                patient_id=patient_id
            )
        
        # Check if scanned
        if is_scanned_pdf(temp_path):
            # Use vision model
            text = extract_text_from_scanned_pdf(temp_path)
            # Continue with extraction...
        else:
            # Use regular text extraction
            from services.parsers.report_parser import parse_pdf
            parsed = parse_pdf(temp_path)
            # Continue with existing flow...
    
    # Store cloudinary_url in database
    # parsed.cloudinary_url = upload_result["secure_url"]
    # parsed.cloudinary_public_id = upload_result["public_id"]
```

### Step 2: Add Database Fields

Create migration:

```bash
alembic revision --autogenerate -m "add cloudinary fields"
```

Add to models:

```python
# In models/report.py, models/bill.py, etc.
class Report(Base):
    # ... existing fields ...
    cloudinary_url: str = Column(String, nullable=True)
    cloudinary_public_id: str = Column(String, nullable=True)
    resource_type: str = Column(String, default="raw")  # "raw" or "image"
```

### Step 3: Update Storage Services

Modify `services/db_store/store_report.py` etc. to save Cloudinary URLs:

```python
def store_report(db, validated_report, patient_id, cloudinary_url, cloudinary_public_id):
    report = Report(
        patient_id=patient_id,
        report_name=validated_report.header.report_name,
        # ... other fields ...
        cloudinary_url=cloudinary_url,
        cloudinary_public_id=cloudinary_public_id,
    )
    db.add(report)
    db.commit()
```

## File Structure

```
core/
├── txt_to_txt_llm_init.py    # Text-based LLM (Groq)
├── img_to_txt_llm_init.py    # Vision LLM (HuggingFace) - PRODUCTION READY
└── config.py                  # Updated with HF_TOKEN, NOVITA_API_KEY

services/
├── storage/
│   ├── __init__.py
│   └── cloudinary_storage.py # Cloud storage service
│
├── llm_validators/            # All updated to use txt_to_txt_llm_init
│   ├── llm_report_validator.py
│   ├── llm_bill_validator.py
│   └── llm_prescription_validator.py
│
└── parsers/                   # All updated to use txt_to_txt_llm_init
    └── unified_pdf_parser.py
```

## Testing

### Test Vision Model

```bash
# Test with scanned PDF
python core/img_to_txt_llm_init.py path/to/scanned.pdf --output extracted.txt

# Test with image
python core/img_to_txt_llm_init.py path/to/image.jpg --output extracted.txt
```

### Test Cloudinary Upload

```python
from services.storage import upload_medical_pdf

with open("test.pdf", "rb") as f:
    result = upload_medical_pdf(
        file=f,
        filename="test.pdf",
        document_type="report",
        patient_id=1
    )
    print(result["secure_url"])
```

## Key Features

### Vision Model (`img_to_txt_llm_init.py`)
- ✅ Zero system dependencies (pure Python)
- ✅ Automatic chunking (2 pages per API call)
- ✅ Progress bar with tqdm
- ✅ Handles PDFs and images
- ✅ Production-tested code from HuggingFace docs
- ✅ LangChain compatible
- ✅ Automatic DPI scaling (200 DPI default)
- ✅ Image optimization (max 1800px)

### Cloudinary Storage
- ✅ Organized folder structure
- ✅ Automatic tagging
- ✅ Secure URLs
- ✅ CDN distribution
- ✅ Easy file management
- ✅ Metadata storage

## Benefits

1. **No Local Storage**: All files in cloud
2. **Vision Support**: Process scanned documents
3. **Production Ready**: Official HuggingFace code
4. **Zero System Deps**: No poppler, no external tools
5. **Scalable**: Cloud storage + API-based processing
6. **Maintainable**: Clean separation of concerns

## Next Steps

1. ✅ Configuration updated
2. ✅ Vision model integrated
3. ✅ Cloudinary service created
4. ✅ Dependencies added
5. ⏳ Update routes to use Cloudinary
6. ⏳ Add database migration
7. ⏳ Implement file type detection
8. ⏳ Test end-to-end flow

## Notes

- Vision model uses HuggingFace's automatic provider selection
- Cloudinary free tier: 25 GB storage, 25 GB bandwidth/month
- HuggingFace free tier available for testing
- Keep `public/pdfs/` as fallback during migration
