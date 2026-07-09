# Findings: making the statement-parsing pipeline more solid

*Investigation date: 2026-07-09. Based on reading source code and notebook code
cells only — no statement contents, CSV exports, or notebook outputs were opened.*

## 1. What exists today

| Piece | File | State |
|---|---|---|
| BOI PDF parser | `boi_statement_parser.py` | Works, heuristic layout-based extraction, writes `output.csv` |
| Redaction tool | `redact_pdf.py` | Solid: rasterizing redactor with dry-run + "NOT found" warnings |
| Exploration | `explore_statement.ipynb` | Ad-hoc grouping of one statement |
| Categorisation + analysis | `sankey.ipynb` | Hand-maintained category maps (BOI + Revolut) plus regex heuristics; **no Sankey chart exists yet** despite the name |
| Privacy guardrails | `CLAUDE.md`, `.claude/settings.json`, `.gitignore`, `cleanup_sensitive.ps1` | Good layered setup |

The end-to-end flow is: BOI PDFs → `output.csv` → notebook categorisation;
Revolut CSV → notebook categorisation. The two streams are never merged into a
common schema, and no chart output exists yet.

## 2. Bugs found (fix first — these are cheap and real)

1. **`main()` now crashes because of the redacted PDFs.**
   `boi_statement_parser.py:240` globs `*.pdf`, which now matches
   `*_redacted*.pdf`. Redacted files are image-only, so every page yields zero
   transactions, and `clean_transactions()` then hits `df["date"]` on an empty,
   column-less DataFrame → `KeyError`. Fix: skip files whose name contains
   `redacted` (and `_unlocked`), and return early / raise a clear message when a
   PDF produces zero transactions.

2. **The dedupe in `sankey.ipynb` is a no-op.** Cell 3 calls
   `df.drop_duplicates()` without assigning the result back, so duplicate rows
   (e.g. from overlapping statement periods) survive into every downstream
   total. Should be `df = df.drop_duplicates()` — but see §4 on why
   dedupe-by-whole-row is itself unsafe (two identical coffees on the same day
   are legitimately two transactions).

3. **Revolut transfer labels are malformed.** In `categorise_rev_details`,
   `np.where(is_transfer, "Transfer (" + transfer_match, ")")` puts the closing
   paren in the *else* branch, producing labels like `Transfer (Name` (no
   closing paren) and a stray `")"` default. Should be
   `"Transfer (" + transfer_match + ")"`.

4. **`pd.concat(dfs)` produces duplicate indices and writes them to CSV**, which
   the notebook then has to drop as an unnamed column. Use
   `pd.concat(dfs, ignore_index=True)` and `to_csv(..., index=False)`.

## 3. Parser robustness (`boi_statement_parser.py`)

The extraction strategy (find header line → derive column x-boundaries → bucket
words by y then x) is sound for a fixed-layout statement, but several
heuristics will fail silently on edge cases:

- **No validation that extraction was correct.** The statement itself contains
  a checksum you're not using: the printed running balance. After
  `calculate_balance()` fills gaps, *verify* every printed (non-NaN) balance
  equals previous balance + in − out. Any mismatch means a row was dropped,
  split, or mis-columned. This single check converts "silently wrong numbers"
  into a loud error and is the highest-value robustness improvement available.
- **Multi-line transaction details become phantom rows.** `extract_rows` treats
  every visual line as a transaction. A details field wrapping onto a second
  line yields an extra row with 0 in/0 out that pollutes counts and dilutes
  categorisation (the continuation text is severed from its transaction).
  Merge lines that have text only in the details column into the previous row.
- **`find_table_bounds` gap heuristic** (first spacing > 2× median) can
  truncate the table early if the statement has a mid-table gap, or run past
  the subtotal if spacing is uniform. Anchoring on known footer text (e.g. the
  subtotal/"balance forward" line) would be more deterministic.
- **Column assignment uses `w["x0"]` only** (`extract_rows`), so a word
  straddling a boundary lands left. Using the word's x-midpoint is more
  forgiving. The `if i < 3` magic number in `build_columns` encodes
  "first 3 boundaries hug the left edge of the next header" — worth a comment
  or a per-column alignment spec, since it will confound future edits.
- **`calculate_balance` propagates NaN** if the first row's balance is missing
  (e.g. page-1 balance-forward parsing fails) — everything downstream becomes
  NaN with no warning.
- **No CLI.** Input folder, output path, and file selection are hardcoded.
  `argparse` with explicit input files would also naturally fix bug #1.
- Prints should become `logging` so a future CLI can have `--quiet`/`--verbose`.

## 4. Multi-statement handling

