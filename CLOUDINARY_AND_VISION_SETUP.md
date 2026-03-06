# Cloudinary Storage & Vision Model Setup

## Overview

The system now supports:
1. **Cloudinary Storage**: PDFs and images stored in cloud instead of local filesystem
2. **Vision Models**: Process scanned PDFs and images using vision-capable LLMs

## Changes Made

### 1. Cloudinary Storage Service

**Location**: `services/storage/cloudinary_storage.py`

**Features**:
- Upload PDFs to Cloudinary with organized folder structure
- Upload images (for image-based documents)
- Delete files when needed
- Generate secure URLs
- Automatic organization by document type and patient ID

**Folder Structure in Cloudinary**:
```
medical_documents/
├── reports/
│   └── patient_{id}/
│       └── {timestamp}_{filename}.pdf
├── bills/
│   └── patient_{id}/
│       └── {timestamp}_{filename}.pdf
└── prescriptions/
    └── patient_{id}/
        └── {timestamp}_{filename}.pdf
```

**Usage**:
```python
from services.storage import upload_medical_pdf, upload_medical_image

# Upload PDF
result = upload_medical_pdf(
    file=file_object,
    filename="report.pdf",
    document_type="report",  # or "bill", "prescription"
    patient_id=123
)

# Upload Image
result = upload_medical_image(
    file=image_object,
    filename="scan.jpg",
    document_type="report",
    patient_id=123
)

# Result contains:
# - url: Public URL
# - secure_url: HTTPS URL
# - public_id: Cloudinary identifier
# - bytes: File size
```

### 2. Vision Model Support

**Text-to-Text LLM** (`core/txt_to_txt_llm_init.py`):
- Renamed from `llm_init.py` for clarity
- Handles text-based PDFs
- Uses Groq with `openai/gpt-oss-120b`

**Image-to-Text LLM** (`core/img_to_txt_llm_init.py`):
- New module for vision tasks
- Two providers:
  - **HuggingFace**: `Qwen/Qwen2.5-VL-7B-Instruct` for uploaded images
  - **Novita**: Vision inference for scanned PDFs

**Usage**:
```python
# For text PDFs (existing)
from core.txt_to_txt_llm_init import llm

# For images
from core.img_to_txt_llm_init import get_vision_llm_for_image
vision_llm = get_vision_llm_for_image()

# For scanned PDFs
from core.img_to_txt_llm_init import get_vision_llm_for_scanned_pdf
scanned_llm = get_vision_llm_for_scanned_pdf()
```

### 3. Configuration Updates

**New Environment Variables** (add to `.env`):
```env
# Cloudinary (already exists)
CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# HuggingFace for vision models
HF_TOKEN=your_huggingface_token

# Novita for scanned PDF processing
NOVITA_API_KEY=your_novita_api_key
```

## Implementation Guide

### Step 1: Update Routes to Use Cloudinary

Instead of saving to `public/pdfs/`, use Cloudinary:

```python
# OLD (local storage)
pdf_path = Path("public/pdfs") / filename
with pdf_path.open("wb") as buffer:
    shutil.copyfileobj(file.file, buffer)

# NEW (Cloudinary)
from services.storage import upload_medical_pdf

upload_result = upload_medical_pdf(
    file=file.file,
    filename=file.filename,
    document_type="report",  # or "bill", "prescription"
    patient_id=patient_id
)

# Store upload_result["secure_url"] in database instead of local path
```

### Step 2: Detect File Type (PDF vs Image)

```python
from pathlib import Path

file_ext = Path(file.filename).suffix.lower()

if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
    # Image file - use vision model
    upload_result = upload_medical_image(...)
    # Use img_to_txt_llm_init for extraction
    
elif file_ext == '.pdf':
    # PDF file - check if scanned
    upload_result = upload_medical_pdf(...)
    
    # Detect if scanned (low text content)
    text = extract_text_from_pdf(temp_path)
    if len(text.strip()) < 100:  # Likely scanned
        # Use img_to_txt_llm_init with Novita
        pass
    else:
        # Use txt_to_txt_llm_init (existing flow)
        pass
```

### Step 3: Update Database Models

Add `cloudinary_url` and `cloudinary_public_id` fields to store Cloudinary references:

```python
# In models/report.py, models/bill.py, models/medication.py
class Report(Base):
    # ... existing fields ...
    cloudinary_url: str = Column(String, nullable=True)
    cloudinary_public_id: str = Column(String, nullable=True)
    resource_type: str = Column(String, default="raw")  # "raw" or "image"
```

## Migration Steps

1. **Install Dependencies**:
```bash
pip install cloudinary langchain-huggingface
```

2. **Update `.env`**:
Add `HF_TOKEN` and `NOVITA_API_KEY`

3. **Create Alembic Migration**:
```bash
alembic revision --autogenerate -m "add cloudinary fields to documents"
alembic upgrade head
```

4. **Update Routes**:
- Replace local file saving with Cloudinary uploads
- Add file type detection
- Route to appropriate LLM based on file type

5. **Test**:
- Upload text PDF → should use Groq
- Upload scanned PDF → should use Novita
- Upload image → should use HuggingFace

## Benefits

### Cloudinary Storage
- ✅ No local disk space needed
- ✅ Automatic CDN distribution
- ✅ Secure URLs with expiration
- ✅ Image transformations available
- ✅ Backup and redundancy
- ✅ Easy file management via dashboard

### Vision Model Support
- ✅ Process scanned documents
- ✅ Handle image uploads
- ✅ Better OCR quality
- ✅ Support for handwritten notes
- ✅ Multi-modal document processing

## File Structure

```
core/
├── txt_to_txt_llm_init.py    # Text-based LLM (Groq)
├── img_to_txt_llm_init.py    # Vision LLMs (HF/Novita)
└── config.py                  # Updated with new env vars

services/
└── storage/
    ├── __init__.py
    └── cloudinary_storage.py  # Cloudinary service
```

## Next Steps

1. Update all three routes (reports, bills, prescriptions) to use Cloudinary
2. Add file type detection logic
3. Implement vision model extraction flow
4. Add database migration for Cloudinary fields
5. Update storage services to use Cloudinary URLs
6. Remove local `public/pdfs/` directory (after migration)

## Notes

- Cloudinary free tier: 25 GB storage, 25 GB bandwidth/month
- HuggingFace inference: Free tier available
- Novita: Pay-per-use pricing
- Keep local storage as fallback during migration
