"""Cumulative savings line + balance trajectory, exercised on synthetic
frames only (fake accounts, fake balances, fake amounts)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from charts.savings import balance_trajectory, build_savings_chart, cumulative_savings_by_date


def frame_of(rows):
    """rows: (date, amount, balance, account, category, subcategory)."""
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "amount": [Decimal(str(r[1])) for r in rows],
            "balance": [Decimal(str(r[2])) if r[2] is not None else None for r in rows],
            "account": [r[3] for r in rows],
            "category": [r[4] for r in rows],
            "subcategory": [r[5] for r in rows],
        }
    )


def test_cumulative_savings_accumulates_in_date_order():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "900.00", "boi_current", "Savings", ""),
            (date(2026, 1, 10), "-50.00", "850.00", "boi_current", "Savings", ""),
            (date(2026, 1, 15), "20.00", "870.00", "boi_current", "Savings", "Withdrawal"),
        ]
    )
    cumulative = cumulative_savings_by_date(frame)
    assert list(cumulative.index) == [date(2026, 1, 5), date(2026, 1, 10), date(2026, 1, 15)]
    assert list(cumulative.values) == [Decimal("-100.00"), Decimal("-150.00"), Decimal("-130.00")]


def test_non_savings_rows_excluded_from_cumulative():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "900.00", "boi_current", "Savings", ""),
            (date(2026, 1, 6), "-40.00", "860.00", "boi_current", "Food", "Groceries"),
        ]
    )
    cumulative = cumulative_savings_by_date(frame)
    assert list(cumulative.values) == [Decimal("-100.00")]


def test_case_insensitive_category_match():
    frame = frame_of(
        [(date(2026, 1, 5), "-100.00", "900.00", "boi_current", "SAVINGS ACCOUNT", "")]
    )
    cumulative = cumulative_savings_by_date(frame)
    assert list(cumulative.values) == [Decimal("-100.00")]


def test_balance_trajectory_per_account_last_value_per_day():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-10.00", "990.00", "boi_current", "Food", ""),
            (date(2026, 1, 5), "-5.00", "985.00", "boi_current", "Food", ""),  # same day, later row wins
            (date(2026, 1, 6), "50.00", "1035.00", "revolut_current", "Income", ""),
        ]
    )
    trajectory = balance_trajectory(frame)
    boi_row = trajectory[(trajectory["account"] == "boi_current") & (trajectory["date"] == date(2026, 1, 5))]
    assert boi_row.iloc[0]["balance"] == Decimal("985.00")
    revolut_row = trajectory[trajectory["account"] == "revolut_current"]
    assert revolut_row.iloc[0]["balance"] == Decimal("1035.00")


def test_rows_without_balance_excluded_from_trajectory():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-10.00", None, "boi_current", "Food", ""),
        ]
    )
    trajectory = balance_trajectory(frame)
    assert trajectory.empty


def test_build_savings_chart_has_one_trace_per_series():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "900.00", "boi_current", "Savings", ""),
            (date(2026, 1, 6), "50.00", "1035.00", "revolut_current", "Income", ""),
        ]
    )
    fig = build_savings_chart(frame)
    names = {t.name for t in fig.data}
    assert "cumulative savings" in names
    assert "boi_current balance" in names
    assert "revolut_current balance" in names
    for t in fig.data:
        assert t.type == "scatter"
