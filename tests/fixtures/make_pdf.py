"""Synthetic statement PDF generator, driven by a profile.

Generates a fake statement PDF (reportlab) laid out according to a profile's
columns, so every shipped PDF profile gets a round-trip test: generated
ground truth == parsed output. No real statement data is used or needed --
this is the only fixture data the pdf_table engine test suite touches.

Row text is caller-supplied and printed verbatim (already date-formatted /
thousands-separated / blank for a continuation row), so the generator has no
opinion on formatting -- it only controls page layout.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from statement_parser.profile import Profile

FONT = "Helvetica"
FONT_SIZE = 9
LINE_HEIGHT = 14
TOP_MARGIN = 60
HEADER_GAP = 20

# Default column x-positions tuned for the boi_current profile's 5 columns
# on an A4 page: wide gaps so that neither header word widths nor row text
# widths ever cross into a neighbouring column's x-range. A description cell
# must stay under ~40 characters (roughly the desc->out gap at 9pt
# Helvetica) or it will bleed into the next column -- use a second row with
# only the description field set to simulate a wrapped continuation line
# instead of one long string.
BOI_COLUMN_X = {
    "date": 40,
    "description": 110,
    "out": 340,
    "in": 420,
    "balance": 500,
}


def render_pdf(
    path: Path,
    profile: Profile,
    pages: Sequence[Sequence[Dict[str, str]]],
    column_x: Dict[str, float] = None,
    *,
    page_size=A4,
) -> None:
    """Render a synthetic statement PDF.

    `pages` is a list of pages; each page is a list of row dicts (field ->
    text to print exactly as it should appear on the page; omit or use ""
    for a blank cell). `column_x` maps each profile column field to its left
    x position; defaults to BOI_COLUMN_X.
    """
    if column_x is None:
        column_x = BOI_COLUMN_X

    width, height = page_size
    c = canvas.Canvas(str(path), pagesize=page_size)

    header_cells = [(col.field, col.header) for col in profile.columns]

    for page_rows in pages:
        c.setFont(FONT, FONT_SIZE)
        y = height - TOP_MARGIN
        for field, text in header_cells:
            c.drawString(column_x[field], y, text)

        y -= HEADER_GAP
        for row in page_rows:
            for col in profile.columns:
                text = row.get(col.field, "")
                if text:
                    c.drawString(column_x[col.field], y, text)
            y -= LINE_HEIGHT

        c.showPage()

    c.save()
