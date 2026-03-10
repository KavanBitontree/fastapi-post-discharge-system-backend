"""
services/ird_service.py
------------------------
Insurance Ready Document (IRD) Generator.

Pipeline
--------
1. Fetch discharge + patient + reports (with descriptions) + bills from DB
2. Format report descriptions into a structured clinical note
3. Call ICD-10 RAG pipeline in-process (reuses loaded embedder + Pinecone index)
4. Separate report_url / bill_url lists
5. Generate PDF using ReportLab (Python-native, no system binaries needed)
6. Upload PDF buffer to Cloudinary → ird_documents/ folder
7. Return result dict

Schema facts (from inspection):
  reports          : id, discharge_id, report_name, report_date, specimen_type,
                     status, report_url
  report_descriptions: test_name, section, normal_result, abnormal_result,
                       flag, units, reference_range_low, reference_range_high
  bills            : id, discharge_id, bill_url
  discharge_history: id, patient_id, discharge_date  (no ird_url column → skip)
  patients         : full_name, dob, gender
"""

from __future__ import annotations

import io
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import cloudinary.uploader
from sqlalchemy.orm import Session, joinedload

from core.config import settings
from models.bill import Bill
from models.discharge_history import DischargeHistory
from models.patient import Patient
from models.report import Report

logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Asia/Kolkata")


# ── Step 2: Format report descriptions into a clinical note ──────────────────

def _expand_flag(flag: str) -> str:
    """Map raw DB flag abbreviations to unambiguous clinical words."""
    f = (flag or "").strip().upper()
    mapping = {
        "H": "HIGH",
        "HH": "CRITICAL HIGH",
        "L": "LOW",
        "LL": "CRITICAL LOW",
        "A": "ABNORMAL",
        "**": "CRITICAL",
        "C": "CRITICAL",
        "POS": "POSITIVE",
        "NEG": "NEGATIVE",
        "REF": "REFERRED",
    }
    return mapping.get(f, f) or "ABNORMAL"


def _format_reports_to_clinical_text(reports: List[Report]) -> str:
    """
    Converts Report rows + ReportDescription children into a structured clinical
    note designed for the ICD-10 RAG planner.

    Structure produced:
        INVESTIGATIONS
        [report name | date | specimen per report]

        ABNORMAL RESULTS  ← prominent; planner reads this first
        [one line per flagged finding with full context]

        NORMAL / WITHIN-RANGE RESULTS  ← context only; de-emphasised
        [one line per normal finding]
    """
    # ── Section 1: Investigations header ────────────────────────────────────
    investigation_lines: List[str] = []
    for rpt in reports:
        line = rpt.report_name or "Unknown Report"
        if rpt.report_date:
            line += f" | Date: {rpt.report_date.strftime('%Y-%m-%d')}"
        if rpt.specimen_type:
            line += f" | Specimen: {rpt.specimen_type}"
        if rpt.status:
            line += f" | Status: {rpt.status}"
        investigation_lines.append(f"- {line}")

    investigations = "\n".join(investigation_lines) or "- No investigation records."

    # ── Sections 2 & 3: Abnormal vs Normal results ──────────────────────────
    abnormal_lines: List[str] = []
    normal_lines: List[str] = []

    for rpt in reports:
        report_label = rpt.report_name or "Report"
        for desc in rpt.descriptions or []:
            raw_flag = (desc.flag or "").strip()
            result = desc.abnormal_result or desc.normal_result or "N/A"

            # Build result line
            line = f"  {desc.test_name}: {result}"
            if desc.units:
                line += f" {desc.units}"
            if desc.reference_range_low and desc.reference_range_high:
                line += f" (reference range: {desc.reference_range_low}–{desc.reference_range_high})"
            if desc.section:
                line += f" | section: {desc.section}"
            line += f" | report: {report_label}"

            if raw_flag:
                flag_word = _expand_flag(raw_flag)
                line = f"  {desc.test_name}: {result}"
                if desc.units:
                    line += f" {desc.units}"
                line += f" — {flag_word}"
                if desc.reference_range_low and desc.reference_range_high:
                    line += f" (reference range: {desc.reference_range_low}–{desc.reference_range_high})"
                if desc.section:
                    line += f" | section: {desc.section}"
                line += f" | report: {report_label}"
                abnormal_lines.append(line)
            else:
                normal_lines.append(line)

    abnormal_block = (
        "ABNORMAL RESULTS (clinically significant — use these for ICD-10 coding)\n"
        + ("\n".join(abnormal_lines) if abnormal_lines else "  None")
    )
    normal_block = (
        "NORMAL / WITHIN-RANGE RESULTS (for context only)\n"
        + ("\n".join(normal_lines) if normal_lines else "  None")
    )

    return (
        f"INVESTIGATIONS\n{investigations}\n\n"
        f"{abnormal_block}\n\n"
        f"{normal_block}"
    )


