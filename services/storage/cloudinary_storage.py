"""
Cloudinary Storage Service
---------------------------
Handles PDF and image uploads to Cloudinary with proper organization.

Separation of concerns:
- Upload files to Cloudinary
- Generate secure URLs
- Delete files when needed
- Organize by document type (reports, bills, prescriptions)
"""

import cloudinary
import cloudinary.uploader
from typing import Optional, BinaryIO
from datetime import datetime
from pathlib import Path

from core.config import settings

# Configure Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)


class CloudinaryStorage:
    """Cloudinary storage service for medical documents."""
    
    # Folder structure in Cloudinary
    FOLDERS = {
        "report": "medical_documents/reports",
        "bill": "medical_documents/bills",
        "prescription": "medical_documents/prescriptions",
    }
    
    @classmethod
    def upload_pdf(
        cls,
        file: BinaryIO,
        filename: str,
        document_type: str,
        patient_id: int,
    ) -> dict:
        """
        Upload PDF to Cloudinary.
        
        Parameters
        ----------
        file : BinaryIO
            File object to upload
        filename : str
            Original filename
        document_type : str
            Type of document: 'report', 'bill', or 'prescription'
        patient_id : int
            Patient ID for organization
            
        Returns
        -------
        dict
            Upload result with 'url', 'public_id', 'secure_url'
        """
        if document_type not in cls.FOLDERS:
            raise ValueError(f"Invalid document_type: {document_type}")
        
        try:
            # Generate unique public_id
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = Path(filename).stem.replace(" ", "_")
            # Don't include folder in public_id since we're already specifying it separately
            public_id = f"patient_{patient_id}/{timestamp}_{safe_filename}"
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                file,
                public_id=public_id,
                resource_type="raw",  # For PDFs
                folder=cls.FOLDERS[document_type],
                tags=[f"patient_{patient_id}", document_type, "medical_document"],
                context=f"patient_id={patient_id}|document_type={document_type}|filename={filename}",
            )
            
            return {
                "url": result["url"],
                "secure_url": result["secure_url"],
                "public_id": result["public_id"],
                "bytes": result["bytes"],
                "format": result.get("format", "pdf"),  # Default to 'pdf' for raw files
                "resource_type": result["resource_type"],
            }
        except Exception as e:
            raise Exception(f"Cloudinary upload failed: {str(e)}")
    
    @classmethod
    def upload_image(
        cls,
        file: BinaryIO,
        filename: str,
        document_type: str,
        patient_id: int,
    ) -> dict:
        """
        Upload image to Cloudinary.
        
        Parameters
        ----------
        file : BinaryIO
            Image file object to upload
        filename : str
            Original filename
        document_type : str
            Type of document: 'report', 'bill', or 'prescription'
        patient_id : int
            Patient ID for organization
            
        Returns
        -------
        dict
            Upload result with 'url', 'public_id', 'secure_url'
        """
        if document_type not in cls.FOLDERS:
            raise ValueError(f"Invalid document_type: {document_type}")
        
        try:
            # Generate unique public_id
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = Path(filename).stem.replace(" ", "_")
            # Don't include folder in public_id since we're already specifying it separately
            public_id = f"patient_{patient_id}/{timestamp}_{safe_filename}"
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                file,
                public_id=public_id,
                resource_type="image",  # For images
                folder=cls.FOLDERS[document_type],
                tags=[f"patient_{patient_id}", document_type, "medical_document", "image"],
                context=f"patient_id={patient_id}|document_type={document_type}|filename={filename}",
            )
            
            return {
                "url": result["url"],
                "secure_url": result["secure_url"],
                "public_id": result["public_id"],
                "bytes": result["bytes"],
                "format": result["format"],
                "resource_type": result["resource_type"],
                "width": result.get("width"),
                "height": result.get("height"),
            }
        except Exception as e:
            raise Exception(f"Cloudinary upload failed: {str(e)}")
    
    @classmethod
    def delete_file(cls, public_id: str, resource_type: str = "raw") -> dict:
        """
        Delete file from Cloudinary.
        
        Parameters
        ----------
        public_id : str
            Cloudinary public_id of the file
        resource_type : str
            'raw' for PDFs, 'image' for images
            
        Returns
        -------
        dict
            Deletion result
        """
        result = cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
        )
        return result
    
    @classmethod
    def get_file_url(cls, public_id: str, resource_type: str = "raw") -> str:
        """
        Get secure URL for a file.
        
        Parameters
        ----------
        public_id : str
            Cloudinary public_id
        resource_type : str
            'raw' for PDFs, 'image' for images
            
        Returns
        -------
        str
            Secure URL
        """
        if resource_type == "image":
            return cloudinary.CloudinaryImage(public_id).build_url(secure=True)
        else:
            return cloudinary.CloudinaryResource(public_id).build_url(
                resource_type="raw",
                secure=True
            )


# Convenience functions
def upload_medical_pdf(
    file: BinaryIO,
    filename: str,
    document_type: str,
    patient_id: int,
) -> dict:
    """Upload medical PDF to Cloudinary."""
    return CloudinaryStorage.upload_pdf(file, filename, document_type, patient_id)


def upload_medical_image(
    file: BinaryIO,
    filename: str,
    document_type: str,
    patient_id: int,
) -> dict:
    """Upload medical image to Cloudinary."""
    return CloudinaryStorage.upload_image(file, filename, document_type, patient_id)


def delete_medical_file(public_id: str, resource_type: str = "raw") -> dict:
    """Delete medical file from Cloudinary."""
    return CloudinaryStorage.delete_file(public_id, resource_type)
