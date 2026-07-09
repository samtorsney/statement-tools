"""categorise CLI: run/report, exercised on synthetic canonical CSVs only
(fake merchants, fake amounts)."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from categorise.cli import main

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


def write_canonical_csv(path: Path, rows):
    """rows: list of (date, description, amount, account) tuples."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        for i, (date, description, amount, account) in enumerate(rows):
            writer.writerow(
                {
                    "date": date,
                    "description": description,
                    "amount": amount,
                    "balance": "",
                    "currency": "",
                    "account": account,
                    "source_file": "synthetic.pdf",
                    "page": "1",
                    "row": str(i),
                }
            )


def read_csv(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def personal_rules(tmp_path: Path) -> Path:
    p = tmp_path / "personal_rules.yaml"
    p.write_text(
        "- match: exact\n"
        "  pattern: FAKE FURNITURE STORE\n"
        "  category: House/Furniture\n"
        "  account: boi_current\n"
        "- match: prefix\n"
        "  pattern: ATM\n"
        "  category: Personal Override\n"
        "  account: boi_current\n"
        "- match: exact\n"
        "  pattern: TO FAKE SAVINGS\n"
        "  category: Savings\n"
        "  transfer: true\n",
        encoding="utf-8",
    )
    return p


def test_run_fully_categorised_exits_zero(tmp_path, personal_rules, capsys):
    in_csv = tmp_path / "canonical.csv"
    out_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv,
        [
            ("2026-01-05", "FAKE FURNITURE STORE", "-120.00", "boi_current"),
            ("2026-01-06", "FAKECO SALARY JAN", "2000.00", "boi_current"),
            ("2026-01-07", "TO FAKE SAVINGS", "-500.00", "boi_current"),
        ],
    )

    rc = main(
        [
            "run",
            "--rules",
            str(personal_rules),
            "--in",
            str(in_csv),
            "--out",
            str(out_csv),
        ]
    )
    assert rc == 0

    rows = read_csv(out_csv)
    assert [r["category"] for r in rows] == ["House", "Income", "Savings"]
    assert [r["subcategory"] for r in rows] == ["Furniture", "Salary", ""]
    assert [r["is_transfer"] for r in rows] == ["False", "False", "True"]
    # Original canonical columns must survive untouched.
    assert rows[0]["description"] == "FAKE FURNITURE STORE"
    assert rows[0]["amount"] == "-120.00"


def test_run_personal_rules_beat_builtin(tmp_path, personal_rules):
    in_csv = tmp_path / "canonical.csv"
    out_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv, [("2026-01-05", "ATM FAKE STREET", "-50.00", "boi_current")]
    )

    rc = main(
        ["run", "--rules", str(personal_rules), "--in", str(in_csv), "--out", str(out_csv)]
    )
    assert rc == 0
    rows = read_csv(out_csv)
    assert rows[0]["category"] == "Personal Override"  # builtin says Cash/ATM


def test_run_builtin_only_when_no_rules_flag(tmp_path):
    in_csv = tmp_path / "canonical.csv"
    out_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv, [("2026-01-05", "ATM FAKE STREET", "-50.00", "boi_current")]
    )
    rc = main(["run", "--in", str(in_csv), "--out", str(out_csv)])
    assert rc == 0
    rows = read_csv(out_csv)
    assert rows[0]["category"] == "Cash"
    assert rows[0]["subcategory"] == "ATM"


def test_run_uncategorised_beyond_tolerance_exits_nonzero(tmp_path, capsys):
    in_csv = tmp_path / "canonical.csv"
    out_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv,
        [
            ("2026-01-05", "MYSTERY MERCHANT ZZZ", "-42.00", "boi_current"),
            ("2026-01-06", "FAKECO SALARY JAN", "2000.00", "boi_current"),
        ],
    )

    rc = main(["run", "--in", str(in_csv), "--out", str(out_csv)])
    assert rc == 1
    # The categorised CSV is still written so `report` can run on it.
    assert out_csv.exists()

    out = capsys.readouterr().out
    # Count-only summary: no description text, no amounts. The CLI echoes
    # the --out PATH on stdout, and pytest's tmp_path contains a
    # run-numbered directory (pytest-NNN) that can legitimately contain
    # any digit substring -- scrub it before the digit assertions or this
    # test flakes whenever NNN happens to contain "42".
    out_scrubbed = out.replace(str(tmp_path), "<tmp>")
    assert "MYSTERY MERCHANT ZZZ" not in out_scrubbed
    assert "42" not in out_scrubbed
    assert "1 uncategorised" in out_scrubbed


