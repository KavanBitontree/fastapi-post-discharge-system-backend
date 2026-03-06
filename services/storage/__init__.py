"""
Storage Services
----------------
File storage services for medical documents.

Currently supports:
- Cloudinary: Cloud storage for PDFs and images
"""

from .cloudinary_storage import (
    CloudinaryStorage,
    upload_medical_pdf,
    upload_medical_image,
    delete_medical_file,
)

__all__ = [
    "CloudinaryStorage",
    "upload_medical_pdf",
    "upload_medical_image",
    "delete_medical_file",
]
