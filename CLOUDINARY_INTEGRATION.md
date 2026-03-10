# Cloudinary Integration - Patient-Friendly Report System

## ✅ Integration Complete

### What Was Changed

**File**: `routes/patient_friendly_report_routes.py`

#### New Features:
1. **Cloudinary Upload**: Generated PDF is now uploaded to Cloudinary
2. **Database Storage**: Cloudinary URL is saved to `patient_friendly_summary_url` field
3. **URL Return**: API returns Cloudinary link instead of direct download

### Updated Endpoint

**POST** `/api/patient-friendly-report/convert-pdf`

#### New Parameters:
- `file` (required): PDF file upload
- `discharge_id` (optional): Discharge history ID to save URL to database

#### New Response:
```json
{
  "cloudinary_url": "https://res.cloudinary.com/...",
  "public_id": "medical_documents/reports/patient_0/...",
  "summary": "...",
  "key_points": [...],
  "medications": [...],
  "follow_up_instructions": "...",
  "warning_signs": [...],
  "processing_time_seconds": 45.2,
  "original_length_chars": 34662,
  "summary_length_chars": 2847
}
```

### Complete Flow

```
1. User uploads discharge summary PDF
   ↓
2. Extract text from PDF
   ↓
3. Convert to patient-friendly report (LLM)
   ↓
4. Generate attractive PDF (ReportLab)
   ↓
5. Upload PDF to Cloudinary
   ↓
6. Save Cloudinary URL to database (if discharge_id provided)
   ↓
7. Return Cloudinary link + report data
```

### Database Integration

**Table**: `discharge_history`
**Field**: `patient_friendly_summary_url`

When `discharge_id` is provided:
- Cloudinary URL is automatically saved to the database
- Can be retrieved later for patient access

### Cloudinary Configuration

Uses existing `services/storage/cloudinary_storage.py`:
- Cloud Name: `settings.CLOUD_NAME`
- API Key: `settings.CLOUDINARY_API_KEY`
- API Secret: `settings.CLOUDINARY_API_SECRET`

**Folder Structure**:
```
medical_documents/
├── reports/
│   └── patient_{patient_id}/
│       └── {timestamp}_{filename}.pdf
├── bills/
└── prescriptions/
```

### Usage Examples

#### Without Database Storage (Anonymous)
```bash
curl -X POST "http://localhost:5001/api/patient-friendly-report/convert-pdf" \
  -F "file=@discharge_summary.pdf"
```

Response:
```json
{
  "cloudinary_url": "https://res.cloudinary.com/...",
  "public_id": "medical_documents/reports/patient_0/...",
  ...
}
```

#### With Database Storage
```bash
curl -X POST "http://localhost:5001/api/patient-friendly-report/convert-pdf" \
  -F "file=@discharge_summary.pdf" \
  -F "discharge_id=123"
```

Response:
```json
{
  "cloudinary_url": "https://res.cloudinary.com/...",
  "public_id": "medical_documents/reports/patient_5/...",
  ...
}
```

Database is updated:
```sql
UPDATE discharge_history 
SET patient_friendly_summary_url = 'https://res.cloudinary.com/...'
WHERE id = 123;
```

### Python Example

```python
import requests

# With discharge_id to save to database
with open('discharge_summary.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:5001/api/patient-friendly-report/convert-pdf',
        files={'file': f},
        params={'discharge_id': 123}
    )
    
    if response.status_code == 200:
        data = response.json()
        cloudinary_url = data['cloudinary_url']
        print(f"PDF saved to: {cloudinary_url}")
        print(f"Public ID: {data['public_id']}")
    else:
        print(f"Error: {response.status_code}")
        print(response.json())
```

### Benefits

✅ **Persistent Storage**: PDFs stored in Cloudinary (not temporary)
✅ **Database Integration**: URLs saved for later retrieval
✅ **Secure URLs**: Uses HTTPS secure URLs
✅ **Organized**: Files organized by patient and document type
✅ **Scalable**: Cloudinary handles storage and delivery
✅ **Accessible**: URLs can be shared with patients

### Error Handling

- **Invalid file type**: Returns 400 Bad Request
- **Empty PDF**: Returns 422 Unprocessable Entity
- **Conversion failed**: Returns 500 Internal Server Error
- **Cloudinary upload failed**: Returns 500 with error details
- **Database save failed**: Returns 500 with error details

### Testing

1. **Start server**:
```bash
python main.py
```

2. **Open Swagger UI**:
```
http://localhost:5001/docs
```

3. **Test endpoint**:
- Find: `POST /api/patient-friendly-report/convert-pdf`
- Click "Try it out"
- Upload a discharge summary PDF
- Optionally provide discharge_id
- Click "Execute"
- Get Cloudinary URL in response

### Files Modified

- ✅ `routes/patient_friendly_report_routes.py` - Added Cloudinary upload and database storage

### Files Used (No Changes)

- ✅ `services/storage/cloudinary_storage.py` - Existing Cloudinary service
- ✅ `models/discharge_history.py` - Existing database model
- ✅ `services/pdf_generator.py` - PDF generation
- ✅ `services/llm_validators/llm_discharge_summary_converter.py` - LLM conversion

### Status

✅ **INTEGRATION COMPLETE**

The patient-friendly report system now:
1. Generates patient-friendly PDFs
2. Uploads them to Cloudinary
3. Saves URLs to the database
4. Returns Cloudinary links to users

Ready for production use!
