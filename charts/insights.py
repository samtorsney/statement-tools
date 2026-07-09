"""Overview-page insights: pure computation only, no HTML.

Every function here takes a frame with the same real dtypes the other
``charts`` modules expect (``amount``/``balance`` as ``Decimal`` or
``None``, ``date`` as ``datetime.date`` or ``None``, ``account``/
``category``/``subcategory``/``description``/``currency`` as ``str``,
``is_transfer`` as ``bool``) and returns a typed dataclass -- never a
plotly figure, never an HTML string. ``charts/overview.py`` is the only
caller that turns these into markup.

"Spend" and "income" mean the same thing they do in ``charts.monthly``
and ``charts.sankey``: non-transfer rows, negative/positive amount
respectively. Transfer rows (``is_transfer`` true, matched or not) are
excluded from every figure in this module -- a transfer is a reshuffle
between accounts, never income or spend.
"""
from __future__ import annotations

import dataclasses
from datetime import date as Date
from datetime import timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Union

import pandas as pd

UNCATEGORISED = "(uncategorised)"

DEFAULT_RANKING_TOP_N = 10
DEFAULT_MOVERS_TOP_N = 5


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _is_transfer(frame: pd.DataFrame) -> pd.Series:
    return frame["is_transfer"].astype(bool)


def _spend_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Non-transfer, negative-amount rows -- same universe as
    ``charts.monthly.spend_rows``."""
    is_transfer = _is_transfer(frame)
    return frame[(~is_transfer) & (frame["amount"] < 0)]


def _income_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Non-transfer, positive-amount rows."""
    is_transfer = _is_transfer(frame)
    return frame[(~is_transfer) & (frame["amount"] > 0)]


def _decimal_sum(values) -> Decimal:
    total = Decimal("0")
    for v in values:
        total += v
    return total


def _category_label(category: object) -> str:
    text = (category or "").strip() if isinstance(category, str) else ""
    return text or UNCATEGORISED


def detect_currency(frame: pd.DataFrame) -> Optional[str]:
    """Return the one shared currency code if every non-blank ``currency``
    value in `frame` agrees, else ``None`` (mixed values, or no row has a
    currency recorded at all)."""
    if "currency" not in frame.columns:
        return None
    values = {str(c).strip() for c in frame["currency"] if str(c).strip()}
    if len(values) == 1:
        return next(iter(values))
    return None


# --------------------------------------------------------------------------
# Stat tiles
# --------------------------------------------------------------------------


@dataclasses.dataclass
class Tiles:
    income: Decimal
    spend: Decimal
    net: Decimal
    #: ``None`` is the zero-income sentinel -- render "--", never a
    #: division by zero or a misleading 0%.
    savings_rate: Optional[Decimal]
    #: Shared currency code across every in-range row, or ``None`` when
    #: currency is mixed or absent (bare numbers + a header note in that case).
    currency: Optional[str]


def stat_tiles(frame: pd.DataFrame) -> Tiles:
    """Income/spend/net/savings-rate over `frame` (already filtered to the
    requested date range). Transfer rows are excluded from all four."""
    income = _decimal_sum(_income_rows(frame)["amount"])
    spend = -_decimal_sum(_spend_rows(frame)["amount"])
    net = income - spend
    savings_rate = None if income == 0 else (net / income)
    currency = detect_currency(frame)
    return Tiles(income=income, spend=spend, net=net, savings_rate=savings_rate, currency=currency)


# --------------------------------------------------------------------------
# Rankings
# --------------------------------------------------------------------------


@dataclasses.dataclass
class CategoryAmount:
    category: str
    amount: Decimal


@dataclasses.dataclass
class MerchantAmount:
    description: str
    amount: Decimal


@dataclasses.dataclass
class Rankings:
    top_categories: List[CategoryAmount]
    top_merchants: List[MerchantAmount]


def _top_n_by_amount(totals: Dict[str, Decimal], top_n: int) -> List:
    """Sort by amount desc, ties broken alphabetically by key (stable,
    deterministic) -- returns (key, amount) pairs."""
    ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered[:top_n]


def rankings(frame: pd.DataFrame, top_n: int = DEFAULT_RANKING_TOP_N) -> Rankings:
    """Top categories and top merchants by spend (non-transfer, negative
    amount), each capped at `top_n`."""
    spend = _spend_rows(frame)
    if spend.empty:
        return Rankings(top_categories=[], top_merchants=[])

    cat_totals: Dict[str, Decimal] = {}
    merchant_totals: Dict[str, Decimal] = {}
    for category, description, amount in zip(spend["category"], spend["description"], spend["amount"]):
        magnitude = -amount
        cat_key = _category_label(category)
        cat_totals[cat_key] = cat_totals.get(cat_key, Decimal("0")) + magnitude
        merch_key = str(description)
        merchant_totals[merch_key] = merchant_totals.get(merch_key, Decimal("0")) + magnitude

    top_categories = [
        CategoryAmount(category=k, amount=v) for k, v in _top_n_by_amount(cat_totals, top_n)
    ]
    top_merchants = [
        MerchantAmount(description=k, amount=v) for k, v in _top_n_by_amount(merchant_totals, top_n)
    ]
    return Rankings(top_categories=top_categories, top_merchants=top_merchants)


# --------------------------------------------------------------------------
# Movers (vs preceding equal-length window)
# --------------------------------------------------------------------------


@dataclasses.dataclass
class CategoryDelta:
    category: str
    current: Decimal
    prior: Decimal
    delta: Decimal


