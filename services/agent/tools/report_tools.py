"""
services/agent/tools/report_tools.py
--------------------------------------
SQLAlchemy-based tools for the Reports specialist node.
All tools receive patient_id + db session via closure (injected at graph build time).

report_descriptions columns exposed to the LLM in every tool output:
  test_name, section, result value (normal_result / abnormal_result),
  result_status (Normal / Abnormal), units, flag (H=High / L=Low / **=Critical),
  reference_range_low, reference_range_high, report_name, report_date
"""

from __future__ import annotations
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from models.report import Report
from models.report_description import ReportDescription


# ── Shared row formatter ──────────────────────────────────────────────────────

def _desc_line(d: ReportDescription, report: Report | None = None) -> str:
    """
    Render a single ReportDescription row into a rich text line that exposes
    every meaningful column so the LLM can answer any question about the data.

    Output format:
      • {test_name} [{section}] — Result: {value} {units} | Status: Normal/Abnormal
        Flag: H (above normal range) | Ref: {low}–{high} {units} | From: {report_name} ({date})
    """
    value  = d.normal_result or d.abnormal_result or "N/A"
    status = "Normal" if d.normal_result and not d.flag else ("Abnormal" if d.abnormal_result or d.flag else "N/A")

    flag_str = ""
    if d.flag:
        label = {"H": "above normal range", "L": "below normal range", "**": "critical value"}.get(
            d.flag.strip(), "flagged"
        )
        flag_str = f" | Flag: {d.flag} ({label})"

    ref_str = ""
    if d.reference_range_low and d.reference_range_high:
        ref_str = f" | Ref range: {d.reference_range_low}–{d.reference_range_high} {d.units or ''}".rstrip()

    section_str = f" [{d.section}]" if d.section else ""

    source_str = ""
    if report:
        date_str = report.report_date.strftime("%d %b %Y") if report.report_date else "unknown date"
        source_str = f" | From: {report.report_name} ({date_str})"

    return (
        f"  • {d.test_name}{section_str} — "
        f"Result: {value} {d.units or ''} | Status: {status}"
        f"{flag_str}{ref_str}{source_str}"
    ).rstrip()


