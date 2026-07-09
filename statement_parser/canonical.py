"""Canonical transaction schema + sign normalisation.

Every engine (PDF or CSV) produces a list of raw row dicts -- string values
keyed by canonical field name, plus `_page`/`_row` provenance -- and hands
them to `coerce_rows`, which is the single place amounts get parsed, dates
get parsed and forward-filled, missing balances get forward-computed, and
skip_rows filtering happens. This is also where the profile's `in_out` ->
signed-Decimal convention lives, so downstream code never sees per-bank
amount conventions.
"""
from __future__ import annotations

import dataclasses
from datetime import date as Date
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from .engine import strategies
from .errors import CoercionError
from .profile import Profile


@dataclasses.dataclass
class CanonicalRow:
    date: Optional[Date]
    description: str
    amount: Decimal
    balance: Optional[Decimal]
    currency: Optional[str]
    account: str
    source_file: str
    page: Optional[int]
    row: int


def parse_decimal(text: Optional[str], thousands: str, decimal: str) -> Optional[Decimal]:
    """Parse a raw amount/balance cell into a Decimal, or None if blank.

    Handles a thousands separator, a (possibly non-'.') decimal separator,
    and parenthesised negatives (`(12.34)` -> -12.34).
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    if thousands:
        text = text.replace(thousands, "")
    if decimal and decimal != ".":
        text = text.replace(decimal, ".")
    text = text.replace(" ", "")

    if text.startswith("+"):
        text = text[1:]
    if not text or text in ("-", "."):
        return None

    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        # Deliberately do not include the raw text in this message: it may
        # be a fragment of real statement content (e.g. non-transaction
        # footer/subtotal text a table-boundary heuristic failed to
        # exclude), and this error can propagate into logs/tracebacks.
        raise CoercionError(
            f"cannot parse amount/balance text ({len(text)} char(s))"
        ) from exc

    if negative:
        value = -value
    return value


def _parse_dates(raw_rows: List[dict], profile: Profile) -> List[Optional[Date]]:
    fmt = profile.dates.format
    parsed: List[Optional[Date]] = []
    for r in raw_rows:
        text = (r.get("date") or "").strip()
        if not text:
            parsed.append(None)
            continue
        try:
            parsed.append(datetime.strptime(text, fmt).date())
        except ValueError as exc:
            # Do not include the raw text (see parse_decimal for why).
            raise CoercionError(
                f"cannot parse a date cell ({len(text)} char(s)) with format {fmt!r}"
            ) from exc

    fill_fn = strategies.DATE_FILL[profile.dates.fill]
    return fill_fn(parsed)


def _compute_amounts_and_balances(raw_rows: List[dict], profile: Profile):
    style = profile.amounts.style
    thousands = profile.amounts.thousands
    decimal = profile.amounts.decimal

    amounts: List[Decimal] = []
    balances: List[Optional[Decimal]] = []

    for r in raw_rows:
        balance = None
        if profile.balance.present:
            balance = parse_decimal(r.get("balance", ""), thousands, decimal)

        if style == "in_out":
            out_val = parse_decimal(r.get("out", ""), thousands, decimal) or Decimal("0")
            in_val = parse_decimal(r.get("in", ""), thousands, decimal) or Decimal("0")
            amount = in_val - out_val
        elif style == "signed":
            amount = parse_decimal(r.get("amount", ""), thousands, decimal)
            if amount is None:
                raise CoercionError(
                    "amounts.style is 'signed' but a row has a blank amount"
                )
        else:  # pragma: no cover - profile validation already rejects this
            raise CoercionError(f"unknown amounts.style {style!r}")

        amounts.append(amount)
        balances.append(balance)

    return amounts, balances


def _fill_balances(balances: List[Optional[Decimal]], amounts: List[Decimal]) -> List[Optional[Decimal]]:
    """Forward-compute any missing balance from the previous row's balance
    plus this row's signed amount (mirrors legacy calculate_balance)."""
    filled = list(balances)
    for i in range(1, len(filled)):
        if filled[i] is None and filled[i - 1] is not None:
            filled[i] = filled[i - 1] + amounts[i]
    return filled


def _matches_skip_rule(row: dict, rule) -> bool:
    return row.get(rule.field, "") == rule.equals


def coerce_rows(raw_rows: List[dict], profile: Profile, source_file: str) -> List[CanonicalRow]:
    """Turn raw string-valued row dicts (in document order) into canonical
    rows: parse dates (with forward fill), parse/sign amounts, forward-fill
    missing balances, then apply skip_rows -- in that order, matching the
    legacy parser so rows used as fill seeds (e.g. BALANCE FORWARD) still
    contribute their values before being dropped.
    """
    if not raw_rows:
        return []

    dates = _parse_dates(raw_rows, profile)
    amounts, balances = _compute_amounts_and_balances(raw_rows, profile)
    if profile.balance.present:
        balances = _fill_balances(balances, amounts)

    result: List[CanonicalRow] = []
    for i, r in enumerate(raw_rows):
        if any(_matches_skip_rule(r, rule) for rule in profile.skip_rows):
            continue
        result.append(
            CanonicalRow(
                date=dates[i],
                description=(r.get("description") or "").strip(),
                amount=amounts[i],
                balance=balances[i] if profile.balance.present else None,
                currency=(r.get("currency") or None),
                account=profile.meta.name,
                source_file=source_file,
                page=r.get("_page"),
                row=r.get("_row"),
            )
        )
    return result
