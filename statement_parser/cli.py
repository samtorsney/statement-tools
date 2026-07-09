"""CLI: `parse` (extract canonical transactions) and `debug-layout` (profile
authoring support -- prints detected header boxes, derived column
boundaries, and the first rows' bucketing so a contributor can see *why* a
profile misparses a PDF).

NOTE: `debug-layout` is a local troubleshooting tool for the person running
it against their own statements; it prints statement contents to stdout by
design. It must only ever be run against the user's own files on their own
machine, never routed through anything that forwards its output elsewhere.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Optional

import pdfplumber

from .canonical import CanonicalRow
from .engine.csv_table import parse_csv
from .engine.pdf_table import (
    build_columns,
    build_header_blocks,
    extract_page,
    find_header_line,
    parse_pdf,
)
from .errors import BalanceContinuityError, ExtractionError, ProfileError
from .profile import Profile, load_profile
from .validate import check_balance_continuity, check_period_gaps, dedupe_rows

PROFILES_DIR = Path(__file__).parent / "profiles"

CANONICAL_COLUMNS = [
    "date",
    "description",
    "amount",
    "balance",
    "currency",
    "account",
    "source_file",
    "page",
    "row",
]


def resolve_profile(name_or_path: str) -> Profile:
    path = Path(name_or_path)
    if not path.is_file():
        candidate = PROFILES_DIR / f"{name_or_path}.yaml"
        if candidate.is_file():
            path = candidate
        else:
            raise ProfileError(
                f"profile {name_or_path!r} not found as a file or in {PROFILES_DIR}"
            )
    return load_profile(path)


def parse_statement(path: Path, profile: Profile) -> List[CanonicalRow]:
    if profile.meta.source == "pdf":
        return parse_pdf(path, profile)
    return parse_csv(path, profile)


def _row_to_dict(row: CanonicalRow) -> dict:
    return {
        "date": row.date.isoformat() if row.date else "",
        "description": row.description,
        "amount": str(row.amount),
        "balance": str(row.balance) if row.balance is not None else "",
        "currency": row.currency or "",
        "account": row.account,
        "source_file": row.source_file,
        "page": row.page if row.page is not None else "",
        "row": row.row,
    }


def cmd_parse(args: argparse.Namespace) -> int:
    try:
        profile = resolve_profile(args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    all_rows: List[CanonicalRow] = []
    for file_arg in args.files:
        path = Path(file_arg)
        try:
            rows = parse_statement(path, profile)
        except (ExtractionError, ProfileError) as exc:
            print(f"error parsing {path}: {exc}", file=sys.stderr)
            return 1
        all_rows.extend(rows)

    if profile.balance.validate == "continuity":
        try:
            check_balance_continuity(all_rows)
        except BalanceContinuityError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    all_rows = dedupe_rows(all_rows)

    for warning in check_period_gaps(all_rows):
        print(f"warning: {warning}", file=sys.stderr)

    out_path = Path(args.output)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(_row_to_dict(row))

    print(f"wrote {len(all_rows)} transactions to {out_path}")
    return 0


def cmd_debug_layout(args: argparse.Namespace) -> int:
    try:
        profile = resolve_profile(args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if profile.meta.source != "pdf":
        print("error: debug-layout only supports pdf profiles", file=sys.stderr)
        return 1

    path = Path(args.file)
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages
        if args.page is not None:
            pages = [pdf.pages[args.page - 1]]

        for page in pages:
            page_number = page.page_number
            print(f"=== page {page_number} ===")
            try:
                header_words = find_header_line(page, profile)
            except ExtractionError as exc:
                print(f"  header not found: {exc}")
                continue

            blocks = build_header_blocks(header_words, profile)
            columns = build_columns(blocks, page.width)

            print("  header boxes:")
            for b in blocks:
                print(
                    f"    {b['field']:<12} header={b['header']!r:<24} "
                    f"x0={b['x0']:.1f} x1={b['x1']:.1f} top={b['top']:.1f} align={b['align']}"
                )

            print("  derived column boundaries:")
            for field, x0, x1 in columns:
                print(f"    {field:<12} [{x0:.1f}, {x1:.1f})")

            rows = extract_page(page, profile, page_number)
            print(f"  first {min(len(rows), args.max_rows)} bucketed row(s):")
            for row in rows[: args.max_rows]:
                shown = {k: v for k, v in row.items() if not k.startswith("_")}
                print(f"    {shown}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="statement_parser")
    sub = parser.add_subparsers(dest="command", required=True)

    p_parse = sub.add_parser("parse", help="extract canonical transactions to CSV")
    p_parse.add_argument("files", nargs="+", help="statement file(s) to parse")
    p_parse.add_argument("--profile", required=True, help="profile name or path to a profile YAML")
    p_parse.add_argument("--output", required=True, help="output CSV path")
    p_parse.set_defaults(func=cmd_parse)

    p_debug = sub.add_parser("debug-layout", help="show detected header/column layout for a PDF")
    p_debug.add_argument("file", help="PDF statement to inspect")
    p_debug.add_argument("--profile", required=True, help="profile name or path to a profile YAML")
    p_debug.add_argument("--page", type=int, default=None, help="only inspect this 1-based page number")
    p_debug.add_argument("--max-rows", type=int, default=5, help="how many bucketed rows to print per page")
    p_debug.set_defaults(func=cmd_debug_layout)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