def test_run_tolerance_allows_small_uncategorised(tmp_path):
    in_csv = tmp_path / "canonical.csv"
    out_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv,
        [
            ("2026-01-05", "MYSTERY MERCHANT ZZZ", "-42.00", "boi_current"),
            ("2026-01-06", "FAKECO SALARY JAN", "2000.00", "boi_current"),
        ],
    )
    rc = main(["run", "--in", str(in_csv), "--out", str(out_csv), "--tolerance", "42"])
    assert rc == 0
    rc = main(["run", "--in", str(in_csv), "--out", str(out_csv), "--tolerance", "41.99"])
    assert rc == 1


def test_run_zero_amount_uncategorised_passes_default_tolerance(tmp_path):
    in_csv = tmp_path / "canonical.csv"
    out_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv, [("2026-01-05", "ZERO VALUE NOTE", "0.00", "boi_current")]
    )
    rc = main(["run", "--in", str(in_csv), "--out", str(out_csv)])
    assert rc == 0


def test_run_missing_rules_file_errors(tmp_path, capsys):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "X", "1.00", "boi_current")])
    rc = main(
        [
            "run",
            "--rules",
            str(tmp_path / "nope.yaml"),
            "--in",
            str(in_csv),
            "--out",
            str(tmp_path / "out.csv"),
        ]
    )
    assert rc == 1


def test_report_writes_sorted_rows_and_aggregation(tmp_path, capsys):
    in_csv = tmp_path / "canonical.csv"
    cat_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv,
        [
            ("2026-01-05", "SMALL MYSTERY", "-5.00", "boi_current"),
            ("2026-01-06", "BIG MYSTERY", "-900.00", "boi_current"),
            ("2026-01-07", "SMALL MYSTERY", "-7.50", "boi_current"),
            ("2026-01-08", "FAKECO SALARY JAN", "2000.00", "boi_current"),
        ],
    )
    rc = main(["run", "--in", str(in_csv), "--out", str(cat_csv), "--tolerance", "99999"])
    assert rc == 0

    uncat_csv = tmp_path / "uncategorised.csv"
    rc = main(["report", "--in", str(cat_csv), "--out", str(uncat_csv)])
    assert rc == 0

    rows = read_csv(uncat_csv)
    # Only the 3 uncategorised rows, sorted by |amount| descending.
    assert [r["description"] for r in rows] == [
        "BIG MYSTERY",
        "SMALL MYSTERY",
        "SMALL MYSTERY",
    ]
    assert [r["amount"] for r in rows] == ["-900.00", "-7.50", "-5.00"]
    # Helper columns must not leak into the report.
    assert "_abs" not in rows[0] and "_amount_dec" not in rows[0]

    agg_csv = tmp_path / "uncategorised_by_description.csv"
    agg = read_csv(agg_csv)
    assert [r["description"] for r in agg] == ["BIG MYSTERY", "SMALL MYSTERY"]
    assert agg[0]["count"] == "1"
    assert agg[1]["count"] == "2"
    assert agg[1]["total_amount"] == "-12.50"

    # stdout carries counts and paths only -- never transaction data.
    # Scrub the echoed tmp_path first: its run-numbered directory
    # (pytest-NNN) can legitimately contain "900" (same flake class as
    # test_run_uncategorised_beyond_tolerance_exits_nonzero).
    out = capsys.readouterr().out.replace(str(tmp_path), "<tmp>")
    assert "MYSTERY" not in out
    assert "900" not in out
    assert "3 uncategorised row(s)" in out
    assert "2 distinct description(s)" in out


def test_report_explicit_agg_out(tmp_path):
    in_csv = tmp_path / "canonical.csv"
    cat_csv = tmp_path / "categorised.csv"
    write_canonical_csv(
        in_csv, [("2026-01-05", "MYSTERY", "-5.00", "boi_current")]
    )
    main(["run", "--in", str(in_csv), "--out", str(cat_csv), "--tolerance", "99999"])

    uncat_csv = tmp_path / "u.csv"
    agg_csv = tmp_path / "agg.csv"
    rc = main(
        [
            "report",
            "--in",
            str(cat_csv),
            "--out",
            str(uncat_csv),
            "--agg-out",
            str(agg_csv),
        ]
    )
    assert rc == 0
    assert agg_csv.exists()


def test_report_rejects_uncategorised_input(tmp_path, capsys):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "X", "1.00", "boi_current")])
    rc = main(
        ["report", "--in", str(in_csv), "--out", str(tmp_path / "u.csv")]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "category" in err


def test_run_bad_amount_error_does_not_echo_text(tmp_path, capsys):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(
        in_csv, [("2026-01-05", "SOME ROW", "SENSITIVEJUNK", "boi_current")]
    )
    rc = main(["run", "--in", str(in_csv), "--out", str(tmp_path / "out.csv")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "SENSITIVEJUNK" not in captured.out + captured.err
