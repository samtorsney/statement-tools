# Design: Profile-driven statement parser abstraction

*Status: approved 2026-07-09. Approach and design validated in conversation.*

## Goal

Generalise the BOI PDF parser so new statement types — other Irish/EU bank
PDFs, credit-card PDFs, CSV sources (Revolut-style), savings/brokerage
statements — are added by writing a **declarative profile file**, not Python.
The tool is intended to be shareable/open-source, so profiles must be pure
data that can be reviewed and contributed without code review.

The core idea being retained (from `boi_statement_parser.py`): locate the
header line → derive column x-boundaries from header word positions → group
words into y-lines → bucket words into columns → clean and validate.

## Approach decision

Three architectures were considered:

- **A. Declarative profiles + engine with enumerated strategies** *(chosen)* —
  each bank is a YAML file; every behavioural choice selects a named strategy
  from a fixed, registry-validated vocabulary. Weird banks require extending
  the engine with a new named strategy, which all future profiles can reuse.
  Profiles cannot hide arbitrary code — important for accepting community
  contributions.
- **B. Declarative profiles + Python escape hatches** — rejected for now: the
  hooks become the config and the DSL rots. An escape hatch can be added
  later; removing one after publication cannot.
- **C. Python importer classes (beancount/ofxstatement model)** — rejected:
  "add a bank" would mean writing Python, contrary to the goal.

## Architecture

```
statement_parser/
  engine/
    pdf_table.py        # generic layout engine (today's BOI logic, parameterised)
    csv_table.py        # CSV column-mapping engine
    strategies.py       # named-strategy registries (page_detect, table_end, multiline…)
  profile.py            # profile dataclasses + YAML loader + validation
  canonical.py          # canonical transaction schema + sign normalisation
  validate.py           # balance continuity, statement gap/overlap checks
  cli.py                # parse / debug-layout subcommands
  profiles/             # shipped bank profiles (YAML — layout only, zero PII)
tests/
  fixtures/make_pdf.py  # synthetic statement generator, driven by the profiles
```

**Boundary rule:** categorisation stays outside this package. Profiles describe
*layout* (shareable, no personal data); category rules contain payee names
(personal, local, gitignored). This split is what makes the tool publishable.

## Canonical output schema

Every engine — PDF or CSV — emits the same frame:

| field | notes |
|---|---|
| `date` | ISO date |
| `description` | raw details text, multiline-merged |
| `amount` | **signed** `Decimal`: spending negative, income positive |
| `balance` | optional (credit cards / CSVs may not have one) |
| `currency` | optional |
| `account` | profile name / user-supplied account label |
| `source_file`, `page`, `row` | provenance, so every value is traceable |

The `in_out` → signed conversion happens inside the engine (in → `+`,
out → `−`); downstream code never sees per-bank amount conventions.

## Profile schema (per-bank YAML)

```yaml
meta:        { name: boi_current, institution: "Bank of Ireland", country: IE, source: pdf }
page_detect: { strategy: header_match }        # all column headers present ⇒ table page
columns:
  - { header: "Date",                field: date,        align: left_edge }
  - { header: "Transaction details", field: description, align: left_edge }
  - { header: "Payments - out",      field: out,         align: left_edge }
  - { header: "Payments - in",       field: in,          align: midpoint  }
  - { header: "Balance",             field: balance,     align: midpoint  }
table_end:   { strategy: spacing_gap }          # alternatives: footer_text, page_bottom
rows:        { line_tolerance: 3, multiline: merge_into_previous }
amounts:     { style: in_out, thousands: ",", decimal: "." }   # or style: signed
dates:       { format: "%d %b %Y", fill: forward }
balance:     { present: true, validate: continuity }
skip_rows:   [ { field: description, equals: "BALANCE FORWARD" } ]
```

- A CSV profile reuses `meta` / `amounts` / `dates` / `skip_rows` and replaces
  the geometry sections with
  `csv: { encoding, delimiter, column_map: {SourceCol: canonical_field, …} }`.
