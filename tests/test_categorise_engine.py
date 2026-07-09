"""Categorisation engine semantics, exercised on synthetic frames only
(fake merchants, fake amounts)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from categorise.engine import categorise
from categorise.rules import Rule, RuleError, build_rule, load_builtin_rules, load_rules


def frame_of(rows):
    """rows: list of (description, account) tuples -> minimal canonical frame."""
    return pd.DataFrame(
        {
            "description": [r[0] for r in rows],
            "account": [r[1] for r in rows],
        }
    )


# ---------------------------------------------------------------------------
# Match types
# ---------------------------------------------------------------------------

def test_match_types():
    rules = [
        Rule(match="exact", pattern="FAKE GYM", category="Health/Gym"),
        Rule(match="contains", pattern="COFFEE", category="Food/Coffee"),
        Rule(match="prefix", pattern="DD ", category="Bills/Direct Debit"),
        Rule(match="regex", pattern=r"^SUB\d+$", category="Bills/Subscriptions"),
    ]
    out = categorise(
        frame_of(
            [
                ("FAKE GYM", "boi_current"),
                ("BIG COFFEE HOUSE", "boi_current"),
                ("DD ELECTRIC CO", "boi_current"),
                ("SUB12345", "boi_current"),
                ("UNMATCHED THING", "boi_current"),
            ]
        ),
        rules,
    )
    assert list(out["category"]) == ["Health", "Food", "Bills", "Bills", ""]
    assert list(out["subcategory"]) == [
        "Gym",
        "Coffee",
        "Direct Debit",
        "Subscriptions",
        "",
    ]
    assert list(out["is_transfer"]) == [False, False, False, False, False]


def test_exact_is_whole_string_and_case_sensitive():
    rules = [Rule(match="exact", pattern="FAKE GYM", category="Health")]
    out = categorise(
        frame_of(
            [
                ("FAKE GYM MEMBERSHIP", "boi_current"),
                ("fake gym", "boi_current"),
                ("FAKE GYM", "boi_current"),
            ]
        ),
        rules,
    )
    assert list(out["category"]) == ["", "", "Health"]


def test_single_segment_category_has_empty_subcategory():
    rules = [Rule(match="exact", pattern="THING", category="Misc")]
    out = categorise(frame_of([("THING", "any_acct")]), rules)
    assert out.loc[0, "category"] == "Misc"
    assert out.loc[0, "subcategory"] == ""


def test_three_segment_category_path():
    rules = [Rule(match="exact", pattern="X", category="A/B/C")]
    out = categorise(frame_of([("X", "boi_current")]), rules)
    assert out.loc[0, "category"] == "A"
    assert out.loc[0, "subcategory"] == "B/C"


# ---------------------------------------------------------------------------
# Account scoping
# ---------------------------------------------------------------------------

def test_account_scoping():
    rules = [
        Rule(match="exact", pattern="SHOP", category="BOI Only", account="boi_current"),
        Rule(match="exact", pattern="SHOP", category="Everyone", account="any"),
    ]
    out = categorise(
        frame_of([("SHOP", "boi_current"), ("SHOP", "revolut_current")]),
        rules,
    )
    assert out.loc[0, "category"] == "BOI Only"
    assert out.loc[1, "category"] == "Everyone"


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------

def test_first_match_wins_within_a_list():
    rules = [
        Rule(match="contains", pattern="SHOP", category="First"),
        Rule(match="exact", pattern="BIG SHOP", category="Second"),
    ]
    out = categorise(frame_of([("BIG SHOP", "boi_current")]), rules)
    assert out.loc[0, "category"] == "First"


def test_personal_rules_beat_builtin_rules():
    personal = [Rule(match="prefix", pattern="ATM", category="My Override")]
    builtin = load_builtin_rules()
    out = categorise(
        frame_of([("ATM WITHDRAWAL FAKE ST", "boi_current")]),
        personal + builtin,
    )
    # builtin would say Cash/ATM; the personal rule is evaluated first.
    assert out.loc[0, "category"] == "My Override"


# ---------------------------------------------------------------------------
# extract behaviour
# ---------------------------------------------------------------------------

def test_extract_appends_a_category_segment():
    rules = [
        Rule(
            match="regex",
            pattern=r"^FEE(?P<currency>[A-Z]{3})$",
            category="Fees/Card FX",
            extract="currency",
        )
    ]
    out = categorise(frame_of([("FEEGBP", "boi_current")]), rules)
    assert out.loc[0, "category"] == "Fees"
    assert out.loc[0, "subcategory"] == "Card FX/GBP"


def test_extract_on_single_segment_category():
    rules = [
        Rule(
            match="regex",
            pattern=r"(?P<country>[A-Z]{2})$",
            category="Card Payment",
            extract="country",
        )
    ]
    out = categorise(frame_of([("POS 1234US", "boi_current")]), rules)
    assert out.loc[0, "category"] == "Card Payment"
    assert out.loc[0, "subcategory"] == "US"


# ---------------------------------------------------------------------------
# transfer flag
# ---------------------------------------------------------------------------

def test_transfer_flag_carried_to_frame():
    rules = [
        Rule(match="exact", pattern="TO SAVINGS", category="Transfer", transfer=True),
        Rule(match="exact", pattern="GROCERIES", category="Food"),
    ]
    out = categorise(
        frame_of([("TO SAVINGS", "boi_current"), ("GROCERIES", "boi_current")]),
        rules,
    )
    assert list(out["is_transfer"]) == [True, False]


# ---------------------------------------------------------------------------
# Builtin rules (structural semantics from the spec)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def builtin():
    return load_builtin_rules()


def test_builtin_neposchg_card_fx_fee(builtin):
    out = categorise(frame_of([("NEPOSCHGGBP 0.57", "boi_current")]), builtin)
    assert out.loc[0, "category"] == "Fees"
    assert out.loc[0, "subcategory"] == "Card FX/GBP"
    assert not out.loc[0, "is_transfer"]


def test_builtin_neatmchg_atm_fee(builtin):
    out = categorise(frame_of([("NEATMCHGUSD 3.17", "boi_current")]), builtin)
    assert out.loc[0, "category"] == "Fees"
    assert out.loc[0, "subcategory"] == "ATM/USD"


def test_builtin_govt_duty_precedes_atm(builtin):
    out = categorise(
        frame_of(
            [
                ("GOVT DUTY ATM CHARGE", "boi_current"),
                ("ATM FAKE STREET 99", "boi_current"),
            ]
        ),
        builtin,
    )
    assert out.loc[0, "category"] == "Fees"
    assert out.loc[0, "subcategory"] == "ATM Tax"
    assert out.loc[1, "category"] == "Cash"
    assert out.loc[1, "subcategory"] == "ATM"


def test_builtin_tx_prefix_card_payment(builtin):
    out = categorise(frame_of([("TXFAKE MERCHANT", "boi_current")]), builtin)
    assert out.loc[0, "category"] == "Card Payment"
    assert out.loc[0, "subcategory"] == ""


def test_builtin_foreign_pos_extracts_country(builtin):
    out = categorise(frame_of([("POSFAKE SHOP 1234FR", "boi_current")]), builtin)
    assert out.loc[0, "category"] == "Card Payment"
    assert out.loc[0, "subcategory"] == "FR"


def test_builtin_salary(builtin):
    out = categorise(frame_of([("FAKECO SALARY MAR", "boi_current")]), builtin)
    assert out.loc[0, "category"] == "Income"
    assert out.loc[0, "subcategory"] == "Salary"


def test_builtin_boi_rules_do_not_hit_revolut_rows(builtin):
    out = categorise(frame_of([("ATM FAKE STREET", "revolut_current")]), builtin)
    assert out.loc[0, "category"] == ""


def test_builtin_revolut_transfer(builtin):
    out = categorise(
        frame_of(
            [
                ("Transfer to Fake Person", "revolut_current"),
                ("Transfer from Fake Person", "revolut_current"),
                ("Transfer to Fake Person", "boi_current"),  # wrong account
            ]
        ),
        builtin,
    )
    assert out.loc[0, "category"] == "Transfer"
    assert out.loc[0, "subcategory"] == "Fake Person"
    assert bool(out.loc[0, "is_transfer"]) is True
    assert out.loc[1, "subcategory"] == "Fake Person"
    assert bool(out.loc[1, "is_transfer"]) is True
    assert out.loc[2, "category"] == ""


def test_categorise_does_not_mutate_input(builtin):
    frame = frame_of([("ATM FAKE", "boi_current")])
    before = list(frame.columns)
    categorise(frame, builtin)
    assert list(frame.columns) == before


# ---------------------------------------------------------------------------
# Rule loading / validation
# ---------------------------------------------------------------------------

def test_load_rules_roundtrip(tmp_path: Path):
    p = tmp_path / "rules.yaml"
    p.write_text(
        "- match: exact\n"
        "  pattern: FAKE SHOP\n"
        "  category: House/Furniture\n"
        "  account: boi_current\n"
        "  transfer: false\n",
        encoding="utf-8",
    )
    rules = load_rules(p)
    assert rules == [
        Rule(
            match="exact",
            pattern="FAKE SHOP",
            category="House/Furniture",
            account="boi_current",
        )
    ]


@pytest.mark.parametrize(
    "raw",
    [
        {"match": "nope", "pattern": "X", "category": "C"},
        {"match": "exact", "category": "C"},  # missing pattern
        {"match": "exact", "pattern": "X"},  # missing category
        {"match": "exact", "pattern": "X", "category": ""},
        {"match": "exact", "pattern": "X", "category": "A//B"},
        {"match": "exact", "pattern": "X", "category": "C", "bogus": 1},
        {"match": "exact", "pattern": "X", "category": "C", "extract": "g"},
        {"match": "regex", "pattern": "(?P<a>X)", "category": "C", "extract": "b"},
        {"match": "regex", "pattern": "(unclosed", "category": "C"},
        {"match": "exact", "pattern": "X", "category": "C", "transfer": "yes"},
    ],
)
def test_build_rule_rejects_bad_input(raw):
    with pytest.raises(RuleError):
        build_rule(raw, 0, "test.yaml")


def test_rule_errors_never_echo_pattern_text():
    secret = "SECRET PAYEE NAME"
    with pytest.raises(RuleError) as exc_info:
        build_rule(
            {"match": "exact", "pattern": secret, "category": "C", "bogus": 1},
            3,
            "personal.yaml",
        )
    assert secret not in str(exc_info.value)
    assert "rule[3]" in str(exc_info.value)


def test_builtin_rules_file_is_valid_and_ordered():
    rules = load_builtin_rules()
    # Structural expectations that encode the precedence the spec lists.
    boi = [r for r in rules if r.account == "boi_current"]
    rev = [r for r in rules if r.account == "revolut_current"]
    assert len(boi) == 7
    assert len(rev) == 1
    patterns = [r.pattern for r in boi]
    assert patterns.index("GOVT DUTY ATM") < patterns.index("ATM")
    assert rev[0].transfer is True
