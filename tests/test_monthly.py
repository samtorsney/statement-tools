"""Monthly stacked-bar + MoM delta table, exercised on synthetic frames
only (fake accounts, fake categories, fake amounts)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from charts.monthly import build_monthly_bar, monthly_category_totals, monthly_delta_table


def frame_of(rows):
    """rows: (date, amount, account, category, subcategory, is_transfer)."""
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "amount": [Decimal(str(r[1])) for r in rows],
            "account": [r[2] for r in rows],
            "category": [r[3] for r in rows],
            "subcategory": [r[4] for r in rows],
            "is_transfer": [r[5] for r in rows],
        }
    )


def test_monthly_totals_group_by_month_and_category():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-10.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 20), "-15.00", "boi_current", "Food", "Groceries", False),
            (date(2026, 2, 1), "-20.00", "boi_current", "Food", "Coffee", False),
        ]
    )
    pivot = monthly_category_totals(frame)
    assert list(pivot.index) == ["2026-01", "2026-02"]
    assert pivot.loc["2026-01", "Food"] == Decimal("25.00")
    assert pivot.loc["2026-02", "Food"] == Decimal("20.00")


def test_income_and_transfers_excluded_from_monthly_totals():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-10.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 6), "2000.00", "boi_current", "Income", "Salary", False),
            (date(2026, 1, 7), "-500.00", "boi_current", "Transfer", "", True),
        ]
    )
    pivot = monthly_category_totals(frame)
    assert "Income" not in pivot.columns
    assert "Transfer" not in pivot.columns
    assert pivot.loc["2026-01", "Food"] == Decimal("10.00")


def test_double_count_regression_total_spend_matches_non_transfer_negatives():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-10.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 6), "-500.00", "boi_current", "Transfer", "", True),
            (date(2026, 1, 6), "500.00", "revolut_current", "Transfer", "", True),
            (date(2026, 2, 1), "-33.33", "boi_current", "Bills", "Electric", False),
        ]
    )
    pivot = monthly_category_totals(frame)
    total_from_pivot = sum(Decimal(str(v)) for v in pivot.to_numpy().flatten())

    non_transfer_negatives = frame[(~frame["is_transfer"]) & (frame["amount"] < 0)]
    expected = -non_transfer_negatives["amount"].sum()

    assert total_from_pivot == expected == Decimal("43.33")


def test_delta_table_first_month_has_blank_prior_and_delta():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-10.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 2, 5), "-25.00", "boi_current", "Food", "Coffee", False),
        ]
    )
    delta = monthly_delta_table(frame)
    jan = delta[(delta["month"] == "2026-01") & (delta["category"] == "Food")].iloc[0]
    feb = delta[(delta["month"] == "2026-02") & (delta["category"] == "Food")].iloc[0]

    assert jan["prior_amount"] == ""
    assert jan["delta"] == ""
    assert feb["prior_amount"] == Decimal("10.00")
    assert feb["delta"] == Decimal("15.00")


def test_build_monthly_bar_one_trace_per_category():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-10.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 6), "-20.00", "boi_current", "Bills", "Electric", False),
        ]
    )
    fig = build_monthly_bar(frame)
    trace_names = {t.name for t in fig.data}
    assert trace_names == {"Food", "Bills"}
    for t in fig.data:
        assert t.type == "bar"


def test_empty_frame_produces_empty_totals_and_delta():
    frame = frame_of([])
    assert monthly_category_totals(frame).empty
    delta = monthly_delta_table(frame)
    assert list(delta.columns) == ["month", "category", "amount", "prior_amount", "delta"]
    assert delta.empty
