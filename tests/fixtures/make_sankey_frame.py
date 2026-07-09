"""Structural fixture for the sankey redesign: a synthetic categorised frame
shaped like the real data's problem cases -- many long-tail parent
categories, subcategories that mix "keep" and "fold" shares, person-name
transfer subcategories (which must never leak into node labels), paired
cross-account top-ups, and uncategorised rows. Every account/category/name
here is invented; nothing in this file is real statement data, so it is
exempt from the CLAUDE.md privacy rules and safe to read/print directly.

Shape (see docs/superpowers/specs/2026-07-09-sankey-redesign-design.md):

- 2 "real" income sources (Salary, Freelance) plus 5 long-tail "Gift NN"
  sources that must merge into "Other income" under the default min_share.
- 7 "big" spend parent categories (each far above the default 1% min_share)
  plus 29 long-tail "Misc NN" parents (each well under 1%, merging into
  "Other").
- 27 named subcategories across 4 of the big parents (Groceries, Dining,
  Transport, Utilities), split so each parent has a mix of subcategories
  that clear the default 0.5%-of-spend min_share_sub ("real") and ones
  that don't ("tail" -- folding back into the parent, no leaf node).
- 3 big parents (Rent, Insurance, Health) with no subcategory rows at all --
  they must terminate at the category layer, never inventing a "(none)"
  leaf.
- Groceries additionally carries one row with a blank subcategory amid its
  otherwise-subcategorised siblings, exercising the "no implicit parent-name
  leaf" rule.
- 30 matched transfer pairs between two accounts, each carrying a
  person-name subcategory (payee name) that must never surface as a node
  label -- paired transfers only ever produce an account->account link.
- 11 further person-name transfer legs (6 unpaired debits, 5 unpaired
  credits) that find no partner within the netting window -- these must
  aggregate into the single "Transfers (unmatched)" node, never leak the
  person name, and never be silently dropped.
- 25 uncategorised (blank category/subcategory) non-transfer rows.

Column shape matches what charts/cli.py's `_prepare_frame` produces from a
real categorised CSV: real dtypes (date as `datetime.date`, amount as
`Decimal`, is_transfer as `bool`), plus the `currency` column that is part
of the canonical schema (statement_parser/canonical.py) even though
charts/cli.py's REQUIRED_COLUMNS doesn't itself require it.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List

import pandas as pd

ACCOUNT_A = "checking_main"
ACCOUNT_B = "savings_side"

CURRENCY = "EUR"

START_DATE = date(2025, 1, 3)

# ---------------------------------------------------------------------
# Income: 2 real sources + a 5-way long tail that must merge to
# "Other income".
# ---------------------------------------------------------------------
INCOME_BIG = [
    ("Salary", Decimal("4000.00")),
    ("Freelance", Decimal("500.00")),
]
INCOME_TAIL = [(f"Gift {i:02d}", Decimal("15.00")) for i in range(1, 6)]  # 5

# ---------------------------------------------------------------------
# Spend parents with subcategories: each has a "real" set (clears
# min_share_sub) and a "tail" set (folds back into the parent).
# ---------------------------------------------------------------------
GROCERIES_REAL = [
    ("Fresh produce", Decimal("3000.00")),
    ("Meat and fish", Decimal("2200.00")),
    ("Pantry staples", Decimal("1800.00")),
    ("Household", Decimal("1200.00")),
    ("Bakery", Decimal("900.00")),
    ("Drinks", Decimal("600.00")),
]
GROCERIES_TAIL = [
    ("Coffee pods", Decimal("60.00")),
    ("Snacks", Decimal("55.00")),
    ("Spices", Decimal("50.00")),
    ("Other groceries", Decimal("45.00")),
]
GROCERIES_BLANK = Decimal("400.00")  # a row with no subcategory at all

DINING_REAL = [
    ("Restaurants", Decimal("1600.00")),
    ("Takeaway", Decimal("1100.00")),
    ("Coffee shops", Decimal("900.00")),
    ("Bars", Decimal("700.00")),
]
DINING_TAIL = [
    ("Snacks", Decimal("70.00")),
    ("Delivery fees", Decimal("65.00")),
    ("Tips", Decimal("60.00")),
    ("Other dining", Decimal("55.00")),
]

TRANSPORT_REAL = [
    ("Fuel", Decimal("1300.00")),
    ("Public transit", Decimal("1000.00")),
    ("Parking", Decimal("700.00")),
]
TRANSPORT_TAIL = [
    ("Tolls", Decimal("90.00")),
    ("Taxi", Decimal("80.00")),
    ("Bike share", Decimal("70.00")),
]

UTILITIES_REAL = [
    ("Electricity", Decimal("1400.00")),
    ("Gas and water", Decimal("1100.00")),
    ("Broadband", Decimal("600.00")),
]  # no tail here -- nothing folds under Utilities

# Big parents with no subcategory rows at all.
RENT_AMOUNT = Decimal("2600.00")
INSURANCE_AMOUNT = Decimal("1900.00")
HEALTH_AMOUNT = Decimal("1500.00")

TAIL_PARENT_COUNT = 29
TAIL_PARENT_AMOUNT = Decimal("150.00")
TAIL_PARENTS = [f"Misc {i:02d}" for i in range(1, TAIL_PARENT_COUNT + 1)]

UNCATEGORISED_COUNT = 25

PAIRED_TRANSFER_COUNT = 30
UNMATCHED_NEG_AMOUNTS = [
    Decimal(a) for a in ("45.00", "55.00", "65.00", "75.00", "85.00", "95.00")
]
UNMATCHED_POS_AMOUNTS = [Decimal(a) for a in ("30.00", "40.00", "50.00", "60.00", "70.00")]

#: 41 distinct payee names -- 30 used by the paired transfers, 11 by the
#: unmatched legs. Deliberately generic/synthetic, never a real name.
PERSON_NAMES = [f"Test Payee {i:02d}" for i in range(1, 42)]


def _row(
    d: date,
    description: str,
    amount: Decimal,
    account: str,
    category: str,
    subcategory: str,
    is_transfer: bool,
) -> Dict[str, object]:
    return {
        "date": d,
        "description": description,
        "amount": amount,
        "balance": None,
        "account": account,
        "category": category,
        "subcategory": subcategory,
        "is_transfer": is_transfer,
        "currency": CURRENCY,
    }


def make_sankey_frame() -> pd.DataFrame:
    """Build the structural fixture frame (pre-netting, real dtypes).

    Pass through ``charts.netting.net_transfers`` before handing to the
    sankey builder, exactly as ``charts/cli.py`` does for a real categorised
    CSV.
    """
    rows: List[Dict[str, object]] = []
    current_date = START_DATE

    def next_date() -> date:
        nonlocal current_date
        current_date = current_date + timedelta(days=1)
        return current_date

    # -- Income ----------------------------------------------------------
    for label, amount in INCOME_BIG:
        rows.append(_row(next_date(), f"income {label}", amount, ACCOUNT_A, "Income", label, False))
    for label, amount in INCOME_TAIL:
        rows.append(_row(next_date(), f"income {label}", amount, ACCOUNT_A, "Income", label, False))

    # -- Groceries: real + tail subcategories + one blank-subcategory row.
    for label, amount in GROCERIES_REAL:
        rows.append(_row(next_date(), f"spend {label}", -amount, ACCOUNT_A, "Groceries", label, False))
    for label, amount in GROCERIES_TAIL:
        rows.append(_row(next_date(), f"spend {label}", -amount, ACCOUNT_A, "Groceries", label, False))
    rows.append(
        _row(next_date(), "spend Groceries misc", -GROCERIES_BLANK, ACCOUNT_A, "Groceries", "", False)
    )

    # -- Dining.
    for label, amount in DINING_REAL:
        rows.append(_row(next_date(), f"spend {label}", -amount, ACCOUNT_A, "Dining", label, False))
    for label, amount in DINING_TAIL:
        rows.append(_row(next_date(), f"spend {label}", -amount, ACCOUNT_A, "Dining", label, False))

    # -- Transport.
    for label, amount in TRANSPORT_REAL:
        rows.append(_row(next_date(), f"spend {label}", -amount, ACCOUNT_A, "Transport", label, False))
    for label, amount in TRANSPORT_TAIL:
        rows.append(_row(next_date(), f"spend {label}", -amount, ACCOUNT_A, "Transport", label, False))

    # -- Utilities (no tail -- nothing folds here).
    for label, amount in UTILITIES_REAL:
        rows.append(_row(next_date(), f"spend {label}", -amount, ACCOUNT_A, "Utilities", label, False))

    # -- Big parents with no subcategory rows at all.
    rows.append(_row(next_date(), "spend Rent", -RENT_AMOUNT, ACCOUNT_A, "Rent", "", False))
    rows.append(_row(next_date(), "spend Insurance", -INSURANCE_AMOUNT, ACCOUNT_A, "Insurance", "", False))
    rows.append(_row(next_date(), "spend Health", -HEALTH_AMOUNT, ACCOUNT_A, "Health", "", False))

    # -- Long-tail parent categories -- each well under the 1% default share.
    for label in TAIL_PARENTS:
        rows.append(_row(next_date(), f"spend {label}", -TAIL_PARENT_AMOUNT, ACCOUNT_A, label, "", False))

    # -- Uncategorised rows.
    for i in range(1, UNCATEGORISED_COUNT + 1):
        amount = Decimal("25.00") + Decimal(i)
        rows.append(_row(next_date(), f"mystery {i}", -amount, ACCOUNT_A, "", "", False))

    # -- 30 matched transfer pairs across two accounts, each with a
    # person-name subcategory that must never surface as a node label.
    names = iter(PERSON_NAMES)
    for i in range(1, PAIRED_TRANSFER_COUNT + 1):
        amount = Decimal("100.00") + Decimal(i * 7)
        name = next(names)
        pair_date = next_date()
        payer, payee = (ACCOUNT_A, ACCOUNT_B) if i % 2 == 0 else (ACCOUNT_B, ACCOUNT_A)
        rows.append(_row(pair_date, f"transfer to {name}", -amount, payer, "Transfer", name, True))
        rows.append(_row(pair_date, f"transfer from {name}", amount, payee, "Transfer", name, True))

    # -- 6 unpaired debit legs. Amounts never collide with the paired range
    # or with the unpaired-credit range, so netting truly leaves them
    # unmatched regardless of date spacing.
    for amount in UNMATCHED_NEG_AMOUNTS:
        name = next(names)
        rows.append(_row(next_date(), f"transfer to {name}", -amount, ACCOUNT_A, "Transfer", name, True))

    # -- 5 unpaired credit legs.
    for amount in UNMATCHED_POS_AMOUNTS:
        name = next(names)
        rows.append(_row(next_date(), f"transfer from {name}", amount, ACCOUNT_B, "Transfer", name, True))

    remaining = list(names)
    assert not remaining, f"unused person names left over: {remaining}"

    return pd.DataFrame(rows)
