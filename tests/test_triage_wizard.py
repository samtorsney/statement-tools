"""triage.wizard: the interactive loop, driven entirely by scripted
in-memory streams over synthetic fixtures. Never run against real data."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from categorise.rules import Rule
from triage.wizard import WizardOutcome, run_wizard

CANONICAL_COLUMNS = ["description", "account", "amount"]


def make_frame(rows):
    """rows: (description, account, amount) tuples."""
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS)


class _RaisesKeyboardInterrupt:
    """A fake stream whose readline() raises KeyboardInterrupt once, then
    behaves like an exhausted stream -- simulates a Ctrl-C during input()."""

    def __init__(self):
        self._raised = False

    def readline(self):
        if not self._raised:
            self._raised = True
            raise KeyboardInterrupt()
        return ""


def test_empty_uncategorised_set_exits_cleanly():
    frame = make_frame([("FAKECO SALARY JAN", "boi_current", "2000.00")])
    builtin = [Rule(match="contains", pattern="SALARY", category="Income", account="boi_current")]
    out_stream = io.StringIO()

    outcome = run_wizard(frame, Path("unused.yaml"), [], builtin, io.StringIO(""), out_stream)

    assert outcome == WizardOutcome(0, 0, 0, 0)
    assert "nothing to triage" in out_stream.getvalue()


def test_grouped_by_description_sorted_by_total_abs_desc(tmp_path):
    frame = make_frame(
        [
            ("SMALL MYSTERY", "boi_current", "-5.00"),
            ("BIG MYSTERY", "boi_current", "-900.00"),
            ("SMALL MYSTERY", "boi_current", "-7.50"),
        ]
    )
    rules_path = tmp_path / "personal_rules.yaml"
    # Skip every group ('s') -- just checking prompt ordering.
    in_stream = io.StringIO("s\ns\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    text = out_stream.getvalue()
    assert text.index("BIG MYSTERY") < text.index("SMALL MYSTERY")
    assert outcome.skipped == 2
    assert outcome.accepted == 0


def test_accept_by_free_text_category_writes_rule(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP", "boi_current", "-4.50")])
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("Food/Coffee\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    assert outcome.accepted == 1
    assert outcome.after_uncategorised == 0
    content = rules_path.read_text(encoding="utf-8")
    assert "pattern: FAKE COFFEE SHOP" in content
    assert "category: Food/Coffee" in content
    assert "match: exact" in content


def test_accept_by_menu_number(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP", "boi_current", "-4.50")])
    personal = [Rule(match="exact", pattern="OTHER ROW", category="Existing/Category", account="boi_current")]
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("1\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, personal, [], in_stream, out_stream)

    assert outcome.accepted == 1
    content = rules_path.read_text(encoding="utf-8")
    assert "category: Existing/Category" in content


def test_match_type_shortcut_contains(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP 1234", "boi_current", "-4.50")])
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("Food/Coffee:c\n")
    out_stream = io.StringIO()

    run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    content = rules_path.read_text(encoding="utf-8")
    assert "match: contains" in content


def test_match_type_shortcut_prefix(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP 1234", "boi_current", "-4.50")])
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("Food/Coffee:p\n")
    out_stream = io.StringIO()

    run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    content = rules_path.read_text(encoding="utf-8")
    assert "match: prefix" in content


def test_transfer_toggle_sets_flag(tmp_path):
    frame = make_frame([("TO FAKE SAVINGS", "boi_current", "-500.00")])
    rules_path = tmp_path / "personal_rules.yaml"
    # toggle transfer on, then accept as free text category.
    in_stream = io.StringIO("t\nSavings\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    assert outcome.accepted == 1
    content = rules_path.read_text(encoding="utf-8")
    assert "transfer: true" in content


def test_skip_does_not_write_rule(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP", "boi_current", "-4.50")])
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("s\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    assert outcome.skipped == 1
    assert outcome.accepted == 0
    assert not rules_path.exists()


def test_quit_saves_accepted_rules_so_far(tmp_path):
    frame = make_frame(
        [
            ("FAKE COFFEE SHOP", "boi_current", "-4.50"),
            ("ANOTHER MYSTERY ROW", "boi_current", "-10.00"),
        ]
    )
    rules_path = tmp_path / "personal_rules.yaml"
    # Accept the first (larger |amount|) group, then quit before the second.
    in_stream = io.StringIO("Food/Coffee\nq\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    assert outcome.accepted == 1
    assert outcome.skipped == 0
    content = rules_path.read_text(encoding="utf-8")
    assert content.count("- match:") == 1


def test_invalid_menu_input_reprompts(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP", "boi_current", "-4.50")])
    rules_path = tmp_path / "personal_rules.yaml"
    # "99" is out of range (empty menu); then accept via free text.
    in_stream = io.StringIO("99\nFood/Coffee\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    assert outcome.accepted == 1
    assert "invalid input" in out_stream.getvalue()


def test_eof_on_input_stream_behaves_like_quit(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP", "boi_current", "-4.50")])
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("")  # immediate EOF
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    assert outcome.accepted == 0
    assert not rules_path.exists()


def test_ctrl_c_behaves_like_quit_no_partial_write(tmp_path):
    frame = make_frame(
        [
            ("FAKE COFFEE SHOP", "boi_current", "-4.50"),
            ("ANOTHER MYSTERY ROW", "boi_current", "-10.00"),
        ]
    )
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = _RaisesKeyboardInterrupt()
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    assert outcome.accepted == 0
    assert not rules_path.exists()
    assert "before=" in out_stream.getvalue()


def test_backup_created_before_first_write_only(tmp_path):
    frame = make_frame(
        [
            ("FAKE COFFEE SHOP", "boi_current", "-4.50"),
            ("ANOTHER MYSTERY ROW", "boi_current", "-10.00"),
        ]
    )
    rules_path = tmp_path / "personal_rules.yaml"
    rules_path.write_text(
        "- match: exact\n  pattern: PRE EXISTING\n  category: Existing\n",
        encoding="utf-8",
    )

    in_stream = io.StringIO("Food/Coffee\nMisc/Other\n")
    out_stream = io.StringIO()

    run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    backups = list(tmp_path.glob("personal_rules.yaml.*.bak"))
    assert len(backups) == 1
    backup_content = backups[0].read_text(encoding="utf-8")
    assert "PRE EXISTING" in backup_content

    final_content = rules_path.read_text(encoding="utf-8")
    assert "PRE EXISTING" in final_content
    assert final_content.count("- match:") == 3


def test_no_backup_when_rules_file_did_not_exist(tmp_path):
    frame = make_frame([("FAKE COFFEE SHOP", "boi_current", "-4.50")])
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("Food/Coffee\n")
    out_stream = io.StringIO()

    run_wizard(frame, rules_path, [], [], in_stream, out_stream)

    backups = list(tmp_path.glob("personal_rules.yaml.*.bak"))
    assert len(backups) == 0


def test_before_after_counts_printed(tmp_path):
    frame = make_frame(
        [
            ("FAKE COFFEE SHOP", "boi_current", "-4.50"),
            ("FAKECO SALARY JAN", "boi_current", "2000.00"),
        ]
    )
    builtin = [Rule(match="contains", pattern="SALARY", category="Income", account="boi_current")]
    rules_path = tmp_path / "personal_rules.yaml"
    in_stream = io.StringIO("Food/Coffee\n")
    out_stream = io.StringIO()

    outcome = run_wizard(frame, rules_path, [], builtin, in_stream, out_stream)

    assert outcome.before_uncategorised == 1
    assert outcome.after_uncategorised == 0
    text = out_stream.getvalue()
    assert "before=1" in text
    assert "after=0" in text
