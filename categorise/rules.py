"""Rule schema: dataclass, YAML loading, and validation.

One schema serves both the committed structural rules
(``categorise/builtin_rules.yaml``) and the personal, gitignored
``category_rules.yaml``.

Privacy note: personal rule patterns contain payee/merchant names, so
validation errors reference a rule by *file and index only* -- they never
echo pattern or category text. (Builtin rules are PII-free, but the same
loader handles both files, so the sanitised messages apply everywhere.)
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any, List, Optional

import yaml

MATCH_TYPES = ("exact", "contains", "prefix", "regex")

_ALLOWED_KEYS = {"match", "pattern", "category", "account", "transfer", "extract"}

BUILTIN_RULES_PATH = Path(__file__).parent / "builtin_rules.yaml"


class RuleError(Exception):
    """A rules file is malformed. Messages identify the rule by index, never
    by its pattern/category text (personal rules contain payee names)."""


@dataclasses.dataclass
class Rule:
    match: str
    pattern: str
    category: str
    account: str = "any"
    transfer: bool = False
    extract: Optional[str] = None
    # Compiled lazily at construction for match == "regex"; excluded from
    # equality so tests can compare rules structurally.
    regex: Optional[re.Pattern] = dataclasses.field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.match == "regex" and self.regex is None:
            self.regex = re.compile(self.pattern)


def _fail(source: str, index: int, problem: str) -> None:
    raise RuleError(f"{source}: rule[{index}]: {problem}")


def build_rule(raw: Any, index: int, source: str) -> Rule:
    """Validate one parsed-YAML mapping and build a Rule.

    Raises RuleError with the rule's index (never its text) on any problem.
    """
    if not isinstance(raw, dict):
        _fail(source, index, f"must be a mapping, got {type(raw).__name__}")

    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        _fail(
            source,
            index,
            f"unknown key(s): {', '.join(sorted(unknown))}; "
            f"allowed: {', '.join(sorted(_ALLOWED_KEYS))}",
        )

    for required in ("match", "pattern", "category"):
        if required not in raw:
            _fail(source, index, f"missing required key '{required}'")

    match = raw["match"]
    if match not in MATCH_TYPES:
        _fail(
            source,
            index,
            f"match must be one of {', '.join(MATCH_TYPES)}",
        )

    pattern = raw["pattern"]
    if not isinstance(pattern, str) or not pattern:
        _fail(source, index, "pattern must be a non-empty string")

    category = raw["category"]
    if not isinstance(category, str) or not category.strip():
        _fail(source, index, "category must be a non-empty string")
    if any(not seg.strip() for seg in category.split("/")):
        _fail(source, index, "category has an empty '/'-separated segment")

    account = raw.get("account", "any")
    if not isinstance(account, str) or not account:
        _fail(source, index, "account must be a non-empty string")

    transfer = raw.get("transfer", False)
    if not isinstance(transfer, bool):
        _fail(source, index, "transfer must be a boolean")

    extract = raw.get("extract")
    if extract is not None:
        if match != "regex":
            _fail(source, index, "extract is only valid with match: regex")
        if not isinstance(extract, str) or not extract:
            _fail(source, index, "extract must be a non-empty group name")

    compiled = None
    if match == "regex":
        try:
            compiled = re.compile(pattern)
        except re.error:
            # Do not echo the pattern: personal patterns are PII.
            _fail(source, index, "pattern is not a valid regular expression")
        if extract is not None and extract not in compiled.groupindex:
            _fail(
                source,
                index,
                f"extract references named group '{extract}' which the "
                f"pattern does not define",
            )

    return Rule(
        match=match,
        pattern=pattern,
        category=category.strip(),
        account=account,
        transfer=transfer,
        extract=extract,
        regex=compiled,
    )


def load_rules(path: Path) -> List[Rule]:
    """Load and validate a rules YAML file (a top-level list of mappings)."""
    path = Path(path)
    source = path.name  # never embed full personal paths in errors either
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        # YAML errors carry line/column context, not file content.
        raise RuleError(
            f"{source}: invalid YAML at {getattr(exc, 'problem_mark', 'unknown position')}"
        ) from exc
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuleError(f"{source}: rules file must be a top-level list")
    return [build_rule(entry, i, source) for i, entry in enumerate(raw)]


def load_builtin_rules() -> List[Rule]:
    return load_rules(BUILTIN_RULES_PATH)
