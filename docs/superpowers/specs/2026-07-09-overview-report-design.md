# Design: Combined overview report — `statements chart overview`

*Status: approved 2026-07-09 (design validated in conversation). Build 6 in the
orchestration sequence; depends on Builds 1–5.*

## Goal

One self-contained HTML page combining the Sankey with the other insights that
make a spending review complete: headline numbers, rankings and movers, trend
charts, notable transactions, and a data-health panel. One template serves any
date range (a month or a year); sections adapt to range length.

## Approach decision

Fragment assembly, no template engine: reuse the three existing pure figure
builders unchanged, render each via Plotly `to_html(full_html=False,
include_plotlyjs=False)`, inline `plotly.js` exactly once, and compose the
page with string assembly plus one handwritten CSS block. No new
dependencies. (Jinja2 rejected as an unneeded dependency for one page; an
index page linking the existing three files rejected as not actually a
combined report.)

## Page structure (top to bottom)

1. **Header**: title, requested date range, accounts covered, generated-at
   timestamp.
2. **Stat tiles** (4): Income, Spend, Net, Savings rate.
   - Transfer rows (`is_transfer` true) are excluded from all four.
   - income = sum of positive non-transfer amounts in range;
     spend = |sum of negative non-transfer amounts|;
     net = income − spend;
     savings rate = net / income, rendered "—" when income is 0.
   - Currency formatting: if every in-range row shares one `currency` value,
     format with it; mixed or absent currency → bare numbers plus a small
     note in the header.
3. **Sankey**: full width, existing `charts/sankey.py` builder unchanged.
4. **Movers & rankings**: three tables —
   a. top categories by spend (parent category, |amount| desc, top 10);
   b. top merchants by spend (grouped by `description`, non-transfer, top 10);
   c. movers vs the **preceding equal-length window** (window immediately
      before `--from`, same number of days): parent-category spend deltas,
      top 5 increases and top 5 decreases.
   - If the input frame has **no rows at all** in the preceding window, table
     (c) is replaced by one line saying the comparison window has no data —
     never a table of misleading zeros.
5. **Trend charts**: monthly stacked bars (existing builder) rendered **only
   when the range spans ≥ 2 calendar months**; savings line (existing
   builder) always.
6. **Notable transactions**: top 10 by |amount| in range, transfers excluded:
   date, account, description, category, amount.
7. **Data-health panel** (bottom; each item styled as a warning when
   nonzero/gappy, neutral otherwise):
   - uncategorised rows in range: count and total |amount|;
   - unmatched transfer legs: count (from the same netting run);
   - per-account coverage: first/last transaction date and row count;
   - note when the movers comparison was skipped for missing coverage.

## Structure and data flow

- `charts/insights.py` — **pure computation only**, no HTML:
  `stat_tiles(frame, range) -> Tiles`, `rankings(...)`, `movers(frame,
  range) -> Movers | NoPriorCoverage`, `notables(...)`, `health(...)`.
  Typed returns (dataclasses), numerically testable.
- `charts/overview.py` — page assembly: calls netting **once** and feeds the
  Sankey, tiles, and health panel from that single result; renders figures as
  fragments; renders insight results as HTML tables/tiles; one CSS block;
  `plotly.js` inlined once via `plotly.offline.get_plotlyjs()`.
- CLI: `statements chart overview --in categorised.csv --from YYYY-MM-DD
  --to YYYY-MM-DD --out reports/` → writes `overview.html` and
  `unmatched_transfers.csv` (consistent with the other chart subcommands).
- House rules unchanged: required date range, counts-only stdout, empty
  in-range frame exits nonzero with a count-only message.

## Testing

- `insights.py` numeric tests on synthetic frames: tile math including
  zero-income savings rate; ranking order and top-N cutoffs; movers deltas
  including sign; `NoPriorCoverage` when the preceding window is empty;
  mixed-currency fallback; transfer exclusion everywhere it applies.
- Assembly tests: each section has a stable HTML anchor id; `plotly.js`
  source appears exactly once; monthly-bars fragment absent for a
  single-month range and present for a multi-month range.
- CLI end-to-end on a synthetic categorised CSV: exit 0, `overview.html`
  written, stdout counts only.

## Out of scope

- New chart types (daily spend line, budgets, forecasts).
- PDF export, emailing, scheduling.
- Any change to the existing three standalone chart subcommands.

## Build instructions (for the implementing agent)

- **Model: `sonnet`**.
- **Before writing any layout/CSS/chart-assembly code, load the `dataviz`
  skill** (via the Skill tool) and follow it — the page must read as one
  designed system, not three pasted Plotly defaults. Apply it to the tiles,
  tables, and warning styling as well as the figures.
- Read `CLAUDE.md` first. Standing privacy rules: never read non-redacted
  PDFs, real CSV/XLSX files (including anything under `reports/`),
  `redact_terms.txt`, `category_rules.yaml`, or notebooks. Traceback rule:
  no raw input text in error messages.
- All tests green: `.venv\Scripts\python.exe -m pytest` (168 pre-existing +
  new). Report counts only.
- Final smoke run on real data, counts-only output: `statements chart
  overview --in reports/categorised.csv --from 2025-01-01 --to 2025-12-31
  --out reports/` → report exit code and row counts only. Never open the
  generated file.
- `git status --porcelain` before every commit; STOP if any sensitive file
  class appears trackable. Commit per logical step referencing this spec,
  with the usual trailer:
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BfyantzNe3P9S63HWNW1K4
