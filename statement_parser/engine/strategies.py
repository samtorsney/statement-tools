"""Named-strategy registries.

Every behavioural choice a profile can make selects a name from one of these
dicts. Profile validation checks names against these registries so a typo or
an unimplemented strategy fails loudly with the list of real alternatives,
rather than silently doing nothing. Adding vocabulary for a new bank means
adding one function here (with a narrow signature) plus a docs line -- not
inventing per-profile code.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# page_detect: is this PDF page a transaction table page?
# ---------------------------------------------------------------------------

def page_detect_header_match(page: Any, profile: Any) -> bool:
    """All of the profile's column headers appear together on one line."""
    headers = [c.header for c in profile.columns]
    for line in page.extract_text_lines():
        text = line["text"]
        if all(h in text for h in headers):
            return True
    return False


PAGE_DETECT: Dict[str, Any] = {
    "header_match": page_detect_header_match,
}


# ---------------------------------------------------------------------------
# align: how the gap between two adjacent header blocks becomes a column
# boundary. The *right* column's align resolves the boundary between it and
# its left neighbour.
# ---------------------------------------------------------------------------

def align_left_edge(left_block: dict, right_block: dict) -> float:
    """Boundary sits at the right column header's own left edge."""
    return right_block["x0"]


def align_midpoint(left_block: dict, right_block: dict) -> float:
    """Boundary sits halfway between the two header blocks."""
    return (left_block["x1"] + right_block["x0"]) / 2


def align_right_edge(left_block: dict, right_block: dict) -> float:
    """Boundary sits at the right column header's own right edge."""
    return right_block["x1"]


ALIGN: Dict[str, Any] = {
    "left_edge": align_left_edge,
    "midpoint": align_midpoint,
    "right_edge": align_right_edge,
}


# ---------------------------------------------------------------------------
# table_end: where does the transaction table stop on a page?
# ---------------------------------------------------------------------------

def table_end_spacing_gap(page: Any, header_top: float, profile: Any) -> float:
    """First unusually large vertical gap between text lines below the
    header ends the table (legacy boi_statement_parser.py heuristic)."""
    words = page.extract_words(use_text_flow=True)
    data = [w for w in words if w["top"] > header_top + 5]

    lines: Dict[float, list] = {}
    for w in data:
        y = round(w["top"], 1)
        lines.setdefault(y, []).append(w)

    sorted_ys = sorted(lines)
    if len(sorted_ys) < 2:
        return page.height - 10

    spacings = [sorted_ys[i + 1] - sorted_ys[i] for i in range(len(sorted_ys) - 1)]
    median_spacing = sorted(spacings)[len(spacings) // 2]

    for i, spacing in enumerate(spacings):
        if spacing > median_spacing * 2:
            return sorted_ys[i]

    return page.height - 10


def table_end_page_bottom(page: Any, header_top: float, profile: Any) -> float:
    """The table runs to the bottom of the page (small margin)."""
    return page.height - 10


def table_end_footer_text(page: Any, header_top: float, profile: Any) -> float:
    """The table ends at the first line (below the header) containing the
    profile's configured `table_end.text` marker."""
    marker = getattr(profile.table_end, "text", None)
    if not marker:
        raise ValueError(
            "table_end strategy 'footer_text' requires table_end.text to be set"
        )
    for line in page.extract_text_lines():
        if line["top"] > header_top and marker in line["text"]:
            return line["top"]
    return page.height - 10


TABLE_END: Dict[str, Any] = {
    "spacing_gap": table_end_spacing_gap,
    "footer_text": table_end_footer_text,
    "page_bottom": table_end_page_bottom,
}


# ---------------------------------------------------------------------------
# multiline: how continuation lines (wrapped transaction details) are folded
# into the row above them.
# ---------------------------------------------------------------------------

def multiline_merge_into_previous(rows: List[dict], profile: Any) -> List[dict]:
    """A bucketed line with text in *only* the description column is treated
    as a wrapped continuation of the previous row's description, rather than
    a phantom transaction (FINDINGS.md #3)."""
    result: List[dict] = []
    desc_field = "description"
    for row in rows:
        non_empty = [f for f, v in row.items() if v]
        if result and non_empty == [desc_field]:
            prev = result[-1]
            prev[desc_field] = (prev[desc_field] + " " + row[desc_field]).strip()
        else:
            result.append(dict(row))
    return result


def multiline_none(rows: List[dict], profile: Any) -> List[dict]:
    """No merging: every bucketed line becomes its own row (legacy, buggy
    behaviour -- kept only so the registry has more than one option and so
    tests can demonstrate the phantom-row bug it reproduces)."""
    return [dict(row) for row in rows]


MULTILINE: Dict[str, Any] = {
    "merge_into_previous": multiline_merge_into_previous,
    "none": multiline_none,
}


# ---------------------------------------------------------------------------
# dates.fill: how blank date cells (transactions sharing a date with the row
# above, printed only once) are filled in.
# ---------------------------------------------------------------------------

def date_fill_forward(dates: List[Optional[Any]]) -> List[Optional[Any]]:
    out = []
    last = None
    for d in dates:
        if d is None:
            out.append(last)
        else:
            out.append(d)
            last = d
    return out


def date_fill_none(dates: List[Optional[Any]]) -> List[Optional[Any]]:
    return list(dates)


DATE_FILL: Dict[str, Any] = {
    "forward": date_fill_forward,
    "none": date_fill_none,
}


# ---------------------------------------------------------------------------
# balance.validate: what integrity check is run on the balance column.
# Actual continuity checking lives in validate.py (it needs the whole
# document, not a per-row hook); these names are validated here so a typo in
# a profile fails at load time.
# ---------------------------------------------------------------------------

BALANCE_VALIDATE = {"continuity", "none"}


# ---------------------------------------------------------------------------
# amounts.style: how per-row amount text becomes a signed Decimal.
# Parsing itself lives in canonical.py; validated here for the same reason.
# ---------------------------------------------------------------------------

AMOUNT_STYLES = {"in_out", "signed"}
