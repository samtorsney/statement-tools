"""Edge-case fixtures the new engine must fix by construction (FINDINGS.md
#3, #4): multiline transaction details, page breaks, thousands separators,
same-day duplicate transactions, and a deliberately corrupted balance
asserting the loud continuity failure fires. All synthetic -- no real
statement data."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from statement_parser.engine.pdf_table import parse_pdf
from statement_parser.errors import BalanceContinuityError
from statement_parser.profile import load_profile
from statement_parser.validate import check_balance_continuity
from tests.fixtures.make_pdf import BOI_COLUMN_X, render_pdf

PROFILES_DIR = Path(__file__).resolve().parent.parent / "statement_parser" / "profiles"


@pytest.fixture
def boi_profile():
    return load_profile(PROFILES_DIR / "boi_current.yaml")


def test_multiline_details_merge_into_previous_row_not_a_phantom_row(tmp_path, boi_profile):
    rows = [
        {
            "date": "05 Jan 2026",
            "description": "PAYMENT TO ACME",
            "out": "25.00",
            "in": "",
            "balance": "475.00",
        },
        # Continuation line: only description has text -- must merge into
        # the row above, not become its own zero-amount phantom row.
        {"date": "", "description": "SUPPLIES LTD REF 99213", "out": "", "in": "", "balance": ""},
        {
            "date": "06 Jan 2026",
            "description": "REFUND",
            "out": "",
            "in": "5.00",
            "balance": "480.00",
        },
    ]
    pdf_path = tmp_path / "multiline.pdf"
    render_pdf(pdf_path, boi_profile, [rows], BOI_COLUMN_X)

    parsed = parse_pdf(pdf_path, boi_profile)

    assert len(parsed) == 2  # not 3 -- the continuation line didn't become its own row
    assert parsed[0].description == "PAYMENT TO ACME SUPPLIES LTD REF 99213"
    assert parsed[0].amount == Decimal("-25.00")
    assert parsed[1].description == "REFUND"


def test_page_break_carries_date_and_balance_across_pages(tmp_path, boi_profile):
    page1 = [
        {"date": "05 Jan 2026", "description": "OPENING CREDIT", "out": "", "in": "500.00", "balance": "500.00"},
        {"date": "", "description": "SHOP A", "out": "50.00", "in": "", "balance": "450.00"},
    ]
    page2 = [
        # Same statement continues on page 2 with its own header (as a
        # multi-page BOI statement prints the header again on every page).
        {"date": "06 Jan 2026", "description": "SHOP B", "out": "20.00", "in": "", "balance": "430.00"},
        {"date": "", "description": "SHOP C", "out": "", "in": "10.00", "balance": "440.00"},
    ]
    pdf_path = tmp_path / "page_break.pdf"
    render_pdf(pdf_path, boi_profile, [page1, page2], BOI_COLUMN_X)

    parsed = parse_pdf(pdf_path, boi_profile)

    assert len(parsed) == 4
    assert [r.page for r in parsed] == [1, 1, 2, 2]
    assert [r.row for r in parsed] == [1, 2, 3, 4]
    assert parsed[2].date == date(2026, 1, 6)
    assert parsed[3].date == date(2026, 1, 6)  # forward-filled across the page boundary
    assert [r.balance for r in parsed] == [
        Decimal("500.00"),
        Decimal("450.00"),
        Decimal("430.00"),
        Decimal("440.00"),
    ]


def test_thousands_separators_parse_correctly(tmp_path, boi_profile):
    rows = [
        {
            "date": "05 Jan 2026",
            "description": "LARGE DEPOSIT",
            "out": "",
            "in": "12,345.67",
            "balance": "12,345.67",
        },
        {
            "date": "06 Jan 2026",
            "description": "BIG PURCHASE",
            "out": "1,000,000.01",
            "in": "",
            "balance": "-987,654.34",
        },
    ]
    pdf_path = tmp_path / "thousands.pdf"
    render_pdf(pdf_path, boi_profile, [rows], BOI_COLUMN_X)

    parsed = parse_pdf(pdf_path, boi_profile)

    assert parsed[0].amount == Decimal("12345.67")
    assert parsed[0].balance == Decimal("12345.67")
    assert parsed[1].amount == Decimal("-1000000.01")
    assert parsed[1].balance == Decimal("-987654.34")


def test_same_day_duplicate_transactions_both_kept_by_engine(tmp_path, boi_profile):
    rows = [
        {"date": "05 Jan 2026", "description": "COFFEE SHOP", "out": "4.50", "in": "", "balance": "95.50"},
        {"date": "", "description": "COFFEE SHOP", "out": "4.50", "in": "", "balance": "91.00"},
    ]
    pdf_path = tmp_path / "same_day_dupes.pdf"
    render_pdf(pdf_path, boi_profile, [rows], BOI_COLUMN_X)

    parsed = parse_pdf(pdf_path, boi_profile)

    assert len(parsed) == 2
    assert parsed[0].description == parsed[1].description == "COFFEE SHOP"
    assert parsed[0].amount == parsed[1].amount == Decimal("-4.50")
    assert parsed[0].balance != parsed[1].balance  # distinguishable by running balance


def test_corrupted_balance_triggers_loud_continuity_failure(tmp_path, boi_profile):
    rows = [
        {"date": "05 Jan 2026", "description": "OPENING CREDIT", "out": "", "in": "500.00", "balance": "500.00"},
        # Printed balance is wrong: should be 450.00 after a 50.00 debit.
        {"date": "06 Jan 2026", "description": "SHOP", "out": "50.00", "in": "", "balance": "413.37"},
    ]
    pdf_path = tmp_path / "corrupted_balance.pdf"
    render_pdf(pdf_path, boi_profile, [rows], BOI_COLUMN_X)

    parsed = parse_pdf(pdf_path, boi_profile)

    with pytest.raises(BalanceContinuityError, match="discontinuity"):
        check_balance_continuity(parsed)