def build_report_tools(patient_id: int, db: Session) -> list:
    """
    Factory — returns tool list bound to this patient's session.
    Called once per request when building the graph.
    """

    # Pre-build a report lookup so section/test-name searches can attach report context cheaply
    def _report_map() -> dict[int, Report]:
        rows = db.query(Report).filter(Report.patient_id == patient_id).all()
        return {r.id: r for r in rows}

    @tool
    def get_all_reports() -> str:
        """
        Get a summary list of all reports for the patient.
        Use when the patient asks 'what reports do I have?' or 'show my reports'.
        """
        reports = (
            db.query(Report)
            .filter(Report.patient_id == patient_id)
            .order_by(Report.report_date.desc())
            .all()
        )
        if not reports:
            return "No reports found for this patient."

        lines = ["Patient's reports:"]
        for r in reports:
            date_str    = r.report_date.strftime("%d %b %Y") if r.report_date else "Date unknown"
            collect_str = r.collection_date.strftime("%d %b %Y") if r.collection_date else "N/A"
            lines.append(
                f"  • [{r.id}] {r.report_name} — Reported: {date_str} | "
                f"Collected: {collect_str} | Status: {r.status or 'N/A'} | "
                f"Specimen: {r.specimen_type or 'N/A'}"
            )
        return "\n".join(lines)

    @tool
    def get_report_details(report_name: str) -> str:
        """
        Get full test results by report name, section name, OR individual test/analyte name.
        Searches three levels automatically: report name → section → test name.
        Every result row includes: test name, section, result value, normal/abnormal status,
        flag with explanation, reference range, units, and which report it came from.

        Args:
            report_name: Report name (e.g. 'CBC', 'Lipid Panel'),
                         section name (e.g. 'haematology', 'biochemistry'),
                         or individual test/analyte name (e.g. 'neutrophil', 'haemoglobin',
                         'platelet', 'glucose', 'WBC', 'creatinine')
        """
        # ── 1. Try matching by report name ───────────────────────────────────
        reports = (
            db.query(Report)
            .filter(
                Report.patient_id == patient_id,
                Report.report_name.ilike(f"%{report_name}%"),
            )
            .order_by(Report.report_date.desc())
            .all()
        )
        if reports:
            output = []
            for r in reports:
                date_str = r.report_date.strftime("%d %b %Y") if r.report_date else "Unknown date"
                collect  = r.collection_date.strftime("%d %b %Y") if r.collection_date else "N/A"
                output.append(
                    f"Report: {r.report_name} | Date: {date_str} | "
                    f"Collected: {collect} | Status: {r.status or 'N/A'} | "
                    f"Specimen: {r.specimen_type or 'N/A'}"
                )
                descs = db.query(ReportDescription).filter(ReportDescription.report_id == r.id).all()
                if descs:
                    for d in descs:
                        output.append(_desc_line(d))
                else:
                    output.append("  No test details available.")
                output.append("")
            return "\n".join(output)

        rmap = _report_map()

        # ── 2. Try matching by section name ──────────────────────────────────
        section_rows = (
            db.query(ReportDescription)
            .join(Report, Report.id == ReportDescription.report_id)
            .filter(
                Report.patient_id == patient_id,
                ReportDescription.section.ilike(f"%{report_name}%"),
            )
            .order_by(Report.report_date.desc())
            .all()
        )
        if section_rows:
            lines = [f"Results for section: {report_name.upper()}"]
            for d in section_rows:
                lines.append(_desc_line(d, rmap.get(d.report_id)))
            return "\n".join(lines)

        # ── 3. Try matching by individual test name ───────────────────────────
        test_rows = (
            db.query(ReportDescription)
            .join(Report, Report.id == ReportDescription.report_id)
            .filter(
                Report.patient_id == patient_id,
                ReportDescription.test_name.ilike(f"%{report_name}%"),
            )
            .order_by(Report.report_date.desc())
            .all()
        )
        if test_rows:
            lines = [f"Results matching test: {report_name.upper()}"]
            for d in test_rows:
                lines.append(_desc_line(d, rmap.get(d.report_id)))
            return "\n".join(lines)

        return f"No report, section, or test matching '{report_name}' found."

    @tool
    def get_abnormal_results() -> str:
        """
        Get all abnormal or flagged test results across all reports.
        Use when patient asks 'are any of my results abnormal?', 'what was high/low?',
        'any critical values?', 'what should I be concerned about?'
        Includes: test name, section, result value, flag with explanation,
        reference range, and which report it came from.
        """
        flagged = (
            db.query(ReportDescription)
            .join(Report, Report.id == ReportDescription.report_id)
            .filter(
                Report.patient_id == patient_id,
                ReportDescription.flag.isnot(None),
                ReportDescription.flag != "",
            )
            .order_by(Report.report_date.desc())
            .all()
        )
        if not flagged:
            return "All test results are within normal ranges. No flagged values found."

        rmap = _report_map()
        lines = [f"Flagged / abnormal results ({len(flagged)} found):"]
        for d in flagged:
            lines.append(_desc_line(d, rmap.get(d.report_id)))
        return "\n".join(lines)

    @tool
    def get_latest_report(report_name: str) -> str:
        """
        Get the most recent report of a specific type including all its test results.
        Use when patient asks 'when was my last CBC?', 'my latest blood test', 'most recent results'.

        Args:
            report_name: Report type to search for (e.g. 'CBC', 'lipid', 'full blood count')
        """
        report = (
            db.query(Report)
            .filter(
                Report.patient_id == patient_id,
                Report.report_name.ilike(f"%{report_name}%"),
            )
            .order_by(Report.report_date.desc())
            .first()
        )
        if not report:
            return f"No report matching '{report_name}' found."

        date_str = report.report_date.strftime("%d %b %Y") if report.report_date else "Unknown"
        collect  = report.collection_date.strftime("%d %b %Y") if report.collection_date else "Unknown"
        lines = [
            f"Latest {report.report_name}:",
            f"  Report date   : {date_str}",
            f"  Collection    : {collect}",
            f"  Status        : {report.status or 'N/A'}",
            f"  Specimen type : {report.specimen_type or 'N/A'}",
            "  Test results:",
        ]
        descs = db.query(ReportDescription).filter(ReportDescription.report_id == report.id).all()
        if descs:
            for d in descs:
                lines.append(_desc_line(d))
        else:
            lines.append("  No test details available.")
        return "\n".join(lines)

    @tool
    def get_results_by_section(section_name: str) -> str:
        """
        Get all test results belonging to a specific section/category across all reports.
        Use when the patient asks for everything in a section like 'all haematology results',
        'everything in biochemistry', 'full blood bank section'.
        Each result includes: test name, result value, status, flag with explanation,
        reference range, units, and which report it came from.

        Args:
            section_name: Section name or partial match (e.g. 'haematology', 'biochemistry',
                          'blood bank', 'lipid', 'liver', 'kidney', 'thyroid', 'urine').
                          Case-insensitive.
        """
        rows = (
            db.query(ReportDescription)
            .join(Report, Report.id == ReportDescription.report_id)
            .filter(
                Report.patient_id == patient_id,
                ReportDescription.section.ilike(f"%{section_name}%"),
            )
            .order_by(Report.report_date.desc())
            .all()
        )
        if not rows:
            return f"No results found for section '{section_name}'."

        rmap = _report_map()
        lines = [f"Results for section: {section_name.upper()} ({len(rows)} tests found)"]
        for d in rows:
            lines.append(_desc_line(d, rmap.get(d.report_id)))
        return "\n".join(lines)

    @tool
    def get_all_report_data() -> str:
        """
        Get the COMPLETE lab report history — every report with every test result, section,
        flag, reference range, and status. Use for broad requests: 'summarize all my reports',
        'full overview of my results', 'complete lab history', 'how are my tests overall?'
        """
        reports = (
            db.query(Report)
            .filter(Report.patient_id == patient_id)
            .order_by(Report.report_date.desc())
            .all()
        )
        if not reports:
            return "No reports found for this patient."

        sections = []
        for r in reports:
            date_str = r.report_date.strftime("%d %b %Y") if r.report_date else "Date unknown"
            collect  = r.collection_date.strftime("%d %b %Y") if r.collection_date else "N/A"
            header = (
                f"Report: {r.report_name} | Date: {date_str} | "
                f"Collected: {collect} | Status: {r.status or 'N/A'} | "
                f"Specimen: {r.specimen_type or 'N/A'}"
            )
            descs = db.query(ReportDescription).filter(ReportDescription.report_id == r.id).all()
            if descs:
                rows = [_desc_line(d) for d in descs]
                sections.append(header + "\n  Test results:\n" + "\n".join(rows))
            else:
                sections.append(header + "\n  No test details available.")

        return "=== Complete Report History ===\n\n" + "\n\n".join(sections)

    return [get_all_reports, get_report_details, get_abnormal_results, get_latest_report, get_all_report_data, get_results_by_section]