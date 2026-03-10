"""
pdf_generator.py
----------------
Generates attractive, patient-friendly PDF reports from patient-friendly report data.
Designed for easy reading and understanding by patients.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from io import BytesIO
from datetime import datetime
import re


def clean_text(text):
    """
    Clean text by removing problematic characters and emojis.
    Replaces special characters that cause rendering issues.
    """
    if not text:
        return ""
    
    # Remove emoji and special unicode characters
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    
    # Replace common problematic characters
    replacements = {
        '–': '-',  # en dash to hyphen
        '—': '-',  # em dash to hyphen
        ''': "'",  # curly quote to straight quote
        ''': "'",  # curly quote to straight quote
        '"': '"',  # curly double quote to straight quote
        '"': '"',  # curly double quote to straight quote
        '…': '...',  # ellipsis to three dots
        '•': '*',  # bullet to asterisk
        '‑': '-',  # non-breaking hyphen to hyphen
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text


def generate_patient_friendly_pdf(report_data: dict) -> BytesIO:
    """
    Generate an attractive, patient-friendly PDF from report data.
    
    Parameters
    ----------
    report_data : dict
        Dictionary with keys: summary, key_points, medications, 
        follow_up_instructions, warning_signs
    
    Returns
    -------
    BytesIO
        PDF file in memory (can be returned as response or saved)
    """
    
    # Create PDF in memory
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch,
        title="Patient-Friendly Medical Report"
    )
    
    # Create styles
    styles = getSampleStyleSheet()
    
    # Main title style - Large, centered, professional
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#0052CC'),
        spaceAfter=3,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        leading=22
    )
    
    # Subtitle style
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#666666'),
        spaceAfter=8,
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique'
    )
    
    # Section heading style - Bold, colored
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#FFFFFF'),
        spaceAfter=10,
        spaceBefore=12,
        fontName='Helvetica-Bold',
        leading=16
    )
    
    # Body text style - Compact, readable
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['BodyText'],
        fontSize=10,
        alignment=TA_LEFT,
        spaceAfter=6,
        leading=12,
        textColor=colors.HexColor('#333333')
    )
    
    # Bullet point style - Compact
    bullet_style = ParagraphStyle(
        'BulletStyle',
        parent=styles['BodyText'],
        fontSize=10,
        leftIndent=20,
        spaceAfter=5,
        leading=12,
        textColor=colors.HexColor('#333333')
    )
    
    # Medication style - Compact
    med_style = ParagraphStyle(
        'MedicationStyle',
        parent=styles['BodyText'],
        fontSize=9.5,
        leftIndent=20,
        spaceAfter=4,
        leading=11,
        textColor=colors.HexColor('#1a1a1a'),
        fontName='Helvetica'
    )
    
    # Warning style - Red, bold, compact
    warning_style = ParagraphStyle(
        'WarningStyle',
        parent=styles['BodyText'],
        fontSize=10,
        leftIndent=20,
        spaceAfter=5,
        textColor=colors.HexColor('#D32F2F'),
        fontName='Helvetica-Bold',
        leading=12
    )
    
    # Build PDF content
    story = []
    
    # ===== HEADER SECTION =====
    story.append(Paragraph("PATIENT MEDICAL REPORT", title_style))
    story.append(Spacer(1, 0.05*inch))
    
    # Date and info
    today = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(f"Generated on {today}", subtitle_style))
    story.append(Spacer(1, 0.12*inch))
    
    # ===== SUMMARY SECTION =====
    # Create colored header for summary
    summary_header_data = [['HOSPITAL STAY OVERVIEW']]
    summary_header_table = Table(summary_header_data, colWidths=[7.0*inch])
    summary_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0052CC')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(summary_header_table)
    story.append(Spacer(1, 0.08*inch))
    
    # Summary text - cleaned and converted to bullet points
    summary_text = clean_text(report_data.get('summary', ''))
    # Extract key sentences from summary
    sentences = [s.strip() for s in summary_text.split('.') if s.strip() and len(s.strip()) > 20]
    for i, sentence in enumerate(sentences[:6]):  # Limit to 6 key points (was 4)
        story.append(Paragraph(f"* {sentence}.", bullet_style))
    story.append(Spacer(1, 0.12*inch))
    
    # ===== KEY POINTS SECTION =====
    key_points_header_data = [['KEY POINTS']]
    key_points_header_table = Table(key_points_header_data, colWidths=[7.0*inch])
    key_points_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1976D2')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(key_points_header_table)
    story.append(Spacer(1, 0.06*inch))
    
    for point in report_data.get('key_points', [])[:5]:  # Limit to 5 key points (was 3)
        cleaned_point = clean_text(point)
        story.append(Paragraph(f"* {cleaned_point}", bullet_style))
    story.append(Spacer(1, 0.12*inch))
    
    # ===== MEDICATIONS SECTION =====
    meds_header_data = [['MEDICATIONS']]
    meds_header_table = Table(meds_header_data, colWidths=[7.0*inch])
    meds_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#388E3C')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(meds_header_table)
    story.append(Spacer(1, 0.06*inch))
    
    for med in report_data.get('medications', [])[:8]:  # Limit to 8 medications (was 5)
        cleaned_med = clean_text(med)
        story.append(Paragraph(f"- {cleaned_med}", med_style))
    story.append(Spacer(1, 0.12*inch))
    
    # ===== FOLLOW-UP INSTRUCTIONS SECTION =====
    followup_header_data = [['NEXT STEPS']]
    followup_header_table = Table(followup_header_data, colWidths=[7.0*inch])
    followup_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F57C00')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(followup_header_table)
    story.append(Spacer(1, 0.06*inch))
    
    followup_text = clean_text(report_data.get('follow_up_instructions', ''))
    # Extract key sentences from follow-up
    followup_sentences = [s.strip() for s in followup_text.split('.') if s.strip() and len(s.strip()) > 15]
    for sentence in followup_sentences[:5]:  # Limit to 5 key steps (was 3)
        story.append(Paragraph(f"* {sentence}.", bullet_style))
    story.append(Spacer(1, 0.12*inch))
    
    # ===== WARNING SIGNS SECTION =====
    warning_header_data = [['SEEK IMMEDIATE HELP IF']]
    warning_header_table = Table(warning_header_data, colWidths=[7.0*inch])
    warning_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#D32F2F')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(warning_header_table)
    story.append(Spacer(1, 0.06*inch))
    
    for sign in report_data.get('warning_signs', [])[:6]:  # Limit to 6 warning signs (was 4)
        cleaned_sign = clean_text(sign)
        story.append(Paragraph(f"! {cleaned_sign}", warning_style))
    
    story.append(Spacer(1, 0.15*inch))
    
    # ===== FOOTER =====
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#999999'),
        alignment=TA_CENTER,
        spaceAfter=2
    )
    
    story.append(Paragraph("_" * 70, footer_style))
    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph(
        "This is a patient-friendly summary. Consult your healthcare provider for questions.",
        footer_style
    ))
    
    # Build PDF
    doc.build(story)
    
    # Reset buffer position to beginning
    pdf_buffer.seek(0)
    
    return pdf_buffer
