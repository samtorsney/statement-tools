"""charts CLI (`report sankey|monthly|savings`), exercised on synthetic
categorised CSVs only (fake merchants, fake amounts, fake accounts)."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from charts.cli import main

CATEGORISED_COLUMNS = [
    "date",
    "description",
    "amount",
    "balance",
    "currency",
    "account",
    "source_file",
    "page",
    "row",
    "category",
    "subcategory",
    "is_transfer",
]


def write_categorised_csv(path: Path, rows):
    """rows: (date, description, amount, account, category, subcategory,
    is_transfer) tuples. balance left blank for simplicity unless a test
    needs it."""
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


SAMPLE_ROWS = [
    ("2026-01-05", "FAKECO SALARY JAN", "2000.00", "boi_current", "Income", "Salary", False),
    ("2026-01-06", "BIG COFFEE HOUSE", "-4.50", "boi_current", "Food", "Coffee", False),
    ("2026-01-07", "TO FAKE SAVINGS", "-300.00", "boi_current", "Transfer", "", True),
    ("2026-01-07", "FROM BOI", "300.00", "revolut_current", "Transfer", "", True),
    ("2026-01-20", "MYSTERY MERCHANT", "-15.00", "boi_current", "", "", False),
]


def test_sankey_writes_html_and_unmatched_report(tmp_path, capsys):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    rc = main(
        [
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
    assert (out_dir / "unmatched_transfers.csv").exists()

    html = (out_dir / "sankey.html").read_text(encoding="utf-8")
    assert "<html" in html.lower()
    # No transaction text should appear in the generated HTML: node labels
    # are category/account names only, never raw merchant descriptions.
    assert "MYSTERY MERCHANT" not in html
    assert "BIG COFFEE HOUSE" not in html

    out = capsys.readouterr().out
    assert "MYSTERY MERCHANT" not in out
    assert "5 row(s)" in out
    assert "1 uncategorised" in out
    assert "0 unmatched transfer" in out


def test_monthly_writes_bar_and_delta_csv(tmp_path):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    rc = main(
        [
            "monthly",
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
    assert (out_dir / "monthly.html").exists()
    assert (out_dir / "monthly_delta.csv").exists()
    assert (out_dir / "unmatched_transfers.csv").exists()


def test_savings_writes_html(tmp_path):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    rc = main(
        [
            "savings",
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
    assert (out_dir / "savings.html").exists()


def test_date_range_filters_rows(tmp_path, capsys):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    rc = main(
        [
            "sankey",
            "--in",
            str(in_csv),
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-10",  # excludes the 2026-01-20 mystery row
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "4 in range" in out
    assert "0 uncategorised" in out


def test_unmatched_transfer_reported_and_counted(tmp_path, capsys):
    rows = SAMPLE_ROWS + [
        ("2026-01-25", "TO FAKE SAVINGS", "-77.00", "boi_current", "Transfer", "", True),
    ]
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, rows)
    out_dir = tmp_path / "reports"

    rc = main(
        [
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
    out = capsys.readouterr().out
    assert "1 unmatched transfer" in out

    import csv as csv_mod

    with open(out_dir / "unmatched_transfers.csv", newline="", encoding="utf-8") as f:
        unmatched_rows = list(csv_mod.DictReader(f))
    assert len(unmatched_rows) == 1
    assert unmatched_rows[0]["description"] == "TO FAKE SAVINGS"


def test_missing_required_columns_errors(tmp_path, capsys):
    in_csv = tmp_path / "bad.csv"
    with open(in_csv, "w", newline="", encoding="utf-8") as f:
        f.write("date,description,amount\n2026-01-01,X,1.00\n")

    rc = main(
        [
            "sankey",
            "--in",
            str(in_csv),
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--out",
            str(tmp_path / "reports"),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing required column" in err


def test_bad_amount_error_does_not_echo_text(tmp_path, capsys):
    rows = [("2026-01-05", "X", "SENSITIVEJUNK", "boi_current", "", "", False)]
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, rows)

    rc = main(
        [
            "sankey",
            "--in",
            str(in_csv),
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--out",
            str(tmp_path / "reports"),
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "SENSITIVEJUNK" not in captured.out + captured.err


def test_from_after_to_errors(tmp_path, capsys):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    rc = main(
        [
            "sankey",
            "--in",
            str(in_csv),
            "--from",
            "2026-02-01",
            "--to",
            "2026-01-01",
            "--out",
            str(tmp_path / "reports"),
        ]
    )
    assert rc == 1
