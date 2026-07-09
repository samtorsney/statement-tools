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
  2. parent categories -- non-transfer rows with amount < 0, plus the two
                           fixed buckets described below
  3. child categories   -- subcategory of the same rows, when they clear
                           ``min_share_sub``

Matched transfer pairs render as direct account -> account links,
bypassing the category layers entirely -- aggregated per account pair into
a SINGLE link in the NET direction. Both directions' gross flows are
summed first; one ribbon is drawn for ``|gross A->B - gross B->A|``,
pointing whichever way the net flows, and the link's hover text carries
both gross amounts alongside the net. This replaces the earlier
one-link-per-direction rendering, which drew a huge U-shaped loop between
the two same-layer account nodes whenever pairs flowed both ways. If the
two directions exactly offset (net == 0), no ribbon is drawn at all --
there is no flow for hover data to attach to; the overview's health panel
still reports transfer volume.

Unmatched transfer legs (``pair_id`` is null) are no longer dropped: every
one of them is aggregated into a single ``Transfers (unmatched)`` node at
the parent-category layer, never labelled with the row's own
category/subcategory (which may be a person/payee name -- names must never
become nodes). By convention this one node carries *both* directions:
an unpaired debit leg (money left an account without a partner) flows
account -> node; an unpaired credit leg (money arrived without a partner)
flows node -> account. This makes the node's in/out layer-order
inconsistent with the pure left-to-right income->account->category->
subcategory progression (a "backward" ribbon for credit legs) -- that is a
deliberate, documented trade-off in exchange for correctness (unmatched
transfers must be visible and never silently folded into spend or income).
It is safe here because node positions are pinned explicitly
(``arrangement="fixed"``, see below) rather than left to plotly's automatic
depth detection, so the backward ribbon is just a curve, not a layout
error. The alternative of splitting unmatched credit legs onto a second,
income-layer node was rejected because the spec calls for exactly *one*
"Transfers (unmatched)" node, not two.

Small-share aggregation (``min_share`` / ``min_share_sub``): a parent
category (or income source) whose share of total non-transfer spend (or
income) falls below ``min_share`` merges into a single "Other" ("Other
income" on the income side) node -- never its own node, never a fraction of
one. Within a kept parent, a subcategory whose share of total spend falls
below ``min_share_sub`` folds back into the parent: its value still counts
towards the parent's total (via the account->category link) but never gets
its own category->subcategory link or node. A category with no
subcategory rows at all (or only merged/folded ones) simply terminates at
the category layer -- there is no "(none)" placeholder, ever.
"(uncategorised)" is exempt from ``min_share`` merging: it is a data-health
signal, not a size ranking, so it always gets its own node when any
uncategorised rows exist.

Node ordering, height and color follow the ``dataviz`` skill:

- Nodes are sorted by total size (descending) within each layer, and given
  explicit ``x``/``y`` coordinates (``arrangement="fixed"``) so this order
  is exactly what renders -- not merely a hint to plotly's own crossing-
  minimising layout.
- Figure height is derived from the busiest layer's node count (with a
  floor), instead of one fixed constant, so a dense subcategory layer gets
  room to breathe.
- Parent categories are assigned one hue each, in size order, from the
  categorical palette (see the ``dataviz`` skill's ``references/
  palette.md``), minus its first slot (reserved for the income family so
  the two node families never share a hue). Subcategory nodes inherit a
  lighter tint of their parent's hue. Links are tinted at low alpha by
  whichever endpoint carries identity: a link leaving an account node
  takes its DESTINATION's hue (otherwise the neutral account gray would
  dominate the diagram's ink -- account->category links are most of the
  drawn area), while every other link takes its SOURCE's hue (income->
  account keeps the income hue, category->subcategory keeps the parent
  hue, unmatched-credit node->account keeps the warning hue). Net
  account->account transfer ribbons stay neutral gray -- both endpoints
  are accounts, so there is no identity to carry. Accounts are neutral
  gray. "(uncategorised)"
  and "Transfers (unmatched)" use the fixed status "warning" color, never
  reused for anything else. "Other" / "Other income" use a separate
  neutral tone (distinct from both the account gray and the warning color)
  so a reader never mistakes an aggregation bucket for a data-quality
  problem.
- Node labels append a compact amount (e.g. "Groceries · 7.0k"), with a
  currency symbol prefix when the frame's currency is uniform.

Scope note: the returned figure uses fixed (light-mode) hex colors -- it
does not repaint itself for a dark host page the way the surrounding HTML
chrome (see ``charts/overview.py``) does via CSS custom properties. Plotly
bakes mark colors into the SVG at render time; making the figure itself
theme-reactive would need a second render path and is out of scope here.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import plotly.graph_objects as go

