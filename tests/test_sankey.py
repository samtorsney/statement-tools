"""Sankey aggregation, exercised on synthetic frames only (fake accounts,
fake categories, fake amounts). Assertions inspect the `go.Sankey` trace
(fig.data[0]) directly, per the design spec -- never a rendered file."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from charts.netting import net_transfers
from charts.sankey import (
    LAYER_ACCOUNT,
    LAYER_CATEGORY,
    LAYER_INCOME,
    LAYER_SUBCATEGORY,
    OTHER,
    TRANSFERS_UNMATCHED,
    aggregate,
    build_sankey,
)
from tests.fixtures.make_sankey_frame import make_sankey_frame


def frame_of(rows):
    """rows: (date, amount, account, category, subcategory, is_transfer)."""
    frame = pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "amount": [Decimal(str(r[1])) for r in rows],
            "account": [r[2] for r in rows],
            "category": [r[3] for r in rows],
            "subcategory": [r[4] for r in rows],
            "is_transfer": [r[5] for r in rows],
        }
    )
    return net_transfers(frame).netted


def links_by_labels(nodes, links):
    """(src_layer, src_label, dst_layer, dst_label) -> {value, count}."""
    out = {}
    for (src, dst), agg in links.items():
        key = (nodes.layers[src], nodes.labels[src], nodes.layers[dst], nodes.labels[dst])
        out[key] = agg
    return out


def test_income_to_account_link():
    frame = frame_of(
        [
            (date(2026, 1, 5), "2000.00", "boi_current", "Income", "Salary", False),
        ]
    )
    nodes, links = aggregate(frame)
    by_label = links_by_labels(nodes, links)
    key = (LAYER_INCOME, "Salary", LAYER_ACCOUNT, "boi_current")
    assert by_label[key]["value"] == Decimal("2000.00")
    assert by_label[key]["count"] == 1


def test_spend_produces_account_to_category_and_category_to_subcategory_links():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-50.00", "boi_current", "Fees", "Card FX", False),
        ]
    )
    nodes, links = aggregate(frame)
    by_label = links_by_labels(nodes, links)

    account_to_cat = (LAYER_ACCOUNT, "boi_current", LAYER_CATEGORY, "Fees")
    cat_to_sub = (LAYER_CATEGORY, "Fees", LAYER_SUBCATEGORY, "Card FX")

    assert by_label[account_to_cat]["value"] == Decimal("50.00")
    assert by_label[account_to_cat]["count"] == 1
    assert by_label[cat_to_sub]["value"] == Decimal("50.00")
    assert by_label[cat_to_sub]["count"] == 1


def test_multiple_spend_rows_aggregate_into_one_link():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-5.00", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 6), "-3.50", "boi_current", "Food", "Coffee", False),
            (date(2026, 1, 7), "-100.00", "boi_current", "Food", "Groceries", False),
        ]
    )
    nodes, links = aggregate(frame)
    by_label = links_by_labels(nodes, links)

    account_to_food = (LAYER_ACCOUNT, "boi_current", LAYER_CATEGORY, "Food")
    assert by_label[account_to_food]["value"] == Decimal("108.50")
    assert by_label[account_to_food]["count"] == 3

    food_to_coffee = (LAYER_CATEGORY, "Food", LAYER_SUBCATEGORY, "Coffee")
    assert by_label[food_to_coffee]["value"] == Decimal("8.50")
    assert by_label[food_to_coffee]["count"] == 2

    food_to_groceries = (LAYER_CATEGORY, "Food", LAYER_SUBCATEGORY, "Groceries")
    assert by_label[food_to_groceries]["value"] == Decimal("100.00")
    assert by_label[food_to_groceries]["count"] == 1


def test_uncategorised_spend_gets_placeholder_labels():
    frame = frame_of(
        [(date(2026, 1, 5), "-20.00", "boi_current", "", "", False)]
    )
    nodes, links = aggregate(frame)
    by_label = links_by_labels(nodes, links)
    key = (LAYER_ACCOUNT, "boi_current", LAYER_CATEGORY, "(uncategorised)")
    assert by_label[key]["value"] == Decimal("20.00")


def test_paired_transfer_becomes_account_to_account_link_not_spend():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-300.00", "boi_current", "Transfer", "", True),
            (date(2026, 1, 5), "300.00", "revolut_current", "Transfer", "", True),
        ]
    )
    nodes, links = aggregate(frame)
    by_label = links_by_labels(nodes, links)

    transfer_link = (LAYER_ACCOUNT, "boi_current", LAYER_ACCOUNT, "revolut_current")
    assert by_label[transfer_link]["value"] == Decimal("300.00")
    assert by_label[transfer_link]["count"] == 2

    # No category/subcategory nodes at all -- a paired transfer never
    # touches the spend layers.
    assert LAYER_CATEGORY not in nodes.layers
    assert LAYER_SUBCATEGORY not in nodes.layers


def test_unmatched_transfer_aggregates_into_single_transfers_unmatched_node():
    """Regression test for problem 3 in the design spec: unpaired transfer
    legs used to be silently dropped (drawn outflow != actual outflow).
    They now aggregate into exactly one "Transfers (unmatched)" node:
    debit legs flow account->node, credit legs flow node->account."""
    frame = frame_of(
        [
            (date(2026, 1, 5), "-300.00", "boi_current", "Transfer", "", True),
            # No partner within the window -> stays unmatched.
            (date(2026, 3, 1), "300.00", "revolut_current", "Transfer", "", True),
        ]
    )
    nodes, links = aggregate(frame)
    by_label = links_by_labels(nodes, links)

    debit_link = (LAYER_ACCOUNT, "boi_current", LAYER_CATEGORY, TRANSFERS_UNMATCHED)
    credit_link = (LAYER_CATEGORY, TRANSFERS_UNMATCHED, LAYER_ACCOUNT, "revolut_current")
    assert by_label[debit_link]["value"] == Decimal("300.00")
    assert by_label[credit_link]["value"] == Decimal("300.00")

    # Exactly one node for the bucket, not one per unmatched leg.
    assert nodes.labels.count(TRANSFERS_UNMATCHED) == 1


def test_double_count_regression_paired_transfer_not_also_spend():
    """The whole point of netting: a paired transfer must not appear as
    both an account->category spend link *and* an account->account
    transfer link."""
    frame = frame_of(
        [
            (date(2026, 1, 5), "-500.00", "boi_current", "Transfer", "", True),
            (date(2026, 1, 6), "500.00", "revolut_current", "Transfer", "", True),
            (date(2026, 1, 7), "-40.00", "boi_current", "Food", "Groceries", False),
        ]
    )
    nodes, links = aggregate(frame)
    by_label = links_by_labels(nodes, links)

    # Total value flowing out of boi_current across all links must equal
    # exactly the transfer (500) plus the one real spend row (40) -- not
    # 500 twice.
    total_from_boi = sum(
        agg["value"] for (src, dst), agg in links.items() if nodes.layers[src] == LAYER_ACCOUNT and nodes.labels[src] == "boi_current"
    )
    assert total_from_boi == Decimal("540.00")

    assert (LAYER_ACCOUNT, "boi_current", LAYER_CATEGORY, "Transfer") not in by_label


def test_build_sankey_returns_figure_with_matching_totals():
    frame = frame_of(
        [
            (date(2026, 1, 5), "1000.00", "boi_current", "Income", "Salary", False),
            (date(2026, 1, 6), "-40.00", "boi_current", "Food", "Groceries", False),
        ]
    )
    fig = build_sankey(frame)
    trace = fig.data[0]
    assert trace.type == "sankey"
    # Node labels are "<name> · <compact amount>", not the bare name.
    names = {label.split(" · ")[0] for label in trace.node.label}
    assert names == {"Salary", "boi_current", "Food", "Groceries"}
    assert sorted(trace.link.value) == [40.0, 40.0, 1000.0]
    # Node hover customdata carries (total value, count) pairs.
    assert len(trace.node.customdata) == len(trace.node.label)


def test_small_share_parent_categories_merge_into_other():
    """Parents below the default 1% min_share fold into one "Other" node
    instead of each getting their own hairline-ribbon node."""
    rows = [
        (date(2026, 1, 5), "-990.00", "boi_current", "Rent", "", False),
        (date(2026, 1, 6), "-7.00", "boi_current", "Tiny1", "", False),
        (date(2026, 1, 7), "-3.00", "boi_current", "Tiny2", "", False),
    ]
    frame = frame_of(rows)
    nodes, links = aggregate(frame)

    assert "Rent" in nodes.labels
    assert "Tiny1" not in nodes.labels
    assert "Tiny2" not in nodes.labels
    assert OTHER in nodes.labels

    by_label = links_by_labels(nodes, links)
    other_link = (LAYER_ACCOUNT, "boi_current", LAYER_CATEGORY, OTHER)
    assert by_label[other_link]["value"] == Decimal("10.00")


def test_other_absent_when_nothing_merged():
    """"Other" only ever appears when something was actually merged into
    it -- two categories both comfortably above min_share must not produce
    a spurious Other node."""
    rows = [
        (date(2026, 1, 5), "-600.00", "boi_current", "Rent", "", False),
        (date(2026, 1, 6), "-400.00", "boi_current", "Food", "", False),
    ]
    frame = frame_of(rows)
    nodes, links = aggregate(frame)
    assert OTHER not in nodes.labels


def test_small_share_subcategories_fold_into_parent_no_leaf():
    """Subcategories below the default 0.5%-of-spend min_share_sub fold
    back into the parent -- no leaf node, but the value still counts
    towards the parent's own total."""
    rows = [
        (date(2026, 1, 5), "-900.00", "boi_current", "Food", "Groceries", False),
        (date(2026, 1, 6), "-95.00", "boi_current", "Food", "Snacks", False),
        (date(2026, 1, 7), "-2.00", "boi_current", "Food", "Candy", False),
    ]
    frame = frame_of(rows)
    nodes, links = aggregate(frame)

    assert "Groceries" in nodes.labels
    assert "Snacks" in nodes.labels
    assert "Candy" not in nodes.labels  # folded: 2 / 997 < 0.5%

    by_label = links_by_labels(nodes, links)
    food_link = (LAYER_ACCOUNT, "boi_current", LAYER_CATEGORY, "Food")
    assert by_label[food_link]["value"] == Decimal("997.00")  # folded row still counted


