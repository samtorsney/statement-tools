"""Cross-row / cross-file validation: balance continuity, multi-file dedupe,
and statement period gap/overlap warnings.

Validation problems are loud by default: check_balance_continuity raises
(callers should let it propagate to a nonzero exit), there is no silent
partial output.
"""
from __future__ import annotations

import dataclasses
import datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Sequence, Tuple

from .canonical import CanonicalRow
from .errors import BalanceContinuityError

_TOLERANCE = Decimal("0.01")


def check_balance_continuity(
    rows: Sequence[CanonicalRow], tolerance: Decimal = _TOLERANCE
) -> None:
    """Every printed balance must equal the previous row's balance plus this
    row's signed amount. Any mismatch means a row was dropped, split, or
    mis-columned during extraction.

    Scoped per source_file (in the row order the engine produced, i.e.
    document order) -- rows are grouped by `source_file` so calling this
    across multiple concatenated statements doesn't require them to be
    chronologically contiguous. Raises BalanceContinuityError on the first
    mismatch found.
    """
    by_file: Dict[str, List[CanonicalRow]] = {}
    for row in rows:
        by_file.setdefault(row.source_file, []).append(row)

    for source_file, file_rows in by_file.items():
        prev_balance = None
        for row in file_rows:
            if row.balance is None:
                continue
            if prev_balance is not None:
                expected = prev_balance + row.amount
                if abs(expected - row.balance) > tolerance:
                    raise BalanceContinuityError(
                        f"balance discontinuity in {source_file} "
                        f"(page={row.page}, row={row.row}): "
                        f"expected {expected}, printed {row.balance}"
                    )
            prev_balance = row.balance


def dedupe_rows(rows: Iterable[CanonicalRow]) -> List[CanonicalRow]:
    """Multi-file merge dedupe: identical (date, description, amount,
    balance, account) rows collapse to one. Including balance disambiguates
    legitimate same-day duplicate transactions (FINDINGS.md #4), since the
    running balance differs between them.
    """
    seen = set()
    out: List[CanonicalRow] = []
    for row in rows:
        key = (row.date, row.description, row.amount, row.balance, row.account)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


@dataclasses.dataclass
class Period:
    source_file: str
    start: datetime.date
    end: datetime.date


def compute_periods(rows: Iterable[CanonicalRow]) -> List[Period]:
    """The (min date, max date) span covered by each source file, sorted by
    start date."""
    by_file: Dict[str, List[datetime.date]] = {}
    for row in rows:
        if row.date is None:
            continue
        span = by_file.setdefault(row.source_file, [row.date, row.date])
        if row.date < span[0]:
            span[0] = row.date
        if row.date > span[1]:
            span[1] = row.date

    periods = [Period(f, span[0], span[1]) for f, span in by_file.items()]
    periods.sort(key=lambda p: p.start)
    return periods


def check_period_gaps(rows: Iterable[CanonicalRow]) -> List[str]:
    """Warn (return message strings; never raise) about gaps between one
    statement's last date and the next statement's first date, and about
    overlapping statement periods."""
    periods = compute_periods(rows)
    warnings: List[str] = []

    for prev, nxt in zip(periods, periods[1:]):
        if nxt.start > prev.end + datetime.timedelta(days=1):
            warnings.append(
                f"gap: {prev.source_file} ends {prev.end}, "
                f"{nxt.source_file} starts {nxt.start}"
            )
        elif nxt.start <= prev.end:
            warnings.append(
                f"overlap: {prev.source_file} ends {prev.end}, "
                f"{nxt.source_file} starts {nxt.start}"
            )

    return warnings
