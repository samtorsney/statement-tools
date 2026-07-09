"""CLI: `triage` -- interactive terminal wizard for turning uncategorised
descriptions into personal categorisation rules.

Privacy note (see CLAUDE.md and the design spec): this is a local-only
interactive tool for the end user's own terminal. Unlike the other CLIs in
this repo it deliberately prints transaction descriptions and amounts --
that data never leaves the user's machine because the wizard has no network
access and nothing here is invoked by an automated agent. It must never be
exercised against real data other than by the human operator.

Argument/amount validation errors follow the same discipline as the other
CLIs: messages carry row indices and type names only, never cell text.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

import pandas as pd

from categorise.rules import RuleError, load_builtin_rules, load_rules
from .wizard import run_wizard

REQUIRED_INPUT_COLUMNS = ("description", "account", "amount")


class InputError(Exception):
    """An input file is unusable. Messages carry counts/positions/type names
    only -- never cell text."""


def _read_frame(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        raise InputError(f"input file not found: {path}")
    except Exception as exc:  # malformed CSV; never echo its content
        raise InputError(f"could not parse {path} as CSV ({type(exc).__name__})") from exc
    return frame


def _require_columns(frame: pd.DataFrame, columns, path: Path) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise InputError(f"{path} is missing required column(s): {', '.join(missing)}")


def _validate_amounts(frame: pd.DataFrame, path: Path) -> None:
    for i, text in enumerate(frame["amount"]):
        try:
            Decimal(str(text).strip())
        except InvalidOperation as exc:
            raise InputError(f"{path}: row {i}: amount is not a valid number") from exc


def _load_personal_rules(path: Path) -> list:
    if not path.exists():
        return []
    return load_rules(path)


def cmd_triage(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    rules_path = Path(args.rules)

    try:
        frame = _read_frame(in_path)
        _require_columns(frame, REQUIRED_INPUT_COLUMNS, in_path)
        _validate_amounts(frame, in_path)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        personal_rules = _load_personal_rules(rules_path)
        builtin_rules = load_builtin_rules()
    except RuleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    run_wizard(frame, rules_path, personal_rules, builtin_rules, sys.stdin, sys.stdout)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triage")
    parser.add_argument("--in", dest="input", required=True, help="canonical CSV input")
    parser.add_argument(
        "--rules",
        required=True,
        help="personal rules YAML (created if missing)",
    )
    parser.set_defaults(func=cmd_triage)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
