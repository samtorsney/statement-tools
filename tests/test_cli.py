"""cli.py: `parse` and `debug-layout` subcommands, exercised against
synthetic fixtures only."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from statement_parser.cli import main
from statement_parser.profile import load_profile
from tests.fixtures.make_pdf import BOI_COLUMN_X, render_pdf

PROFILES_DIR = Path(__file__).resolve().parent.parent / "statement_parser" / "profiles"


@pytest.fixture
def boi_profile():
    return load_profile(PROFILES_DIR / "boi_current.yaml")


def _simple_pdf(tmp_path, boi_profile):
    rows = [
        {"date": "05 Jan 2026", "description": "OPENING CREDIT", "out": "", "in": "500.00", "balance": "500.00"},
        {"date": "", "description": "COFFEE SHOP", "out": "4.50", "in": "", "balance": "495.50"},
        {"date": "06 Jan 2026", "description": "SALARY", "out": "", "in": "1,234.56", "balance": "1,730.06"},
    ]
    pdf_path = tmp_path / "statement.pdf"
    render_pdf(pdf_path, boi_profile, [rows], BOI_COLUMN_X)
    return pdf_path


def test_cli_parse_writes_canonical_csv(tmp_path, boi_profile):
    pdf_path = _simple_pdf(tmp_path, boi_profile)
    out_path = tmp_path / "out.csv"

    rc = main(["parse", str(pdf_path), "--profile", "boi_current", "--output", str(out_path)])
    assert rc == 0
    assert out_path.exists()

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 3
    assert rows[0]["date"] == "2026-01-05"
    assert rows[0]["description"] == "OPENING CREDIT"
    assert rows[0]["amount"] == "500.00"
    assert rows[0]["balance"] == "500.00"
    assert rows[0]["account"] == "boi_current"
    assert rows[2]["amount"] == "1234.56"
    assert rows[2]["balance"] == "1730.06"


def test_cli_parse_with_explicit_profile_path(tmp_path, boi_profile):
    pdf_path = _simple_pdf(tmp_path, boi_profile)
    out_path = tmp_path / "out.csv"
    profile_path = PROFILES_DIR / "boi_current.yaml"

    rc = main(["parse", str(pdf_path), "--profile", str(profile_path), "--output", str(out_path)])
    assert rc == 0


def test_cli_parse_unknown_profile_errors(tmp_path):
    rc = main(["parse", "whatever.pdf", "--profile", "not_a_real_profile", "--output", str(tmp_path / "out.csv")])
    assert rc == 1


def test_cli_debug_layout_prints_header_boxes_and_boundaries(tmp_path, boi_profile, capsys):
    pdf_path = _simple_pdf(tmp_path, boi_profile)

    rc = main(["debug-layout", str(pdf_path), "--profile", "boi_current"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "page 1" in out
    assert "header boxes" in out
    assert "derived column boundaries" in out
    assert "date" in out
    assert "balance" in out
