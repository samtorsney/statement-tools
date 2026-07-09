"""triage CLI wiring (`triage --in ... --rules ...`): input validation and
stream plumbing, exercised only on synthetic fixtures with a monkeypatched
stdin -- never run against real data."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from triage.cli import main

CANONICAL_COLUMNS = ["date", "description", "amount", "balance", "currency", "account", "source_file", "page", "row"]


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


def test_triage_empty_uncategorised_exits_zero(tmp_path, monkeypatch, capsys):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "FAKECO SALARY JAN", "2000.00", "boi_current")])
    rules_path = tmp_path / "personal_rules.yaml"

    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    rc = main(["--in", str(in_csv), "--rules", str(rules_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to triage" in out


def test_triage_accepts_a_rule_end_to_end(tmp_path, monkeypatch):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "FAKE COFFEE SHOP", "-4.50", "boi_current")])
    rules_path = tmp_path / "personal_rules.yaml"

    monkeypatch.setattr("sys.stdin", io.StringIO("Food/Coffee\n"))

    rc = main(["--in", str(in_csv), "--rules", str(rules_path)])
    assert rc == 0
    assert rules_path.exists()
    content = rules_path.read_text(encoding="utf-8")
    assert "category: Food/Coffee" in content


def test_triage_missing_input_file_errors(tmp_path, capsys):
    rc = main(["--in", str(tmp_path / "nope.csv"), "--rules", str(tmp_path / "rules.yaml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err


def test_triage_missing_required_columns_errors(tmp_path, capsys):
    in_csv = tmp_path / "bad.csv"
    in_csv.write_text("date,description,amount\n2026-01-01,X,1.00\n", encoding="utf-8")

    rc = main(["--in", str(in_csv), "--rules", str(tmp_path / "rules.yaml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing required column" in err


def test_triage_bad_amount_error_does_not_echo_text(tmp_path, capsys):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "X", "SENSITIVEJUNK", "boi_current")])

    rc = main(["--in", str(in_csv), "--rules", str(tmp_path / "rules.yaml")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "SENSITIVEJUNK" not in captured.out + captured.err


def test_triage_creates_rules_file_when_missing(tmp_path, monkeypatch):
    in_csv = tmp_path / "canonical.csv"
    write_canonical_csv(in_csv, [("2026-01-05", "FAKE COFFEE SHOP", "-4.50", "boi_current")])
    rules_path = tmp_path / "does_not_exist_yet.yaml"
    assert not rules_path.exists()

    monkeypatch.setattr("sys.stdin", io.StringIO("Food/Coffee\n"))

    rc = main(["--in", str(in_csv), "--rules", str(rules_path)])
    assert rc == 0
    assert rules_path.exists()