from .insights import detect_currency

UNCATEGORISED = "(uncategorised)"
OTHER = "Other"
OTHER_INCOME = "Other income"
TRANSFERS_UNMATCHED = "Transfers (unmatched)"

LAYER_INCOME = 0
LAYER_ACCOUNT = 1
LAYER_CATEGORY = 2
LAYER_SUBCATEGORY = 3

DEFAULT_MIN_SHARE = Decimal("0.01")
DEFAULT_MIN_SHARE_SUB = Decimal("0.005")

# -- Color system (dataviz skill categorical palette, light mode) ---------
# Slot 0 (blue) is reserved for the income family; parent spend categories
# draw from the remaining 7 slots, in size order, never cycling back to
# blue (an 8th+ parent falls back to modulo re-use, noted below, but the
# fixture this build ships with never exceeds 7 real parents).
_CATEGORICAL = [
    "#2a78d6",  # blue    -- reserved for income
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
    "#e87ba4",  # magenta
    "#eb6834",  # orange
]
INCOME_HUE = _CATEGORICAL[0]
SPEND_PALETTE = _CATEGORICAL[1:]

ACCOUNT_NEUTRAL = "#898781"
OTHER_NEUTRAL = "#c3c2b7"
WARNING_COLOR = "#fab219"

LINK_ALPHA = 0.35
SUBCATEGORY_TINT = 0.55

CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}

MIN_HEIGHT = 500
PX_PER_NODE = 26
HEIGHT_MARGIN = 160


def _as_decimal(value: Union[Decimal, float, str]) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _income_label(category: str, subcategory: str) -> str:
    return subcategory or category or UNCATEGORISED


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _tint(hex_color: str, amount: float = SUBCATEGORY_TINT) -> str:
    """Lighten `hex_color` towards white by `amount` (0..1)."""
    r, g, b = _hex_to_rgb(hex_color)
    r = round(r + (255 - r) * amount)
    g = round(g + (255 - g) * amount)
    b = round(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha})"


def _format_amount(value: float, currency: Optional[str]) -> str:
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        compact = f"{magnitude / 1_000_000:.1f}M"
    elif magnitude >= 1_000:
        compact = f"{magnitude / 1_000:.1f}k"
    elif magnitude >= 10:
        compact = f"{magnitude:.0f}"
    else:
        compact = f"{magnitude:.2f}"
    if currency:
        symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
        return f"{symbol}{compact}"
    return compact


def _node_label(name: str, value: float, currency: Optional[str]) -> str:
    return f"{name} · {_format_amount(value, currency)}"


@dataclasses.dataclass
class NodeRegistry:
    """Assigns a stable integer index to each (layer, key) node, in
    first-seen order, while keeping a separate human-readable label, a
    color "role" (for the color system), and the raw key (so a
    subcategory node can look up its parent's key for tinting)."""

    _index: Dict[Tuple[int, object], int] = dataclasses.field(default_factory=dict)
    labels: List[str] = dataclasses.field(default_factory=list)
    layers: List[int] = dataclasses.field(default_factory=list)
    roles: List[str] = dataclasses.field(default_factory=list)
    keys: List[object] = dataclasses.field(default_factory=list)

    def get(self, layer: int, key: object, label: str, role: str = "category") -> int:
        k = (layer, key)
        if k not in self._index:
            self._index[k] = len(self.labels)
            self.labels.append(label)
            self.layers.append(layer)
            self.roles.append(role)
            self.keys.append(key)
        return self._index[k]


# {"value": Decimal, "count": int}; net account->account transfer links
# additionally carry {"gross_with": Decimal, "gross_against": Decimal} --
# the gross flow with and against the drawn (net) direction.
LinkTotals = Dict[str, object]


def _add_link(
    links: Dict[Tuple[int, int], LinkTotals], src: int, dst: int, value: Decimal, count: int
) -> None:
    agg = links.setdefault((src, dst), {"value": Decimal("0"), "count": 0})
    agg["value"] += value
    agg["count"] += count