def test_no_none_placeholder_ever_created():
    """A parent with no subcategory rows terminates at the category layer
    -- it must never invent a "(none)" leaf."""
    rows = [
        (date(2026, 1, 5), "-500.00", "boi_current", "Rent", "", False),
        (date(2026, 1, 6), "-500.00", "boi_current", "Food", "Groceries", False),
    ]
    frame = frame_of(rows)
    nodes, links = aggregate(frame)
    assert not any("(none)" in label for label in nodes.labels)
    assert "Rent" in nodes.labels


def test_person_names_never_become_node_labels():
    """Transfer subcategories are frequently a payee's name. Neither a
    matched pair nor an unmatched leg may ever surface that name as a node
    label -- matched pairs bypass the category layers entirely, and
    unmatched legs fold into the fixed "Transfers (unmatched)" bucket."""
    rows = [
        (date(2026, 1, 5), "-300.00", "boi_current", "Transfer", "Alex Doe", True),
        (date(2026, 1, 5), "300.00", "revolut_current", "Transfer", "Alex Doe", True),
        # No partner -> unmatched.
        (date(2026, 1, 6), "-77.00", "boi_current", "Transfer", "Jordan Roe", True),
    ]
    frame = frame_of(rows)
    nodes, links = aggregate(frame)
    assert "Alex Doe" not in nodes.labels
    assert "Jordan Roe" not in nodes.labels
    assert TRANSFERS_UNMATCHED in nodes.labels


