"""Transfer netting: pair up ``is_transfer`` rows across accounts.

Once BOI and Revolut rows share one frame, every internal move (top-up,
savings sweep, credit-card repayment) appears twice -- once per side, with
opposite signs. Downstream reporting must not treat both legs as spending
*and* income (the double-count bug this module exists to prevent), nor
silently drop a leg that never finds its partner.

Pairing rule (see the design spec, "Transfer netting"):

- Only rows with ``is_transfer`` truthy are candidates.
- Two rows pair when: opposite sign, equal absolute amount, different
  ``account``, and dates within ``window_days`` (default 3) of each other.
- Pairing is greedy by closest date first; each row pairs at most once.
- Unpaired transfer rows are returned separately (for the
  ``unmatched_transfers.csv`` report) -- never dropped, never counted as
  spend.

This module is a pure frame -> (frame, frame) transform. It expects
``frame`` to already have real dtypes, not the raw strings a CSV reader
produces: ``amount`` as ``Decimal``, ``date`` as ``datetime.date`` (or
``None``), ``account`` as ``str``, and ``is_transfer`` as ``bool``. The CLI
owns parsing the categorised CSV into that shape.
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

import pandas as pd

DEFAULT_WINDOW_DAYS = 3


@dataclasses.dataclass
class NettingResult:
    #: Copy of the input frame plus a ``pair_id`` column: an integer shared
    #: by the two rows of a matched transfer pair, or ``None`` for rows that
    #: are not part of a matched pair (including all non-transfer rows).
    netted: pd.DataFrame
    #: The subset of ``is_transfer`` rows that found no partner within the
    #: window, in original column order (no ``pair_id`` column). This is
    #: what the CLI writes to ``unmatched_transfers.csv``.
    unmatched: pd.DataFrame


def _candidate_pairs(
    frame: pd.DataFrame, transfer_idx: List[int], window_days: int
) -> List[Tuple[int, int, int]]:
    """Return (date-delta-days, i, j) for every i<j transfer-row pair that
    satisfies opposite-sign / equal-|amount| / different-account / within-
    window. Caller sorts by delta and greedily claims rows."""
    candidates: List[Tuple[int, int, int]] = []
    for a in range(len(transfer_idx)):
        i = transfer_idx[a]
        ai = frame.loc[i, "amount"]
        di = frame.loc[i, "date"]
        acct_i = frame.loc[i, "account"]
        if ai == 0 or di is None:
            continue
        for b in range(a + 1, len(transfer_idx)):
            j = transfer_idx[b]
            aj = frame.loc[j, "amount"]
            dj = frame.loc[j, "date"]
            if aj == 0 or dj is None:
                continue
            if (ai > 0) == (aj > 0):
                continue  # same sign -- not opposite legs of a transfer
            if abs(ai) != abs(aj):
                continue
            if acct_i == frame.loc[j, "account"]:
                continue  # must move between different accounts
            delta = abs((di - dj).days)
            if delta > window_days:
                continue
            candidates.append((delta, i, j))
    return candidates


def net_transfers(frame: pd.DataFrame, window_days: int = DEFAULT_WINDOW_DAYS) -> NettingResult:
    """Pair opposite-signed ``is_transfer`` rows; return the annotated frame
    plus the unpaired remainder.

    Greedy-by-closest-date: pairs are considered in ascending date-delta
    order, and a row already claimed by a closer match is skipped for any
    further candidate (this resolves three-or-more-way ambiguity in favour
    of the closest date, ties broken by original row order).
    """
    frame = frame.reset_index(drop=True)
    n = len(frame)

    transfer_idx = [i for i in range(n) if bool(frame.loc[i, "is_transfer"])]
    candidates = _candidate_pairs(frame, transfer_idx, window_days)
    candidates.sort(key=lambda c: c[0])  # stable sort keeps insertion-order ties

    pair_id: List[Optional[int]] = [None] * n
    claimed = set()
    next_id = 0
    for _delta, i, j in candidates:
        if i in claimed or j in claimed:
            continue
        claimed.add(i)
        claimed.add(j)
        pair_id[i] = next_id
        pair_id[j] = next_id
        next_id += 1

    netted = frame.copy()
    # Explicit object dtype: a plain list assignment lets pandas upcast
    # int/None to float64 NaN, which would blur "unmatched" (None) with
    # "matched, pair 0" (0.0) under naive equality checks downstream.
    netted["pair_id"] = pd.Series(pair_id, dtype="object", index=netted.index)

    transfer_set = set(transfer_idx)
    unmatched_mask = [i in transfer_set and pair_id[i] is None for i in range(n)]
    unmatched = netted.loc[unmatched_mask, frame.columns].reset_index(drop=True)

    return NettingResult(netted=netted, unmatched=unmatched)
