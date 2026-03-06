"""
Report Pydantic Schemas
-----------------------
Pydantic models for LLM-based report extraction.
Used for structured output validation.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class TestResult(BaseModel):
    """Individual test result from a medical report."""
    test_name: str = Field(description="Name of the test or measurement")
    section: Optional[str] = Field(None, description="Section or category of the test")
    normal_result: Optional[str] = Field(None, description="Result value when within normal range")
    abnormal_result: Optional[str] = Field(None, description="Result value when outside normal range")
    flag: Optional[str] = Field(None, description="Flag: 'H' (High), 'L' (Low), '*' or '**' (Critical)")
    units: Optional[str] = Field(None, description="Unit of measurement")
    reference_range_low: Optional[str] = Field(None, description="Lower bound of reference range")
    reference_range_high: Optional[str] = Field(None, description="Upper bound of reference range")


class ReportHeader(BaseModel):
    """Header information from a medical report."""
    report_name: str = Field(description="Name/title of the report")
    report_date: Optional[str] = Field(None, description="Report date in MM/DD/YYYY HH:MM or MM/DD/YYYY")
    collection_date: Optional[str] = Field(None, description="Sample collection date/time")
    received_date: Optional[str] = Field(None, description="Sample received date/time")
    specimen_type: Optional[str] = Field(None, description="Type of specimen")
    status: Optional[str] = Field(None, description="Report status")


class ValidatedReport(BaseModel):
    """Complete validated medical report."""
    header: ReportHeader
    test_results: List[TestResult]
