"""PDF export of persisted report data; no model calls or external requests."""
from io import BytesIO
from decimal import Decimal
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def render_report_pdf(report: dict, currency: str | None = None) -> bytes:
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="FinBody", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=9))
    green = colors.HexColor("#204b3b")
    styles['Title'].textColor = green
    styles['Heading2'].textColor = green
    story = []
    def para(text, style="FinBody"):
        story.append(Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style]))
    def money(value):
        return f"{Decimal(str((value or {}).get('amount', '0'))):,.2f}"
    para("FinAgent | Financial Report", "Title")
    para(f"Generated: {report.get('generated_at', '')} | Report: {report.get('report_version', '')}")
    sections = report.get('sections') or {}
    para("Your money at a glance", "Heading2")
    para(sections.get('summary') or "This report combines your saved analysis and budget. Any missing information is listed below.")
    rows = sections.get('budget_overview') or []
    if rows:
        current = sum(Decimal(str(row['current_monthly_spend']['amount'])) for row in rows)
        planned = sum(Decimal(str(row['monthly_limit']['amount'])) for row in rows)
        para(f"The categories below currently cost {current:,.2f} per month. The proposed limits total {planned:,.2f}, a change of {current-planned:,.2f} per month. Amounts are in {escape(currency) if currency else "the source profile currency"}.")
        data = [["Category", "Current / month", "Budget / month", "Priority"]]
        for row in rows:
            data.append([Paragraph(escape(row['category'].replace('_',' ').title()), styles['FinBody']), money(row['current_monthly_spend']), money(row['monthly_limit']), "Essential" if row['is_essential'] else "Flexible"])
        table = Table(data, colWidths=[160, 105, 105, 100], repeatRows=1)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),green), ('TEXTCOLOR',(0,0),(-1,0),colors.white), ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#f5f3e9'),colors.white]), ('VALIGN',(0,0),(-1,-1),'TOP'), ('PADDING',(0,0),(-1,-1),8), ('FONTSIZE',(0,0),(-1,-1),9)]))
        story.extend([table, Spacer(1,14)])
    for key,title in [('spending_insights','Your spending'),('savings_opportunities','Ways to save'),('risk_considerations','Things to keep in mind'),('assumptions','Assumptions'),('limitations','What is missing')]:
        items = sections.get(key) or []
        if items:
            para(title, 'Heading2')
            for item in dict.fromkeys(items): para(item)
    issues = report.get('validation_issues') or []
    if issues:
        para('Checks and missing information', 'Heading2')
        friendly = {'RESEARCH_MISSING':'No research was included. This report does not contain verified web research.', 'ANALYSIS_PARTIAL':'Some analysis features were unavailable. Review the source analysis before relying on this report.', 'UNRESOLVED_DATA_GAPS':'Some transaction details or history are missing. The results reflect only the data you supplied.'}
        for issue in issues: para(friendly.get(issue['code'], issue.get('message', issue['code'])))
    sources = sections.get('sources') or report.get('sources') or []
    if sources:
        para('Research sources', 'Heading2')
        for source in sources:
            para(f"{source.get('title','Source')}: {source.get('url','')}" if isinstance(source,dict) else source)
    para('Source records', 'Heading2')
    for key,value in (report.get('source_versions') or {}).items(): para(f"{key.replace('_', ' ').title()}: {value}")
    def footer(canvas, doc):
        canvas.setFont('Helvetica',8); canvas.setFillColor(green)
        canvas.drawString(50,30,'FinAgent | Based on saved financial records')
        canvas.drawRightString(545,30,f'Page {doc.page}')
    SimpleDocTemplate(output, title='FinAgent Financial Report', author='FinAgent', leftMargin=50,rightMargin=50,topMargin=42,bottomMargin=50).build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
