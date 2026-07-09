"""Cumulative savings line: transfer-to-savings flows + balance trajectory.

Pure builders: frame -> plotly figure / pandas Series/DataFrame. No I/O.
Expects the netted frame's real dtypes (``amount``/``balance`` as
``Decimal`` or ``None``, ``date`` as ``datetime.date``).

"Savings flows" are identified by a case-insensitive substring match
against ``category``/``subcategory`` (default ``"saving"``) rather than
the transfer-netting machinery, since a savings sweep is one category
among many a rules file might define -- the netting layer only knows
"transfer or not", not "transfer to *savings* specifically".
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

DEFAULT_CATEGORY_MATCH = "saving"


def cumulative_savings_by_date(
    frame: pd.DataFrame, category_match: str = DEFAULT_CATEGORY_MATCH
) -> pd.Series:
    """Running sum of signed amount for rows whose category or subcategory
    contains `category_match` (case-insensitive), summed per date and
    accumulated in date order. Positive values mean money moving into
    savings that day."""
    category = frame["category"].astype(str).str.contains(category_match, case=False, na=False)
    subcategory = frame["subcategory"].astype(str).str.contains(
        category_match, case=False, na=False
    )
    savings = frame[category | subcategory]
    if savings.empty:
        return pd.Series(dtype=object)
    by_date = savings.groupby("date")["amount"].sum().sort_index()
    return by_date.cumsum()


def balance_trajectory(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-account (date, balance) points, long format, for rows with a
    known balance -- the last balance recorded on each date, per account
    (later same-day rows supersede earlier ones, matching running-balance
    semantics elsewhere in the pipeline)."""
    has_balance = frame[frame["balance"].notna()]
    if has_balance.empty:
        return pd.DataFrame(columns=["date", "account", "balance"])
    ordered = has_balance.sort_values(["account", "date"])
    last_per_day = ordered.groupby(["account", "date"], as_index=False).last()
    return last_per_day[["date", "account", "balance"]]


def build_savings_chart(
    frame: pd.DataFrame, category_match: str = DEFAULT_CATEGORY_MATCH
) -> go.Figure:
    """Cumulative savings-flow line plus one balance-trajectory line per
    account (where balances exist)."""
    fig = go.Figure()

    cumulative = cumulative_savings_by_date(frame, category_match)
    if len(cumulative):
        fig.add_scatter(
            x=[str(d) for d in cumulative.index],
            y=[float(v) for v in cumulative.values],
            mode="lines",
            name="cumulative savings",
        )

    trajectory = balance_trajectory(frame)
    for account, group in trajectory.groupby("account"):
        fig.add_scatter(
            x=[str(d) for d in group["date"]],
            y=[float(b) for b in group["balance"]],
            mode="lines",
            name=f"{account} balance",
        )

    fig.update_layout(xaxis_title="date", yaxis_title="amount")
    return fig