# ── Step 3: ICD-10 RAG lookup (in-process, no HTTP round-trip) ───────────────

def _call_icd_lookup(clinical_note: str) -> Tuple[List[Dict[str, str]], bool]:
    """
    Runs the ICD-10 RAG pipeline directly in-process.
    Reuses the singletons (embedder + Pinecone index) already loaded by icd_routes.

    Returns:
        (icd_codes, icd_generation_failed)
        icd_codes: list of {"code": str, "title": str, "rationale": str}
    """
    try:
        from icd_rag_bot.rag.planner import plan_queries
        from icd_rag_bot.rag.retriever import retrieve_all_candidates
        from icd_rag_bot.rag.selector import select_codes
        from routes.icd_routes import _get_embedder, _get_pinecone_index

        embedder = _get_embedder()
        index = _get_pinecone_index()

        planned = plan_queries(
            note=clinical_note,
            openrouter_api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_MODEL,
        )
        merged, grouped, candidates_by_problem = retrieve_all_candidates(
            planned_problems=planned,
            index=index,
            namespace=settings.PINECONE_NAMESPACE,
            embed_model=embedder,
            top_k_per_query=50,
            max_candidates_per_problem=35,
            where=None,
            lexical_weight=0.25,
        )
        selected = select_codes(
            note=clinical_note,
            planned_problems=planned,
            merged_candidates=merged,
            candidates_by_problem=candidates_by_problem,
            openrouter_api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_MODEL,
            max_codes_per_problem=3,
        )

        codes: List[Dict[str, str]] = []
        for result in selected.get("results", []):
            for item in result.get("selected_codes", []):
                codes.append({
                    "code": item.get("code", ""),
                    "title": item.get("title", ""),
                    "rationale": item.get("rationale", ""),
                })
        return codes, False

    except Exception as exc:
        logger.error("ICD-10 lookup failed during IRD generation: %s", exc, exc_info=True)
        return [], True


# ── Step 5: PDF generation using ReportLab ───────────────────────────────────

