"""Profile schema tests: malformed profiles must produce helpful ProfileError
messages, not stack traces. Also covers the shipped profiles loading cleanly."""
from __future__ import annotations

from pathlib import Path

import pytest

from statement_parser.profile import build_profile, load_profile
from statement_parser.errors import ProfileError

PROFILES_DIR = Path(__file__).resolve().parent.parent / "statement_parser" / "profiles"

VALID_PDF = {
    "meta": {"name": "test_bank", "institution": "Test Bank", "country": "IE", "source": "pdf"},
    "page_detect": {"strategy": "header_match"},
    "columns": [
        {"header": "Date", "field": "date", "align": "left_edge"},
        {"header": "Details", "field": "description", "align": "left_edge"},
        {"header": "Out", "field": "out", "align": "left_edge"},
        {"header": "In", "field": "in", "align": "midpoint"},
        {"header": "Balance", "field": "balance", "align": "midpoint"},
    ],
    "table_end": {"strategy": "spacing_gap"},
    "rows": {"line_tolerance": 3, "multiline": "merge_into_previous"},
    "amounts": {"style": "in_out", "thousands": ",", "decimal": "."},
    "dates": {"format": "%d %b %Y", "fill": "forward"},
    "balance": {"present": True, "validate": "continuity"},
    "skip_rows": [{"field": "description", "equals": "BALANCE FORWARD"}],
}

VALID_CSV = {
    "meta": {"name": "test_csv", "institution": "Test CSV Bank", "country": "IE", "source": "csv"},
    "csv": {
        "encoding": "utf-8",
        "delimiter": ",",
        "column_map": {"Date": "date", "Details": "description", "Amount": "amount"},
    },
    "amounts": {"style": "signed"},
    "dates": {"format": "%Y-%m-%d"},
    "balance": {"present": False, "validate": "none"},
    "skip_rows": [],
}


def _copy(d):
    import copy

    return copy.deepcopy(d)


def test_shipped_boi_profile_loads():
    profile = load_profile(PROFILES_DIR / "boi_current.yaml")
    assert profile.meta.name == "boi_current"
    assert profile.meta.source == "pdf"
    assert profile.amounts.style == "in_out"
    assert profile.balance.present is True


def test_shipped_revolut_profile_loads():
    profile = load_profile(PROFILES_DIR / "revolut_current.yaml")
    assert profile.meta.name == "revolut_current"
    assert profile.meta.source == "csv"
    assert profile.amounts.style == "signed"
    assert profile.csv.column_map["Amount"] == "amount"


def test_valid_pdf_profile_builds():
    profile = build_profile(_copy(VALID_PDF))
    assert profile.meta.source == "pdf"
    assert len(profile.columns) == 5


def test_valid_csv_profile_builds():
    profile = build_profile(_copy(VALID_CSV))
    assert profile.meta.source == "csv"


def test_unknown_top_level_key_is_hard_error():
    raw = _copy(VALID_PDF)
    raw["totally_unknown_section"] = {}
    with pytest.raises(ProfileError, match="unknown key"):
        build_profile(raw)


def test_unknown_table_end_strategy_is_actionable():
    raw = _copy(VALID_PDF)
    raw["table_end"]["strategy"] = "gap"
    with pytest.raises(ProfileError, match="spacing_gap"):
        build_profile(raw)


def test_unknown_align_strategy_is_actionable():
    raw = _copy(VALID_PDF)
    raw["columns"][0]["align"] = "center"
    with pytest.raises(ProfileError, match="left_edge"):
        build_profile(raw)


def test_unknown_page_detect_strategy_is_actionable():
    raw = _copy(VALID_PDF)
    raw["page_detect"]["strategy"] = "bogus"
    with pytest.raises(ProfileError, match="header_match"):
        build_profile(raw)


def test_unknown_multiline_strategy_is_actionable():
    raw = _copy(VALID_PDF)
    raw["rows"]["multiline"] = "bogus"
    with pytest.raises(ProfileError, match="merge_into_previous"):
        build_profile(raw)


def test_reserved_dates_year_policy_is_rejected():
    raw = _copy(VALID_PDF)
    raw["dates"]["year_policy"] = "assume_current"
    with pytest.raises(ProfileError, match="reserved"):
        build_profile(raw)


def test_missing_required_meta_key_is_error():
    raw = _copy(VALID_PDF)
    del raw["meta"]["source"]
    with pytest.raises(ProfileError, match="missing required key"):
        build_profile(raw)


def test_invalid_meta_source_is_error():
    raw = _copy(VALID_PDF)
    raw["meta"]["source"] = "xml"
    with pytest.raises(ProfileError):
        build_profile(raw)


def test_pdf_profile_missing_columns_is_error():
    raw = _copy(VALID_PDF)
    del raw["columns"]
    with pytest.raises(ProfileError, match="missing required section"):
        build_profile(raw)


def test_csv_section_on_pdf_profile_is_error():
    raw = _copy(VALID_PDF)
    raw["csv"] = {"column_map": {"Date": "date"}}
    with pytest.raises(ProfileError, match="csv-only"):
        build_profile(raw)


def test_pdf_only_section_on_csv_profile_is_error():
    raw = _copy(VALID_CSV)
    raw["columns"] = []
    with pytest.raises(ProfileError, match="pdf-only"):
        build_profile(raw)


def test_in_out_style_requires_in_and_out_fields():
    raw = _copy(VALID_PDF)
    raw["columns"][3]["field"] = "balance"  # remove the only 'in' column
    raw["columns"][3]["header"] = "In2"
    with pytest.raises(ProfileError, match="in_out"):
        build_profile(raw)


def test_signed_style_requires_amount_field():
    raw = _copy(VALID_CSV)
    raw["csv"]["column_map"]["Amount"] = "balance"
    raw["balance"]["present"] = True
    with pytest.raises(ProfileError, match="signed"):
        build_profile(raw)


def test_balance_present_requires_balance_field():
    raw = _copy(VALID_PDF)
    raw["balance"]["present"] = False
    with pytest.raises(ProfileError, match="balance"):
        build_profile(raw)


def test_skip_row_field_must_be_mapped():
    raw = _copy(VALID_PDF)
    raw["skip_rows"].append({"field": "currency", "equals": "USD"})
    with pytest.raises(ProfileError, match="currency"):
        build_profile(raw)


def test_unknown_canonical_field_in_column_is_error():
    raw = _copy(VALID_PDF)
    raw["columns"][0]["field"] = "not_a_real_field"
    with pytest.raises(ProfileError, match="not a canonical field"):
        build_profile(raw)


def test_missing_column_key_is_error():
    raw = _copy(VALID_PDF)
    del raw["columns"][0]["align"]
    with pytest.raises(ProfileError, match="missing required key"):
        build_profile(raw)
