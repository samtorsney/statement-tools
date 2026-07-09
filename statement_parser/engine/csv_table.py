"""CSV column-mapping engine.

Reads a CSV with `csv.column_map` (source header -> canonical field), then
hands the same raw-row-dict shape the PDF engine produces to
canonical.coerce_rows, so both engines emit the identical canonical schema.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Union

from ..canonical import CanonicalRow, coerce_rows
from ..errors import ExtractionError
from ..profile import Profile


def parse_csv(path: Union[str, Path], profile: Profile) -> List[CanonicalRow]:
    if profile.meta.source != "csv":
        raise ExtractionError(
            f"profile {profile.meta.name!r} has meta.source={profile.meta.source!r}, "
            "expected 'csv'"
        )

    path = Path(path)
    column_map = profile.csv.column_map

    raw_rows: List[dict] = []
    with open(path, "r", newline="", encoding=profile.csv.encoding) as f:
        reader = csv.DictReader(f, delimiter=profile.csv.delimiter)
        if reader.fieldnames is None:
            raise ExtractionError(f"{path}: CSV has no header row")
        missing = set(column_map) - set(reader.fieldnames)
        if missing:
            raise ExtractionError(
                f"{path}: CSV is missing expected column(s): {', '.join(sorted(missing))}"
            )

        for line_number, row in enumerate(reader, start=1):
            mapped = {field: row.get(src, "") for src, field in column_map.items()}
            mapped["_page"] = None
            mapped["_row"] = line_number
            raw_rows.append(mapped)

    return coerce_rows(raw_rows, profile, source_file=path.name)
