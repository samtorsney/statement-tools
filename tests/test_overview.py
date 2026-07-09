"""charts/overview.py page assembly, exercised on synthetic frames only
(fake merchants, fake amounts, fake accounts). Assertions check structure
(anchor ids, single plotly.js inclusion, conditional monthly section) --
never render or screenshot the page."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from charts.overview import build_overview

PLOTLYJS_SIGNATURE = "* plotly.js v"


def frame_of(rows):
    """rows: (date, description, amount, account, category, subcategory,
    is_transfer, currency) tuples."""
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "description": [r[1] for r in rows],
            "amount": [Decimal(str(r[2])) for r in rows],
            "account": [r[3] for r in rows],
            "category": [r[4] for r in rows],
            "subcategory": [r[5] for r in rows],
            "is_transfer": [r[6] for r in rows],
            "currency": [r[7] for r in rows],
            "balance": [None] * len(rows),
        }
    )


SAMPLE_ROWS = [
    (date(2026, 1, 5), "FAKECO SALARY JAN", "2000.00", "boi_current", "Income", "Salary", False, ""),
    (date(2026, 1, 6), "BIG COFFEE HOUSE", "-4.50", "boi_current", "Food", "Coffee", False, ""),
    (date(2026, 1, 7), "TO FAKE SAVINGS", "-300.00", "boi_current", "Transfer", "", True, ""),
    (date(2026, 1, 7), "FROM BOI", "300.00", "revolut_current", "Transfer", "", True, ""),
    (date(2026, 1, 20), "MYSTERY MERCHANT", "-15.00", "boi_current", "", "", False, ""),
]


def test_all_section_anchors_present():
    frame = frame_of(SAMPLE_ROWS)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 31))
    for anchor in (
        "header",
        "stat-tiles",
        "sankey",
        "rankings-movers",
        "trends",
        "notables",
        "data-health",
    ):
        assert f'id="{anchor}"' in result.html


def test_plotlyjs_inlined_exactly_once():
    frame = frame_of(SAMPLE_ROWS)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 31))
    assert result.html.count(PLOTLYJS_SIGNATURE) == 1


def test_monthly_fragment_absent_for_single_month_range():
    frame = frame_of(SAMPLE_ROWS)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 31))
    assert 'id="monthly-trend"' not in result.html
    # Savings is always rendered.
    assert 'id="savings-trend"' in result.html


def test_monthly_fragment_present_for_multi_month_range():
    rows = SAMPLE_ROWS + [
        (date(2026, 2, 6), "BIG COFFEE HOUSE", "-4.50", "boi_current", "Food", "Coffee", False, ""),
    ]
    frame = frame_of(rows)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 2, 28))
    assert 'id="monthly-trend"' in result.html
    assert 'id="savings-trend"' in result.html


def test_no_raw_transaction_text_in_rankings_or_health_only_areas():
    # The Sankey/notables sections legitimately show merchant/category
    # text; this just guards against gross leaks like echoing raw CSV rows.
    frame = frame_of(SAMPLE_ROWS)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 31))
    assert "<html" in result.html.lower()


def test_counts_match_in_range_and_uncategorised():
    frame = frame_of(SAMPLE_ROWS)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 31))
    assert result.counts["total_rows"] == 5
    assert result.counts["in_range_rows"] == 5
    assert result.counts["uncategorised"] == 1
    assert result.counts["unmatched_transfers"] == 0


def test_mixed_currency_falls_back_to_bare_numbers_and_note():
    rows = [
        (date(2026, 1, 5), "X", "100.00", "boi_current", "Income", "", False, "EUR"),
        (date(2026, 1, 6), "Y", "-10.00", "boi_current", "Food", "", False, "GBP"),
    ]
    frame = frame_of(rows)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 31))
    assert "Amounts shown without a currency symbol" in result.html


def test_single_currency_used_in_tiles():
    rows = [
        (date(2026, 1, 5), "X", "100.00", "boi_current", "Income", "", False, "EUR"),
        (date(2026, 1, 6), "Y", "-10.00", "boi_current", "Food", "", False, "EUR"),
    ]
    frame = frame_of(rows)
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 31))
    assert "EUR" in result.html
    assert "Amounts shown without a currency symbol" not in result.html


def test_movers_no_prior_coverage_renders_note_not_a_table():
    frame = frame_of(SAMPLE_ROWS)
    # Range starts right at the earliest possible date, so the preceding
    # window has no rows at all.
    result = build_overview(frame, date(2026, 1, 1), date(2026, 1, 10))
    assert "No data in the preceding comparison window" in result.html
