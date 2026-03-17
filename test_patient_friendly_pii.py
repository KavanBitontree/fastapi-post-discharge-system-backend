#!/usr/bin/env python3
"""Test PII redaction in patient-friendly report flow."""

from services.pii_redaction import redact_pii_from_text

# Sample discharge summary text
discharge_summary = """
DISCHARGE SUMMARY

Patient Name: Williams, Thomas B.
Patient ID: MED-2026-063291
Date of Birth: 05/14/1967
Age: 58 years
Sex: Male
Email: thomas.williams@gmail.com
Phone: +1 (312) 555-8821
Address: 123 Oak Street, Chicago, IL 60601

ADMISSION DATE: 03/05/2026
DISCHARGE DATE: 03/15/2026

DIAGNOSIS:
Type 2 Diabetes Mellitus (E11)
Hypertension (I10)
Hyperlipidemia (E78.5)

HOSPITAL COURSE:
Patient admitted with elevated blood glucose levels. During hospitalization, patient underwent comprehensive metabolic panel and cardiovascular assessment.

MEDICATIONS AT DISCHARGE:
1. Metformin 500 mg - twice daily
2. Lisinopril 10 mg - once daily
3. Atorvastatin 20 mg - once daily

FOLLOW-UP INSTRUCTIONS:
Return to clinic in 2 weeks for blood glucose monitoring.
Contact Dr. Michael T. Grover at m.grover@medicarehospital.org for any concerns.
Hospital phone: (312) 555-0198

DISCHARGE PHYSICIAN:
Dr. Michael T. Grover, MD, FACP
Endocrinologist & Diabetologist
"""

print("=" * 70)
print("PATIENT-FRIENDLY REPORT - PII REDACTION TEST")
print("=" * 70)
print()

print("Step 1: Extract text from discharge summary PDF")
print(f"  Text length: {len(discharge_summary)} chars")
print()

print("Step 2: Redact PII before sending to LLM")
redacted_text, metadata = redact_pii_from_text(
    discharge_summary,
    document_type="discharge_summary",
    filename="discharge_summary.pdf"
)

print(f"  Redaction count: {metadata['redaction_count']}")
print(f"  Patient names: {metadata['patient_names']}")
print(f"  Patient IDs: {metadata['patient_ids']}")
print(f"  Patient emails: {metadata['patient_emails']}")
print(f"  Patient phones: {metadata['patient_phones']}")
print(f"  Patient addresses: {metadata['patient_addresses']}")
print()

print("Step 3: Verify redaction")
checks = [
    ("Patient name redacted", "Williams, Thomas B." not in redacted_text),
    ("Patient ID redacted", "MED-2026-063291" not in redacted_text),
    ("Patient email redacted", "thomas.williams@gmail.com" not in redacted_text),
    ("Patient phone redacted", "+1 (312) 555-8821" not in redacted_text),
    ("Patient address redacted", "123 Oak Street" not in redacted_text),
    ("Doctor email preserved", "m.grover@medicarehospital.org" in redacted_text),
    ("Hospital phone preserved", "(312) 555-0198" in redacted_text),
    ("Medications preserved", "Metformin" in redacted_text),
]

all_passed = True
for check_name, result in checks:
    status = "✓" if result else "✗"
    print(f"  {status} {check_name}")
    if not result:
        all_passed = False

print()

print("Step 4: Show sample of redacted text")
print("-" * 70)
for line in redacted_text.split('\n')[:20]:
    if line.strip():
        print(line)
print("-" * 70)
print()

if all_passed:
    print("✓ ALL CHECKS PASSED!")
    print("  - Patient PII redacted before LLM")
    print("  - Hospital info preserved")
    print("  - Medical info preserved")
    print("  - Ready for patient-friendly conversion")
else:
    print("✗ SOME CHECKS FAILED")

print()
print("=" * 70)
