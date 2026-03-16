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
import markdown as _md_lib
from bs4 import BeautifulSoup, NavigableString, Tag


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


def _node_to_rl_xml(node):
    """
    Recursively convert a BeautifulSoup node to a ReportLab-safe XML string.
    Inline tags are mapped: strong/b -> <b>, em/i -> <i>, code -> Courier font.
    All text content is properly XML-escaped for ReportLab's Paragraph parser.
    """
    if isinstance(node, NavigableString):
        # BS4 already decoded HTML entities; re-escape for ReportLab XML
        s = str(node)
        s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return s
    if not isinstance(node, Tag):
        return ''
    inner = ''.join(_node_to_rl_xml(child) for child in node.children)
    tag = node.name
    if tag in ('strong', 'b'):
        return f'<b>{inner}</b>'
    elif tag in ('em', 'i'):
        return f'<i>{inner}</i>'
    elif tag == 'code':
        return f'<font face="Courier">{inner}</font>'
    elif tag == 'br':
        return '<br/>'
    else:
        return inner


def _normalize_md(text):
    """
    Pre-process LLM output to ensure numbered list items are on separate lines.
    LLMs often return inline numbered lists like "text 2. Next item 3. Another"
    which markdown cannot parse as a list without explicit newlines.
    Only splits before items that start with a capital letter to avoid breaking
    mid-sentence numbers like "take 2.5 mg" or "in 2 weeks".
    """
    if not text:
        return text
    # Insert a blank line before numbered list markers that appear mid-line.
    # Matches: (non-newline)(spaces)(digits + period + space + Capital letter)
    text = re.sub(r'(?<!\n)([ \t]+)(\d+)\.\s+(?=[A-Z])', r'\n\2. ', text)
    return text


