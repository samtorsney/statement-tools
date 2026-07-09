"""Migration script tested against a SYNTHETIC notebook fixture with the
same cell structure as the real one -- fake merchants only. The real
sankey.ipynb is never opened by tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from categorise.migrate_notebook_rules import (
    convert_category,
    is_transfer_category,
    main,
)

OUTPUT_SENTINEL = "LEAKED-OUTPUT-SENTINEL-9f2c"


def make_notebook(path: Path, boi_src: str, rev_src: str, extra_cells=()):
    """Build an .ipynb JSON file structurally like the real notebook:
    markdown cells, code cells with magics, the two dict assignments, and a
    code cell carrying an outputs array that must never be read."""
    def code_cell(source, outputs=None):
        return {
            "cell_type": "code",
            "execution_count": 1,
            "metadata": {},
            "outputs": outputs or [],
            "source": source.splitlines(keepends=True),
        }

    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Fake analysis\n"]},
        code_cell("%matplotlib inline\nimport pandas as pd\n"),
        code_cell(boi_src),
        code_cell(rev_src),
        code_cell(
            "df.head()\n",
            outputs=[
                {
                    "output_type": "execute_result",
                    "data": {"text/plain": [OUTPUT_SENTINEL]},
                    "metadata": {},
                    "execution_count": 1,
                }
            ],
        ),
        *extra_cells,
    ]
    nb = {
        "cells": cells,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(nb), encoding="utf-8")


BOI_SRC = """\
details_category_map = {
    'FAKE FURNITURE STORE': 'House (Furniture)',
    'FAKE GROCER LTD': 'Food',
    'TO FAKE SAVINGS AC': 'Savings',
    'FAKE CC REPAY': 'Credit Card Repayment',
}
"""

REV_SRC = """\
rev_details_category_map = {
    'Fake Coffee Bar': 'Food (Coffee)',
    'Top-up via bank': 'Top Up',
    'To EUR Fake Pocket': 'Savings (Pocket)',
    'From EUR Fake Pocket': 'Pocket Withdrawal',
}
"""


@pytest.fixture
def notebook(tmp_path: Path) -> Path:
    nb_path = tmp_path / "synthetic_sankey.ipynb"
    make_notebook(nb_path, BOI_SRC, REV_SRC)
    return nb_path


def run_migration(notebook: Path, out: Path, *extra):
    return main(["--notebook", str(notebook), "--out", str(out), *extra])


def test_migration_writes_expected_rules(notebook, tmp_path, capsys):
    out = tmp_path / "category_rules.yaml"
    rc = run_migration(notebook, out)
    assert rc == 0

    rules = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(rules) == 8
    assert all(r["match"] == "exact" for r in rules)

    by_pattern = {r["pattern"]: r for r in rules}

    # Parenthesised suffix -> parent/child path.
    assert by_pattern["FAKE FURNITURE STORE"]["category"] == "House/Furniture"
    assert by_pattern["Fake Coffee Bar"]["category"] == "Food/Coffee"
    # Plain categories pass through.
    assert by_pattern["FAKE GROCER LTD"]["category"] == "Food"

    # Accounts follow the source dict.
    assert by_pattern["FAKE GROCER LTD"]["account"] == "boi_current"
    assert by_pattern["Fake Coffee Bar"]["account"] == "revolut_current"

    # Transfer-ish categories are flagged.
    assert by_pattern["TO FAKE SAVINGS AC"]["transfer"] is True
    assert by_pattern["FAKE CC REPAY"]["transfer"] is True
    assert by_pattern["Top-up via bank"]["transfer"] is True
    assert by_pattern["To EUR Fake Pocket"]["transfer"] is True  # Savings (Pocket)
    assert by_pattern["From EUR Fake Pocket"]["transfer"] is True
    # Ordinary spending is not.
    assert by_pattern["FAKE GROCER LTD"]["transfer"] is False
    assert by_pattern["Fake Coffee Bar"]["transfer"] is False


def test_migration_never_reads_outputs_and_prints_counts_only(
    notebook, tmp_path, capsys
):
    out = tmp_path / "category_rules.yaml"
    rc = run_migration(notebook, out)
    assert rc == 0

    # The outputs sentinel must not reach the rules file.
    text = out.read_text(encoding="utf-8")
    assert OUTPUT_SENTINEL not in text

    # stdout: counts only -- no merchant names, no categories.
    printed = capsys.readouterr().out
    assert OUTPUT_SENTINEL not in printed
    assert "FAKE" not in printed and "Fake" not in printed
    assert "Furniture" not in printed
    assert "boi_current=4" in printed
    assert "revolut_current=4" in printed
    assert "transfer-flagged=5" in printed
    assert "8 rule(s)" in printed


def test_migration_output_loads_with_rule_loader(notebook, tmp_path):
    from categorise.rules import load_rules

    out = tmp_path / "category_rules.yaml"
    assert run_migration(notebook, out) == 0
    rules = load_rules(out)
    assert len(rules) == 8


def test_migration_refuses_overwrite_without_force(notebook, tmp_path, capsys):
    out = tmp_path / "category_rules.yaml"
    assert run_migration(notebook, out) == 0
    assert run_migration(notebook, out) == 1  # exists, no --force
    assert run_migration(notebook, out, "--force") == 0


def test_migration_last_assignment_wins(tmp_path):
    nb_path = tmp_path / "nb.ipynb"
    later = (
        "details_category_map = {\n"
        "    'FAKE GROCER LTD': 'Groceries',\n"
        "}\n"
    )
    make_notebook(
        nb_path,
        BOI_SRC,
        REV_SRC,
        extra_cells=[
            {
                "cell_type": "code",
                "execution_count": 2,
                "metadata": {},
                "outputs": [],
                "source": later.splitlines(keepends=True),
            }
        ],
    )
    out = tmp_path / "rules.yaml"
    assert main(["--notebook", str(nb_path), "--out", str(out)]) == 0
    rules = yaml.safe_load(out.read_text(encoding="utf-8"))
    boi = [r for r in rules if r["account"] == "boi_current"]
    assert len(boi) == 1
    assert boi[0]["category"] == "Groceries"


def test_migration_missing_dict_errors_cleanly(tmp_path, capsys):
    nb_path = tmp_path / "nb.ipynb"
    make_notebook(nb_path, BOI_SRC, "x = 1\n")  # no rev dict
    rc = main(["--notebook", str(nb_path), "--out", str(tmp_path / "r.yaml")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "rev_details_category_map" in err
    assert "FAKE" not in err  # no dict contents in the error


def test_migration_missing_notebook_errors_cleanly(tmp_path, capsys):
    rc = main(
        ["--notebook", str(tmp_path / "missing.ipynb"), "--out", str(tmp_path / "r.yaml")]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err + captured.out


def test_convert_category():
    assert convert_category("House (Furniture)") == "House/Furniture"
    assert convert_category("Food") == "Food"
    assert convert_category("  Savings (Pocket)  ") == "Savings/Pocket"


def test_is_transfer_category():
    assert is_transfer_category("Savings")
    assert is_transfer_category("Savings/Pocket")
    assert is_transfer_category("Top Up")
    assert is_transfer_category("Credit Card Repayment")
    assert is_transfer_category("Pocket Withdrawal")
    assert not is_transfer_category("Food/Coffee")
    assert not is_transfer_category("Income/Salary")
