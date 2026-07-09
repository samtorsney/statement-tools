# Design: Reporting & charts (Sankey, monthly views)

*Status: specced 2026-07-09. Derived from FINDINGS.md §6 and §5.4. Depends on
the parser-abstraction and categorisation builds — consumes a categorised
canonical CSV. Final build in the sequence.*

## Goal

Produce the visual outputs the project exists for: a Sankey of money flow and
supporting monthly views, computed correctly in the presence of
inter-account transfers.

## Transfer netting (the correctness core)

Once BOI and Revolut rows share one frame, every internal move (top-up,
savings sweep, credit-card repayment) appears twice — once per side. Without
netting, a Sankey double-counts these as both spending and income.

- Rows with `is_transfer: true` are **paired**: opposite signs, equal
  |amount|, different accounts, dates within a configurable window
  (default ±3 days).
- Pairing is greedy by closest date; each row pairs at most once.
- Paired flows render as account→account links, not spending.
- **Unpaired transfer rows are surfaced, not dropped**: written to an
  `unmatched_transfers.csv` report (file only, never stdout) and counted in
  the run summary. An unpaired transfer usually means a missing statement
  month or a mis-flagged rule.

## Outputs

All outputs are written to a `reports/` directory. **Add `reports/` to
`.gitignore` in this build** — every artifact contains real financial data.

1. **Sankey** (`plotly` `go.Sankey`, self-contained HTML file):
   node layers = income sources → accounts → parent categories → child
   categories; transfers routed account→account. Link/node hover shows
   amounts and transaction counts.
2. **Monthly stacked bar** (HTML): spend per month stacked by parent category.
3. **Cumulative savings line** (HTML): running sum of transfer-to-savings
   flows plus balance trajectory where balances exist.
4. **Month-over-month delta table** (CSV): per-category spend vs prior month.

## CLI

```
report sankey  --in categorised.csv --from 2025-01-01 --to 2025-12-31 --out reports/
report monthly --in categorised.csv --from ... --to ...   # bars + delta table
report savings --in categorised.csv ...
```

Date ranges are required parameters — no hardcoded year windows (fixes the
`> '2025-01-01'` literals in the current notebook). Sign convention: input is
the canonical signed-amount schema; spending is negative.

## Structure

- `charts/netting.py` — transfer pairing (pure, frame → frame + unmatched)
- `charts/sankey.py`, `charts/monthly.py`, `charts/savings.py` — pure
  builders: frame → plotly figure / table
- `charts/cli.py` — I/O, file writing, run summary (counts only on stdout)

## Testing

- Synthetic categorised-CSV fixtures with known flows → assert Sankey node
  and link totals numerically (inspect the `go.Sankey` data structure, not
  the rendered HTML).
- Netting tests: exact pair, cross-month pair inside window, amount mismatch
  (no pair), three-way ambiguity (greedy closest-date wins), unpaired row
  lands in the unmatched report.
- Double-count regression test: total spending with netting on == sum of
  non-transfer negatives; with a deliberately unpaired transfer, the run
  summary flags it.

## Build instructions (for the implementing agent)

- **Model: `sonnet`** — the netting semantics and Sankey aggregation need
  real reasoning; chart assembly alone would be `haiku`-able, but the
  correctness core isn't. No need for `opus`.
- Add `plotly` (pinned) to `requirements.txt`.
- Read `CLAUDE.md` first. Hard privacy rules: never read real CSVs (including
  files under `reports/` you just generated), non-redacted PDFs, or
  notebooks. All verification runs on synthetic fixtures; stdout may carry
  only counts, totals-match booleans, filenames, and exit codes.
- Verify `reports/` is gitignored (`git check-ignore reports/x` with a dummy
  path) before the final commit.