def _generate_pdf(
    patient: Patient,
    discharge: DischargeHistory,
    icd_codes: List[Dict[str, str]],
    icd_failed: bool,
    report_links: List[str],
    bill_links: List[str],
    discharge_summary_url: Optional[str] = None,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    NAVY = colors.HexColor("#1a3a5c")

    title_style = ParagraphStyle(
        "IRDTitle", parent=styles["Heading1"],
        fontSize=16, alignment=TA_CENTER, spaceAfter=6, textColor=NAVY,
    )
    h2_style = ParagraphStyle(
        "IRDH2", parent=styles["Heading2"],
        fontSize=11, spaceBefore=14, spaceAfter=4, textColor=NAVY,
    )
    normal = styles["Normal"]
    small_style = ParagraphStyle(
        "IRDSmall", parent=normal, fontSize=8, textColor=colors.gray,
    )
    link_style = ParagraphStyle(
        "IRDLink", parent=normal, fontSize=10, textColor=colors.HexColor("#0000CC"),
    )
    warn_style = ParagraphStyle(
        "IRDWarn", parent=normal, fontSize=10, textColor=colors.red,
    )
    italic_style = ParagraphStyle(
        "IRDItalic", parent=normal, fontSize=9, leftIndent=16,
        textColor=colors.HexColor("#444444"),
    )

    now = datetime.now(TIMEZONE)
    now_str = now.strftime("%d %b %Y, %I:%M %p IST")

    story = []

    # ── HEADER ────────────────────────────────────────────────────────────────
    story.append(Paragraph("INSURANCE READY DOCUMENT (IRD)", title_style))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY))
    story.append(Spacer(1, 0.4 * cm))

    # ── PATIENT INFORMATION ───────────────────────────────────────────────────
    story.append(Paragraph("PATIENT INFORMATION", h2_style))

    dob_str = patient.dob.strftime("%d %b %Y") if patient.dob else "N/A"
    discharge_date_str = (
        discharge.discharge_date.strftime("%d %b %Y") if discharge.discharge_date else "N/A"
    )

    info_data = [
        ["Name:", patient.full_name or "N/A"],
        ["Date of Birth:", dob_str],
        ["Gender:", patient.gender or "N/A"],
        ["Discharge Date:", discharge_date_str],
        ["Generated On:", now_str],
    ]
    info_table = Table(info_data, colWidths=[4 * cm, 12 * cm])
    info_table.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    story.append(info_table)
    story.append(Spacer(1, 0.4 * cm))

    # ── ICD-10 DIAGNOSIS CODES ────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Paragraph("ICD-10 DIAGNOSIS CODES", h2_style))

    if icd_failed:
        story.append(Paragraph(
            "WARNING: ICD-10 code generation failed. Please add codes manually.",
            warn_style,
        ))
    elif not icd_codes:
        story.append(Paragraph("No ICD-10 codes were generated.", normal))
    else:
        for item in icd_codes:
            story.append(Paragraph(f"<b>{item['code']}</b> — {item['title']}", normal))


    story.append(Spacer(1, 0.4 * cm))

    # ── DISCHARGE SUMMARY ─────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Paragraph("DISCHARGE SUMMARY", h2_style))

    if discharge_summary_url:
        story.append(Paragraph(
            f'<a href="{discharge_summary_url}" color="#0000CC"><u>{discharge_summary_url}</u></a>',
            link_style,
        ))
    else:
        story.append(Paragraph("No discharge summary available.", normal))

    story.append(Spacer(1, 0.4 * cm))

    # ── MEDICAL REPORTS & DOCUMENTS ───────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Paragraph("MEDICAL REPORTS &amp; DOCUMENTS", h2_style))

    if not report_links:
        story.append(Paragraph("No report documents found.", normal))
    else:
        for n, url in enumerate(report_links, 1):
            story.append(Paragraph(
                f'Report {n}: <a href="{url}" color="#0000CC"><u>{url}</u></a>',
                link_style,
            ))
            story.append(Spacer(1, 0.1 * cm))

    story.append(Spacer(1, 0.4 * cm))

    # ── BILLS & INVOICES ──────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Paragraph("BILLS &amp; INVOICES", h2_style))

    if not bill_links:
        story.append(Paragraph("No bill documents found.", normal))
    else:
        for n, url in enumerate(bill_links, 1):
            story.append(Paragraph(
                f'Bill {n}: <a href="{url}" color="#0000CC"><u>{url}</u></a>',
                link_style,
            ))
            story.append(Spacer(1, 0.1 * cm))

    story.append(Spacer(1, 0.6 * cm))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        f"Auto-generated for insurance claim submission. "
        f"| Generated: {now_str}",
        small_style,
    ))

    doc.build(story)
    return buffer.getvalue()


# ── Step 6: Upload to Cloudinary ─────────────────────────────────────────────

def _upload_to_cloudinary(pdf_bytes: bytes, discharge_id: int, patient_id: int) -> str:
    from services.storage.cloudinary_storage import CloudinaryStorage
    try:
        result = CloudinaryStorage.upload_pdf(
            file=io.BytesIO(pdf_bytes),
            filename=f"IRD_{discharge_id}_{int(time.time())}.pdf",
            document_type="ird",
            patient_id=patient_id,
        )
        return result["secure_url"]
    except Exception as exc:
        logger.error("Cloudinary upload failed for discharge %s: %s", discharge_id, exc, exc_info=True)
        raise RuntimeError(f"PDF generation succeeded but Cloudinary upload failed: {exc}") from exc


