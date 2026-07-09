"""validate.py: balance continuity (loud, raises), multi-file dedupe on
(date, description, amount, balance, account), and period gap/overlap
warnings. All built from synthetic CanonicalRow instances -- no PDFs/CSVs
needed for this module."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from statement_parser.canonical import CanonicalRow
from statement_parser.errors import BalanceContinuityError
from statement_parser.validate import check_balance_continuity, check_period_gaps, dedupe_rows


def make_row(
    d,
    desc,
    amount,
    balance,
    account="boi_current",
    source_file="a.pdf",
    page=1,
    row=1,
):
    return CanonicalRow(
        date=d,
        description=desc,
        amount=Decimal(amount),
        balance=Decimal(balance) if balance is not None else None,
        currency=None,
        account=account,
        source_file=source_file,
        page=page,
        row=row,
    )


def test_balance_continuity_passes_for_consistent_rows():
    rows = [
        make_row(date(2026, 1, 1), "open", "100.00", "100.00", row=1),
        make_row(date(2026, 1, 2), "spend", "-10.00", "90.00", row=2),
        make_row(date(2026, 1, 3), "credit", "5.00", "95.00", row=3),
    ]
    check_balance_continuity(rows)  # should not raise


def test_balance_continuity_raises_on_mismatch():
    rows = [
        make_row(date(2026, 1, 1), "open", "100.00", "100.00", row=1),
        make_row(date(2026, 1, 2), "spend", "-10.00", "85.00", row=2),  # should be 90.00
    ]
    with pytest.raises(BalanceContinuityError, match="discontinuity"):
        check_balance_continuity(rows)


def test_balance_continuity_skips_rows_with_no_printed_balance():
    rows = [
        make_row(date(2026, 1, 1), "open", "100.00", "100.00", row=1),
        make_row(date(2026, 1, 2), "unknown", "-10.00", None, row=2),
        make_row(date(2026, 1, 3), "credit", "5.00", "95.00", row=3),
    ]
    check_balance_continuity(rows)  # should not raise; middle row has no balance to check


def test_balance_continuity_scoped_per_source_file():
    # Two files concatenated out of chronological order relative to each
    # other must not be compared against each other's running balance.
    rows = [
        make_row(date(2026, 1, 1), "a", "100.00", "100.00", source_file="jan.pdf", row=1),
        make_row(date(2026, 2, 1), "b", "50.00", "9999.00", source_file="feb.pdf", row=1),
    ]
    check_balance_continuity(rows)  # should not raise -- different files


def test_dedupe_collapses_exact_duplicates():
    rows = [
        make_row(date(2026, 1, 1), "coffee", "-4.50", "95.50", row=1),
        make_row(date(2026, 1, 1), "coffee", "-4.50", "95.50", row=1),
    ]
    deduped = dedupe_rows(rows)
    assert len(deduped) == 1


def test_dedupe_keeps_legitimate_same_day_duplicates_with_different_balance():
    rows = [
        make_row(date(2026, 1, 1), "coffee", "-4.50", "95.50", row=1),
        make_row(date(2026, 1, 1), "coffee", "-4.50", "91.00", row=2),  # second coffee, same day
    ]
    deduped = dedupe_rows(rows)
    assert len(deduped) == 2


def test_period_gaps_detects_gap():
    rows = [
        make_row(date(2026, 1, 1), "a", "1", "1", source_file="jan.pdf"),
        make_row(date(2026, 1, 31), "b", "1", "2", source_file="jan.pdf"),
        make_row(date(2026, 3, 1), "c", "1", "3", source_file="mar.pdf"),
    ]
    warnings = check_period_gaps(rows)
    assert any("gap" in w for w in warnings)


def test_period_gaps_detects_overlap():
    rows = [
        make_row(date(2026, 1, 1), "a", "1", "1", source_file="jan.pdf"),
        make_row(date(2026, 1, 20), "b", "1", "2", source_file="jan.pdf"),
        make_row(date(2026, 1, 15), "c", "1", "3", source_file="jan2.pdf"),
        make_row(date(2026, 2, 1), "d", "1", "4", source_file="jan2.pdf"),
    ]
    warnings = check_period_gaps(rows)
    assert any("overlap" in w for w in warnings)


def test_period_gaps_no_warning_for_contiguous_periods():
    rows = [
        make_row(date(2026, 1, 1), "a", "1", "1", source_file="jan.pdf"),
        make_row(date(2026, 1, 31), "b", "1", "2", source_file="jan.pdf"),
        make_row(date(2026, 2, 1), "c", "1", "3", source_file="feb.pdf"),
        make_row(date(2026, 2, 28), "d", "1", "4", source_file="feb.pdf"),
    ]
    warnings = check_period_gaps(rows)
    assert warnings == []