def _md_to_rl_xml(text):
    """
    Convert a single markdown string to a ReportLab XML inline string.
    Suitable for embedding inside a Paragraph (e.g. a list item).
    Block wrappers (<p>, <li>) are unwrapped; only inline formatting is kept.
    """
    if not text or not text.strip():
        return ''
    text = _normalize_md(text)
    html = _md_lib.markdown(text)
    soup = BeautifulSoup(html, 'html.parser')
    parts = []
    for element in soup.children:
        if isinstance(element, NavigableString):
            s = str(element).strip()
            if s:
                parts.append(s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        elif isinstance(element, Tag):
            if element.name in ('ul', 'ol'):
                for li in element.find_all('li', recursive=False):
                    parts.append(''.join(_node_to_rl_xml(child) for child in li.children))
            else:
                parts.append(''.join(_node_to_rl_xml(child) for child in element.children))
    return ' '.join(p for p in parts if p.strip())


def _md_to_flowables(text, base_style, bullet_prefix='&#8226;', limit=None):
    """
    Convert a markdown text block to a list of ReportLab Paragraph flowables.
    Each block element (p, li, heading) becomes its own Paragraph.
    Inline formatting (bold, italic, code) is converted to ReportLab XML tags.
    """
    if not text or not text.strip():
        return []
    text = _normalize_md(text)
    html = _md_lib.markdown(text)
    soup = BeautifulSoup(html, 'html.parser')
    flowables = []

    def _add(rl_xml):
        if rl_xml and rl_xml.strip():
            flowables.append(Paragraph(rl_xml, base_style))

    for element in soup.children:
        if limit and len(flowables) >= limit:
            break
        if isinstance(element, NavigableString):
            s = str(element).strip()
            if s:
                _add(s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        elif isinstance(element, Tag):
            name = element.name
            if name == 'ol':
                for idx, li in enumerate(element.find_all('li', recursive=False), start=1):
                    inner = ''.join(_node_to_rl_xml(child) for child in li.children)
                    _add(f'<b>{idx}.</b> {inner}')
                    if limit and len(flowables) >= limit:
                        break
            elif name == 'ul':
                for li in element.find_all('li', recursive=False):
                    inner = ''.join(_node_to_rl_xml(child) for child in li.children)
                    _add(f'{bullet_prefix} {inner}')
                    if limit and len(flowables) >= limit:
                        break
            elif name == 'p':
                inner = ''.join(_node_to_rl_xml(child) for child in element.children)
                _add(inner)
            elif name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                inner = ''.join(_node_to_rl_xml(child) for child in element.children)
                _add(f'<b>{inner}</b>')
            else:
                inner = ''.join(_node_to_rl_xml(child) for child in element.children)
                _add(inner)

    return flowables[:limit] if limit else flowables


def generate_patient_friendly_pdf(report_data: dict) -> BytesIO:
    """
    Generate an attractive, patient-friendly PDF from report data.
    Optimized for 1.5-2 pages with compact, point-wise formatting.
    
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
    
    # Create PDF in memory with tighter margins for 1.5-2 page format
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        rightMargin=0.4*inch,
        leftMargin=0.4*inch,
        topMargin=0.4*inch,
        bottomMargin=0.4*inch,
        title="Patient-Friendly Medical Report"
    )
    
    # Create styles
    styles = getSampleStyleSheet()
    
    # Main title style - Compact, centered, professional
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#0052CC'),
        spaceAfter=1,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        leading=18
    )
    
    # Subtitle style - Compact
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#666666'),
        spaceAfter=4,
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique'
    )
    
    # Section heading style - Bold, colored, compact
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#FFFFFF'),
        spaceAfter=6,
        spaceBefore=6,
        fontName='Helvetica-Bold',
        leading=14
    )
    
    # Body text style - Very compact, readable
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['BodyText'],
        fontSize=9,
        alignment=TA_LEFT,
        spaceAfter=3,
        leading=10,
        textColor=colors.HexColor('#333333')
    )
    
    # Bullet point style - Very compact
    bullet_style = ParagraphStyle(
        'BulletStyle',
        parent=styles['BodyText'],
        fontSize=9,
        leftIndent=15,
        spaceAfter=2,
        leading=10,
        textColor=colors.HexColor('#333333')
    )
    
    # Medication style - Very compact
    med_style = ParagraphStyle(
        'MedicationStyle',
        parent=styles['BodyText'],
        fontSize=8.5,
        leftIndent=15,
        spaceAfter=2,
        leading=9,
        textColor=colors.HexColor('#1a1a1a'),
        fontName='Helvetica'
    )
    
    # Precaution style - Orange/amber, bold, very compact
    precaution_style = ParagraphStyle(
        'PrecautionStyle',
        parent=styles['BodyText'],
        fontSize=8.5,
        leftIndent=15,
        spaceAfter=2,
        textColor=colors.HexColor('#E65100'),
        fontName='Helvetica-Bold',
        leading=9
    )
    
    # Warning style - Red, bold, very compact
    warning_style = ParagraphStyle(
        'WarningStyle',
        parent=styles['BodyText'],
        fontSize=9,
        leftIndent=15,
        spaceAfter=2,
        textColor=colors.HexColor('#D32F2F'),
        fontName='Helvetica-Bold',
        leading=10
    )
    
    # Build PDF content
    story = []
    
    # ===== HEADER SECTION =====
    story.append(Paragraph("PATIENT MEDICAL REPORT", title_style))
    story.append(Spacer(1, 0.02*inch))
    
    # Date and info
    today = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(f"Generated on {today}", subtitle_style))
    story.append(Spacer(1, 0.06*inch))
    
    # ===== SUMMARY SECTION =====
    # Create colored header for summary
    summary_header_data = [['HOSPITAL STAY OVERVIEW']]
    summary_header_table = Table(summary_header_data, colWidths=[7.2*inch])
    summary_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0052CC')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_header_table)
    story.append(Spacer(1, 0.04*inch))
    
    # Summary text - parse markdown and render with inline formatting preserved
    # NOTE: Medications should ONLY appear in the MEDICATIONS section, not here
    summary_text = clean_text(report_data.get('summary', ''))
    for para in _md_to_flowables(summary_text, bullet_style, bullet_prefix='&#8226;', limit=5):
        story.append(para)
    story.append(Spacer(1, 0.06*inch))
    
    # ===== KEY POINTS SECTION =====
    key_points_header_data = [['KEY POINTS']]
    key_points_header_table = Table(key_points_header_data, colWidths=[7.2*inch])
    key_points_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1976D2')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(key_points_header_table)
    story.append(Spacer(1, 0.03*inch))
    
    for point in report_data.get('key_points', [])[:4]:  # Limit to 4 key points
        rl_xml = _md_to_rl_xml(clean_text(point))
        if rl_xml:
            story.append(Paragraph(f'• {rl_xml}', bullet_style))
    story.append(Spacer(1, 0.06*inch))
    
    # ===== MEDICATIONS SECTION =====
    meds_header_data = [['MEDICATIONS']]
    meds_header_table = Table(meds_header_data, colWidths=[7.2*inch])
    meds_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#388E3C')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(meds_header_table)
    story.append(Spacer(1, 0.03*inch))
    
    for med in report_data.get('medications', [])[:6]:  # Limit to 6 medications
        rl_xml = _md_to_rl_xml(clean_text(med))
        if rl_xml:
            story.append(Paragraph(f'- {rl_xml}', med_style))
    story.append(Spacer(1, 0.06*inch))
    
    # ===== PRECAUTIONS SECTION =====
    precautions = report_data.get('precautions', [])
    if precautions:
        precautions_header_data = [['IMPORTANT PRECAUTIONS']]
        precautions_header_table = Table(precautions_header_data, colWidths=[7.2*inch])
        precautions_header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#E65100')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(precautions_header_table)
        story.append(Spacer(1, 0.03*inch))
        
        for precaution in precautions[:8]:  # Limit to 8 precautions
            rl_xml = _md_to_rl_xml(clean_text(precaution))
            if rl_xml:
                story.append(Paragraph(f'⚠ {rl_xml}', precaution_style))
        story.append(Spacer(1, 0.06*inch))
    
    # ===== FOLLOW-UP INSTRUCTIONS SECTION =====
    followup_header_data = [['NEXT STEPS']]
    followup_header_table = Table(followup_header_data, colWidths=[7.2*inch])
    followup_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F57C00')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(followup_header_table)
    story.append(Spacer(1, 0.03*inch))
    
    followup_text = clean_text(report_data.get('follow_up_instructions', ''))
    for para in _md_to_flowables(followup_text, bullet_style, bullet_prefix='&#8226;', limit=4):
        story.append(para)
    story.append(Spacer(1, 0.06*inch))
    
    # ===== WARNING SIGNS SECTION =====
    warning_header_data = [['SEEK IMMEDIATE HELP IF']]
    warning_header_table = Table(warning_header_data, colWidths=[7.2*inch])
    warning_header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#D32F2F')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(warning_header_table)
    story.append(Spacer(1, 0.03*inch))
    
    for sign in report_data.get('warning_signs', [])[:5]:  # Limit to 5 warning signs
        rl_xml = _md_to_rl_xml(clean_text(sign))
        if rl_xml:
            story.append(Paragraph(f'! {rl_xml}', warning_style))
    
    story.append(Spacer(1, 0.08*inch))
    
    # ===== FOOTER =====
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=7,
        textColor=colors.HexColor('#999999'),
        alignment=TA_CENTER,
        spaceAfter=1
    )
    
    story.append(Paragraph("_" * 70, footer_style))
    story.append(Spacer(1, 0.02*inch))
    story.append(Paragraph(
        "This is a patient-friendly summary. Consult your healthcare provider for questions.",
        footer_style
    ))
    
    # Build PDF
    doc.build(story)
    
    # Reset buffer position to beginning
    pdf_buffer.seek(0)
    
    return pdf_buffer
