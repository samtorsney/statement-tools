"""`statements chart overview` / `charts.cli overview`, exercised on
synthetic categorised CSVs only (fake merchants, fake amounts, fake
accounts)."""
from __future__ import annotations

from pathlib import Path

import pytest

from charts.cli import main
from tests.test_charts_cli import SAMPLE_ROWS, write_categorised_csv


def test_overview_writes_html_and_unmatched_report(tmp_path, capsys):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    rc = main(
        [
            "overview",
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
    assert (out_dir / "overview.html").exists()
    assert (out_dir / "unmatched_transfers.csv").exists()

    html = (out_dir / "overview.html").read_text(encoding="utf-8")
    assert "<html" in html.lower()

    out = capsys.readouterr().out
    assert "MYSTERY MERCHANT" not in out
    assert "5 row(s)" in out
    assert "1 uncategorised" in out
    assert "0 unmatched transfer" in out


def test_overview_stdout_is_counts_only_no_transaction_text(tmp_path, capsys):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    main(
        [
            "overview",
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
    out = capsys.readouterr().out
    for leak in ("BIG COFFEE HOUSE", "MYSTERY MERCHANT", "FAKECO SALARY JAN"):
        assert leak not in out


def test_overview_empty_in_range_exits_nonzero_count_only(tmp_path, capsys):
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    rc = main(
        [
            "overview",
            "--in",
            str(in_csv),
            "--from",
            "2030-01-01",
            "--to",
            "2030-01-31",
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 1
    assert not (out_dir / "overview.html").exists()
    err = capsys.readouterr().err
    assert "0 in range" in err
    for leak in ("BIG COFFEE HOUSE", "MYSTERY MERCHANT", "FAKECO SALARY JAN"):
        assert leak not in err


def test_overview_unmatched_transfer_written_and_counted(tmp_path, capsys):
    rows = SAMPLE_ROWS + [
        ("2026-01-25", "TO FAKE SAVINGS", "-77.00", "boi_current", "Transfer", "", True),
    ]
    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, rows)
    out_dir = tmp_path / "reports"

    rc = main(
        [
            "overview",
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


def test_overview_missing_required_columns_errors(tmp_path, capsys):
    in_csv = tmp_path / "bad.csv"
    with open(in_csv, "w", newline="", encoding="utf-8") as f:
        f.write("date,description,amount\n2026-01-01,X,1.00\n")

    rc = main(
        [
            "overview",
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


def test_statements_dispatcher_chart_overview_delegates(tmp_path):
    import statement_tools_cli

    in_csv = tmp_path / "categorised.csv"
    write_categorised_csv(in_csv, SAMPLE_ROWS)
    out_dir = tmp_path / "reports"

    rc = statement_tools_cli.main(
        [
            "chart",
            "overview",
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
    assert (out_dir / "overview.html").exists()