- Every magic number / special case in the current parser gets a named home:
  the `if i < 3` boundary rule becomes per-column `align`; the gap heuristic
  becomes `table_end.strategy`; date forward-fill becomes `dates.fill`.
- The schema may reserve fields that are not yet implemented (e.g.
  `dates.year_policy` for credit cards printing "12 Jan" without a year).
  Reserved fields are documented but rejected by the loader until implemented.

## PDF engine pipeline

Per page:

1. **page_detect** strategy → is this a table page? (`header_match` = all
   profile headers found on one line)
2. **Header location** — match each profile column's (possibly multi-word)
   header text to word boxes; generalises `find_header_line` +
   `build_header_blocks`, driven by `columns` instead of a hardcoded map.
3. **Boundary derivation** — each gap between adjacent columns resolved by the
   *right* column's `align`: `left_edge` (boundary at its header's x0),
   `midpoint`, or `right_edge`.
4. **Line grouping** — words bucketed into lines by y within
   `rows.line_tolerance`.
5. **Column bucketing** — by word **x-midpoint** (not x0), fixing the
   boundary-straddle weakness.
6. **Multiline policy** — `merge_into_previous`: a line with text only in the
   `description` column appends to the prior row (eliminates phantom rows).
7. **Coercion** — amounts per `style` / `thousands` / `decimal` → signed
   `Decimal`; dates per `format` + `fill`.
8. **skip_rows** filters.
9. **Validation + emit** canonical rows with `page` / `row` provenance.

Steps 1, 3 (per column), 6, and table-end detection are registry lookups —
plain dicts, e.g. `TABLE_END = {"spacing_gap": …, "footer_text": …,
"page_bottom": …}`. Adding vocabulary for a new bank = one function with a
narrow signature + a docs line.

## Profile loading, validation, errors

- Plain dataclasses + explicit `validate()`; the only new dependency is
  `pyyaml`.
- Strategy names are validated against their registries at load time with
  actionable messages: `unknown table_end strategy 'gap'; available:
  spacing_gap, footer_text, page_bottom`.
- **Unknown keys are hard errors** (typo safety for contributed profiles).
- Extraction failures raise structured errors carrying file / page / strategy
  context.
- Validation problems (e.g. balance discontinuity) are **loud by default**:
  nonzero exit, no silent partial output. Balance continuity check: every
  printed balance must equal previous balance + amount; any mismatch means a
  row was dropped, split, or mis-columned.

## Profile authoring support

`cli.py debug-layout statement.pdf --profile x` prints the detected header
boxes, derived column boundaries, and the first rows' bucketing, so a
contributor can see *why* a profile misparses. Text dump first; rendered
overlay image is a possible later addition.

## Testing

- **Profile-driven fixtures:** `tests/fixtures/make_pdf.py` generates a
  synthetic statement *from a profile* (reportlab), so every shipped profile
  automatically gets a round-trip test: generated ground truth == parsed
  output. No real statement data anywhere near CI.
- **Edge-case fixtures:** multiline details, page breaks, thousands
  separators, same-day duplicate transactions, and a deliberately corrupted
  balance (asserting the loud failure fires).
- **Profile schema tests:** malformed profiles must produce the helpful
  errors, not stack traces.
- **Local-only parity check (never CI):** new engine vs old
  `boi_statement_parser.py` on a real statement before the old script is
  deleted.

## Migration

1. `boi_statement_parser.py` → `profiles/boi_current.yaml` + generic engine.
2. Revolut notebook cells → `profiles/revolut_current.yaml`.
3. Old script survives until the parity check passes, then is deleted.
4. Notebooks become consumers of the canonical CSV.

Known bugs in the current code (documented in `FINDINGS.md` §2) are fixed by
construction in the new engine rather than patched in the old script — except
anything needed to run the parity comparison.

## Out of scope

- Categorisation engine and rules file (FINDINGS §5) — separate project.
- Sankey/chart generation (FINDINGS §6) — separate project, consumes the
  canonical schema.
- OCR / image-only PDFs: the engine requires a text layer; redacted
  (rasterized) statements are explicitly unsupported and skipped by filename.
