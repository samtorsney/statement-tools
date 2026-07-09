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
