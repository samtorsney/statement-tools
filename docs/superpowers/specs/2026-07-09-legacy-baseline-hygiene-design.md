# Design: Legacy baseline fixes & repo hygiene

*Status: specced 2026-07-09. Derived from FINDINGS.md §2, §7. First build in the
sequence — everything else depends on a runnable baseline and a committed repo.*

## Goal

Make `boi_statement_parser.py` runnable again (it currently crashes — see
FINDINGS §2.1), give the repo a dependency manifest, and commit the existing
source. This creates the baseline needed for the parity check in the parser
abstraction spec.

## Scope

### 1. Fix the redacted-PDF crash (`boi_statement_parser.py`)

- `main()` must skip any PDF whose filename contains `redacted` or
  `_unlocked` (case-insensitive). Print a one-line "skipping <name>" notice.
- `process_statement()` on a PDF that yields zero transactions must not crash:
  print a warning naming the file and return an empty DataFrame with the
  expected columns (`date, details, out, in, balance`). `clean_transactions()`
  must guard against an empty transaction list.
- `main()` must not crash if *no* PDFs produce transactions (write nothing,
  print a summary, exit nonzero).

### 2. Fix the concat/index defect

- `pd.concat(dfs, ignore_index=True)` and `to_csv(csv_path, index=False)`.
- `extracted_from` column: store `pdf.name` (filename only), not the full path.

### 3. Dependency manifest

- Add `requirements.txt` pinned to the versions currently in `.venv`:
  pdfplumber 0.11.8, pandas 2.3.3, numpy 2.0.2, pypdfium2 5.3.0,
  pillow 11.3.0, pikepdf 9.11.0.
- Add a `requirements-dev.txt` with `pytest` (unpinned minor).
  Later specs add their own deps (`pyyaml`, `plotly`, `reportlab`) when built.

### 4. Commit the existing source

Commit (in one or two logical commits): `boi_statement_parser.py`,
`redact_pdf.py`, `cleanup_sensitive.ps1`, `CLAUDE.md`, `FINDINGS.md`,
`.gitignore`, `.claude/settings.json`, the new requirements files.
`git status` must be checked before every commit; if any `.pdf`, `.csv`,
`.xlsx`, `.ipynb`, or `*terms*` file ever appears as trackable, STOP and
report instead of committing.

## Explicit non-goals

- The notebook bugs (FINDINGS §2.2, §2.3) — the notebooks are retired by the
  categorisation spec; do not edit any `.ipynb` file.
- Balance-continuity validation — lands in the new engine
  (parser-abstraction spec), not the legacy script.
- Any behaviour change to extraction logic beyond the crash guards above.

## Verification gates (run in order; each must pass before the next commit)

1. `python -c "import boi_statement_parser"` — imports clean.
2. Run `python boi_statement_parser.py` in the project folder (which contains
   both original and redacted PDFs). Expected: redacted files reported as
   skipped, per-file transaction counts printed, exit 0, `output.csv` written.
   **Do not open or print the contents of `output.csv`** — verify only that it
   exists and its line count is > 1 (`(Get-Content output.csv | Measure-Object -Line).Lines`).
3. `git status --porcelain` shows no sensitive file classes before each commit.

## Build instructions (for the implementing agent)

- **Model: `haiku`** — small, mechanical, fully-specified diffs with runnable
  acceptance commands. Escalate to `sonnet` only if a gate fails twice.
- Read `CLAUDE.md` before starting. Hard privacy rules, non-negotiable:
  never read any non-redacted PDF, any `.csv`/`.xlsx` (including `output.csv`
  you just generated), `redact_terms.txt`, or notebook files. Verification
  output may include only filenames, counts, and exit codes — never
  transaction rows.
- One commit per scope item, message referencing this spec.