def test_flow_conservation_across_account_layer():
    """Regression test for problem 3: total ribbon value leaving the
    account layer must equal non-transfer spend plus the absolute value of
    unmatched negative transfer legs (and symmetrically for inflow) --
    "leaving"/"entering" means crossing out of the account layer, so
    matched account->account transfer ribbons (which stay within the
    layer) are correctly excluded from both sides."""
    frame = make_sankey_frame()
    result = net_transfers(frame)
    netted = result.netted
    nodes, links = aggregate(netted)

    leaving = sum(
        agg["value"]
        for (src, dst), agg in links.items()
        if nodes.layers[src] == LAYER_ACCOUNT and nodes.layers[dst] != LAYER_ACCOUNT
    )
    entering = sum(
        agg["value"]
        for (src, dst), agg in links.items()
        if nodes.layers[dst] == LAYER_ACCOUNT and nodes.layers[src] != LAYER_ACCOUNT
    )

    non_transfer = netted[~netted["is_transfer"].astype(bool)]
    total_spend = -non_transfer[non_transfer["amount"] < 0]["amount"].sum()
    total_income = non_transfer[non_transfer["amount"] > 0]["amount"].sum()

    unmatched = result.unmatched
    unmatched_neg = -unmatched[unmatched["amount"] < 0]["amount"].sum()
    unmatched_pos = unmatched[unmatched["amount"] > 0]["amount"].sum()

    assert leaving == total_spend + unmatched_neg
    assert entering == total_income + unmatched_pos


def test_node_count_bound_on_structural_fixture():
    """With defaults on the ~96-node-shaped structural fixture, total node
    count must come out well under 40 (the pre-redesign real data hit 96)."""
    frame = make_sankey_frame()
    netted = net_transfers(frame).netted
    nodes, links = aggregate(netted)
    assert len(nodes.labels) < 40


def test_build_sankey_renders_structural_fixture_without_error():
    frame = make_sankey_frame()
    netted = net_transfers(frame).netted
    fig = build_sankey(netted)
    trace = fig.data[0]
    assert trace.type == "sankey"
    assert not any("(none)" in label for label in trace.node.label)
    for name in ("Alex Doe", "Jordan Roe"):
        assert not any(name in label for label in trace.node.label)
