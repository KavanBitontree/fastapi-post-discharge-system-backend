# Patient ID Integration - Patient-Friendly Report System

## ✅ Integration Complete

### What Was Changed

**File**: `routes/patient_friendly_report_routes.py`

#### Updated Endpoint:
- **Old**: `POST /api/patient-friendly-report/convert-pdf`
- **New**: `POST /api/patient-friendly-report/convert-pdf/{patient_id}`

### New Workflow

```
1. User provides patient_id in URL
   ↓
2. Upload discharge summary PDF
   ↓
3. Extract text from PDF
   ↓
4. Convert to patient-friendly report (LLM)
   ↓
5. Generate attractive PDF (ReportLab)
   ↓
6. Upload PDF to Cloudinary
   ↓
7. Find LATEST discharge history for patient
   ↓
8. Save Cloudinary URL to patient_friendly_summary_url
   ↓
9. Return Cloudinary link + report data
```

### Updated Endpoint

**POST** `/api/patient-friendly-report/convert-pdf/{patient_id}`

**URL Parameters**:
- `patient_id` (required): Patient ID from URL path

**Form Parameters**:
- `file` (required): Discharge summary PDF

**Response**:
```json
{
  "cloudinary_url": "https://res.cloudinary.com/...",
  "public_id": "medical_documents/reports/patient_5/...",
  "patient_id": 5,
  "discharge_id": 123,
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

### Database Integration

**Automatic Process**:
1. Receives `patient_id` from URL
2. Queries `discharge_history` table
3. Finds latest discharge for that patient (ordered by `created_at DESC`)
4. Updates `patient_friendly_summary_url` field with Cloudinary link
5. Commits to database

**Query**:
```sql
SELECT * FROM discharge_history 
WHERE patient_id = {patient_id}
ORDER BY created_at DESC
LIMIT 1;
```

**Update**:
```sql
UPDATE discharge_history 
SET patient_friendly_summary_url = '{cloudinary_url}'
WHERE id = {latest_discharge_id};
```

### Usage Examples

#### Using cURL
```bash
curl -X POST "http://localhost:5001/api/patient-friendly-report/convert-pdf/5" \
  -F "file=@discharge_summary.pdf"
```

Response:
```json
{
  "cloudinary_url": "https://res.cloudinary.com/...",
  "patient_id": 5,
  "discharge_id": 123,
  ...
}
```

#### Using Python
```python
import requests

patient_id = 5

with open('discharge_summary.pdf', 'rb') as f:
    response = requests.post(
        f'http://localhost:5001/api/patient-friendly-report/convert-pdf/{patient_id}',
        files={'file': f}
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"Patient ID: {data['patient_id']}")
        print(f"Discharge ID: {data['discharge_id']}")
        print(f"Cloudinary URL: {data['cloudinary_url']}")
        print(f"Processing time: {data['processing_time_seconds']}s")
    else:
        print(f"Error: {response.status_code}")
        print(response.json())
```

#### Using JavaScript/Fetch
```javascript
const patientId = 5;
const formData = new FormData();
formData.append('file', fileInput.files[0]);

fetch(`http://localhost:5001/api/patient-friendly-report/convert-pdf/${patientId}`, {
  method: 'POST',
  body: formData
})
.then(response => response.json())
.then(data => {
  console.log('Patient ID:', data.patient_id);
  console.log('Discharge ID:', data.discharge_id);
  console.log('Cloudinary URL:', data.cloudinary_url);
})
.catch(error => console.error('Error:', error));
```

### Swagger UI Testing

1. Open: `http://localhost:5001/docs`
2. Find: `POST /api/patient-friendly-report/convert-pdf/{patient_id}`
3. Click "Try it out"
4. Enter `patient_id` (e.g., 5)
5. Click "Choose File" and select PDF
6. Click "Execute"
7. View response with Cloudinary URL

### Error Handling

- **Invalid file type**: Returns 400 Bad Request
- **Empty PDF**: Returns 422 Unprocessable Entity
- **Conversion failed**: Returns 500 Internal Server Error
- **Cloudinary upload failed**: Returns 500 with error details
- **No discharge history found**: Returns 200 with `discharge_id: null` (warning logged)

### Database Fields Updated

**Table**: `discharge_history`
**Field**: `patient_friendly_summary_url`

**Before**:
```
patient_friendly_summary_url = NULL
```

**After**:
```
patient_friendly_summary_url = "https://res.cloudinary.com/..."
```

### Benefits

✅ **Patient-Specific**: Uses patient_id from URL
✅ **Automatic Lookup**: Finds latest discharge automatically
✅ **Database Integration**: Saves URL for later retrieval
✅ **Persistent Storage**: PDFs stored in Cloudinary
✅ **Secure URLs**: Uses HTTPS secure URLs
✅ **Complete Response**: Returns all report data + Cloudinary link

### Files Modified

- ✅ `routes/patient_friendly_report_routes.py` - Updated endpoint with patient_id

### Files Used (No Changes)

- ✅ `models/discharge_history.py` - Database model
- ✅ `services/storage/cloudinary_storage.py` - Cloudinary service
- ✅ `services/pdf_generator.py` - PDF generation
- ✅ `services/llm_validators/llm_discharge_summary_converter.py` - LLM conversion

### Status

✅ **INTEGRATION COMPLETE**

The patient-friendly report system now:
1. Accepts patient_id from URL
2. Generates patient-friendly PDFs
3. Uploads them to Cloudinary
4. Finds latest discharge history for patient
5. Saves Cloudinary URL to database
6. Returns complete response with all data

Ready for production use!
