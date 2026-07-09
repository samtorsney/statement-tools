"""Pure categorisation engine: canonical frame + rules -> categorised frame.

``categorise(frame, rules)`` adds ``category``, ``subcategory`` and
``is_transfer`` columns. No I/O happens here; the CLI owns reading and
writing files.

Semantics
---------
- Rules are evaluated in list order per row; the first rule whose account
  and pattern both match wins. Callers wanting "personal beats builtin"
  simply pass ``personal_rules + builtin_rules``.
- ``account`` on a rule is either a canonical account name (matched against
  the frame's ``account`` column) or ``"any"``.
- Match types operate on the ``description`` column, case-sensitively:
  ``exact`` (whole string), ``contains`` (substring), ``prefix``
  (startswith), ``regex`` (``re.search``).
- A rule's ``category`` is a '/'-separated path. If the rule has
  ``extract``, the named regex group's value is appended as one more path
  segment (this reproduces the old dynamic labels like ``Card FX Fee (GBP)``
  as ``Fees/Card FX/GBP`` without string concatenation in rule files).
  The frame's ``category`` column gets the first segment and
  ``subcategory`` the remaining segments re-joined with '/'.
- Unmatched rows get empty-string category/subcategory and
  ``is_transfer=False``; downstream reporting treats ``category == ""`` as
  uncategorised.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import pandas as pd

from .rules import Rule


def _rule_matches(rule: Rule, description: str) -> Tuple[bool, Optional[str]]:
    """Return (matched, extracted-group-value-or-None) for one rule."""
    if rule.match == "exact":
        return description == rule.pattern, None
    if rule.match == "contains":
        return rule.pattern in description, None
    if rule.match == "prefix":
        return description.startswith(rule.pattern), None
    # regex
    m = rule.regex.search(description)
    if not m:
        return False, None
    if rule.extract is not None:
        return True, m.group(rule.extract)
    return True, None


def first_match(
    description: str, account: str, rules: Sequence[Rule]
) -> Tuple[Optional[Rule], Optional[str]]:
    """First rule (in list order) matching this description+account."""
    for rule in rules:
        if rule.account != "any" and rule.account != account:
            continue
        matched, extracted = _rule_matches(rule, description)
        if matched:
            return rule, extracted
    return None, None


def _split_category(rule: Rule, extracted: Optional[str]) -> Tuple[str, str]:
    segments = rule.category.split("/")
    if extracted is not None:
        segments = segments + [extracted]
    return segments[0], "/".join(segments[1:])


def categorise(frame: pd.DataFrame, rules: Sequence[Rule]) -> pd.DataFrame:
    """Return a copy of `frame` with category/subcategory/is_transfer added.

    `frame` must have string-valued ``description`` and ``account`` columns
    (the canonical schema guarantees both).
    """
    categories: List[str] = []
    subcategories: List[str] = []
    transfers: List[bool] = []

    for description, account in zip(frame["description"], frame["account"]):
        rule, extracted = first_match(str(description), str(account), rules)
        if rule is None:
            categories.append("")
            subcategories.append("")
            transfers.append(False)
        else:
            category, subcategory = _split_category(rule, extracted)
            categories.append(category)
            subcategories.append(subcategory)
            transfers.append(rule.transfer)

    out = frame.copy()
    out["category"] = categories
    out["subcategory"] = subcategories
    out["is_transfer"] = transfers
    return out
