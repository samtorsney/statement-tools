"""Sankey diagram: categorised + netted frame -> plotly ``go.Figure``.

Pure builder -- no I/O. Expects the frame produced by
``charts.netting.net_transfers`` (i.e. it has a ``pair_id`` column: an
int shared by the two rows of a matched transfer, or ``NaN``/``None``
otherwise) plus the categorised-CSV columns ``account``, ``category``,
``subcategory``, ``is_transfer``, ``amount`` (``Decimal``).

Node layers, left to right:

  0. income sources   -- label = subcategory (falling back to category)
                          of non-transfer rows with amount > 0
  1. accounts
  2. parent categories -- non-transfer rows with amount < 0
  3. child categories   -- subcategory of the same rows

Matched transfer pairs render as direct account -> account links (source =
the paying leg's account, target = the receiving leg's account), bypassing
the category layers entirely. Unmatched transfer rows (``pair_id`` is
null) are excluded here -- they are surfaced only in the
``unmatched_transfers.csv`` report, never silently folded into spend or
income.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go

UNCATEGORISED = "(uncategorised)"
NO_SUBCATEGORY = "(none)"

LAYER_INCOME = 0
LAYER_ACCOUNT = 1
LAYER_CATEGORY = 2
LAYER_SUBCATEGORY = 3


def _income_label(category: str, subcategory: str) -> str:
    return subcategory or category or UNCATEGORISED


@dataclasses.dataclass
class NodeRegistry:
    """Assigns a stable integer index to each (layer, key) node, in
    first-seen order, while keeping a separate human-readable label."""

    _index: Dict[Tuple[int, object], int] = dataclasses.field(default_factory=dict)
    labels: List[str] = dataclasses.field(default_factory=list)
    layers: List[int] = dataclasses.field(default_factory=list)

    def get(self, layer: int, key: object, label: str) -> int:
        k = (layer, key)
        if k not in self._index:
            self._index[k] = len(self.labels)
            self.labels.append(label)
            self.layers.append(layer)
        return self._index[k]


LinkTotals = Dict[str, object]  # {"value": Decimal, "count": int}


def _add_link(
    links: Dict[Tuple[int, int], LinkTotals], src: int, dst: int, value: Decimal, count: int
) -> None:
    agg = links.setdefault((src, dst), {"value": Decimal("0"), "count": 0})
    agg["value"] += value
    agg["count"] += count


def aggregate(frame: pd.DataFrame) -> Tuple[NodeRegistry, Dict[Tuple[int, int], LinkTotals]]:
    """Aggregate `frame` into a node registry + link totals keyed by
    (source index, target index). Split out from `build_sankey` so tests
    (and the CLI, for the run summary) can inspect totals without touching
    plotly figure internals."""
    nodes = NodeRegistry()
    links: Dict[Tuple[int, int], LinkTotals] = {}

    is_transfer = frame["is_transfer"].astype(bool)
    paired = frame[is_transfer & frame["pair_id"].notna()]

    for _pair_id, group in paired.groupby("pair_id"):
        if len(group) != 2:
            continue  # malformed pairing -- ignore rather than guess
        row_a, row_b = (group.iloc[0], group.iloc[1])
        payer, payee = (row_a, row_b) if row_a["amount"] < 0 else (row_b, row_a)
        src = nodes.get(LAYER_ACCOUNT, str(payer["account"]), str(payer["account"]))
        dst = nodes.get(LAYER_ACCOUNT, str(payee["account"]), str(payee["account"]))
        _add_link(links, src, dst, abs(payer["amount"]), 2)

    for _, row in frame[~is_transfer].iterrows():
        amount = row["amount"]
        account = str(row["account"])
        category = row["category"] or ""
        subcategory = row["subcategory"] or ""

        if amount > 0:
            label = _income_label(category, subcategory)
            src = nodes.get(LAYER_INCOME, label, label)
            dst = nodes.get(LAYER_ACCOUNT, account, account)
            _add_link(links, src, dst, amount, 1)
        elif amount < 0:
            cat_label = category or UNCATEGORISED
            sub_label = subcategory or NO_SUBCATEGORY
            src1 = nodes.get(LAYER_ACCOUNT, account, account)
            dst1 = nodes.get(LAYER_CATEGORY, cat_label, cat_label)
            _add_link(links, src1, dst1, -amount, 1)

            src2 = nodes.get(LAYER_CATEGORY, cat_label, cat_label)
            dst2 = nodes.get(LAYER_SUBCATEGORY, (cat_label, sub_label), sub_label)
            _add_link(links, src2, dst2, -amount, 1)
        # amount == 0: no flow either way

    return nodes, links


def _node_totals(
    nodes: NodeRegistry, links: Dict[Tuple[int, int], LinkTotals]
) -> List[Tuple[float, int]]:
    totals = [(Decimal("0"), 0) for _ in nodes.labels]
    for (src, dst), agg in links.items():
        for idx in (src, dst):
            value, count = totals[idx]
            totals[idx] = (value + agg["value"], count + agg["count"])
    return [(float(v), c) for v, c in totals]


def build_sankey(frame: pd.DataFrame) -> go.Figure:
    """Build the Sankey `go.Figure`. Hover shows the flow amount and
    transaction count for both links and nodes."""
    nodes, links = aggregate(frame)

    sources: List[int] = []
    targets: List[int] = []
    values: List[float] = []
    link_customdata: List[List[float]] = []
    for (src, dst), agg in links.items():
        sources.append(src)
        targets.append(dst)
        values.append(float(agg["value"]))
        link_customdata.append([float(agg["value"]), agg["count"]])

    node_customdata = [[value, count] for value, count in _node_totals(nodes, links)]

    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    label=nodes.labels,
                    customdata=node_customdata,
                    hovertemplate="%{label}<br>total: %{customdata[0]:.2f}"
                    "<br>transactions: %{customdata[1]}<extra></extra>",
                ),
                link=dict(
                    source=sources,
                    target=targets,
                    value=values,
                    customdata=link_customdata,
                    hovertemplate="%{source.label} -> %{target.label}"
                    "<br>amount: %{customdata[0]:.2f}"
                    "<br>transactions: %{customdata[1]}<extra></extra>",
                ),
            )
        ]
    )
    return fig
