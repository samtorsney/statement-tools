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
    aggregate,
    build_sankey,
)


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


def test_unmatched_transfer_excluded_from_sankey_entirely():
    frame = frame_of(
        [
            (date(2026, 1, 5), "-300.00", "boi_current", "Transfer", "", True),
            # No partner within the window -> stays unmatched.
            (date(2026, 3, 1), "300.00", "revolut_current", "Transfer", "", True),
        ]
    )
    nodes, links = aggregate(frame)
    assert links == {}
    assert nodes.labels == []


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
    assert set(trace.node.label) == {"Salary", "boi_current", "Food", "Groceries"}
    assert sorted(trace.link.value) == [40.0, 40.0, 1000.0]
    # Node hover customdata carries (total value, count) pairs.
    assert len(trace.node.customdata) == len(trace.node.label)
