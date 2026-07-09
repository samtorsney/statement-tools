"""Interactive triage wizard core.

``run_wizard`` is the stdlib-only, stream-injected interactive loop. It
groups uncategorised canonical rows by description (sorted by total
|amount| descending) and lets the user turn each group into a personal
categorisation rule, appended to the personal rules file one at a time.

This is the end user's own data on their own terminal -- unlike the other
CLIs in this repo, descriptions and amounts are printed to ``out_stream`` by
design (see the design spec, §2).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import IO, List, Optional, Sequence, Tuple

import pandas as pd
import yaml

from categorise.engine import categorise
from categorise.rules import Rule

QUIT = "q"
SKIP = "s"
TOGGLE_TRANSFER = "t"


@dataclass
class WizardOutcome:
    accepted: int
    skipped: int
    before_uncategorised: int
    after_uncategorised: int


def _group_uncategorised(frame: pd.DataFrame) -> List[Tuple[str, int, Decimal]]:
    """Uncategorised rows grouped by description: (description, count, total),
    sorted by |total| descending."""
    uncategorised = frame[frame["category"] == ""]
    if uncategorised.empty:
        return []
    groups: List[Tuple[str, int, Decimal]] = []
    for description, sub in uncategorised.groupby("description", sort=False):
        amounts = [Decimal(str(a)) for a in sub["amount"]]
        total = sum(amounts, Decimal("0"))
        groups.append((str(description), len(sub), total))
    groups.sort(key=lambda g: abs(g[2]), reverse=True)
    return groups


def _category_menu(rules: Sequence[Rule]) -> List[str]:
    seen: List[str] = []
    for rule in rules:
        if rule.category not in seen:
            seen.append(rule.category)
    return sorted(seen)


def _account_for_group(frame: pd.DataFrame, description: str) -> str:
    accounts = set(frame.loc[frame["description"] == description, "account"])
    if len(accounts) == 1:
        return next(iter(accounts))
    return "any"


def _backup_if_needed(path: Path, backup_done: List[bool]) -> Optional[Path]:
    """Copy an existing rules file to a timestamped .bak once per session,
    the first time this session is about to write to it. No-op if the file
    doesn't exist yet (nothing to back up) or a backup already happened."""
    if backup_done[0]:
        return None
    backup_done[0] = True
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.{timestamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def _append_rule(path: Path, rule: dict) -> None:
    text = yaml.safe_dump([rule], sort_keys=False, default_flow_style=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def _parse_selection(raw: str, menu: Sequence[str]) -> Optional[Tuple[str, str]]:
    """Parse a category-selection line into (category, match_type), or None
    if the input is invalid (caller re-prompts)."""
    raw = raw.strip()
    if not raw:
        return None

    match_type = "exact"
    body = raw
    if len(raw) >= 2 and raw[-2] == ":" and raw[-1] in ("c", "p"):
        match_type = "contains" if raw[-1] == "c" else "prefix"
        body = raw[:-2].strip()
    if not body:
        return None

    if body.isdigit():
        index = int(body) - 1
        if index < 0 or index >= len(menu):
            return None
        return menu[index], match_type

    segments = body.split("/")
    if any(not seg.strip() for seg in segments):
        return None
    return body, match_type


def _prompt_text(description: str, count: int, total: Decimal, menu: Sequence[str], transfer_on: bool) -> str:
    lines = [
        "",
        f"Description: {description}",
        f"Count: {count}   Total: {total}",
        "Categories:",
    ]
    for i, cat in enumerate(menu, start=1):
        lines.append(f"  {i}) {cat}")
    lines.append(
        "Enter a category number or new category text ('/' for subcategories)."
    )
    lines.append(
        "Append ':c' for contains match, ':p' for prefix match (default: exact)."
    )
    lines.append(
        f"'t' = toggle transfer (currently: {'on' if transfer_on else 'off'})   "
        "'s' = skip   'q' = quit and save"
    )
    lines.append("> ")
    return "\n".join(lines)


def run_wizard(
    frame: pd.DataFrame,
    rules_path: Path,
    personal_rules: List[Rule],
    builtin_rules: List[Rule],
    in_stream: IO[str],
    out_stream: IO[str],
) -> WizardOutcome:
    """Drive the interactive loop. `frame` must have description/account/
    amount columns (category need not be present; it is computed here)."""
    all_rules = list(personal_rules) + list(builtin_rules)
    before = categorise(frame, all_rules)
    before_uncategorised = int((before["category"] == "").sum())

    groups = _group_uncategorised(before)
    if not groups:
        out_stream.write("no uncategorised transactions found; nothing to triage\n")
        return WizardOutcome(0, 0, before_uncategorised, before_uncategorised)

    menu = _category_menu(all_rules)
    backup_done = [False]
    working_rules: List[Rule] = list(personal_rules)

    accepted = 0
    skipped = 0
    quit_requested = False

    for description, count, total in groups:
        if quit_requested:
            break
        transfer_on = False
        while True:
            out_stream.write(_prompt_text(description, count, total, menu, transfer_on))
            try:
                line = in_stream.readline()
            except KeyboardInterrupt:
                quit_requested = True
                break

            if line == "":
                # EOF on the input stream: behave like quit.
                quit_requested = True
                break

            choice = line.strip()
            if choice == QUIT:
                quit_requested = True
                break
            if choice == SKIP:
                skipped += 1
                break
            if choice == TOGGLE_TRANSFER:
                transfer_on = not transfer_on
                continue

            selection = _parse_selection(choice, menu)
            if selection is None:
                out_stream.write("invalid input, try again\n")
                continue

            category, match_type = selection
            account = _account_for_group(frame, description)
            rule_dict = {"match": match_type, "pattern": description, "category": category}
            if account != "any":
                rule_dict["account"] = account
            if transfer_on:
                rule_dict["transfer"] = True

            backup_path = _backup_if_needed(rules_path, backup_done)
            if backup_path is not None:
                out_stream.write(f"backed up existing rules to {backup_path.name}\n")
            _append_rule(rules_path, rule_dict)

            working_rules.append(
                Rule(
                    match=match_type,
                    pattern=description,
                    category=category,
                    account=account,
                    transfer=transfer_on,
                )
            )
            if category not in menu:
                menu.append(category)
                menu.sort()
            accepted += 1
            out_stream.write(f"accepted: {category} ({match_type})\n")
            break

    after = categorise(frame, working_rules + list(builtin_rules))
    after_uncategorised = int((after["category"] == "").sum())

    out_stream.write(
        f"\ntriage complete: {accepted} rule(s) accepted, {skipped} skipped; "
        f"uncategorised before={before_uncategorised} after={after_uncategorised}\n"
    )
    return WizardOutcome(accepted, skipped, before_uncategorised, after_uncategorised)
