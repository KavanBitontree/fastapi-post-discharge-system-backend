"""
pii_redaction.py
----------------
Service for detecting and redacting PII (Personally Identifiable Information) 
from medical documents before sending to LLM.

Redacts these 6 fields:
1. Patient Name
2. Patient ID
3. Patient Email
4. Patient Address
5. Patient Phone Number
6. Passport Number
"""

import re
from typing import Dict, List, Tuple
from pathlib import Path
from datetime import datetime
import json


class PIIRedactor:
    """Detects and redacts specific PII fields from text."""
    
    # Pattern for Patient Name (handles multiple formats)
    # Matches: "Patient Name:", "Name :" (in patient section only)
    # Stops at field boundaries like "Report", "Account", "Date of Birth", "Passport", "DOB", "MRN", or newline
    # Does NOT match doctor names (preceded by "Dr.", "MD", "FACP", etc.)
    PATIENT_NAME_PATTERN = r'(?:Patient\s+)?Name\s*:\s*([^\n]+?)(?=\s+(?:Report|Account|Date\s+of\s+Birth|Passport|DOB|MRN|Branch|LabNo|Collected|Received|Reported|PageNo|Consultant)|\n|$)'
    
    # Pattern for Patient ID (handles multiple formats)
    # Matches: "Patient ID:", "Account #:", "Passport:", "MRN:", "Lab No:", "LabNo:"
    # Captures ID up to field boundaries
    PATIENT_ID_PATTERN = r'(?:Patient\s+ID|Account\s+#|Passport|MRN|Lab\s*No)\s*:\s*([^\n]+?)(?=\s+(?:Collection|Age|Received|Invoice|Date\s+of\s+Birth|DOB|Branch|Collected|Reported|PageNo)|\n|$)'
    
    # Pattern for Patient Email (handles multiple formats)
    # Matches: "Patient Email:", "Email:" (in patient section), or standalone email addresses
    # Excludes doctor/hospital emails by checking context
    # Captures email address only (stops at whitespace or field boundary)
    PATIENT_EMAIL_PATTERN = r'(?:Patient\s+)?Email\s*:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?=\s|$|\n|[\s]*\||[\s]*Ext\.)'
    
    # Pattern for Patient Address (specifically after "Patient Address:" or "Address:")
    # Captures address up to newline or next field
    PATIENT_ADDRESS_PATTERN = r'(?:Patient\s+)?Address\s*:\s*([^\n]+?)(?=\n|$)'
    
    # Pattern for Patient Phone (handles multiple formats)
    # Matches: "Patient Phone:", "Phone:" (in patient section), or standalone phone numbers
    # Excludes doctor/hospital phones by checking context
    # Captures phone up to "Due Date", "Invoice", or newline
    PATIENT_PHONE_PATTERN = r'(?:Patient\s+)?Phone\s*:\s*([^\n]+?)(?=\s+(?:Due\s+Date|Invoice|Collection|Report|Lab|Email|Refills|Diagnosis|Rx)|\n|$)|(?<!Ext\.\s)(\+?1?\s*\(?[0-9]{3}\)?[\s.-]?[0-9]{3}[\s.-]?[0-9]{4})(?=\s+(?:as\s+per|WHATSAPP|Medication|for\s+queries)|\n|$)'
    
    # Pattern for Passport Number (specifically after "Passport:")
    # Captures passport number up to field boundaries
    PASSPORT_PATTERN = r'Passport\s*:\s*([^\n]+?)(?=\s+(?:LabNo|Lab\s+No|DOB|MRN|Branch|Collected|Received|Reported|PageNo)|\n|$)'
    
    def __init__(self, save_to_test_folder: bool = False):
        """
        Initialize PII redactor.
        
        Parameters
        ----------
        save_to_test_folder : bool
            If True, saves redacted PII to test folder for verification.
            Default is False to avoid wasting tokens during development.
        """
        self.save_to_test_folder = save_to_test_folder
        self.test_folder = Path("test")
        self.file_counter = 0  # Counter for simple file naming
        
        if self.save_to_test_folder:
            self.test_folder.mkdir(exist_ok=True)
    
    
    def detect_patient_name(self, text: str) -> List[str]:
        """Detect patient name in text - captures only the name value, excludes doctor names."""
        names = []
        matches = re.findall(self.PATIENT_NAME_PATTERN, text, re.IGNORECASE)
        for match in matches:
            name = match.strip()
            
            # Skip if already redacted
            if name and not name.startswith('['):
                # Filter out doctor names (contain "Dr.", "MD", "FACP", "FACC", etc.)
                # Also filter out names with underscores (formatting artifacts)
                doctor_indicators = ['dr.', 'md,', 'facp', 'facc', 'md facp', 'md facc', 'phd', 'dds', 'dvm']
                is_doctor_name = any(indicator in name.lower() for indicator in doctor_indicators)
                has_underscores = '_' in name
                
                if not is_doctor_name and not has_underscores:
                    names.append(name)
        
        return list(set(names))
    
    def detect_patient_id(self, text: str) -> List[str]:
        """Detect patient ID in text - captures only the ID value."""
        ids = []
        matches = re.findall(self.PATIENT_ID_PATTERN, text, re.IGNORECASE)
        for match in matches:
            pid = match.strip()
            if pid and not pid.startswith('['):
                ids.append(pid)
        return list(set(ids))
    
    def detect_patient_email(self, text: str) -> List[str]:
        """Detect patient email in text - captures only the email value from patient section."""
        emails = []
        
        # First, try to find emails in labeled patient fields
        matches = re.findall(self.PATIENT_EMAIL_PATTERN, text, re.IGNORECASE)
        for match in matches:
            # Handle both single string and tuple results from multiple capture groups
            if isinstance(match, tuple):
                email = match[0] or match[1]  # Use first non-empty group
            else:
                email = match
            email = email.strip()
            
            # Only include if it looks like a patient email (not doctor/hospital domain)
            # Patient emails typically don't have hospital domain names
            if email and not email.startswith('[') and '@' in email:
                # Exclude common hospital/doctor domains
                if not any(domain in email.lower() for domain in ['medicarehospital', 'hospital', 'clinic', 'medical']):
                    emails.append(email)
        
        return list(set(emails))
    
    def detect_patient_address(self, text: str) -> List[str]:
        """Detect patient address in text - captures only the address value."""
        addresses = []
        matches = re.findall(self.PATIENT_ADDRESS_PATTERN, text, re.IGNORECASE)
        for match in matches:
            address = match.strip()
            if address and not address.startswith('['):
                addresses.append(address)
        return list(set(addresses))
    
    def detect_patient_phone(self, text: str) -> List[str]:
        """Detect patient phone in text - captures only the phone value from patient section."""
        phones = []
        matches = re.findall(self.PATIENT_PHONE_PATTERN, text, re.IGNORECASE)
        for match in matches:
            # Handle both single string and tuple results from multiple capture groups
            if isinstance(match, tuple):
                phone = match[0] or match[1]  # Use first non-empty group
            else:
                phone = match
            phone = phone.strip()
            
            # Only include if it's in a patient context (not hospital/doctor context)
            # Check if phone appears after "Phone:" label or in WHATSAPP/medication reminder context
            if phone and not phone.startswith('['):
                # Find the context around this phone number
                phone_index = text.find(phone)
                if phone_index != -1:
                    # Get context before the phone number (look back 100 chars)
                    context_start = max(0, phone_index - 100)
                    context_before = text[context_start:phone_index].lower()
                    
                    # Check if it's in patient section (has "phone:" or "whatsapp" or "medication reminder")
                    # and NOT in "prescribed by" or "for queries" section
                    is_patient_context = any(keyword in context_before for keyword in ['phone :', 'whatsapp', 'medication reminder', 'as per schedule'])
                    is_hospital_context = any(keyword in context_before for keyword in ['prescribed by', 'for queries', 'ext.'])
                    
                    if is_patient_context or (not is_hospital_context and 'phone :' in context_before):
                        phones.append(phone)
        
        return list(set(phones))
    
    def detect_passport(self, text: str) -> List[str]:
        """Detect passport number in text - captures only the passport value."""
        passports = []
        matches = re.findall(self.PASSPORT_PATTERN, text, re.IGNORECASE)
        for match in matches:
            passport = match.strip()
            if passport and not passport.startswith('['):
                passports.append(passport)
        return list(set(passports))
    
    def redact_text(
        self, 
        text: str, 
        document_type: str = "unknown",
        filename: str = "unknown.pdf"
    ) -> Tuple[str, Dict]:
        """
        Redact PII from text using two-pass approach:
        
        PASS 1: Detect and store all PII values
        PASS 2: Redact stored values and save to file
        
        Redacts these 6 fields:
        1. Patient Name (from "Patient Name:" field only)
        2. Patient ID (from "Patient ID:" field only)
        3. Patient Email (from "Patient Email:" field only)
        4. Patient Address (from "Patient Address:" field only)
        5. Patient Phone Number (from "Patient Phone:" field only)
        6. Passport Number (from "Passport:" field only)
        
        Does NOT redact:
        - Lab contact information
        - Ordering physician names
        - Lab director names
        - Lab contact phone/email
        
        Parameters
        ----------
        text : str
            Original text to redact
        document_type : str
            Type of document (bill, report, prescription)
        filename : str
            Original filename for tracking
        
        Returns
        -------
        Tuple[str, Dict]
            (redacted_text, metadata_dict)
            
        Note: If save_to_test_folder is enabled, returns early after saving
        test files to avoid wasting tokens on LLM processing during masking verification.
        """
        
        # ═══════════════════════════════════════════════════════════════════
        # PASS 1: DETECT AND STORE ALL PII VALUES
        # ═══════════════════════════════════════════════════════════════════
        print(f"[PII] PASS 1: Detecting PII fields...")
        
        patient_names = self.detect_patient_name(text)
        patient_ids = self.detect_patient_id(text)
        patient_emails = self.detect_patient_email(text)
        patient_addresses = self.detect_patient_address(text)
        patient_phones = self.detect_patient_phone(text)
        passports = self.detect_passport(text)
        
        print(f"[PII] PASS 1 Results:")
        print(f"  Names: {patient_names}")
        print(f"  IDs: {patient_ids}")
        print(f"  Emails: {patient_emails}")
        print(f"  Addresses: {patient_addresses}")
        print(f"  Phones: {patient_phones}")
        print(f"  Passports: {passports}")
        
        # Create metadata with detected values
        metadata = {
            "document_type": document_type,
            "filename": filename,
            "timestamp": datetime.now().isoformat(),
            "patient_names": patient_names,
            "patient_ids": patient_ids,
            "patient_emails": patient_emails,
            "patient_addresses": patient_addresses,
            "patient_phones": patient_phones,
            "passports": passports,
            "redaction_count": len(patient_names) + len(patient_ids) + len(patient_emails) + len(patient_addresses) + len(patient_phones) + len(passports),
            "original_length": len(text),
        }
        
        # ═══════════════════════════════════════════════════════════════════
        # PASS 2: REDACT STORED VALUES
        # ═══════════════════════════════════════════════════════════════════
        print(f"[PII] PASS 2: Redacting {metadata['redaction_count']} PII items...")
        
        redacted_text = text
        
        # Redact passports FIRST (before IDs, since passport values might overlap with other IDs)
        for passport in passports:
            redacted_text = redacted_text.replace(passport, "[PASSPORT_REDACTED]")
            print(f"[PII]   ✓ Redacted passport: {passport}")
        
        # Redact patient names (exact match only)
        for name in patient_names:
            redacted_text = redacted_text.replace(name, "[PATIENT_NAME_REDACTED]")
            print(f"[PII]   ✓ Redacted name: {name}")
        
        # Redact patient IDs (exact match only)
        for pid in patient_ids:
            redacted_text = redacted_text.replace(pid, "[PATIENT_ID_REDACTED]")
            print(f"[PII]   ✓ Redacted ID: {pid}")
        
        # Redact patient emails (exact match only)
        for email in patient_emails:
            redacted_text = redacted_text.replace(email, "[PATIENT_EMAIL_REDACTED]")
            print(f"[PII]   ✓ Redacted email: {email}")
        
        # Redact patient addresses (exact match only)
        for address in patient_addresses:
            redacted_text = redacted_text.replace(address, "[PATIENT_ADDRESS_REDACTED]")
            print(f"[PII]   ✓ Redacted address: {address}")
        
        # Redact patient phones (exact match only)
        for phone in patient_phones:
            redacted_text = redacted_text.replace(phone, "[PATIENT_PHONE_REDACTED]")
            print(f"[PII]   ✓ Redacted phone: {phone}")
        
        metadata["redacted_length"] = len(redacted_text)
        
        print(f"[PII] PASS 2 Complete: Redacted {metadata['redaction_count']} items")
        
        # ═══════════════════════════════════════════════════════════════════
        # PASS 3: SAVE TO TEST FILES (if enabled)
        # ═══════════════════════════════════════════════════════════════════
        if self.save_to_test_folder and metadata["redaction_count"] > 0:
            print(f"[PII] PASS 3: Saving to test files...")
            self._save_redaction_info(filename, metadata, text, redacted_text)
            # Return early to avoid wasting tokens on LLM processing during masking verification
            metadata["test_mode"] = True
            metadata["message"] = "Test mode: Masking verification complete. Stopped before LLM processing."
            print(f"[PII] PASS 3 Complete: Test files saved")
            return redacted_text, metadata
        
        return redacted_text, metadata
    
    def _save_redaction_info(
        self, 
        filename: str, 
        metadata: Dict, 
        original_text: str, 
        redacted_text: str
    ):
        """Save redaction information to test folder for verification."""
        
        # Increment counter for simple naming
        self.file_counter += 1
        
        # Simple naming: test1.txt, test2.txt, etc.
        base_name = f"test{self.file_counter}"
        
        # Save metadata as JSON
        metadata_file = self.test_folder / f"{base_name}_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Save redacted text as-is (just the redacted content)
        redacted_file = self.test_folder / f"{base_name}.txt"
        with open(redacted_file, 'w', encoding='utf-8') as f:
            f.write(redacted_text)
        
        print(f"[PII] ✓ Saved redaction to: test/{base_name}.txt")
        print(f"[PII] ✓ Saved metadata to: test/{base_name}_metadata.json")


# Global instance
_redactor = None


def get_pii_redactor() -> PIIRedactor:
    """Get or create global PII redactor instance."""
    global _redactor
    if _redactor is None:
        _redactor = PIIRedactor(save_to_test_folder=False)
    return _redactor


def redact_pii_from_text(
    text: str, 
    document_type: str = "unknown",
    filename: str = "unknown.pdf"
) -> Tuple[str, Dict]:
    """
    Convenience function to redact PII from text.
    
    Parameters
    ----------
    text : str
        Original text to redact
    document_type : str
        Type of document (bill, report, prescription)
    filename : str
        Original filename for tracking
    
    Returns
    -------
    Tuple[str, Dict]
        (redacted_text, metadata_dict)
    """
    redactor = get_pii_redactor()
    return redactor.redact_text(text, document_type, filename)
