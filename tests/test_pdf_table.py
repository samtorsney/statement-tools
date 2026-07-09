"""Round-trip test for the generic PDF table engine: a synthetic statement
generated FROM the boi_current profile (reportlab) must parse back out to
exactly the ground truth used to generate it. No real statement data is
used anywhere in this file.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from statement_parser.engine.pdf_table import parse_pdf
from statement_parser.profile import load_profile
from tests.fixtures.make_pdf import BOI_COLUMN_X, render_pdf

PROFILES_DIR = Path(__file__).resolve().parent.parent / "statement_parser" / "profiles"


def format_amount(value, thousands=",", decimal="."):
    if value is None:
        return ""
    q = value.quantize(Decimal("0.01"))
    text = f"{q:,.2f}"
    text = text.replace(",", "\x00T\x00").replace(".", "\x00D\x00")
    text = text.replace("\x00T\x00", thousands).replace("\x00D\x00", decimal)
    return text


@pytest.fixture
def boi_profile():
    return load_profile(PROFILES_DIR / "boi_current.yaml")


def _build_ground_truth():
    """A simple, single-page ground truth: 6 plain transactions, some
    sharing a date (forward-fill), running balance computed exactly like
    the engine should reconstruct it."""
    txns = [
        {"date": date(2026, 1, 5), "description": "OPENING CREDIT", "in": Decimal("500.00"), "out": None},
        {"date": date(2026, 1, 5), "description": "COFFEE SHOP", "in": None, "out": Decimal("4.50")},
        {"date": date(2026, 1, 6), "description": "SALARY PAYMENT ACME LTD", "in": Decimal("1234.56"), "out": None},
        {"date": date(2026, 1, 7), "description": "SUPERMARKET SHOP", "in": None, "out": Decimal("62.10")},
        {"date": date(2026, 1, 7), "description": "ATM WITHDRAWAL", "in": None, "out": Decimal("100.00")},
        {"date": date(2026, 1, 8), "description": "REFUND FROM SHOP", "in": Decimal("10.00"), "out": None},
    ]

    balance = Decimal("0.00")
    ground_truth = []
    for t in txns:
        amount = (t["in"] or Decimal("0")) - (t["out"] or Decimal("0"))
        balance = (balance + amount).quantize(Decimal("0.01"))
        ground_truth.append(
            {
                "date": t["date"],
                "description": t["description"],
                "amount": amount,
                "balance": balance,
            }
        )
    return txns, ground_truth


def _render_rows_for_pdf(txns):
    """Convert ground-truth transactions into the raw-text row dicts
    render_pdf expects, with date forward-fill blanking applied (only the
    first row of a run of same-date transactions prints the date, exactly
    like a real BOI statement)."""
    rows = []
    last_date = None
    running_balance = Decimal("0.00")
    for t in txns:
        amount = (t["in"] or Decimal("0")) - (t["out"] or Decimal("0"))
        running_balance = (running_balance + amount).quantize(Decimal("0.01"))
        date_text = t["date"].strftime("%d %b %Y") if t["date"] != last_date else ""
        last_date = t["date"]
        rows.append(
            {
                "date": date_text,
                "description": t["description"],
                "out": format_amount(t["out"]),
                "in": format_amount(t["in"]),
                "balance": format_amount(running_balance),
            }
        )
    return rows


def test_round_trip_matches_ground_truth(tmp_path, boi_profile):
    txns, ground_truth = _build_ground_truth()
    rows = _render_rows_for_pdf(txns)

    pdf_path = tmp_path / "synthetic_statement.pdf"
    render_pdf(pdf_path, boi_profile, [rows], BOI_COLUMN_X)

    parsed = parse_pdf(pdf_path, boi_profile)

    assert len(parsed) == len(ground_truth)
    for parsed_row, expected in zip(parsed, ground_truth):
        assert parsed_row.date == expected["date"]
        assert parsed_row.description == expected["description"]
        assert parsed_row.amount == expected["amount"]
        assert parsed_row.balance == expected["balance"]
        assert parsed_row.account == "boi_current"
        assert parsed_row.source_file == "synthetic_statement.pdf"


def test_round_trip_provenance_is_sequential(tmp_path, boi_profile):
    txns, _ = _build_ground_truth()
    rows = _render_rows_for_pdf(txns)

    pdf_path = tmp_path / "synthetic_statement.pdf"
    render_pdf(pdf_path, boi_profile, [rows], BOI_COLUMN_X)

    parsed = parse_pdf(pdf_path, boi_profile)
    assert [r.row for r in parsed] == list(range(1, len(parsed) + 1))
    assert all(r.page == 1 for r in parsed)
