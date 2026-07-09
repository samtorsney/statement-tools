# statement-tools

Turn bank statements (PDF or CSV) into one canonical transaction ledger,
categorise the transactions with declarative rules, and render Sankey /
monthly / savings charts from the result — all locally, with no network
calls.

## 1. What it does

```
statement (PDF or CSV)  --parse-->  canonical transaction CSV
                                          |
                                          v
                            --categorise-->  categorised CSV
                                          |
                                          v
                              --chart-->  Sankey / monthly / savings HTML
```

- **Parse**: a profile YAML describes one bank's statement layout — PDF
  column geometry (header positions, alignment, multi-line rows) or a CSV
  column-name mapping. `statements parse` reads one or more statement files
  through a profile and writes one canonical CSV: `date, description,
  amount, balance, currency, account, source_file, page, row`.
- **Categorise**: declarative pattern rules (exact / contains / prefix /
  regex match on the description, optionally scoped to an account) assign a
  `category`, `subcategory`, and `is_transfer` flag to each row. Personal
  rules are evaluated before built-in structural rules; first match wins.
- **Chart**: a categorised CSV over a date range becomes a Sankey diagram of
  money flow, a monthly stacked spend bar with a month-over-month delta
  table, or a cumulative-savings/balance line — as standalone HTML files
  (via Plotly) that open in any browser. `chart overview` combines them into
  a single report page with headline stat tiles (income / spend / net /
  savings rate), top categories and merchants, biggest movers vs the
  preceding period, notable transactions, and a data-health panel
  (uncategorised spend, unmatched transfers, per-account coverage).
- **Triage**: an interactive terminal wizard turns the long tail of
  uncategorised transactions into new personal rules without hand-editing
  YAML.

Two bank profiles ship today: **Bank of Ireland** current account (PDF) and
**Revolut** current account (CSV export). Adding another bank means writing
one profile YAML — see §3.

## 2. Quickstart (5 minutes)

Install the package (in a virtualenv):

```sh
pip install .
```

This installs a single console script, `statements`, plus the
`statement_parser`, `categorise`, `charts`, and `triage` packages it wraps.

Parse a statement with a shipped profile:

```sh
statements parse my_statement.pdf --profile boi_current --output transactions.csv
```

(For a Revolut CSV export: `statements parse export.csv --profile
revolut_current --output transactions.csv`.)

Categorise it, using your personal rules file (created on first use — see
§4) plus the built-in rules:

```sh
statements categorise --rules category_rules.yaml --in transactions.csv --out categorised.csv
```

`categorise` exits non-zero if the total absolute amount of uncategorised
rows exceeds `--tolerance` (default: 0), so a month can't silently ship with
unlabelled spend. Send the leftovers through the triage wizard:

```sh
statements triage --in transactions.csv --rules category_rules.yaml
```

This walks you through each distinct uncategorised description (largest
total amount first), lets you assign or create a category, and appends the
resulting rule to `category_rules.yaml`. Re-run `categorise` afterwards to
pick up the new rules.

Render a chart over a date range:

```sh
statements chart sankey --in categorised.csv --from 2026-01-01 --to 2026-01-31 --out reports/
```

Open `reports/sankey.html` in a browser. `chart monthly` and `chart savings`
take the same `--in/--from/--to/--out` arguments and write `monthly.html` /
`savings.html` respectively.

Or generate everything as one page — the Sankey plus stat tiles, rankings,
movers vs the preceding period, notable transactions, and a data-health
panel:

```sh
statements chart overview --in categorised.csv --from 2026-01-01 --to 2026-01-31 --out reports/
```

This writes a self-contained `reports/overview.html` (works offline; no
network calls). Sections adapt to the range — a single month skips the
monthly trend bars, and the movers comparison is omitted when there's no
data for the preceding window.

## 3. Adding a bank

A profile is one YAML file under `statement_parser/profiles/`, named
`<profile_name>.yaml`. `meta.source` picks the shape:

**PDF example** (see `statement_parser/profiles/boi_current.yaml` for a
complete, annotated one):

```yaml
meta:
  name: my_bank_current      # matches the filename (my_bank_current.yaml)
  institution: "My Bank"
  country: IE
  source: pdf

page_detect:
  strategy: header_match      # find each page's header row by matching column headers

columns:
  - { header: "Date",              field: date,        align: left_edge }
  - { header: "Transaction",       field: description, align: left_edge }
  - { header: "Debit",             field: out,         align: left_edge }
  - { header: "Credit",            field: in,          align: left_edge }
  - { header: "Balance",           field: balance,     align: midpoint }

table_end:
  strategy: spacing_gap        # stop at the first large vertical gap after the header

rows:
  line_tolerance: 3            # px tolerance for "same row" when bucketing words
  multiline: merge_into_previous   # a row with only a description continues the row above

amounts:
  style: in_out                # separate debit/credit columns (vs. style: signed, one signed column)
  thousands: ","
  decimal: "."

dates:
  format: "%d %b %Y"
  fill: forward                # blank dates on continuation rows inherit the last real date

balance:
  present: true
  validate: continuity         # each row's balance must equal the previous +/- this row's amount

skip_rows:
  - { field: description, equals: "OPENING BALANCE" }
```

**CSV example** (see `statement_parser/profiles/revolut_current.yaml`):

```yaml
meta:
  name: my_bank_csv
  institution: "My Bank"
  country: IE
  source: csv

csv:
  encoding: utf-8
  delimiter: ","
  column_map:
    "Date": date
    "Description": description
    "Amount": amount           # style: signed -> one amount column, not in/out
    "Balance": balance

amounts:
  style: signed
  thousands: ""
  decimal: "."

dates:
  format: "%Y-%m-%d"
  fill: none

balance:
  present: true
  validate: none

skip_rows: []
```

