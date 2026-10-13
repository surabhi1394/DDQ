"""Write the review as a spreadsheet in the team's ESG DDQ checklist layout."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .pipeline import Review

COLUMNS = [
    ("ESG Consideration", 48),
    ("Response", 10),
    ("Existing Conditions", 60),
    ("Mitigation / Handling", 50),
    ("Priority", 11),
    ("Type", 16),
    ("Risk", 11),
    ("Cost Estimate", 28),
    ("Sources", 30),
    ("Pre/Post Site Visit (Hide for report)", 14),
    ("Verifier", 40),
]
SECTION_FILL = PatternFill("solid", fgColor="D9E1D2")
HEADER_FILL = PatternFill("solid", fgColor="EFEFEF")
REVIEW_FILL = PatternFill("solid", fgColor="FFF2CC")
WRAP = Alignment(wrap_text=True, vertical="top")


def write_report(review: Review, path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "ESG DDQ"
    for idx, (_, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    section = None
    for row in review.rows:
        if row.item.section != section:
            section = row.item.section
            if ws.max_row > 1:
                ws.append([])
            ws.append([section])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
            for c in range(1, len(COLUMNS) + 1):
                ws.cell(row=ws.max_row, column=c).fill = SECTION_FILL
            ws.append([name for name, _ in COLUMNS])
            for c in range(1, len(COLUMNS) + 1):
                cell = ws.cell(row=ws.max_row, column=c)
                cell.font, cell.fill = Font(bold=True), HEADER_FILL
        a = row.answer
        conditions = a.existing_conditions + ("\n[Confirm on site visit]" if a.confirm_on_site else "")
        verifier = "Verified" if row.verified else f"NEEDS REVIEW: {row.verifier_note}"
        ws.append([
            row.item.question, a.response, conditions, a.mitigation, a.priority, row.item.type,
            a.risk, a.cost_estimate, "; ".join(a.sources), row.item.timing, verifier,
        ])
        for c in range(1, len(COLUMNS) + 1):
            ws.cell(row=ws.max_row, column=c).alignment = WRAP
        if not row.verified:
            ws.cell(row=ws.max_row, column=len(COLUMNS)).fill = REVIEW_FILL

    data = wb.create_sheet("Data sources")
    data.append(["Connector", "Status", "Summary", "Source"])
    for c in review.connectors:
        data.append([c.connector, c.status.value, c.summary, c.source])
    data.append([])
    data.append(["Research notes"])
    data.append([review.research_notes])
    for col, width in zip("ABCD", (16, 16, 90, 40)):
        data.column_dimensions[col].width = width
    for r in data.iter_rows():
        for cell in r:
            cell.alignment = WRAP

    prop = wb.create_sheet("Property")
    for key, value in review.profile.model_dump(exclude_none=True).items():
        if value in ([], ""):
            continue
        prop.append([key, "; ".join(map(str, value)) if isinstance(value, list) else value])
    prop.column_dimensions["A"].width, prop.column_dimensions["B"].width = 26, 100

    path = Path(path)
    wb.save(path)
    return path
