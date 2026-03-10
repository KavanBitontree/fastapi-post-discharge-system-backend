# Dual PDF Storage - Patient-Friendly Report System

## ✅ Dual Storage Complete

### What Was Changed

**File**: `routes/patient_friendly_report_routes.py`

#### Updated Functionality:
1. **Upload Original Discharge Summary** - To Cloudinary
2. **Upload Patient-Friendly Report** - To Cloudinary
3. **Save Both URLs** - To database fields
4. **Return Both Links** - In response

### Updated Endpoint

**POST** `/api/patient-friendly-report/convert-pdf/{patient_id}`

**Parameters**:
- `patient_id` (URL path): Patient ID
- `file` (form): Discharge summary PDF

**Response**:
```json
{
  "discharge_summary_url": "https://res.cloudinary.com/.../discharge_summary_patient_5.pdf",
  "discharge_summary_public_id": "medical_documents/reports/patient_5/...",
  "patient_friendly_url": "https://res.cloudinary.com/.../patient_friendly_report_patient_5.pdf",
  "patient_friendly_public_id": "medical_documents/reports/patient_5/...",
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
5. Upload ORIGINAL discharge summary to Cloudinary ✅ NEW
   ↓
6. Upload PATIENT-FRIENDLY report to Cloudinary ✅ NEW
   ↓
7. Find latest discharge history for patient
   ↓
8. Save BOTH URLs to database ✅ NEW
   - discharge_summary_url (original)
   - patient_friendly_summary_url (simplified)
   ↓
9. Return response with both Cloudinary links ✅ NEW
```

### Database Integration

**Table**: `discharge_history`

**Fields Updated**:
1. `discharge_summary_url` - Original discharge summary PDF
2. `patient_friendly_summary_url` - Patient-friendly report PDF

**Before**:
```sql
discharge_summary_url = NULL
patient_friendly_summary_url = NULL
```

**After**:
```sql
discharge_summary_url = "https://res.cloudinary.com/.../discharge_summary_patient_5.pdf"
patient_friendly_summary_url = "https://res.cloudinary.com/.../patient_friendly_report_patient_5.pdf"
```

### Cloudinary Storage

**Folder Structure**:
```
medical_documents/reports/
├── patient_5/
│   ├── 20260310_133425_discharge_summary_patient_5.pdf
│   └── 20260310_133430_patient_friendly_report_patient_5.pdf
├── patient_6/
│   ├── 20260310_140000_discharge_summary_patient_6.pdf
│   └── 20260310_140005_patient_friendly_report_patient_6.pdf
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
  "discharge_summary_url": "https://res.cloudinary.com/.../discharge_summary_patient_5.pdf",
  "patient_friendly_url": "https://res.cloudinary.com/.../patient_friendly_report_patient_5.pdf",
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
        print(f"Original PDF: {data['discharge_summary_url']}")
        print(f"Patient-Friendly PDF: {data['patient_friendly_url']}")
        print(f"Discharge ID: {data['discharge_id']}")
    else:
        print(f"Error: {response.status_code}")
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
  console.log('Original PDF:', data.discharge_summary_url);
  console.log('Patient-Friendly PDF:', data.patient_friendly_url);
  console.log('Discharge ID:', data.discharge_id);
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
7. View response with both Cloudinary URLs

### Database Query

**Find discharge with both URLs**:
```sql
SELECT 
  id,
  patient_id,
  discharge_summary_url,
  patient_friendly_summary_url,
  created_at
FROM discharge_history
WHERE patient_id = 5
ORDER BY created_at DESC
LIMIT 1;
```

**Result**:
```
id | patient_id | discharge_summary_url | patient_friendly_summary_url | created_at
123| 5          | https://res.cloudinary.com/.../discharge_summary_patient_5.pdf | https://res.cloudinary.com/.../patient_friendly_report_patient_5.pdf | 2026-03-10 13:34:25
```

### Benefits

✅ **Original Preserved**: Original discharge summary stored for reference
✅ **Patient-Friendly Available**: Simplified version for patient access
✅ **Both Persistent**: Both stored in Cloudinary (not temporary)
✅ **Database Linked**: Both URLs saved to discharge history
✅ **Easy Retrieval**: Can access either version anytime
✅ **Audit Trail**: Original document preserved for compliance

### Error Handling

- **Invalid file type**: Returns 400 Bad Request
- **Empty PDF**: Returns 422 Unprocessable Entity
- **Conversion failed**: Returns 500 Internal Server Error
- **Cloudinary upload failed**: Returns 500 with error details
- **No discharge history**: Returns 200 with `discharge_id: null` (warning logged)

### Processing Steps

1. **Read PDF** - Load original file into memory
2. **Extract Text** - Use pdfplumber to extract all text
3. **Convert** - Use LLM to create patient-friendly version
4. **Generate PDF** - Create formatted patient-friendly PDF
5. **Upload Original** - Send original to Cloudinary
6. **Upload Friendly** - Send patient-friendly to Cloudinary
7. **Find Discharge** - Query latest discharge for patient
8. **Save URLs** - Update both database fields
9. **Return Response** - Send both URLs to user

### Files Modified

- ✅ `routes/patient_friendly_report_routes.py` - Dual PDF upload and storage

### Files Used (No Changes)

- ✅ `models/discharge_history.py` - Database model
- ✅ `services/storage/cloudinary_storage.py` - Cloudinary service
- ✅ `services/pdf_generator.py` - PDF generation
- ✅ `services/llm_validators/llm_discharge_summary_converter.py` - LLM conversion

### Status

✅ **DUAL STORAGE COMPLETE**

The patient-friendly report system now:
1. Accepts patient_id from URL
2. Generates patient-friendly PDFs
3. Uploads BOTH original and patient-friendly PDFs to Cloudinary
4. Finds latest discharge history for patient
5. Saves BOTH Cloudinary URLs to database
6. Returns complete response with all data

Ready for production use!
