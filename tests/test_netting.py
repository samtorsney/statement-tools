"""Transfer-pairing semantics, exercised on synthetic frames only (fake
accounts, fake amounts, fake dates)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from charts.netting import net_transfers


def frame_of(rows):
    """rows: list of (date, amount, account, is_transfer) tuples."""
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "amount": [Decimal(str(r[1])) for r in rows],
            "account": [r[2] for r in rows],
            "is_transfer": [r[3] for r in rows],
        }
    )


def test_exact_pair_same_date():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 5), "100.00", "revolut_current", True),
        ]
    )
    result = net_transfers(frame)
    assert list(result.netted["pair_id"]) == [0, 0]
    assert len(result.unmatched) == 0


def test_cross_month_pair_within_window():
    # Dec 30 -> Jan 1 is 2 days apart, crossing a month boundary; within the
    # default +-3 day window.
    frame = frame_of(
        [
            (date(2025, 12, 30), "-250.00", "boi_current", True),
            (date(2026, 1, 1), "250.00", "revolut_current", True),
        ]
    )
    result = net_transfers(frame)
    assert list(result.netted["pair_id"]) == [0, 0]
    assert len(result.unmatched) == 0


def test_outside_window_does_not_pair():
    frame = frame_of(
        [
            (date(2026, 1, 1), "-250.00", "boi_current", True),
            (date(2026, 1, 5), "250.00", "revolut_current", True),  # 4 days > default 3
        ]
    )
    result = net_transfers(frame)
    assert list(result.netted["pair_id"]) == [None, None]
    assert len(result.unmatched) == 2


def test_amount_mismatch_does_not_pair():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 5), "99.99", "revolut_current", True),
        ]
    )
    result = net_transfers(frame)
    assert list(result.netted["pair_id"]) == [None, None]
    unmatched_amounts = sorted(str(a) for a in result.unmatched["amount"])
    assert unmatched_amounts == ["-100.00", "99.99"]


def test_same_account_does_not_pair():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 5), "100.00", "boi_current", True),
        ]
    )
    result = net_transfers(frame)
    assert list(result.netted["pair_id"]) == [None, None]
    assert len(result.unmatched) == 2


def test_three_way_ambiguity_greedy_closest_date_wins():
    # Row 0 (-100 on Jan 5) could pair with row 1 (+100 on Jan 6, 1 day away)
    # or row 2 (+100 on Jan 8, 3 days away). Both are inside the window, but
    # the closer one should be claimed, leaving row 2 unpaired.
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 6), "100.00", "revolut_current", True),
            (date(2026, 1, 8), "100.00", "revolut_current", True),
        ]
    )
    result = net_transfers(frame)
    assert list(result.netted["pair_id"]) == [0, 0, None]
    assert len(result.unmatched) == 1
    assert result.unmatched.iloc[0]["amount"] == Decimal("100.00")


def test_unpaired_transfer_row_reported_unmatched_others_untouched():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 5), "100.00", "revolut_current", True),
            (date(2026, 1, 10), "-42.00", "boi_current", True),  # no partner
            (date(2026, 1, 5), "-30.00", "boi_current", False),  # not a transfer at all
        ]
    )
    result = net_transfers(frame)
    assert list(result.netted["pair_id"]) == [0, 0, None, None]
    assert len(result.unmatched) == 1
    assert result.unmatched.iloc[0]["amount"] == Decimal("-42.00")
    # Non-transfer rows never appear in the unmatched report even if unpaired.
    assert False not in result.unmatched["is_transfer"].tolist()


def test_each_row_pairs_at_most_once():
    # Three -100 legs and one +100 leg on the same date/account-pair: only
    # one -100 can be claimed, the other two are unmatched.
    frame = frame_of(
        [
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 5), "-100.00", "boi_current", True),
            (date(2026, 1, 5), "100.00", "revolut_current", True),
        ]
    )
    result = net_transfers(frame)
    pair_ids = list(result.netted["pair_id"])
    assert pair_ids.count(None) == 2
    assert sum(1 for p in pair_ids if p is not None) == 2
    assert len(result.unmatched) == 2


def test_extra_columns_survive_in_unmatched():
    frame = frame_of(
        [(date(2026, 1, 5), "-42.00", "boi_current", True)]
    )
    frame["description"] = ["FAKE UNPAIRED TRANSFER"]
    result = net_transfers(frame)
    assert list(result.unmatched.columns) == list(frame.columns)
    assert result.unmatched.iloc[0]["description"] == "FAKE UNPAIRED TRANSFER"
