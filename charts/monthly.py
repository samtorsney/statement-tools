"""Monthly stacked-bar spend chart + month-over-month category delta table.

Pure builders: frame -> plotly figure / pandas DataFrame. No I/O. Like
``charts.sankey``, these expect the netted frame's real dtypes (``amount``
as ``Decimal``, ``date`` as ``datetime.date``, ``is_transfer`` as ``bool``).

"Spend" here means non-transfer rows with a negative amount -- the same
definition ``charts.sankey`` uses for its account -> category links, so the
two views can't silently disagree about what counts as spend. Transfer
rows (paired or not) are excluded: a matched transfer is a reshuffle
between accounts, not spend, and an unmatched one belongs only in the
``unmatched_transfers.csv`` report.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go

UNCATEGORISED = "(uncategorised)"


def _month_key(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def spend_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Non-transfer, negative-amount rows -- the universe both the Sankey
    and this module treat as "spend"."""
    is_transfer = frame["is_transfer"].astype(bool)
    return frame[(~is_transfer) & (frame["amount"] < 0)]


def monthly_category_totals(frame: pd.DataFrame) -> pd.DataFrame:
    """Month (``YYYY-MM``) x category matrix of summed spend, as positive
    Decimal totals (canonical schema has spend as negative amount)."""
    spend = spend_rows(frame).copy()
    if spend.empty:
        return pd.DataFrame()

    spend["month"] = spend["date"].map(_month_key)
    spend["category_label"] = spend["category"].replace("", UNCATEGORISED)
    spend["spend"] = spend["amount"].map(lambda a: -a)

    pivot = spend.pivot_table(
        index="month",
        columns="category_label",
        values="spend",
        aggfunc="sum",
        fill_value=Decimal("0"),
    )
    return pivot.sort_index()


def build_monthly_bar(frame: pd.DataFrame) -> go.Figure:
    """Stacked bar of spend per month, one trace per parent category."""
    pivot = monthly_category_totals(frame)
    fig = go.Figure()
    for category in pivot.columns:
        fig.add_bar(
            name=str(category),
            x=list(pivot.index),
            y=[float(v) for v in pivot[category]],
        )
    fig.update_layout(barmode="stack", xaxis_title="month", yaxis_title="spend")
    return fig


def monthly_delta_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Long-format month-over-month delta: one row per (month, category)
    with this month's spend, the prior month's spend, and the difference.
    The first month a category appears has no prior value (blank, not 0 --
    0 would misleadingly imply "no change" rather than "no data")."""
    pivot = monthly_category_totals(frame)
    if pivot.empty:
        return pd.DataFrame(columns=["month", "category", "amount", "prior_amount", "delta"])

    months = list(pivot.index)
    rows = []
    for i, month in enumerate(months):
        for category in pivot.columns:
            amount = pivot.loc[month, category]
            prior = pivot.loc[months[i - 1], category] if i > 0 else None
            delta = amount - prior if prior is not None else None
            rows.append(
                {
                    "month": month,
                    "category": category,
                    "amount": amount,
                    "prior_amount": prior if prior is not None else "",
                    "delta": delta if delta is not None else "",
                }
            )
    return pd.DataFrame(rows, columns=["month", "category", "amount", "prior_amount", "delta"])