@dataclasses.dataclass
class Movers:
    window_days: int
    #: Top 5 (or `top_n`) categories whose spend rose, delta desc.
    increases: List[CategoryDelta]
    #: Top 5 (or `top_n`) categories whose spend fell, delta asc (most
    #: negative first).
    decreases: List[CategoryDelta]


class NoPriorCoverage:
    """Sentinel returned by `movers` when the preceding comparison window
    has no rows at all -- never a table of misleading zeros."""

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "NoPriorCoverage()"

    def __eq__(self, other) -> bool:
        return isinstance(other, NoPriorCoverage)


def _category_spend_totals(frame: pd.DataFrame) -> Dict[str, Decimal]:
    spend = _spend_rows(frame)
    totals: Dict[str, Decimal] = {}
    for category, amount in zip(spend["category"], spend["amount"]):
        key = _category_label(category)
        totals[key] = totals.get(key, Decimal("0")) + (-amount)
    return totals


def movers(
    full_frame: pd.DataFrame,
    date_from: Date,
    date_to: Date,
    top_n: int = DEFAULT_MOVERS_TOP_N,
) -> Union[Movers, NoPriorCoverage]:
    """Per-parent-category spend deltas between `[date_from, date_to]` and
    the immediately preceding window of the same length (in days).

    `full_frame` must not be pre-filtered to the requested range -- this
    function does its own windowing so it can see the preceding period.
    """
    window_days = (date_to - date_from).days + 1
    prior_to = date_from - timedelta(days=1)
    prior_from = prior_to - timedelta(days=window_days - 1)

    dates = full_frame["date"]
    current_mask = dates.map(lambda d: d is not None and date_from <= d <= date_to)
    prior_mask = dates.map(lambda d: d is not None and prior_from <= d <= prior_to)

    prior_frame = full_frame[prior_mask]
    if prior_frame.empty:
        return NoPriorCoverage()

    current_frame = full_frame[current_mask]

    current_totals = _category_spend_totals(current_frame)
    prior_totals = _category_spend_totals(prior_frame)

    categories = set(current_totals) | set(prior_totals)
    deltas = []
    for category in categories:
        current = current_totals.get(category, Decimal("0"))
        prior = prior_totals.get(category, Decimal("0"))
        deltas.append(CategoryDelta(category=category, current=current, prior=prior, delta=current - prior))

    increases = sorted(
        (d for d in deltas if d.delta > 0), key=lambda d: (-d.delta, d.category)
    )[:top_n]
    decreases = sorted(
        (d for d in deltas if d.delta < 0), key=lambda d: (d.delta, d.category)
    )[:top_n]

    return Movers(window_days=window_days, increases=increases, decreases=decreases)


# --------------------------------------------------------------------------
# Notable transactions
# --------------------------------------------------------------------------


@dataclasses.dataclass
class Notable:
    date: Optional[Date]
    account: str
    description: str
    category: str
    amount: Decimal


def notables(frame: pd.DataFrame, top_n: int = DEFAULT_RANKING_TOP_N) -> List[Notable]:
    """Top `top_n` non-transfer rows by absolute amount, largest first."""
    is_transfer = _is_transfer(frame)
    candidates = frame[~is_transfer]
    if candidates.empty:
        return []

    rows = list(candidates.itertuples(index=False))
    columns = list(candidates.columns)

    def _get(row, name):
        return getattr(row, name) if name in columns else None

    ranked = sorted(rows, key=lambda r: -abs(_get(r, "amount")))
    out: List[Notable] = []
    for row in ranked[:top_n]:
        out.append(
            Notable(
                date=_get(row, "date"),
                account=str(_get(row, "account")),
                description=str(_get(row, "description")),
                category=_category_label(_get(row, "category")),
                amount=_get(row, "amount"),
            )
        )
    return out


# --------------------------------------------------------------------------
# Data-health panel
# --------------------------------------------------------------------------


@dataclasses.dataclass
class AccountCoverage:
    account: str
    first_date: Optional[Date]
    last_date: Optional[Date]
    row_count: int


@dataclasses.dataclass
class Health:
    uncategorised_count: int
    uncategorised_total_abs: Decimal
    unmatched_transfer_count: int
    accounts: List[AccountCoverage]


def health(in_range_frame: pd.DataFrame, unmatched_frame: pd.DataFrame) -> Health:
    """Data-health figures for `in_range_frame` (the already date-filtered,
    already-netted frame) plus its companion `unmatched_frame` (the same
    netting run's unpaired-transfer output)."""
    is_transfer = _is_transfer(in_range_frame)
    uncategorised_mask = (~is_transfer) & (
        in_range_frame["category"].map(lambda c: not (c or "").strip())
    )
    uncategorised = in_range_frame[uncategorised_mask]
    uncategorised_count = int(len(uncategorised))
    uncategorised_total_abs = _decimal_sum(abs(a) for a in uncategorised["amount"])

    unmatched_transfer_count = int(len(unmatched_frame))

    accounts: List[AccountCoverage] = []
    if len(in_range_frame):
        for account, group in in_range_frame.groupby("account"):
            dates = [d for d in group["date"] if d is not None]
            accounts.append(
                AccountCoverage(
                    account=str(account),
                    first_date=min(dates) if dates else None,
                    last_date=max(dates) if dates else None,
                    row_count=int(len(group)),
                )
            )
        accounts.sort(key=lambda a: a.account)

    return Health(
        uncategorised_count=uncategorised_count,
        uncategorised_total_abs=uncategorised_total_abs,
        unmatched_transfer_count=unmatched_transfer_count,
        accounts=accounts,
    )