def aggregate(
    frame: pd.DataFrame,
    *,
    min_share: Union[Decimal, float] = DEFAULT_MIN_SHARE,
    min_share_sub: Union[Decimal, float] = DEFAULT_MIN_SHARE_SUB,
) -> Tuple[NodeRegistry, Dict[Tuple[int, int], LinkTotals]]:
    """Aggregate `frame` into a node registry + link totals keyed by
    (source index, target index). Split out from `build_sankey` so tests
    (and the CLI, for the run summary) can inspect totals without touching
    plotly figure internals."""
    min_share = _as_decimal(min_share)
    min_share_sub = _as_decimal(min_share_sub)

    nodes = NodeRegistry()
    links: Dict[Tuple[int, int], LinkTotals] = {}

    is_transfer = frame["is_transfer"].astype(bool)

    # -- Matched transfer pairs: ONE net-direction link per account pair
    # (see module docstring). Gross both-way totals ride along on the link
    # so build_sankey can surface them in the hover text. ------------------
    paired = frame[is_transfer & frame["pair_id"].notna()]
    pair_gross: Dict[Tuple[str, str], Dict[str, object]] = {}
    for _pair_id, group in paired.groupby("pair_id"):
        if len(group) != 2:
            continue  # malformed pairing -- ignore rather than guess
        row_a, row_b = (group.iloc[0], group.iloc[1])
        payer, payee = (row_a, row_b) if row_a["amount"] < 0 else (row_b, row_a)
        payer_acct, payee_acct = str(payer["account"]), str(payee["account"])
        key = (payer_acct, payee_acct) if payer_acct <= payee_acct else (payee_acct, payer_acct)
        gross = pair_gross.setdefault(key, {"fwd": Decimal("0"), "rev": Decimal("0"), "count": 0})
        direction = "fwd" if (payer_acct, payee_acct) == key else "rev"
        gross[direction] += abs(payer["amount"])
        gross["count"] += 2

    for (acct_a, acct_b), gross in pair_gross.items():
        net = gross["fwd"] - gross["rev"]
        if net == 0:
            continue  # fully offsetting flows: nothing to draw (documented)
        if net > 0:
            src_acct, dst_acct = acct_a, acct_b
            gross_with, gross_against = gross["fwd"], gross["rev"]
        else:
            src_acct, dst_acct = acct_b, acct_a
            gross_with, gross_against = gross["rev"], gross["fwd"]
        src = nodes.get(LAYER_ACCOUNT, src_acct, src_acct, "account")
        dst = nodes.get(LAYER_ACCOUNT, dst_acct, dst_acct, "account")
        _add_link(links, src, dst, abs(net), gross["count"])
        # Gross both-way flow, oriented to the drawn (net) direction.
        links[(src, dst)]["gross_with"] = gross_with
        links[(src, dst)]["gross_against"] = gross_against

    # -- Unmatched transfer legs: one aggregate node, never the row's own
    # category/subcategory text (which may be a person/payee name). ------
    unmatched = frame[is_transfer & frame["pair_id"].isna()]
    xfer_key = "__transfers_unmatched__"
    for _, row in unmatched.iterrows():
        amount = row["amount"]
        if amount == 0:
            continue
        account = str(row["account"])
        acct_idx = nodes.get(LAYER_ACCOUNT, account, account, "account")
        xfer_idx = nodes.get(LAYER_CATEGORY, xfer_key, TRANSFERS_UNMATCHED, "warning")
        if amount < 0:
            _add_link(links, acct_idx, xfer_idx, -amount, 1)
        else:
            _add_link(links, xfer_idx, acct_idx, amount, 1)

    non_transfer = frame[~is_transfer]

    # -- Income: aggregate per (account, label); merge low-share labels
    # into "Other income" using each label's GLOBAL (cross-account) share.
    income_rows = non_transfer[non_transfer["amount"] > 0]
    income_label_totals: Dict[str, Decimal] = {}
    income_link_raw: Dict[Tuple[str, str], Tuple[Decimal, int]] = {}
    for _, row in income_rows.iterrows():
        label = _income_label(row["category"] or "", row["subcategory"] or "")
        account = str(row["account"])
        amount = row["amount"]
        income_label_totals[label] = income_label_totals.get(label, Decimal("0")) + amount
        v, c = income_link_raw.get((account, label), (Decimal("0"), 0))
        income_link_raw[(account, label)] = (v + amount, c + 1)

    total_income = sum(income_label_totals.values()) if income_label_totals else Decimal("0")
    merged_income_labels = set()
    if total_income > 0:
        for label, total in income_label_totals.items():
            if total / total_income < min_share:
                merged_income_labels.add(label)

    for (account, label), (value, count) in income_link_raw.items():
        merged = label in merged_income_labels
        display_label = OTHER_INCOME if merged else label
        role = "other" if merged else "income"
        src = nodes.get(LAYER_INCOME, display_label, display_label, role)
        dst = nodes.get(LAYER_ACCOUNT, account, account, "account")
        _add_link(links, src, dst, value, count)

    # -- Spend: same two-pass shape (global share for merge decisions,
    # then build the actual per-account/per-subcategory links). ----------
    spend_rows = non_transfer[non_transfer["amount"] < 0]

    category_totals: Dict[str, Decimal] = {}
    for _, row in spend_rows.iterrows():
        cat = row["category"] or ""
        label = UNCATEGORISED if cat == "" else cat
        category_totals[label] = category_totals.get(label, Decimal("0")) + (-row["amount"])

    total_spend = sum(category_totals.values()) if category_totals else Decimal("0")
    merged_categories = set()
    if total_spend > 0:
        for label, total in category_totals.items():
            if label == UNCATEGORISED:
                continue  # a data-health signal, never merged away
            if total / total_spend < min_share:
                merged_categories.add(label)

    def _display_label(cat: str) -> str:
        label = UNCATEGORISED if cat == "" else cat
        if label == UNCATEGORISED:
            return UNCATEGORISED
        return OTHER if label in merged_categories else label

    sub_totals: Dict[Tuple[str, str], Decimal] = {}
    for _, row in spend_rows.iterrows():
        cat = row["category"] or ""
        label = UNCATEGORISED if cat == "" else cat
        sub = row["subcategory"] or ""
        if sub == "" or label == UNCATEGORISED or label in merged_categories:
            continue
        key = (label, sub)
        sub_totals[key] = sub_totals.get(key, Decimal("0")) + (-row["amount"])

    folded_subs = set()
    if total_spend > 0:
        for key, total in sub_totals.items():
            if total / total_spend < min_share_sub:
                folded_subs.add(key)

    account_category_raw: Dict[Tuple[str, str], Tuple[Decimal, int]] = {}
    category_sub_raw: Dict[Tuple[str, str], Tuple[Decimal, int]] = {}

    for _, row in spend_rows.iterrows():
        account = str(row["account"])
        cat = row["category"] or ""
        label = UNCATEGORISED if cat == "" else cat
        sub = row["subcategory"] or ""
        amount = -row["amount"]
        display_label = _display_label(cat)

        v, c = account_category_raw.get((account, display_label), (Decimal("0"), 0))
        account_category_raw[(account, display_label)] = (v + amount, c + 1)

        if display_label not in (UNCATEGORISED, OTHER) and sub != "" and (label, sub) not in folded_subs:
            key = (display_label, sub)
            v2, c2 = category_sub_raw.get(key, (Decimal("0"), 0))
            category_sub_raw[key] = (v2 + amount, c2 + 1)

    for (account, display_label), (value, count) in account_category_raw.items():
        if display_label == UNCATEGORISED:
            role = "warning"
        elif display_label == OTHER:
            role = "other"
        else:
            role = "category"
        src = nodes.get(LAYER_ACCOUNT, account, account, "account")
        dst = nodes.get(LAYER_CATEGORY, display_label, display_label, role)
        _add_link(links, src, dst, value, count)

    for (display_label, sub), (value, count) in category_sub_raw.items():
        src = nodes.get(LAYER_CATEGORY, display_label, display_label, "category")
        dst = nodes.get(LAYER_SUBCATEGORY, (display_label, sub), sub, "subcategory")
        _add_link(links, src, dst, value, count)

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


