"""charts/insights.py numeric tests, exercised on synthetic frames only
(fake accounts, fake merchants, fake amounts)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from charts.insights import (
    Movers,
    NoPriorCoverage,
    detect_currency,
    health,
    movers,
    notables,
    rankings,
    stat_tiles,
)


def frame_of(rows, currency=None):
    """rows: (date, description, amount, account, category, subcategory,
    is_transfer) tuples."""
    data = {
        "date": [r[0] for r in rows],
        "description": [r[1] for r in rows],
        "amount": [Decimal(str(r[2])) for r in rows],
        "account": [r[3] for r in rows],
        "category": [r[4] for r in rows],
        "subcategory": [r[5] for r in rows],
        "is_transfer": [r[6] for r in rows],
    }
    if currency is not None:
        data["currency"] = currency if isinstance(currency, list) else [currency] * len(rows)
    else:
        data["currency"] = [""] * len(rows)
    return pd.DataFrame(data)


# --------------------------------------------------------------------------
# stat_tiles
# --------------------------------------------------------------------------


def test_stat_tiles_basic_income_spend_net_savings_rate():
    frame = frame_of(
        [
            (date(2026, 1, 5), "FAKECO SALARY", "1000.00", "boi_current", "Income", "Salary", False),
            (date(2026, 1, 6), "BIG COFFEE HOUSE", "-40.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 7), "MYSTERY MERCHANT", "-60.00", "boi_current", "Food", "Groceries", False),
        ]
    )
    tiles = stat_tiles(frame)
    assert tiles.income == Decimal("1000.00")
    assert tiles.spend == Decimal("100.00")
    assert tiles.net == Decimal("900.00")
    assert tiles.savings_rate == Decimal("900.00") / Decimal("1000.00")


def test_stat_tiles_zero_income_gives_none_sentinel_not_a_crash():
    frame = frame_of(
        [
            (date(2026, 1, 6), "BIG COFFEE HOUSE", "-40.00", "boi_current", "Food", "Coffee", False),
        ]
    )
    tiles = stat_tiles(frame)
    assert tiles.income == Decimal("0")
    assert tiles.spend == Decimal("40.00")
    assert tiles.savings_rate is None


def test_stat_tiles_excludes_transfers():
    frame = frame_of(
        [
            (date(2026, 1, 5), "FAKECO SALARY", "1000.00", "boi_current", "Income", "Salary", False),
            (date(2026, 1, 6), "TO FAKE SAVINGS", "-300.00", "boi_current", "Transfer", "", True),
            (date(2026, 1, 6), "FROM BOI", "300.00", "revolut_current", "Transfer", "", True),
        ]
    )
    tiles = stat_tiles(frame)
    assert tiles.income == Decimal("1000.00")
    assert tiles.spend == Decimal("0")
    assert tiles.net == Decimal("1000.00")


def test_stat_tiles_empty_frame_all_zero_and_no_savings_rate():
    frame = frame_of([])
    tiles = stat_tiles(frame)
    assert tiles.income == Decimal("0")
    assert tiles.spend == Decimal("0")
    assert tiles.net == Decimal("0")
    assert tiles.savings_rate is None


# --------------------------------------------------------------------------
# currency detection
# --------------------------------------------------------------------------


def test_detect_currency_single_shared_value():
    frame = frame_of(
        [(date(2026, 1, 5), "X", "10.00", "boi_current", "", "", False)],
        currency="EUR",
    )
    assert detect_currency(frame) == "EUR"


def test_detect_currency_mixed_returns_none():
    frame = frame_of(
        [
            (date(2026, 1, 5), "X", "10.00", "boi_current", "", "", False),
            (date(2026, 1, 6), "Y", "-5.00", "revolut_current", "", "", False),
        ],
        currency=["EUR", "GBP"],
    )
    assert detect_currency(frame) is None


def test_detect_currency_absent_returns_none():
    frame = frame_of(
        [(date(2026, 1, 5), "X", "10.00", "boi_current", "", "", False)],
        currency="",
    )
    assert detect_currency(frame) is None


# --------------------------------------------------------------------------
# rankings
# --------------------------------------------------------------------------


def test_rankings_orders_categories_and_merchants_by_spend_desc():
    frame = frame_of(
        [
            (date(2026, 1, 1), "BIG COFFEE HOUSE", "-5.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 2), "BIG COFFEE HOUSE", "-5.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 3), "GROCERY MART", "-100.00", "boi_current", "Food", "Groceries", False),
            (date(2026, 1, 4), "ELECTRIC CO", "-50.00", "boi_current", "Utilities", "", False),
        ]
    )
    result = rankings(frame)
    assert [c.category for c in result.top_categories] == ["Food", "Utilities"]
    assert result.top_categories[0].amount == Decimal("110.00")
    assert [m.description for m in result.top_merchants][:2] == ["GROCERY MART", "ELECTRIC CO"]
    assert result.top_merchants[0].amount == Decimal("100.00")


def test_rankings_cuts_off_at_top_10():
    rows = [
        (date(2026, 1, i + 1), f"MERCHANT {i}", str(-(i + 1)), "boi_current", f"Cat{i}", "", False)
        for i in range(15)
    ]
    frame = frame_of(rows)
    result = rankings(frame)
    assert len(result.top_categories) == 10
    assert len(result.top_merchants) == 10
    # Highest-spend categories come first (Cat14 has amount 15, the max).
    assert result.top_categories[0].category == "Cat14"


def test_rankings_excludes_transfers_and_income():
    frame = frame_of(
        [
            (date(2026, 1, 1), "SALARY", "2000.00", "boi_current", "Income", "Salary", False),
            (date(2026, 1, 2), "TO SAVINGS", "-300.00", "boi_current", "Transfer", "", True),
            (date(2026, 1, 2), "FROM BOI", "300.00", "revolut_current", "Transfer", "", True),
            (date(2026, 1, 3), "GROCERY MART", "-20.00", "boi_current", "Food", "", False),
        ]
    )
    result = rankings(frame)
    assert [c.category for c in result.top_categories] == ["Food"]
    assert [m.description for m in result.top_merchants] == ["GROCERY MART"]


def test_rankings_uncategorised_gets_placeholder_label():
    frame = frame_of([(date(2026, 1, 1), "X", "-10.00", "boi_current", "", "", False)])
    result = rankings(frame)
    assert result.top_categories[0].category == "(uncategorised)"


def test_rankings_empty_frame_returns_empty_lists():
    result = rankings(frame_of([]))
    assert result.top_categories == []
    assert result.top_merchants == []


# --------------------------------------------------------------------------
# movers
# --------------------------------------------------------------------------


def test_movers_computes_deltas_vs_preceding_equal_length_window():
    # Range: Feb 1-10 (10 days). Preceding window: Jan 22-31 (10 days).
    frame = frame_of(
        [
            (date(2026, 1, 25), "X", "-50.00", "boi_current", "Food", "", False),
            (date(2026, 2, 5), "X", "-80.00", "boi_current", "Food", "", False),
            (date(2026, 1, 26), "Y", "-100.00", "boi_current", "Fees", "", False),
            (date(2026, 2, 6), "Y", "-10.00", "boi_current", "Fees", "", False),
        ]
    )
    result = movers(frame, date(2026, 2, 1), date(2026, 2, 10))
    assert isinstance(result, Movers)
    assert result.window_days == 10
    by_cat = {d.category: d for d in result.increases + result.decreases}
    assert by_cat["Food"].current == Decimal("80.00")
    assert by_cat["Food"].prior == Decimal("50.00")
    assert by_cat["Food"].delta == Decimal("30.00")
    assert by_cat["Fees"].delta == Decimal("-90.00")
    assert "Food" in [d.category for d in result.increases]
    assert "Fees" in [d.category for d in result.decreases]


def test_movers_no_prior_coverage_when_preceding_window_is_empty():
    frame = frame_of(
        [
            (date(2026, 2, 5), "X", "-80.00", "boi_current", "Food", "", False),
        ]
    )
    result = movers(frame, date(2026, 2, 1), date(2026, 2, 10))
    assert result == NoPriorCoverage()
    assert isinstance(result, NoPriorCoverage)


def test_movers_caps_at_top_5_increases_and_decreases():
    rows = []
    for i in range(8):
        rows.append((date(2026, 1, 25), "X", str(-(i + 1)), "boi_current", f"Up{i}", "", False))
        rows.append((date(2026, 2, 5), "X", str(-(i + 1) * 10), "boi_current", f"Up{i}", "", False))
    frame = frame_of(rows)
    result = movers(frame, date(2026, 2, 1), date(2026, 2, 10))
    assert len(result.increases) == 5
    assert len(result.decreases) == 0


def test_movers_ties_are_broken_alphabetically():
    frame = frame_of(
        [
            (date(2026, 1, 25), "X", "-10.00", "boi_current", "Zeta", "", False),
            (date(2026, 1, 25), "X", "-10.00", "boi_current", "Alpha", "", False),
            (date(2026, 2, 5), "X", "-20.00", "boi_current", "Zeta", "", False),
            (date(2026, 2, 5), "X", "-20.00", "boi_current", "Alpha", "", False),
        ]
    )
    result = movers(frame, date(2026, 2, 1), date(2026, 2, 10))
    assert [d.category for d in result.increases[:2]] == ["Alpha", "Zeta"]


# --------------------------------------------------------------------------
# notables
# --------------------------------------------------------------------------


def test_notables_top_n_by_absolute_amount_excludes_transfers():
    frame = frame_of(
        [
            (date(2026, 1, 1), "BIG PURCHASE", "-500.00", "boi_current", "Shopping", "", False),
            (date(2026, 1, 2), "SALARY", "2000.00", "boi_current", "Income", "Salary", False),
            (date(2026, 1, 3), "TO SAVINGS", "-9999.00", "boi_current", "Transfer", "", True),
            (date(2026, 1, 3), "FROM BOI", "9999.00", "revolut_current", "Transfer", "", True),
            (date(2026, 1, 4), "SMALL COFFEE", "-4.00", "boi_current", "Food", "", False),
        ]
    )
    result = notables(frame, top_n=2)
    assert len(result) == 2
    assert result[0].description == "SALARY"
    assert result[0].amount == Decimal("2000.00")
    assert result[1].description == "BIG PURCHASE"


def test_notables_empty_when_only_transfers():
    frame = frame_of(
        [
            (date(2026, 1, 3), "TO SAVINGS", "-300.00", "boi_current", "Transfer", "", True),
        ]
    )
    assert notables(frame) == []


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------


def test_health_counts_uncategorised_and_per_account_coverage():
    frame = frame_of(
        [
            (date(2026, 1, 5), "X", "-10.00", "boi_current", "", "", False),
            (date(2026, 1, 6), "Y", "-20.00", "boi_current", "Food", "", False),
            (date(2026, 1, 10), "Z", "-5.00", "revolut_current", "", "", False),
        ]
    )
    empty_unmatched = frame_of([])
    result = health(frame, empty_unmatched)
    assert result.uncategorised_count == 2
    assert result.uncategorised_total_abs == Decimal("15.00")
    assert result.unmatched_transfer_count == 0

    by_account = {a.account: a for a in result.accounts}
    assert by_account["boi_current"].first_date == date(2026, 1, 5)
    assert by_account["boi_current"].last_date == date(2026, 1, 6)
    assert by_account["boi_current"].row_count == 2
    assert by_account["revolut_current"].row_count == 1


def test_health_reports_unmatched_transfer_count_from_same_run():
    frame = frame_of([(date(2026, 1, 5), "X", "-10.00", "boi_current", "Food", "", False)])
    unmatched = frame_of(
        [(date(2026, 1, 5), "TO SAVINGS", "-300.00", "boi_current", "Transfer", "", True)]
    )
    result = health(frame, unmatched)
    assert result.unmatched_transfer_count == 1


def test_health_excludes_transfers_from_uncategorised_count():
    frame = frame_of(
        [
            (date(2026, 1, 5), "TO SAVINGS", "-300.00", "boi_current", "", "", True),
        ]
    )
    result = health(frame, frame_of([]))
    assert result.uncategorised_count == 0
