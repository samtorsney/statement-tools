"""The `statements` top-level dispatcher: argv-forwarding only, exercised
against synthetic fixtures (fake merchants, fake amounts)."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

import statement_tools_cli
from statement_parser.profile import load_profile
from tests.fixtures.make_pdf import BOI_COLUMN_X, render_pdf

PROFILES_DIR = Path(__file__).resolve().parent.parent / "statement_parser" / "profiles"

CANONICAL_COLUMNS = [
    "date",
    "description",
    "amount",
    "balance",
    "currency",
    "account",
    "source_file",
    "page",
    "row",
]

CATEGORISED_COLUMNS = CANONICAL_COLUMNS + ["category", "subcategory", "is_transfer"]


def write_canonical_csv(path: Path, rows):
    """rows: (date, description, amount, account) tuples."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        for i, (dt, desc, amount, account) in enumerate(rows):
            writer.writerow(
                {
                    "date": dt,
                    "description": desc,
                    "amount": amount,
                    "balance": "",
                    "currency": "",
                    "account": account,
                    "source_file": "synthetic.pdf",
                    "page": "1",
                    "row": str(i),
                }
            )


def write_categorised_csv(path: Path, rows):
    """rows: (date, description, amount, account, category, subcategory,
    is_transfer) tuples."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CATEGORISED_COLUMNS)
        writer.writeheader()
        for i, (dt, desc, amount, account, category, subcategory, is_transfer) in enumerate(rows):
            writer.writerow(
                {
                    "date": dt,
                    "description": desc,
                    "amount": amount,
                    "balance": "",
                    "currency": "",
                    "account": account,
                    "source_file": "synthetic.csv",
                    "page": "",
                    "row": str(i),
                    "category": category,
                    "subcategory": subcategory,
                    "is_transfer": str(is_transfer),
                }
            )


def test_help_lists_all_subcommands(capsys):
    rc = statement_tools_cli.main(["--help"])
    assert rc == 0
    out = capsys.readouterr().out
    for name in ("parse", "debug-layout", "categorise", "report", "triage", "chart"):
        assert name in out
    for chart_type in ("sankey", "monthly", "savings"):
        assert chart_type in out


def test_no_args_errors(capsys):
    rc = statement_tools_cli.main([])
    assert rc == 1


def test_unknown_command_errors(capsys):
    rc = statement_tools_cli.main(["not-a-real-command"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown command" in err


def test_parse_delegates_to_statement_parser_cli(tmp_path):
    profile = load_profile(PROFILES_DIR / "boi_current.yaml")
    rows = [
        {"date": "05 Jan 2026", "description": "OPENING CREDIT", "out": "", "in": "500.00", "balance": "500.00"},
    ]
    pdf_path = tmp_path / "statement.pdf"
    render_pdf(pdf_path, profile, [rows], BOI_COLUMN_X)
    out_path = tmp_path / "out.csv"

    rc = statement_tools_cli.main(
        ["parse", str(pdf_path), "--profile", "boi_current", "--output", str(out_path)]
    )
    assert rc == 0
    assert out_path.exists()


def test_debug_layout_delegates(tmp_path, capsys):
    profile = load_profile(PROFILES_DIR / "boi_current.yaml")
    rows = [
        {"date": "05 Jan 2026", "description": "OPENING CREDIT", "out": "", "in": "500.00", "balance": "500.00"},
    ]
    pdf_path = tmp_path / "statement.pdf"
    render_pdf(pdf_path, profile, [rows], BOI_COLUMN_X)

    rc = statement_tools_cli.main(["debug-layout", str(pdf_path), "--profile", "boi_current"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "header boxes" in out


def test_categorise_delegates_to_run(tmp_path):
    in_csv = tmp_path / "canonical.csv"
    out_csv = tmp_path / "categorised.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "FAKECO SALARY JAN", "2000.00", "boi_current")])

    rc = statement_tools_cli.main(
        ["categorise", "--in", str(in_csv), "--out", str(out_csv)]
    )
    assert rc == 0
    rows = list(csv.DictReader(open(out_csv, newline="", encoding="utf-8")))
    assert rows[0]["category"] == "Income"


def test_report_delegates(tmp_path):
    in_csv = tmp_path / "canonical.csv"
    cat_csv = tmp_path / "categorised.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "MYSTERY MERCHANT ZZZ", "-42.00", "boi_current")])
    rc = statement_tools_cli.main(
        ["categorise", "--in", str(in_csv), "--out", str(cat_csv), "--tolerance", "9999"]
    )
    assert rc == 0

    uncat_csv = tmp_path / "uncategorised.csv"
    rc = statement_tools_cli.main(["report", "--in", str(cat_csv), "--out", str(uncat_csv)])
    assert rc == 0
    assert uncat_csv.exists()


def test_chart_sankey_delegates(tmp_path):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(
        in_csv,
        [
            ("2026-01-05", "FAKECO SALARY JAN", "2000.00", "boi_current", "Income", "Salary", False),
            ("2026-01-06", "BIG COFFEE HOUSE", "-4.50", "boi_current", "Food", "Coffee", False),
        ],
    )
    out_dir = tmp_path / "reports"

    rc = statement_tools_cli.main(
        [
            "chart",
            "sankey",
            "--in",
            str(in_csv),
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0
    assert (out_dir / "sankey.html").exists()


def test_chart_unknown_type_errors(capsys):
    rc = statement_tools_cli.main(["chart", "not-a-chart"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown chart type" in err


def test_chart_no_type_errors(capsys):
    rc = statement_tools_cli.main(["chart"])
    assert rc == 1


def test_triage_delegates(tmp_path, monkeypatch, capsys):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "FAKECO SALARY JAN", "2000.00", "boi_current")])
    rules_path = tmp_path / "personal_rules.yaml"

    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    rc = statement_tools_cli.main(
        ["triage", "--in", str(in_csv), "--rules", str(rules_path)]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to triage" in out
