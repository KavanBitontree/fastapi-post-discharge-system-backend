"""
Enums for the application
"""
from enum import Enum


class DeviceType(str, Enum):
    """Device types for refresh tokens"""
    MOBILE = "mobile"
    DESKTOP = "desktop"


class MedicineForm(str, Enum):
    """Forms of medicine"""
    TABLET = "tablet"
    CAPSULE = "capsule"
    SYRUP = "syrup"
    INJECTION = "injection"
    DROPS = "drops"
    CREAM = "cream"
    OINTMENT = "ointment"
    INHALER = "inhaler"
    POWDER = "powder"
    OTHER = "other"