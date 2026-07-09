"""CSV engine + revolut_current profile test, using a synthetic CSV shaped
like Revolut's standard export (never the user's real revolut_statement.csv)."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from statement_parser.engine.csv_table import parse_csv
from statement_parser.profile import load_profile

PROFILES_DIR = Path(__file__).resolve().parent.parent / "statement_parser" / "profiles"

REVOLUT_HEADERS = [
    "Type",
    "Product",
    "Started Date",
    "Completed Date",
    "Description",
    "Amount",
    "Fee",
    "Currency",
    "State",
    "Balance",
]


@pytest.fixture
def revolut_profile():
    return load_profile(PROFILES_DIR / "revolut_current.yaml")


def _write_synthetic_csv(path: Path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVOLUT_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_csv_engine_maps_columns_and_signs_amount(tmp_path, revolut_profile):
    rows = [
        {
            "Type": "TOPUP",
            "Product": "Current",
            "Started Date": "2026-01-05 09:00:00",
            "Completed Date": "2026-01-05 09:00:01",
            "Description": "Top-Up by *1234",
            "Amount": "500.00",
            "Fee": "0.00",
            "Currency": "EUR",
            "State": "COMPLETED",
            "Balance": "500.00",
        },
        {
            "Type": "CARD_PAYMENT",
            "Product": "Current",
            "Started Date": "2026-01-06 12:30:00",
            "Completed Date": "2026-01-06 12:30:05",
            "Description": "Coffee Shop",
            "Amount": "-4.50",
            "Fee": "0.00",
            "Currency": "EUR",
            "State": "COMPLETED",
            "Balance": "495.50",
        },
    ]
    csv_path = tmp_path / "synthetic_revolut.csv"
    _write_synthetic_csv(csv_path, rows)

    parsed = parse_csv(csv_path, revolut_profile)

    assert len(parsed) == 2
    assert parsed[0].date == date(2026, 1, 5)
    assert parsed[0].description == "Top-Up by *1234"
    assert parsed[0].amount == Decimal("500.00")
    assert parsed[0].balance == Decimal("500.00")
    assert parsed[0].currency == "EUR"
    assert parsed[0].account == "revolut_current"
    assert parsed[0].source_file == "synthetic_revolut.csv"
    assert parsed[0].page is None
    assert parsed[0].row == 1

    assert parsed[1].amount == Decimal("-4.50")
    assert parsed[1].balance == Decimal("495.50")
    assert parsed[1].row == 2


def test_csv_engine_missing_expected_column_is_error(tmp_path, revolut_profile):
    path = tmp_path / "broken.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("Type,Product\nTOPUP,Current\n")

    from statement_parser.errors import ExtractionError

    with pytest.raises(ExtractionError):
        parse_csv(path, revolut_profile)


# ---------------------------------------------------------------------------
# Interleaved-products fixture: Revolut exports mix multiple Products
# (Current account, pockets/vaults, currency exchanges) in one file sharing
# a single Balance column, each with its own independent running balance.
# File-wide balance continuity is therefore NOT a valid invariant for this
# source, which is why revolut_current.yaml ships with
# balance.validate: none.
# ---------------------------------------------------------------------------

def _interleaved_products_rows():
    """Current account (500 -> 495.50) interleaved with a vault
    (100 -> 150): every product switch is a legitimate balance jump."""

    def row(product, started, desc, amount, balance):
        return {
            "Type": "TRANSFER",
            "Product": product,
            "Started Date": started,
            "Completed Date": started,
            "Description": desc,
            "Amount": amount,
            "Fee": "0.00",
            "Currency": "EUR",
            "State": "COMPLETED",
            "Balance": balance,
        }

    return [
        row("Current", "2026-01-05 09:00:00", "Top-Up", "500.00", "500.00"),
        row("Deposit", "2026-01-05 10:00:00", "To vault", "100.00", "100.00"),
        row("Current", "2026-01-06 12:00:00", "Coffee", "-4.50", "495.50"),
        row("Deposit", "2026-01-07 10:00:00", "To vault", "50.00", "150.00"),
    ]


def test_interleaved_products_violate_continuity_when_checked(tmp_path, revolut_profile):
    """Regression guard for the invariant itself: continuity checking still
    fires loudly when a profile opts into it -- the interleaved-products
    data shape genuinely violates file-wide continuity."""
    import dataclasses

    from statement_parser.errors import BalanceContinuityError
    from statement_parser.validate import check_balance_continuity

    csv_path = tmp_path / "interleaved.csv"
    _write_synthetic_csv(csv_path, _interleaved_products_rows())

    # Same profile, but with continuity checking switched on.
    strict_profile = dataclasses.replace(
        revolut_profile,
        balance=dataclasses.replace(revolut_profile.balance, validate="continuity"),
    )
    parsed = parse_csv(csv_path, strict_profile)

    with pytest.raises(BalanceContinuityError):
        check_balance_continuity(parsed)


def test_shipped_revolut_profile_does_not_continuity_check(revolut_profile):
    """revolut_current.yaml must ship with validate: none -- see the YAML
    comment for why (interleaved products share one Balance column)."""
    assert revolut_profile.balance.validate == "none"
    assert revolut_profile.balance.present is True  # balance still captured


def test_cli_parse_interleaved_products_succeeds_with_shipped_profile(tmp_path):
    from statement_parser.cli import main

    csv_path = tmp_path / "interleaved.csv"
    _write_synthetic_csv(csv_path, _interleaved_products_rows())
    out_path = tmp_path / "out.csv"

    rc = main(["parse", str(csv_path), "--profile", "revolut_current", "--output", str(out_path)])
    assert rc == 0

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
    # Balance values are still captured even though they are not
    # continuity-checked.
    assert [r["balance"] for r in rows] == ["500.00", "100.00", "495.50", "150.00"]