Unknown keys, unknown strategy names, and missing required sections are all
hard errors with actionable messages — the loader (`statement_parser/profile.py`)
validates the whole file up front, before any parsing happens.

**`statements debug-layout`** is the profile-authoring tool for PDF
profiles: point it at a statement and it prints, per page, the detected
header boxes, the column boundaries derived from them, and the first few
bucketed rows — so you can see exactly why a profile does or doesn't match a
given PDF's layout, without printing the full statement.

```sh
statements debug-layout my_statement.pdf --profile my_bank_current --max-rows 5
```

For the full profile schema (every key, every strategy, and the reasoning
behind each design choice) see
[`docs/superpowers/specs/2026-07-09-statement-parser-abstraction-design.md`](docs/superpowers/specs/2026-07-09-statement-parser-abstraction-design.md).

## 4. Categorisation model

Two rule files, one schema (`categorise/rules.py`):

- **Built-in rules** (`categorise/builtin_rules.yaml`): committed,
  structural, PII-free — bank fee codes, ATM prefixes, foreign point-of-sale
  patterns. Safe to share publicly because they encode statement *formats*,
  not anyone's actual transactions.
- **Personal rules** (`category_rules.yaml` at the repo root by convention):
  your own payee/merchant mappings. Gitignored — see §5. Created on first
  use by the triage wizard, or hand-written using the same schema.

**Precedence**: personal rules are evaluated before built-in rules; within
either file, rules are evaluated in list order and the **first match wins**.
This lets a personal rule override a built-in one (e.g. re-labelling an ATM
withdrawal your builtin rule would otherwise catch generically).

Each rule has a `match` type (`exact`, `contains`, `prefix`, or `regex`,
matched against the transaction description), a `pattern`, a `category`
(a `/`-separated path — the first segment becomes `category`, the rest
`subcategory`), an optional `account` to scope the rule to one profile's
transactions (default: any), and an optional `transfer: true` flag.

**Why transfer flagging matters**: once statements from multiple accounts
(e.g. Bank of Ireland *and* Revolut) share one categorised CSV, every
internal transfer between your own accounts appears twice — once as an
outgoing row on one side, once as an incoming row on the other, with
opposite signs. Charting must not count both legs as real spending and real
income (double-counting) or silently drop a leg without a match. Rows
marked `transfer: true` are excluded from category totals and instead
passed through transfer-netting (`charts/netting.py`), which pairs opposite-
sign, equal-amount rows across accounts within a date window; unpaired
transfer rows are written to `unmatched_transfers.csv` rather than dropped.

## 5. Privacy model

**Everything in this project runs locally. Nothing here makes a network
call, uploads statement data, or phones home.**

This folder is designed to hold real, sensitive bank statements alongside
the code that processes them. Several file classes are gitignored on
purpose and must never be committed:

- Statement source files and any derived export: `*.pdf`, `*.csv`, `*.xlsx`,
  `*.xls`, `*.ofx`, `*.qif` (anywhere in the repo).
- Redaction term lists (`*terms*.txt`, `secrets.txt`, `*.secrets`) — these
  can contain names, account numbers, and addresses.
- Notebooks (`*.ipynb`) — cell outputs can embed statement data.
- Your personal rules file, `category_rules.yaml` — it contains your own
  payee/merchant names. (`categorise/builtin_rules.yaml`, the structural
  rule set, is a different file and *is* tracked.)
- `reports/` — every Sankey/monthly/savings HTML file and delta/unmatched-
  transfer CSV in there contains real financial data.

**Before committing, run `git status` and make sure none of the above shows
up as trackable.** If you ever change `.gitignore`, re-check it especially
carefully — a stale or narrowed ignore rule silently re-exposes real data.

The CLIs enforce a stdout/stderr discipline of their own: `categorise` and
`chart` print counts, file paths, and exit codes only — never transaction
descriptions or amounts — because that output can end up in shell history,
CI logs, or a terminal someone is screen-sharing. `triage` is the one
exception: it is an interactive tool for your own terminal on your own
data, so it does print descriptions and amounts by design.

If you need to share an excerpt of a real statement (e.g. to report a
parsing bug), use `redact_pdf.py` to black out PII and rasterize the PDF
first — it never leaves a recoverable text layer, unlike the original.
Never share an original, unredacted PDF or a raw CSV/XLSX export.

## 6. Development

Install dev dependencies (adds `pikepdf`, `reportlab`, and `pytest` on top
of the runtime dependencies pulled in by `pip install .`):

```sh
pip install -r requirements-dev.txt
```

Run the test suite:

```sh
pytest
```

All tests run against synthetic, generated fixtures (`tests/fixtures/make_pdf.py`
renders fake statement PDFs from a profile; CLI tests write fake canonical/
categorised CSVs directly) — no real statement data is needed to develop or
test this project.

To add a bank profile: write a new YAML file under
`statement_parser/profiles/`, then use `statements debug-layout` against a
sample statement to check the derived column boundaries and bucketed rows
match what you expect. Add a round-trip test using `tests/fixtures/make_pdf.py`
to render a synthetic PDF for your profile and assert the parsed output.

To add built-in categorisation rules: extend `categorise/builtin_rules.yaml`
using the schema in §4 — keep it PII-free and structural (fee codes, generic
prefixes), not merchant-specific; merchant mappings belong in each user's own
`category_rules.yaml`.
