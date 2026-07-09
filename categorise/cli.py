"""CLI: `run` (categorise a canonical CSV) and `report` (uncategorised
breakdown written to files).

Privacy invariants (see CLAUDE.md and the design spec):

- stdout/stderr only ever carry counts, file paths, and rule indices --
  never transaction descriptions or amounts. The uncategorised report
  contains transaction data, so it is WRITTEN TO FILE ONLY.
- `run` exits nonzero when the summed |amount| of uncategorised rows
  exceeds --tolerance (default 0), so a month cannot be silently "done"
  with material unlabelled spend.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .engine import categorise
from .rules import Rule, RuleError, load_builtin_rules, load_rules

REQUIRED_INPUT_COLUMNS = ("description", "account", "amount")


class InputError(Exception):
    """A CSV input is unusable. Messages carry counts/positions only."""


def _read_frame(path: Path) -> pd.DataFrame:
    """Read a CSV as strings (no NaN coercion) so values round-trip."""
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        raise InputError(f"input file not found: {path}")
    except Exception as exc:  # malformed CSV; do not echo its content
        raise InputError(
            f"could not parse {path} as CSV ({type(exc).__name__})"
        ) from exc
    return frame


def _require_columns(frame: pd.DataFrame, columns, path: Path) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise InputError(
            f"{path} is missing required column(s): {', '.join(missing)}"
        )


def _decimal_amounts(frame: pd.DataFrame, path: Path) -> List[Decimal]:
    amounts = []
    for i, text in enumerate(frame["amount"]):
        try:
            amounts.append(Decimal(str(text).strip()))
        except InvalidOperation as exc:
            # Never echo the cell text; report position only.
            raise InputError(
                f"{path}: row {i}: amount is not a valid number"
            ) from exc
    return amounts


def _load_rule_chain(personal_path: Optional[str]) -> List[Rule]:
    """Personal rules (if given) first, then builtin -- the spec's precedence."""
    personal: List[Rule] = []
    if personal_path is not None:
        personal = load_rules(Path(personal_path))
    return personal + load_builtin_rules()


def cmd_run(args: argparse.Namespace) -> int:
    try:
        rules = _load_rule_chain(args.rules)
    except (RuleError, FileNotFoundError) as exc:
        # RuleError messages are index-only by construction (rules.py).
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        frame = _read_frame(Path(args.input))
        _require_columns(frame, REQUIRED_INPUT_COLUMNS, Path(args.input))
        amounts = _decimal_amounts(frame, Path(args.input))
        tolerance = Decimal(args.tolerance)
    except (InputError, InvalidOperation) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = categorise(frame, rules)
    out.to_csv(args.output, index=False)

    uncategorised = [
        amount
        for amount, category in zip(amounts, out["category"])
        if category == ""
    ]
    uncategorised_total = sum((abs(a) for a in uncategorised), Decimal("0"))

    total = len(out)
    n_uncat = len(uncategorised)
    # Counts only -- no amounts, no descriptions.
    print(
        f"categorised {total - n_uncat} of {total} row(s); "
        f"{n_uncat} uncategorised; wrote {args.output}"
    )

    if uncategorised_total > tolerance:
        print(
            f"error: uncategorised |amount| exceeds tolerance across "
            f"{n_uncat} row(s); run `categorise report` to inspect them "
            f"(written to file, not printed)"
        )
        return 1
    return 0


def _default_agg_path(out_path: Path) -> Path:
    return out_path.with_name(out_path.stem + "_by_description" + out_path.suffix)


def cmd_report(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    try:
        frame = _read_frame(in_path)
        _require_columns(frame, ("category",), in_path)
        _require_columns(frame, REQUIRED_INPUT_COLUMNS, in_path)
        amounts = _decimal_amounts(frame, in_path)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    frame = frame.copy()
    frame["_amount_dec"] = amounts
    uncat = frame[frame["category"] == ""].copy()
    uncat["_abs"] = uncat["_amount_dec"].map(abs)
    uncat = uncat.sort_values("_abs", ascending=False, kind="stable")

    out_path = Path(args.output)
    uncat.drop(columns=["_amount_dec", "_abs"]).to_csv(out_path, index=False)

    # Per-description aggregation (sum, count), largest |sum| first, to make
    # rule-writing efficient. File only; never printed.
    agg_path = Path(args.agg_output) if args.agg_output else _default_agg_path(out_path)
    grouped = (
        uncat.groupby("description", sort=False)["_amount_dec"]
        .agg([("total_amount", "sum"), ("count", "size")])
        .reset_index()
    )
    grouped["_abs"] = grouped["total_amount"].map(abs)
    grouped = grouped.sort_values("_abs", ascending=False, kind="stable").drop(
        columns=["_abs"]
    )
    grouped.to_csv(agg_path, index=False)

    # Counts only on stdout.
    print(
        f"wrote {len(uncat)} uncategorised row(s) to {out_path} and "
        f"{len(grouped)} distinct description(s) to {agg_path}"
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="categorise")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="categorise a canonical CSV")
    p_run.add_argument(
        "--rules",
        default=None,
        help="personal rules YAML (evaluated before the builtin rules); "
        "omit to use builtin rules only",
    )
    p_run.add_argument("--in", dest="input", required=True, help="canonical CSV input")
    p_run.add_argument("--out", dest="output", required=True, help="categorised CSV output")
    p_run.add_argument(
        "--tolerance",
        default="0",
        help="maximum allowed summed |amount| of uncategorised rows "
        "before `run` exits nonzero (default 0)",
    )
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser(
        "report",
        help="write uncategorised rows + per-description aggregation to files "
        "(never to stdout)",
    )
    p_report.add_argument("--in", dest="input", required=True, help="categorised CSV input")
    p_report.add_argument(
        "--out", dest="output", required=True, help="uncategorised rows CSV output"
    )
    p_report.add_argument(
        "--agg-out",
        dest="agg_output",
        default=None,
        help="per-description aggregation CSV output "
        "(default: <out>_by_description.csv)",
    )
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
