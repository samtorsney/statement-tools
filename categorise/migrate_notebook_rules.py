"""One-shot migration: notebook category dicts -> personal category_rules.yaml.

Parses a notebook file AS JSON and reads ONLY the ``source`` arrays of code
cells -- never ``outputs``, which can embed rendered statement data. Each
cell's source is parsed with ``ast.parse``; assignments to the two known
dict variables are recovered with ``ast.literal_eval``:

- ``details_category_map``      -> rules with ``account: boi_current``
- ``rev_details_category_map``  -> rules with ``account: revolut_current``

Conversion:
- each ``{description: category}`` entry becomes an ``exact`` rule;
- ``'Parent (Child)'`` category values become ``'Parent/Child'`` paths;
- transfer-ish categories (savings sweeps, top-ups, credit-card
  repayments, pocket/vault moves) get ``transfer: true``.

Privacy: the output file is personal data (gitignored). This script prints
ONLY counts and file paths -- never a key, value, or rule -- and converts
unexpected exceptions to their type name so a traceback cannot echo
notebook content.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# notebook dict variable -> canonical account name
TARGET_VARS = {
    "details_category_map": "boi_current",
    "rev_details_category_map": "revolut_current",
}

# Category parents that are internal money movements, not spend/income.
# Compared lowercase against the parent segment of the converted path, so
# 'Savings (Pocket)' -> 'Savings/Pocket' -> parent 'savings' is covered.
_TRANSFER_PARENTS = {
    "savings",
    "top up",
    "top-up",
    "topup",
    "credit card repayment",
    "pocket withdrawal",
    "pocket deposit",
    "vault",
    "transfer",
}

_PAREN_SUFFIX = re.compile(r"^(?P<parent>.*?)\s*\((?P<child>.+)\)\s*$")


def convert_category(value: str) -> str:
    """'Parent (Child)' -> 'Parent/Child'; anything else passes through."""
    value = value.strip()
    m = _PAREN_SUFFIX.match(value)
    if m:
        return f"{m.group('parent').strip()}/{m.group('child').strip()}"
    return value


def is_transfer_category(converted: str) -> bool:
    parent = converted.split("/")[0].strip().lower()
    return parent in _TRANSFER_PARENTS


def extract_maps(notebook_path: Path) -> Dict[str, Dict[str, str]]:
    """Read only code-cell ``source`` text; return {var_name: dict}.

    If a variable is assigned more than once across cells, the last
    assignment wins (matching notebook execution order top-to-bottom).
    """
    with open(notebook_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    found: Dict[str, Dict[str, str]] = {}
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Cells with IPython magics etc. are not our targets.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            targets = [n for n in names if n in TARGET_VARS]
            if not targets:
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                # Not a literal dict (e.g. built via comprehension); skip.
                continue
            if not isinstance(value, dict):
                continue
            for name in targets:
                found[name] = {str(k): str(v) for k, v in value.items()}
    return found


def build_rules(maps: Dict[str, Dict[str, str]]) -> List[dict]:
    rules: List[dict] = []
    for var_name, account in TARGET_VARS.items():
        for pattern, raw_category in maps.get(var_name, {}).items():
            category = convert_category(raw_category)
            rule = {
                "match": "exact",
                "pattern": pattern,
                "category": category,
                "account": account,
                "transfer": is_transfer_category(category),
            }
            rules.append(rule)
    return rules


def migrate(
    notebook_path: Path, out_path: Path, force: bool
) -> Tuple[int, Dict[str, int], int]:
    """Returns (total_rules, per-account counts, transfer count)."""
    if out_path.exists() and not force:
        raise FileExistsError(
            f"{out_path} already exists; pass --force to overwrite"
        )

    maps = extract_maps(notebook_path)
    missing = [v for v in TARGET_VARS if v not in maps]
    if missing:
        raise KeyError(
            f"notebook is missing expected dict assignment(s): "
            f"{', '.join(missing)}"
        )

    rules = build_rules(maps)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(rules, f, sort_keys=False, allow_unicode=True)

    # Round-trip through the real loader so a malformed conversion fails
    # here, not at first use. RuleError messages are index-only (safe).
    from .rules import load_rules

    load_rules(out_path)

    per_account = {
        account: sum(1 for r in rules if r["account"] == account)
        for account in TARGET_VARS.values()
    }
    transfers = sum(1 for r in rules if r["transfer"])
    return len(rules), per_account, transfers


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_notebook_rules",
        description="One-shot: notebook category dicts -> category_rules.yaml. "
        "Prints counts only.",
    )
    parser.add_argument(
        "--notebook", default="sankey.ipynb", help="notebook to read (source cells only)"
    )
    parser.add_argument(
        "--out", default="category_rules.yaml", help="personal rules YAML to write"
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing output file"
    )
    args = parser.parse_args(argv)

    try:
        total, per_account, transfers = migrate(
            Path(args.notebook), Path(args.out), args.force
        )
    except (FileExistsError, FileNotFoundError, KeyError) as exc:
        # These carry only paths / variable names, never notebook content.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Never let a raw traceback echo notebook text.
        print(
            f"error: migration failed with {type(exc).__name__} "
            f"(details suppressed to avoid leaking notebook content)",
            file=sys.stderr,
        )
        return 1

    counts = ", ".join(f"{account}={n}" for account, n in per_account.items())
    print(
        f"wrote {total} rule(s) to {args.out} ({counts}; "
        f"transfer-flagged={transfers})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