Statements overlap (and you'll keep adding months), so the pipeline needs a
notion of transaction identity:

- Dedupe on `(date, details, out, in, balance)` — including balance
  disambiguates same-day identical transactions, since the running balance
  differs. Do this in the parser/merge step, not the notebook.
- Track statement period per file so you can detect **gaps** (a missing month)
  as well as overlaps. Balance continuity across statement boundaries
  (closing balance of one = opening of next) is another free integrity check.

## 5. Categorisation — the core "make it solid" opportunity

Current state: two hardcoded dicts + regex heuristics in notebook cells, with a
manual triage loop for uncategorised rows. Recommendations, in order:

1. **Move rules out of the notebook into a data file** (e.g. `category_rules.yaml`,
   already covered by `.gitignore`-style thinking — it contains merchant/payee
   names, so treat it like `redact_terms.txt`: local-only, listed in
   `.gitignore`). One schema for both accounts:
   ```yaml
   - match: exact | contains | prefix | regex
     pattern: "..."
     category: "Groceries"
     account: boi | revolut | any
   ```
   Apply rules in file order (first match wins). This replaces both dicts, all
   the `str.contains`/`startswith` branches, and the `np.select` blocks with
   one generic engine that's testable.
2. **Make "uncategorised" a first-class output**, not a notebook cell: the
   pipeline should emit an uncategorised report sorted by |amount| and refuse
   to claim a month is "done" while material spend is unlabelled. This
   formalises the triage loop already being done by hand in cells 9 and 20.
3. **Category hierarchy.** Sankeys want levels (`House > Furniture`,
   `Fees > Card FX`). Encode as `parent/child` in the rule file rather than
   parenthesised suffixes in category strings, which are hard to aggregate.
4. **Internal-transfer netting — critical for correct Sankeys.** BOI→Revolut
   top-ups, savings sweeps, and credit-card repayments appear on *both* sides
   once accounts are merged. Without pairing/netting them, the Sankey
   double-counts these flows as both spending and income. Mark categories as
   `transfer: true` in the rules and route them account→account in the diagram
   instead of into spending.
5. **On the "LLM calls to auto-categorise" idea** (markdown note in
   `sankey.ipynb`): this conflicts with the repo's own data-hygiene rule
   ("never send statement data to external services"). If pursued, either run
   a local model, or send *only* the normalised merchant string (never amounts,
   dates, balances, or account identifiers) with explicit opt-in — and cache
   results in the local rules file so each merchant is sent at most once. A
   cheaper first step: most volume is repeat merchants, so the manual rule
   file converges quickly; the LLM only earns its keep on the long tail.

## 6. Unified schema + charts

- **Normalise both sources into one canonical frame** before analysis:
  `date, account, description, amount (signed), category, subcategory,
  source_file`. BOI's `out`/`in` columns become signed `amount`; Revolut's
  columns map directly. Everything downstream (charts, reports) consumes only
  this schema.
- **Sankey:** `plotly` is the obvious choice (`go.Sankey`) and is **not yet
  installed** in `.venv`. Structure: Income sources → accounts → top-level
  categories → subcategories, with transfers routed account→account (§5.4).
  Build it as a function taking the canonical frame + a month/date range, not
  as notebook cells.
- **Other charts worth having:** monthly stacked bars by category (trend view),
  cumulative savings line, and a simple month-over-month category delta table.
- Date filters are currently hardcoded (`> '2025-01-01'` in two places) —
  should be parameters.

## 7. Project structure & engineering hygiene

- **Not a git repo.** A thorough `.gitignore` exists but there's no repository,
  so the code itself (parser, redactor, rules engine) has no history or backup.
  `git init` is safe — the ignore rules already exclude every sensitive file
  class. Verify with `git status` after init that only code/docs are listed.
- **No dependency manifest.** Add `pyproject.toml` (or `requirements.txt`)
  pinning `pdfplumber`, `pandas`, `numpy`, `pypdfium2`, `pillow`, `pikepdf`,
  and (new) `plotly`, `pytest`, `pyyaml`.
- **No tests — and real statements can't be fixtures.** The unlock:
  **generate a synthetic BOI-format statement PDF** (reportlab or fpdf2)
  containing fake transactions in the same layout. Then the parser, the
  balance-continuity check, multi-line details handling, and the rules engine
  are all testable in CI with zero sensitive data. The redactor can be tested
  the same way: redact a synthetic PDF, then assert `extract_text()` on the
  output is empty.
- **Suggested layout** once it grows past one file:
  ```
  statement_tools/
    parsers/boi_pdf.py      # current parser, minus CLI
    parsers/revolut_csv.py  # currently lives in notebook cells 14–19
    categorise.py           # rules engine (§5)
    charts.py               # sankey + monthly views
    cli.py                  # parse / categorise / report subcommands
  tests/
    make_fixture_pdf.py     # synthetic statement generator
  ```
  Notebooks then become thin consumers instead of the system of record.

## 8. Privacy posture (already good; two small notes)

- The layered setup (behavioral rule in `CLAUDE.md` + permission denies +
  gitignore + rasterizing redactor + cleanup script) is coherent. Keep it.
- Notebook *outputs* currently embed real statement data (both notebooks have
  saved outputs). `.gitignore` excludes `*.ipynb` entirely, which works, but if
  notebooks should ever be versioned, `nbstripout` as a pre-commit hook is the
  standard fix.
- Any new `category_rules.yaml` and this kind of derived artifact should be
  added to `.gitignore` term-list section if it contains payee names (§5.1).

## 9. Suggested order of work

1. Fix the four bugs in §2 (an hour, immediate correctness win).
2. Add the balance-continuity validation (§3) — turns silent errors loud.
3. `git init` + dependency manifest (§7).
4. Extract the rules engine + rule file from the notebooks (§5.1–5.2).
5. Canonical schema merge + transfer netting (§6, §5.4).
6. Synthetic-PDF fixture + pytest suite (§7).
7. Build the Sankey and monthly charts on the canonical frame (§6).
