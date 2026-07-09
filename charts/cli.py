"""CLI: `report sankey|monthly|savings` -- categorised CSV -> chart files.

Privacy invariants (see CLAUDE.md and the design spec):

- stdout/stderr only ever carry counts, filenames, and exit codes -- never
  transaction descriptions, amounts, dates, or categories. All row-level
  detail (uncategorised rows, unmatched transfers) is written to files
  under ``--out``, never printed.
- ``--from``/``--to`` are required: no hardcoded date-range literals.
- ``reports/`` (the conventional ``--out`` target) is gitignored; this CLI
  does not itself enforce that, but callers should never point ``--out``
  at a tracked location.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date as Date
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .monthly import build_monthly_bar, monthly_delta_table
from .netting import DEFAULT_WINDOW_DAYS, net_transfers
from .sankey import build_sankey
from .savings import build_savings_chart

REQUIRED_COLUMNS = (
    "date",
    "description",
    "amount",
    "balance",
    "account",
    "category",
    "subcategory",
    "is_transfer",
)

UNMATCHED_TRANSFERS_FILENAME = "unmatched_transfers.csv"


class InputError(Exception):
    """A categorised CSV (or a date argument) is unusable. Messages carry
    counts/positions/type names only -- never cell text."""


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


def _parse_date_arg(text: str, flag: str) -> Date:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise InputError(f"{flag} is not a valid ISO date ({type(exc).__name__})") from exc


def _parse_date_column(frame: pd.DataFrame, path: Path) -> List[Optional[Date]]:
    dates: List[Optional[Date]] = []
    for i, text in enumerate(frame["date"]):
        text = str(text).strip()
        if not text:
            dates.append(None)
            continue
        try:
            dates.append(datetime.strptime(text, "%Y-%m-%d").date())
        except ValueError as exc:
            raise InputError(f"{path}: row {i}: date is not a valid ISO date") from exc
    return dates


def _parse_decimal_column(frame: pd.DataFrame, column: str, path: Path) -> List[Optional[Decimal]]:
    values: List[Optional[Decimal]] = []
    for i, text in enumerate(frame[column]):
        text = str(text).strip()
        if not text:
            values.append(None)
            continue
        try:
            values.append(Decimal(text))
        except InvalidOperation as exc:
            raise InputError(f"{path}: row {i}: {column} is not a valid number") from exc
    return values


def _parse_bool_column(frame: pd.DataFrame, column: str, path: Path) -> List[bool]:
    values: List[bool] = []
    for i, text in enumerate(frame[column]):
        norm = str(text).strip().lower()
        if norm == "true":
            values.append(True)
        elif norm == "false":
            values.append(False)
        else:
            raise InputError(f"{path}: row {i}: {column} is not a valid boolean")
    return values


def _prepare_frame(input_path: Path) -> pd.DataFrame:
    """Read the categorised CSV and coerce it into the real-dtype frame the
    pure builders (netting/sankey/monthly/savings) expect."""
    frame = _read_frame(input_path)
    _require_columns(frame, REQUIRED_COLUMNS, input_path)

    out = frame.copy()
    out["date"] = _parse_date_column(frame, input_path)
    out["amount"] = _parse_decimal_column(frame, "amount", input_path)
    out["balance"] = _parse_decimal_column(frame, "balance", input_path)
    out["is_transfer"] = _parse_bool_column(frame, "is_transfer", input_path)

    if any(a is None for a in out["amount"]):
        raise InputError(f"{input_path}: amount column has blank value(s)")

    return out


def _filter_date_range(frame: pd.DataFrame, date_from: Date, date_to: Date) -> pd.DataFrame:
    mask = frame["date"].map(lambda d: d is not None and date_from <= d <= date_to)
    return frame[mask].reset_index(drop=True)


def _write_unmatched(unmatched: pd.DataFrame, out_dir: Path) -> Path:
    path = out_dir / UNMATCHED_TRANSFERS_FILENAME
    unmatched.to_csv(path, index=False)
    return path


def _run_common(args: argparse.Namespace):
    """Shared read/parse/filter/net pipeline. Returns
    (netted_frame, unmatched_frame, out_dir, counts) or raises InputError."""
    input_path = Path(args.input)
    date_from = _parse_date_arg(args.date_from, "--from")
    date_to = _parse_date_arg(args.date_to, "--to")
    if date_from > date_to:
        raise InputError("--from must not be after --to")

    frame = _prepare_frame(input_path)
    total_rows = len(frame)
    in_range = _filter_date_range(frame, date_from, date_to)

    uncategorised = int(
        ((~in_range["is_transfer"]) & (in_range["category"] == "")).sum()
    )

    result = net_transfers(in_range, window_days=args.window_days)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    counts = {
        "total_rows": total_rows,
        "in_range_rows": len(in_range),
        "uncategorised": uncategorised,
        "unmatched_transfers": len(result.unmatched),
    }
    return result, out_dir, counts


def cmd_sankey(args: argparse.Namespace) -> int:
    try:
        result, out_dir, counts = _run_common(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    unmatched_path = _write_unmatched(result.unmatched, out_dir)
    fig = build_sankey(result.netted)
    html_path = out_dir / "sankey.html"
    fig.write_html(html_path)

    print(
        f"read {counts['total_rows']} row(s); {counts['in_range_rows']} in range; "
        f"{counts['uncategorised']} uncategorised; "
        f"{counts['unmatched_transfers']} unmatched transfer(s); "
        f"wrote {html_path} and {unmatched_path}"
    )
    return 0


def cmd_monthly(args: argparse.Namespace) -> int:
    try:
        result, out_dir, counts = _run_common(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    unmatched_path = _write_unmatched(result.unmatched, out_dir)
    fig = build_monthly_bar(result.netted)
    html_path = out_dir / "monthly.html"
    fig.write_html(html_path)

    delta = monthly_delta_table(result.netted)
    delta_path = out_dir / "monthly_delta.csv"
    delta.to_csv(delta_path, index=False)

    print(
        f"read {counts['total_rows']} row(s); {counts['in_range_rows']} in range; "
        f"{counts['uncategorised']} uncategorised; "
        f"{counts['unmatched_transfers']} unmatched transfer(s); "
        f"wrote {html_path}, {delta_path} and {unmatched_path}"
    )
    return 0


def cmd_savings(args: argparse.Namespace) -> int:
    try:
        result, out_dir, counts = _run_common(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    unmatched_path = _write_unmatched(result.unmatched, out_dir)
    fig = build_savings_chart(result.netted)
    html_path = out_dir / "savings.html"
    fig.write_html(html_path)

    print(
        f"read {counts['total_rows']} row(s); {counts['in_range_rows']} in range; "
        f"{counts['uncategorised']} uncategorised; "
        f"{counts['unmatched_transfers']} unmatched transfer(s); "
        f"wrote {html_path} and {unmatched_path}"
    )
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--in", dest="input", required=True, help="categorised CSV input")
    parser.add_argument("--from", dest="date_from", required=True, help="range start, YYYY-MM-DD (inclusive)")
    parser.add_argument("--to", dest="date_to", required=True, help="range end, YYYY-MM-DD (inclusive)")
    parser.add_argument("--out", dest="out_dir", required=True, help="output directory")
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"transfer-pairing date window in days (default {DEFAULT_WINDOW_DAYS})",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="report")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sankey = sub.add_parser("sankey", help="Sankey diagram of money flow")
    _add_common_args(p_sankey)
    p_sankey.set_defaults(func=cmd_sankey)

    p_monthly = sub.add_parser("monthly", help="monthly stacked spend bar + MoM delta table")
    _add_common_args(p_monthly)
    p_monthly.set_defaults(func=cmd_monthly)

    p_savings = sub.add_parser("savings", help="cumulative savings + balance trajectory line")
    _add_common_args(p_savings)
    p_savings.set_defaults(func=cmd_savings)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
