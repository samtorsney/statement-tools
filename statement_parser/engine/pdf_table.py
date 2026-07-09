"""Generic PDF table engine (today's BOI logic, parameterised by profile).

Per page: page_detect -> header location -> boundary derivation -> line
grouping -> column bucketing (by word x-midpoint, not x0) -> multiline
merge -> hand raw rows to canonical.coerce_rows for typed coercion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import pdfplumber

from ..canonical import CanonicalRow, coerce_rows
from ..errors import ExtractionError
from ..profile import Profile
from . import strategies


def _round_line_key(top: float) -> float:
    return round(top, 1)


def find_header_line(page: Any, profile: Profile) -> List[dict]:
    """Find the line of words containing every profile column header."""
    words = page.extract_words(use_text_flow=True)

    lines: Dict[float, List[dict]] = {}
    for w in words:
        lines.setdefault(_round_line_key(w["top"]), []).append(w)

    headers = [c.header for c in profile.columns]
    for line in lines.values():
        line_text = " ".join(w["text"] for w in line)
        if all(h in line_text for h in headers):
            return line

    raise ExtractionError(
        "header line not found",
        page=getattr(page, "page_number", None),
        strategy=profile.page_detect.strategy if profile.page_detect else None,
    )


def build_header_blocks(line_words: List[dict], profile: Profile) -> List[dict]:
    """Match each profile column's (possibly multi-word) header text to word
    boxes on the header line. Returned in profile.columns declaration order,
    each carrying its own field/align so later steps don't need the profile."""
    line_words = sorted(line_words, key=lambda w: w["x0"])
    blocks = []

    for col in profile.columns:
        parts = col.header.split()
        found = None
        for i in range(len(line_words) - len(parts) + 1):
            candidate = line_words[i : i + len(parts)]
            if [w["text"] for w in candidate] == parts:
                found = candidate
                break
        if found is None:
            raise ExtractionError(f"header not found: {col.header!r}")
        blocks.append(
            {
                "field": col.field,
                "header": col.header,
                "align": col.align,
                "x0": found[0]["x0"],
                "x1": found[-1]["x1"],
                "top": found[0]["top"],
            }
        )

    return blocks


def build_columns(blocks: List[dict], page_width: float) -> List[Tuple[str, float, float]]:
    """Derive column x-boundaries. Each gap between adjacent header blocks
    (sorted left-to-right) is resolved by the *right* block's align
    strategy."""
    ordered = sorted(blocks, key=lambda b: b["x0"])

    boundaries = []
    for i in range(len(ordered) - 1):
        left_block = ordered[i]
        right_block = ordered[i + 1]
        align_fn = strategies.ALIGN[right_block["align"]]
        boundaries.append(align_fn(left_block, right_block))

    xs = [0.0] + boundaries + [page_width]
    return [(b["field"], xs[i], xs[i + 1]) for i, b in enumerate(ordered)]


def group_lines(words: List[dict], tolerance: float) -> List[List[dict]]:
    words = sorted(words, key=lambda w: w["top"])
    lines: List[List[dict]] = []
    current: List[dict] = []
    last_y = None

    for w in words:
        if last_y is None or abs(w["top"] - last_y) < tolerance:
            current.append(w)
        else:
            lines.append(current)
            current = [w]
        last_y = w["top"]

    if current:
        lines.append(current)

    return lines


def bucket_words_into_row(
    line_words: List[dict], columns: List[Tuple[str, float, float]]
) -> Dict[str, str]:
    """Bucket words into columns by x-midpoint, so a word straddling a
    boundary lands wherever most of it sits (FINDINGS.md #3), not always
    left as the legacy x0-only check did."""
    row = {field: "" for field, _, _ in columns}

    for w in line_words:
        mid = (w["x0"] + w["x1"]) / 2
        for field, x0, x1 in columns:
            if x0 <= mid < x1:
                row[field] += w["text"] + " "
                break

    return {k: v.strip() for k, v in row.items()}


def extract_page(page: Any, profile: Profile, page_number: int) -> List[dict]:
    detect_fn = strategies.PAGE_DETECT[profile.page_detect.strategy]
    if not detect_fn(page, profile):
        return []

    header_words = find_header_line(page, profile)
    blocks = build_header_blocks(header_words, profile)
    columns = build_columns(blocks, page.width)

    header_top = blocks[0]["top"]

    table_end_fn = strategies.TABLE_END[profile.table_end.strategy]
    table_bottom = table_end_fn(page, header_top, profile)

    words = page.extract_words(use_text_flow=True)
    data = [w for w in words if header_top + 5 < w["top"] < table_bottom]

    lines = group_lines(data, profile.rows.line_tolerance)

    bucketed = []
    for line in lines:
        row = bucket_words_into_row(line, columns)
        if any(row.values()):
            bucketed.append(row)

    multiline_fn = strategies.MULTILINE[profile.rows.multiline]
    merged = multiline_fn(bucketed, profile)

    # A genuine transaction always has some description text (that's how a
    # continuation line is recognised as belonging to one, above). A row
    # with content in another column but a blank description is not a
    # transaction -- most likely non-table text (a subtotal/footer line,
    # a page note) that the table_end heuristic failed to exclude
    # (FINDINGS.md #3). Drop it rather than let it crash amount coercion or
    # masquerade as a transaction with a nonsensical value.
    merged = [row for row in merged if row.get("description", "").strip()]

    for row in merged:
        row["_page"] = page_number

    return merged


def parse_pdf(path: Union[str, Path], profile: Profile) -> List[CanonicalRow]:
    if profile.meta.source != "pdf":
        raise ExtractionError(
            f"profile {profile.meta.name!r} has meta.source={profile.meta.source!r}, "
            "expected 'pdf'"
        )

    path = Path(path)
    raw_rows: List[dict] = []

    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            raw_rows.extend(extract_page(page, profile, page_number))

    for i, row in enumerate(raw_rows, start=1):
        row["_row"] = i

    return coerce_rows(raw_rows, profile, source_file=path.name)
