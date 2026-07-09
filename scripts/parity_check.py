"""Local-only parity check: legacy boi_statement_parser.py vs the new
profile-driven engine (boi_current profile), run over the user's real BOI
statement PDFs.

CONFIDENTIALITY: this script must NEVER print transaction rows, dates,
descriptions, or amounts -- only per-file row counts, per-column
equal/not-equal booleans, and an aggregate-sums-match boolean. It is a
local, human-run comparison, never wired into CI (there is no synthetic
substitute for "does this reproduce the legacy parser on my real
statements"). Do not add prints of row contents to this file.

Usage: .venv\\Scripts\\python.exe scripts\\parity_check.py
"""
from __future__ import annotations

import contextlib
import io
import math
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import boi_statement_parser as legacy  # noqa: E402
from statement_parser.engine.pdf_table import parse_pdf  # noqa: E402
from statement_parser.profile import load_profile  # noqa: E402

PROFILE_PATH = REPO_ROOT / "statement_parser" / "profiles" / "boi_current.yaml"
TOLERANCE = Decimal("0.01")


def find_real_statements():
    """Every *.pdf in the repo root except redacted/unlocked ones, mirroring
    the skip rule in boi_statement_parser.py's own main()."""
    files = []
    for pdf in sorted(REPO_ROOT.glob("*.pdf")):
        name_lower = pdf.name.lower()
        if "redacted" in name_lower or "_unlocked" in name_lower:
            continue
        files.append(pdf)
    return files


def _run_legacy(pdf_path: Path):
    # Legacy code prints progress lines (counts only, no content) as it
    # runs; discard them so this script's own stdout stays exactly what the
    # confidentiality contract promises.
    with contextlib.redirect_stdout(io.StringIO()):
        return legacy.process_statement(pdf_path)


def _run_new_engine(pdf_path: Path, profile):
    return parse_pdf(pdf_path, profile)


def _safe_decimal(value) -> Decimal:
    """legacy's pd.to_numeric(errors='coerce') silently turns unparseable
    cells (e.g. non-transaction footer/subtotal text a table-boundary
    heuristic failed to exclude) into float NaN. Treat those as 0 for
    comparison purposes -- this script only ever reports booleans/counts, so
    there is no need to know (or print) what the original text was."""
    try:
        if isinstance(value, float) and math.isnan(value):
            return Decimal("0")
    except TypeError:
        pass
    return Decimal(str(value))


def _is_nan(value) -> bool:
    try:
        return isinstance(value, float) and math.isnan(value)
    except TypeError:
        return False


def compare_file(pdf_path: Path, profile) -> dict:
    legacy_df = _run_legacy(pdf_path)
    new_rows = _run_new_engine(pdf_path, profile)

    legacy_count = len(legacy_df)
    new_count = len(new_rows)

    # Known, intentional difference (FINDINGS.md #3): the shared spacing_gap
    # table_end heuristic sometimes lets a non-transaction line (a footer /
    # subtotal label) through on both engines. Legacy silently coerces its
    # unparseable in/out cell(s) to NaN and keeps the row; the new engine
    # drops the row by construction (no description text -> not a
    # transaction). Normalise by excluding legacy rows with a NaN in/out
    # before comparing row-for-row, so this known difference doesn't mask a
    # real one. This never inspects the row's actual text, only whether its
    # numeric coercion failed.
    legacy_noise_mask = [
        _is_nan(i) or _is_nan(o) for i, o in zip(legacy_df["in"], legacy_df["out"])
    ]
    legacy_df_normalised = legacy_df[[not m for m in legacy_noise_mask]].reset_index(drop=True)
    legacy_dropped_noise_rows = sum(legacy_noise_mask)
    legacy_count_normalised = len(legacy_df_normalised)

    result = {
        "file": pdf_path.name,
        "legacy_row_count": legacy_count,
        "new_row_count": new_count,
        "legacy_dropped_noise_rows": legacy_dropped_noise_rows,
        "date_equal": False,
        "description_equal": False,
        "amount_equal": False,
        "balance_equal": False,
    }

    legacy_df = legacy_df_normalised
    legacy_count = legacy_count_normalised

    if legacy_count == new_count and legacy_count > 0:
        legacy_dates = [str(d) for d in legacy_df["date"]]
        new_dates = [r.date.isoformat() if r.date else "" for r in new_rows]
        result["date_equal"] = legacy_dates == new_dates

        legacy_desc = [str(d).strip() for d in legacy_df["details"]]
        new_desc = [r.description for r in new_rows]
        result["description_equal"] = legacy_desc == new_desc

        legacy_amount = [
            (_safe_decimal(i) - _safe_decimal(o)).quantize(Decimal("0.01"))
            for i, o in zip(legacy_df["in"], legacy_df["out"])
        ]
        new_amount = [r.amount.quantize(Decimal("0.01")) for r in new_rows]
        result["amount_equal"] = legacy_amount == new_amount

        legacy_balance = [_safe_decimal(b).quantize(Decimal("0.01")) for b in legacy_df["balance"]]
        new_balance = [
            r.balance.quantize(Decimal("0.01")) if r.balance is not None else None
            for r in new_rows
        ]
        result["balance_equal"] = legacy_balance == new_balance
    elif legacy_count == new_count == 0:
        # Both extracted nothing: vacuously equal, nothing to diverge on.
        result["date_equal"] = True
        result["description_equal"] = True
        result["amount_equal"] = True
        result["balance_equal"] = True

    # Sums are compared independently of row alignment, so this stays a
    # meaningful signal even when row counts differ (e.g. the legacy
    # multiline phantom-row bug -- FINDINGS.md #3 -- inflates legacy's row
    # count with zero-amount rows that don't change the sum).
    legacy_sum = (
        sum(
            (_safe_decimal(i) - _safe_decimal(o))
            for i, o in zip(legacy_df["in"], legacy_df["out"])
        )
        if legacy_count
        else Decimal("0")
    )
    new_sum = sum((r.amount for r in new_rows), Decimal("0"))
    result["aggregate_sums_match"] = abs(legacy_sum - new_sum) <= TOLERANCE

    return result


def main() -> int:
    profile = load_profile(PROFILE_PATH)
    files = find_real_statements()

    if not files:
        print("no real BOI statement PDFs found in repo root; nothing to compare")
        return 0

    overall_ok = True
    for pdf_path in files:
        result = compare_file(pdf_path, profile)
        print(f"file: {result['file']}")
        print(f"  legacy_row_count: {result['legacy_row_count']}")
        print(f"  new_row_count: {result['new_row_count']}")
        print(f"  legacy_dropped_noise_rows (normalised before comparing): {result['legacy_dropped_noise_rows']}")
        print(f"  date_column_equal: {result['date_equal']}")
        print(f"  description_column_equal: {result['description_equal']}")
        print(f"  amount_column_equal: {result['amount_equal']}")
        print(f"  balance_column_equal: {result['balance_equal']}")
        print(f"  aggregate_sums_match: {result['aggregate_sums_match']}")

        if not all(
            [
                result["date_equal"],
                result["description_equal"],
                result["amount_equal"],
                result["balance_equal"],
                result["aggregate_sums_match"],
            ]
        ):
            overall_ok = False

    print(f"overall_parity_ok: {overall_ok}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