def _assign_colors(nodes: NodeRegistry, totals: List[Tuple[float, int]]) -> List[str]:
    colors: List[Optional[str]] = [None] * len(nodes.labels)

    category_indices = [
        i for i in range(len(nodes.labels)) if nodes.layers[i] == LAYER_CATEGORY and nodes.roles[i] == "category"
    ]
    category_indices.sort(key=lambda i: (-totals[i][0], i))

    category_color: Dict[str, str] = {}
    for rank, idx in enumerate(category_indices):
        hue = SPEND_PALETTE[rank % len(SPEND_PALETTE)]
        colors[idx] = hue
        category_color[nodes.labels[idx]] = hue

    for i, role in enumerate(nodes.roles):
        if colors[i] is not None:
            continue
        if role == "account":
            colors[i] = ACCOUNT_NEUTRAL
        elif role == "income":
            colors[i] = INCOME_HUE
        elif role == "other":
            colors[i] = OTHER_NEUTRAL
        elif role == "warning":
            colors[i] = WARNING_COLOR
        elif role == "subcategory":
            parent_label = nodes.keys[i][0]
            colors[i] = _tint(category_color.get(parent_label, OTHER_NEUTRAL))
        else:  # pragma: no cover -- defensive fallback, no known role hits this
            colors[i] = OTHER_NEUTRAL

    return [c for c in colors]  # type: ignore[misc]