# ── Main orchestrator ─────────────────────────────────────────────────────────

def generate_ird(discharge_id: int, db: Session) -> Dict[str, Any]:
    """
    Full IRD generation pipeline for a given discharge_id.

    Raises:
        ValueError: if discharge not found or no reports exist
        RuntimeError: if Cloudinary upload fails after PDF is generated
    """
    # Step 1: Fetch discharge + patient
    discharge: Optional[DischargeHistory] = (
        db.query(DischargeHistory)
        .filter(DischargeHistory.id == discharge_id)
        .first()
    )
    if not discharge:
        raise ValueError("Discharge record not found")

    patient: Patient = discharge.patient

    # Step 1b: Fetch reports with their descriptions (needed for clinical note)
    reports: List[Report] = (
        db.query(Report)
        .options(joinedload(Report.descriptions))
        .filter(Report.discharge_id == discharge_id)
        .all()
    )
    if not reports:
        raise ValueError(
            f"No clinical reports found for discharge ID: {discharge_id}. "
            "Cannot generate ICD-10 codes."
        )

    # Step 1c: Fetch bills
    bills: List[Bill] = (
        db.query(Bill)
        .filter(Bill.discharge_id == discharge_id)
        .all()
    )

    # Step 2: Build clinical note from report descriptions
    clinical_note = _format_reports_to_clinical_text(reports)

    # Step 3: ICD-10 lookup (never raises — returns empty + flag on failure)
    icd_codes, icd_failed = _call_icd_lookup(clinical_note)

    # Step 4: Separate Cloudinary URLs
    report_links = [r.report_url for r in reports if r.report_url]
    bill_links   = [b.bill_url for b in bills if b.bill_url]

    # Step 5: Generate PDF
    pdf_bytes = _generate_pdf(
        patient=patient,
        discharge=discharge,
        icd_codes=icd_codes,
        icd_failed=icd_failed,
        report_links=report_links,
        bill_links=bill_links,
        discharge_summary_url=discharge.discharge_summary_url,
    )

    # Step 6: Upload to Cloudinary
    ird_url = _upload_to_cloudinary(pdf_bytes, discharge_id, patient.id)

    # Step 7: discharge_history has no ird_url column → skip DB update

    # Step 8: Return result
    return {
        "success": True,
        "ird_url": ird_url,
        "icd_codes": icd_codes,
        "icd_generation_failed": icd_failed,
        "report_count": len(report_links),
        "bill_count": len(bill_links),
        "patient_name": patient.full_name,
        "discharge_date": str(discharge.discharge_date) if discharge.discharge_date else None,
    }


def generate_ird_pdf_bytes(discharge_id: int, db: Session) -> tuple[bytes, str]:
    """
    Generates only the PDF (no Cloudinary upload) — used by the preview endpoint.
    Returns (pdf_bytes, patient_name).
    """
    discharge: Optional[DischargeHistory] = (
        db.query(DischargeHistory)
        .filter(DischargeHistory.id == discharge_id)
        .first()
    )
    if not discharge:
        raise ValueError("Discharge record not found")

    patient: Patient = discharge.patient

    reports: List[Report] = (
        db.query(Report)
        .options(joinedload(Report.descriptions))
        .filter(Report.discharge_id == discharge_id)
        .all()
    )
    if not reports:
        raise ValueError(
            f"No clinical reports found for discharge ID: {discharge_id}."
        )

    bills: List[Bill] = (
        db.query(Bill)
        .filter(Bill.discharge_id == discharge_id)
        .all()
    )

    clinical_note = _format_reports_to_clinical_text(reports)
    icd_codes, icd_failed = _call_icd_lookup(clinical_note)
    report_links = [r.report_url for r in reports if r.report_url]
    bill_links   = [b.bill_url for b in bills if b.bill_url]

    pdf_bytes = _generate_pdf(
        patient=patient,
        discharge=discharge,
        icd_codes=icd_codes,
        icd_failed=icd_failed,
        report_links=report_links,
        bill_links=bill_links,
        discharge_summary_url=discharge.discharge_summary_url,
    )
    return pdf_bytes, patient.full_name or f"discharge_{discharge_id}"
