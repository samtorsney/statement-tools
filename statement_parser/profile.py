"""Profile dataclasses + YAML loader + validation.

A profile is pure data describing one statement layout (PDF geometry or CSV
column mapping). Unknown keys are hard errors (typo safety for contributed
profiles); strategy names are validated against the registries in
engine/strategies.py with actionable messages; fields the schema reserves for
future use (e.g. dates.year_policy) are documented here but rejected until
implemented.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from .engine import strategies
from .errors import ProfileError

# Canonical field vocabulary a column (PDF) or column_map value (CSV) may
# target. "in"/"out" are only valid with amounts.style == "in_out"; "amount"
# is only valid with amounts.style == "signed".
CANONICAL_FIELDS = {
    "date",
    "description",
    "amount",
    "in",
    "out",
    "balance",
    "currency",
}

_ALIGN_CHOICES = tuple(strategies.ALIGN)

# Reserved-but-not-yet-implemented fields: documented in the schema, but the
# loader rejects them with a specific "not implemented" message rather than
# the generic "unknown key" error, so a contributor knows it's a known gap
# rather than a typo.
_RESERVED_FIELDS = {
    "dates": {
        "year_policy": (
            "dates.year_policy is reserved for statements that print dates "
            "without a year (e.g. credit cards printing '12 Jan'); not yet "
            "implemented. Use a full-year dates.format instead."
        ),
    },
}


def _require_mapping(value: Any, section: str) -> dict:
    if not isinstance(value, dict):
        raise ProfileError(
            f"section '{section}' must be a mapping, got {type(value).__name__}"
        )
    return value


def _check_keys(d: dict, allowed: set, section: str) -> None:
    reserved = _RESERVED_FIELDS.get(section, {})
    for key in d:
        if key in reserved:
            raise ProfileError(f"{section}.{key} is reserved: {reserved[key]}")
        if key not in allowed:
            raise ProfileError(
                f"unknown key '{section}.{key}'; allowed keys for {section}: "
                f"{', '.join(sorted(allowed))}"
            )


def _validate_strategy(name: Any, registry: Union[dict, set], label: str) -> None:
    if not isinstance(name, str) or name not in registry:
        available = ", ".join(sorted(registry))
        raise ProfileError(
            f"unknown {label} strategy '{name}'; available: {available}"
        )


@dataclasses.dataclass
class Meta:
    name: str
    institution: str
    country: str
    source: str  # "pdf" | "csv"


@dataclasses.dataclass
class ColumnSpec:
    header: str
    field: str
    align: str


@dataclasses.dataclass
class PageDetect:
    strategy: str = "header_match"


@dataclasses.dataclass
class TableEnd:
    strategy: str = "spacing_gap"
    text: Optional[str] = None  # only consumed by the footer_text strategy


@dataclasses.dataclass
class RowsConfig:
    line_tolerance: float = 3
    multiline: str = "merge_into_previous"


@dataclasses.dataclass
class AmountsConfig:
    style: str = "signed"
    thousands: str = ","
    decimal: str = "."


@dataclasses.dataclass
class DatesConfig:
    format: str = "%Y-%m-%d"
    fill: str = "none"


@dataclasses.dataclass
class BalanceConfig:
    present: bool = False
    validate: str = "none"


@dataclasses.dataclass
class SkipRow:
    field: str
    equals: str


@dataclasses.dataclass
class CsvConfig:
    encoding: str = "utf-8"
    delimiter: str = ","
    column_map: Dict[str, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Profile:
    meta: Meta
    amounts: AmountsConfig
    dates: DatesConfig
    balance: BalanceConfig
    skip_rows: List[SkipRow]
    page_detect: Optional[PageDetect] = None
    columns: Optional[List[ColumnSpec]] = None
    table_end: Optional[TableEnd] = None
    rows: Optional[RowsConfig] = None
    csv: Optional[CsvConfig] = None
    source_path: Optional[Path] = None


_TOP_LEVEL_KEYS = {
    "meta",
    "page_detect",
    "columns",
    "table_end",
    "rows",
    "amounts",
    "dates",
    "balance",
    "skip_rows",
    "csv",
}

_PDF_ONLY_KEYS = {"page_detect", "columns", "table_end", "rows"}
_CSV_ONLY_KEYS = {"csv"}


def _build_meta(raw: dict) -> Meta:
    raw = _require_mapping(raw, "meta")
    allowed = {"name", "institution", "country", "source"}
    _check_keys(raw, allowed, "meta")
    missing = allowed - set(raw)
    if missing:
        raise ProfileError(f"meta is missing required key(s): {', '.join(sorted(missing))}")
    source = raw["source"]
    if source not in ("pdf", "csv"):
        raise ProfileError(f"meta.source must be 'pdf' or 'csv', got {source!r}")
    return Meta(
        name=raw["name"],
        institution=raw["institution"],
        country=raw["country"],
        source=source,
    )


def _build_page_detect(raw: dict) -> PageDetect:
    raw = _require_mapping(raw, "page_detect")
    _check_keys(raw, {"strategy"}, "page_detect")
    strategy = raw.get("strategy", "header_match")
    _validate_strategy(strategy, strategies.PAGE_DETECT, "page_detect")
    return PageDetect(strategy=strategy)


def _build_columns(raw: Any) -> List[ColumnSpec]:
    if not isinstance(raw, list) or not raw:
        raise ProfileError("columns must be a non-empty list")
    allowed = {"header", "field", "align"}
    out = []
    for i, entry in enumerate(raw):
        entry = _require_mapping(entry, f"columns[{i}]")
        _check_keys(entry, allowed, f"columns[{i}]")
        missing = allowed - set(entry)
        if missing:
            raise ProfileError(
                f"columns[{i}] is missing required key(s): {', '.join(sorted(missing))}"
            )
        align = entry["align"]
        if align not in _ALIGN_CHOICES:
            raise ProfileError(
                f"unknown align strategy '{align}' in columns[{i}]; "
                f"available: {', '.join(sorted(_ALIGN_CHOICES))}"
            )
        field = entry["field"]
        if field not in CANONICAL_FIELDS:
            raise ProfileError(
                f"columns[{i}].field '{field}' is not a canonical field; "
                f"available: {', '.join(sorted(CANONICAL_FIELDS))}"
            )
        out.append(ColumnSpec(header=entry["header"], field=field, align=align))
    return out


def _build_table_end(raw: dict) -> TableEnd:
    raw = _require_mapping(raw, "table_end")
    _check_keys(raw, {"strategy", "text"}, "table_end")
    strategy = raw.get("strategy", "spacing_gap")
    _validate_strategy(strategy, strategies.TABLE_END, "table_end")
    text = raw.get("text")
    if strategy == "footer_text" and not text:
        raise ProfileError("table_end.text is required when strategy is 'footer_text'")
    return TableEnd(strategy=strategy, text=text)


def _build_rows(raw: dict) -> RowsConfig:
    raw = _require_mapping(raw, "rows")
    _check_keys(raw, {"line_tolerance", "multiline"}, "rows")
    multiline = raw.get("multiline", "merge_into_previous")
    _validate_strategy(multiline, strategies.MULTILINE, "multiline")
    return RowsConfig(
        line_tolerance=raw.get("line_tolerance", 3),
        multiline=multiline,
    )


def _build_amounts(raw: Optional[dict]) -> AmountsConfig:
    if raw is None:
        return AmountsConfig()
    raw = _require_mapping(raw, "amounts")
    _check_keys(raw, {"style", "thousands", "decimal"}, "amounts")
    style = raw.get("style", "signed")
    _validate_strategy(style, strategies.AMOUNT_STYLES, "amounts.style")
    return AmountsConfig(
        style=style,
        thousands=raw.get("thousands", ","),
        decimal=raw.get("decimal", "."),
    )


def _build_dates(raw: Optional[dict]) -> DatesConfig:
    if raw is None:
        return DatesConfig()
    raw = _require_mapping(raw, "dates")
    _check_keys(raw, {"format", "fill"}, "dates")
    fill = raw.get("fill", "none")
    _validate_strategy(fill, strategies.DATE_FILL, "dates.fill")
    return DatesConfig(format=raw.get("format", "%Y-%m-%d"), fill=fill)


def _build_balance(raw: Optional[dict]) -> BalanceConfig:
    if raw is None:
        return BalanceConfig()
    raw = _require_mapping(raw, "balance")
    _check_keys(raw, {"present", "validate"}, "balance")
    validate = raw.get("validate", "none")
    _validate_strategy(validate, strategies.BALANCE_VALIDATE, "balance.validate")
    return BalanceConfig(present=bool(raw.get("present", False)), validate=validate)


def _build_skip_rows(raw: Any) -> List[SkipRow]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProfileError("skip_rows must be a list")
    allowed = {"field", "equals"}
    out = []
    for i, entry in enumerate(raw):
        entry = _require_mapping(entry, f"skip_rows[{i}]")
        _check_keys(entry, allowed, f"skip_rows[{i}]")
        missing = allowed - set(entry)
        if missing:
            raise ProfileError(
                f"skip_rows[{i}] is missing required key(s): {', '.join(sorted(missing))}"
            )
        field = entry["field"]
        if field not in CANONICAL_FIELDS:
            raise ProfileError(
                f"skip_rows[{i}].field '{field}' is not a canonical field; "
                f"available: {', '.join(sorted(CANONICAL_FIELDS))}"
            )
        out.append(SkipRow(field=field, equals=entry["equals"]))
    return out


def _build_csv(raw: dict) -> CsvConfig:
    raw = _require_mapping(raw, "csv")
    _check_keys(raw, {"encoding", "delimiter", "column_map"}, "csv")
    column_map = raw.get("column_map")
    if not isinstance(column_map, dict) or not column_map:
        raise ProfileError("csv.column_map must be a non-empty mapping")
    for src, field in column_map.items():
        if field not in CANONICAL_FIELDS:
            raise ProfileError(
                f"csv.column_map[{src!r}] targets '{field}', which is not a "
                f"canonical field; available: {', '.join(sorted(CANONICAL_FIELDS))}"
            )
    return CsvConfig(
        encoding=raw.get("encoding", "utf-8"),
        delimiter=raw.get("delimiter", ","),
        column_map=dict(column_map),
    )


def _cross_validate(profile: Profile) -> None:
    source = profile.meta.source

    if source == "pdf":
        missing = [
            k
            for k, v in (
                ("page_detect", profile.page_detect),
                ("columns", profile.columns),
                ("table_end", profile.table_end),
                ("rows", profile.rows),
            )
            if v is None
        ]
        if missing:
            raise ProfileError(
                f"pdf profile is missing required section(s): {', '.join(missing)}"
            )
        fields = {c.field for c in profile.columns}
    else:  # csv
        if profile.csv is None:
            raise ProfileError("csv profile is missing required section: csv")
        fields = set(profile.csv.column_map.values())

    if "date" not in fields:
        raise ProfileError("profile must map a 'date' field")
    if "description" not in fields:
        raise ProfileError("profile must map a 'description' field")

    style = profile.amounts.style
    if style == "in_out":
        needed = {"in", "out"} - fields
        if needed:
            raise ProfileError(
                f"amounts.style is 'in_out' but profile is missing field(s): "
                f"{', '.join(sorted(needed))}"
            )
        if "amount" in fields:
            raise ProfileError("amounts.style is 'in_out'; a column must not target 'amount'")
    elif style == "signed":
        if "amount" not in fields:
            raise ProfileError("amounts.style is 'signed' but no column targets 'amount'")
        if "in" in fields or "out" in fields:
            raise ProfileError("amounts.style is 'signed'; columns must not target 'in'/'out'")

    if profile.balance.present and "balance" not in fields:
        raise ProfileError("balance.present is true but no column targets 'balance'")
    if not profile.balance.present and "balance" in fields:
        raise ProfileError(
            "a column targets 'balance' but balance.present is false; set it to true"
        )

    for rule in profile.skip_rows:
        if rule.field not in fields:
            raise ProfileError(
                f"skip_rows references field '{rule.field}' which the profile does not map"
            )


def build_profile(raw: Any, source_path: Optional[Path] = None) -> Profile:
    """Validate a parsed-YAML dict and build a Profile. Raises ProfileError
    with an actionable message on any malformed input."""
    raw = _require_mapping(raw, "<root>")
    _check_keys(raw, _TOP_LEVEL_KEYS, "<root>")

    if "meta" not in raw:
        raise ProfileError("profile is missing required section: meta")
    meta = _build_meta(raw["meta"])

    if meta.source == "pdf":
        for key in _CSV_ONLY_KEYS:
            if key in raw:
                raise ProfileError(f"'{key}' is a csv-only section; this profile has meta.source=pdf")
    else:
        for key in _PDF_ONLY_KEYS:
            if key in raw:
                raise ProfileError(f"'{key}' is a pdf-only section; this profile has meta.source=csv")

    page_detect = _build_page_detect(raw["page_detect"]) if "page_detect" in raw else None
    columns = _build_columns(raw["columns"]) if "columns" in raw else None
    table_end = _build_table_end(raw["table_end"]) if "table_end" in raw else None
    rows = _build_rows(raw["rows"]) if "rows" in raw else None
    csv_cfg = _build_csv(raw["csv"]) if "csv" in raw else None

    amounts = _build_amounts(raw.get("amounts"))
    dates = _build_dates(raw.get("dates"))
    balance = _build_balance(raw.get("balance"))
    skip_rows = _build_skip_rows(raw.get("skip_rows"))

    profile = Profile(
        meta=meta,
        amounts=amounts,
        dates=dates,
        balance=balance,
        skip_rows=skip_rows,
        page_detect=page_detect,
        columns=columns,
        table_end=table_end,
        rows=rows,
        csv=csv_cfg,
        source_path=source_path,
    )
    _cross_validate(profile)
    return profile


def load_profile(path: Union[str, Path]) -> Profile:
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path}: invalid YAML: {exc}") from exc
    if raw is None:
        raise ProfileError(f"{path}: profile file is empty")
    try:
        return build_profile(raw, source_path=path)
    except ProfileError as exc:
        raise ProfileError(f"{path}: {exc}") from exc