def build_sankey(
    frame: pd.DataFrame,
    *,
    min_share: Union[Decimal, float] = DEFAULT_MIN_SHARE,
    min_share_sub: Union[Decimal, float] = DEFAULT_MIN_SHARE_SUB,
) -> go.Figure:
    """Build the Sankey `go.Figure`. Hover shows the flow amount and
    transaction count for both links and nodes; node labels also show a
    compact amount inline (see module docstring for the color/label/layout
    system)."""
    nodes, links = aggregate(frame, min_share=min_share, min_share_sub=min_share_sub)
    currency = detect_currency(frame)
    totals = _node_totals(nodes, links)
    colors = _assign_colors(nodes, totals)

    layer_groups: Dict[int, List[int]] = {}
    for idx, layer in enumerate(nodes.layers):
        layer_groups.setdefault(layer, []).append(idx)
    for layer in layer_groups:
        layer_groups[layer].sort(key=lambda i: (-totals[i][0], i))

    ordered_layers = sorted(layer_groups)
    n_layers = len(ordered_layers)

    remap: Dict[int, int] = {}
    xs: List[float] = []
    ys: List[float] = []
    new_order: List[int] = []
    for pos, layer in enumerate(ordered_layers):
        x = 0.5 if n_layers == 1 else 0.001 + 0.998 * (pos / (n_layers - 1))
        group = layer_groups[layer]
        count = len(group)
        for rank, idx in enumerate(group):
            remap[idx] = len(new_order)
            new_order.append(idx)
            xs.append(x)
            y = (rank + 0.5) / count
            ys.append(min(max(y, 0.001), 0.999))

    labels = [_node_label(nodes.labels[i], totals[i][0], currency) for i in new_order]
    node_colors = [colors[i] for i in new_order]
    node_customdata = [[totals[i][0], totals[i][1]] for i in new_order]

    default_link_hover = (
        "%{source.label} -> %{target.label}"
        "<br>amount: %{customdata[0]:.2f}"
        "<br>transactions: %{customdata[1]}<extra></extra>"
    )
    transfer_link_hover = (
        "%{source.label} -> %{target.label}"
        "<br>net: %{customdata[0]:.2f}"
        "<br>gross with flow: %{customdata[2]:.2f}"
        "<br>gross against: %{customdata[3]:.2f}"
        "<br>transactions: %{customdata[1]}<extra></extra>"
    )

    sources: List[int] = []
    targets: List[int] = []
    values: List[float] = []
    link_colors: List[str] = []
    link_customdata: List[List[float]] = []
    link_hovers: List[str] = []
    for (src, dst), agg in links.items():
        sources.append(remap[src])
        targets.append(remap[dst])
        values.append(float(agg["value"]))
        # Tint by whichever endpoint carries identity: destination hue for
        # links leaving an account node (else neutral account gray would
        # dominate the ink), source hue for everything else. Account ->
        # account net transfer links stay gray via colors[dst] == gray.
        if nodes.layers[src] == LAYER_ACCOUNT:
            link_colors.append(_rgba(colors[dst], LINK_ALPHA))
        else:
            link_colors.append(_rgba(colors[src], LINK_ALPHA))
        if "gross_with" in agg:
            link_customdata.append(
                [
                    float(agg["value"]),
                    agg["count"],
                    float(agg["gross_with"]),
                    float(agg["gross_against"]),
                ]
            )
            link_hovers.append(transfer_link_hover)
        else:
            link_customdata.append([float(agg["value"]), agg["count"], 0.0, 0.0])
            link_hovers.append(default_link_hover)

    max_layer_count = max((len(g) for g in layer_groups.values()), default=1)
    height = max(MIN_HEIGHT, max_layer_count * PX_PER_NODE + HEIGHT_MARGIN)

    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="fixed",
                node=dict(
                    label=labels,
                    x=xs,
                    y=ys,
                    color=node_colors,
                    customdata=node_customdata,
                    hovertemplate="%{label}<br>total: %{customdata[0]:.2f}"
                    "<br>transactions: %{customdata[1]}<extra></extra>",
                ),
                link=dict(
                    source=sources,
                    target=targets,
                    value=values,
                    color=link_colors,
                    customdata=link_customdata,
                    hovertemplate=link_hovers,
                ),
            )
        ]
    )
    fig.update_layout(height=height, font=dict(size=12))
    return fig
