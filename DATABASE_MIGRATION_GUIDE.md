# Database Migration Guide: Cloudinary Fields

## Overview

This guide explains how to add Cloudinary storage fields to your database models.

## Current State

Currently, the routes upload to Cloudinary and return the URLs in the API response, but the database models don't have fields to store this information permanently.

## Required Changes

### 1. Update Models

Add Cloudinary fields to the following models:

#### `models/report.py`
```python
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from core.database import Base
from datetime import datetime

class Report(Base):
    __tablename__ = "reports"
    
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    report_name = Column(String(255), nullable=False)
    report_date = Column(Date, nullable=True)
    collection_date = Column(Date, nullable=True)
    received_date = Column(Date, nullable=True)
    specimen_type = Column(String(100), nullable=True)
    status = Column(String(50), nullable=True)
    report_url = Column(Text, nullable=True)  # Keep for backward compatibility
    
    # NEW FIELDS
    cloudinary_url = Column(Text, nullable=True)
    cloudinary_public_id = Column(String(255), nullable=True)
    resource_type = Column(String(50), default="pdf")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    patient = relationship("Patient", back_populates="reports")
    descriptions = relationship("ReportDescription", back_populates="report", cascade="all, delete-orphan")
```

#### `models/bill.py`
```python
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Numeric, Text, DateTime
from sqlalchemy.orm import relationship
from core.database import Base
from datetime import datetime

class Bill(Base):
    __tablename__ = "bills"
    
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    invoice_number = Column(String(100), unique=True, nullable=False)
    invoice_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    initial_amount = Column(Numeric(10, 2), nullable=True)
    discount_amount = Column(Numeric(10, 2), nullable=True)
    tax_amount = Column(Numeric(10, 2), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=False)
    bill_url = Column(Text, nullable=True)  # Keep for backward compatibility
    
    # NEW FIELDS
    cloudinary_url = Column(Text, nullable=True)
    cloudinary_public_id = Column(String(255), nullable=True)
    resource_type = Column(String(50), default="pdf")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    patient = relationship("Patient", back_populates="bills")
    descriptions = relationship("BillDescription", back_populates="bill", cascade="all, delete-orphan")
```

#### `models/medication.py` (for prescriptions)
```python
# Add to Medication model if you want to store prescription PDFs
# Alternatively, create a new Prescription model

class Medication(Base):
    __tablename__ = "medications"
    
    # ... existing fields ...
    
    # NEW FIELDS (optional - if you want to link prescriptions to medications)
    prescription_url = Column(Text, nullable=True)
    cloudinary_url = Column(Text, nullable=True)
    cloudinary_public_id = Column(String(255), nullable=True)
    resource_type = Column(String(50), default="pdf")
```

### 2. Create Alembic Migration

```bash
# Generate migration
alembic revision --autogenerate -m "add_cloudinary_fields_to_reports_bills"

# Review the generated migration file in alembic/versions/
# Make sure it includes:
# - Adding cloudinary_url column
# - Adding cloudinary_public_id column
# - Adding resource_type column

# Apply migration
alembic upgrade head
```

### 3. Update Store Functions

Update the store functions to save Cloudinary information:

#### `services/db_store/store_report.py`
```python
def store_report(
    db: Session,
    validated_report: ValidatedReport,
    patient_id: int,
    report_url: str,
    cloudinary_public_id: Optional[str] = None,
    resource_type: str = "pdf"
) -> Report:
    """Store report with Cloudinary information."""
    
    # ... existing code ...
    
    report = Report(
        patient_id=patient_id,
        report_name=validated_report.header.report_name,
        # ... other fields ...
        report_url=report_url,  # Keep for backward compatibility
        cloudinary_url=report_url,  # NEW
        cloudinary_public_id=cloudinary_public_id,  # NEW
        resource_type=resource_type,  # NEW
    )
    
    # ... rest of function ...
```

#### `services/db_store/store_bill.py`
Similar changes for bills.

### 4. Update Routes

Routes are already updated to pass Cloudinary information. Just need to update the store function calls:

#### `routes/report_routes.py`
```python
# Already done - just need to update store_report call
report = store_report(
    db=db,
    validated_report=validated_report,
    patient_id=patient.id,
    report_url=cloudinary_url,
    cloudinary_public_id=cloudinary_public_id,
    resource_type="pdf"
)
```

## Migration Steps

### Step 1: Backup Database
```bash
# Backup your database before migration
pg_dump -h your_host -U your_user -d your_db > backup_before_cloudinary.sql
```

### Step 2: Update Models
- Add the new fields to `models/report.py`
- Add the new fields to `models/bill.py`
- Optionally add to `models/medication.py`

### Step 3: Generate Migration
```bash
alembic revision --autogenerate -m "add_cloudinary_fields"
```

### Step 4: Review Migration
Open the generated file in `alembic/versions/` and verify:
```python
def upgrade():
    # Should include:
    op.add_column('reports', sa.Column('cloudinary_url', sa.Text(), nullable=True))
    op.add_column('reports', sa.Column('cloudinary_public_id', sa.String(255), nullable=True))
    op.add_column('reports', sa.Column('resource_type', sa.String(50), nullable=True))
    
    op.add_column('bills', sa.Column('cloudinary_url', sa.Text(), nullable=True))
    op.add_column('bills', sa.Column('cloudinary_public_id', sa.String(255), nullable=True))
    op.add_column('bills', sa.Column('resource_type', sa.String(50), nullable=True))
```

### Step 5: Apply Migration
```bash
alembic upgrade head
```

### Step 6: Update Store Functions
- Update `store_report()` to accept and save Cloudinary fields
- Update `store_bill()` to accept and save Cloudinary fields
- Update route calls to pass Cloudinary information

### Step 7: Test
```bash
# Test report upload
curl -X POST http://localhost:8000/api/reports/upload \
  -F "patient_id=1" \
  -F "file=@test_report.pdf" \
  -F "strategy=auto"

# Verify database has cloudinary_url and cloudinary_public_id
```

## Data Migration (Optional)

If you have existing records with local file paths, you can migrate them to Cloudinary:

```python
# migration_script.py
from models.report import Report
from models.bill import Bill
from services.storage.cloudinary_storage import upload_medical_pdf
from core.database import SessionLocal
from pathlib import Path

def migrate_existing_files():
    db = SessionLocal()
    
    # Migrate reports
    reports = db.query(Report).filter(Report.cloudinary_url == None).all()
    for report in reports:
        if report.report_url and report.report_url.startswith("/public/pdfs/"):
            local_path = Path(report.report_url.lstrip("/"))
            if local_path.exists():
                with open(local_path, "rb") as f:
                    result = upload_medical_pdf(
                        file=f,
                        filename=local_path.name,
                        document_type="report",
                        patient_id=report.patient_id
                    )
                
                report.cloudinary_url = result["secure_url"]
                report.cloudinary_public_id = result["public_id"]
                report.resource_type = "pdf"
                db.commit()
                print(f"Migrated report {report.id}")
    
    # Similar for bills
    # ...
    
    db.close()

if __name__ == "__main__":
    migrate_existing_files()
```

## Rollback Plan

If something goes wrong:

```bash
# Rollback migration
alembic downgrade -1

# Restore from backup
psql -h your_host -U your_user -d your_db < backup_before_cloudinary.sql
```

## Verification

After migration, verify:

1. ✅ New columns exist in database
2. ✅ New uploads save Cloudinary information
3. ✅ API returns Cloudinary URLs
4. ✅ Old records still work (backward compatibility)
5. ✅ Files accessible via Cloudinary URLs

## Notes

- Keep `report_url` and `bill_url` for backward compatibility
- New uploads should populate both old and new fields
- Gradually migrate old records to Cloudinary
- Consider cleanup script to delete old local files after migration

## Support

If you encounter issues:
1. Check Alembic migration logs
2. Verify database schema matches models
3. Test with a single record first
4. Keep backups before major changes
