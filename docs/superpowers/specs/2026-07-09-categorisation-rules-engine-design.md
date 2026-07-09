# Design: Categorisation rules engine

*Status: specced 2026-07-09. Derived from FINDINGS.md §5. Depends on the
parser-abstraction build (consumes the canonical schema). Retires the
categorisation logic currently living in `sankey.ipynb` cells.*

## Goal

Replace the notebook-embedded category dicts and regex heuristics with a
declarative rules file plus a small generic engine, and make "uncategorised"
a first-class report. Fixes FINDINGS §2.2 and §2.3 by construction (the
notebook code containing those bugs is retired).

## Privacy boundary (drives the whole design)

Two kinds of rules exist and they must live in separate files:

- **Structural rules** (`categorise/builtin_rules.yaml`, committed): patterns
  derived from bank formats, no personal data — e.g. `NEPOSCHG<CCY>` → Card FX
  Fee, `NEATMCHG<CCY>` → ATM Fee, `TX` prefix → Card Payment, foreign-POS
  country extraction, Revolut `Transfer to/from <name>` → transfer.
- **Personal rules** (`category_rules.yaml`, local-only, gitignored): payee and
  merchant mappings. Add `category_rules.yaml` and `*rules*.yaml` exceptions
  carefully: gitignore must cover the personal file while the builtin file
  stays tracked (use an explicit path, not a broad glob).

## Rule schema (one format for both files)

```yaml
- match: exact | contains | prefix | regex
  pattern: "..."
  category: "House/Furniture"      # parent/child path, '/'-separated
  account: boi_current | revolut_current | any   # default: any
  transfer: false                  # true ⇒ internal flow, netted in reports
  extract: null                    # optional: regex group name appended to
                                   # category, e.g. currency or country code
```

Precedence: personal file first, then builtin; within a file, first match
wins. A `regex` rule with `extract` reproduces today's dynamic labels
(`Card FX Fee (GBP)`) without string concatenation in code.

## Engine and CLI

- `categorise/engine.py`: pure function `categorise(frame, rules) -> frame`
  adding `category`, `subcategory`, `is_transfer` columns to a canonical
  frame. No I/O in the engine.
- CLI `categorise run --rules category_rules.yaml --in canonical.csv --out categorised.csv`.
- CLI `categorise report --in categorised.csv --out uncategorised.csv`:
  uncategorised rows sorted by |amount| descending, plus a per-description
  aggregation (sum, count) to make rule-writing efficient. **Written to file,
  never printed** — the report contains transaction data.
- `run` exits nonzero (with a count-only summary on stdout) if uncategorised
  |amount| exceeds a `--tolerance` threshold (default 0), so a month can't be
  silently "done" with material unlabelled spend.

## Migration of existing rules

- A one-shot script `categorise/migrate_notebook_rules.py` parses
  `sankey.ipynb` as JSON, reads **source cells only** (never `outputs`),
  extracts the two dicts (`details_category_map`, `rev_details_category_map`)
  by AST-parsing the cell source, and writes them as `exact` rules into the
  local `category_rules.yaml`.
- Parenthesised suffixes in existing category values (e.g. `House (Furniture)`)
  are converted to `parent/child` paths.
- The notebook regex heuristics are hand-translated into
  `builtin_rules.yaml` as part of this build (they are structural, PII-free,
  and listed above).
- Transfer-ish categories (savings sweeps, Revolut top-ups, credit-card
  repayments, pocket/vault moves) get `transfer: true` during migration.

## Testing

- Fixture-based: a synthetic canonical CSV with fake merchants + a fixture
  rules file → assert categories, subcategories, transfer flags, precedence
  (personal beats builtin, first match wins), and `extract` behaviour.
- Migration test runs against a **synthetic notebook fixture** with the same
  cell structure, not the real `sankey.ipynb`.
- Threshold behaviour: uncategorised spend above tolerance ⇒ nonzero exit.

## Build instructions (for the implementing agent)

- **Model: `sonnet`** — multi-file design with an AST-based migration and
  precedence semantics; too much judgement for `haiku`, no need for `opus`.
  Escalate only if the round-trip tests fail twice for design (not typo)
  reasons.
- Read `CLAUDE.md` first. Hard privacy rules: never read non-redacted PDFs,
  any real `.csv`/`.xlsx`, `redact_terms.txt`, or notebook `outputs` arrays.
  The real `sankey.ipynb` may be touched **only** by the migration script
  (source cells only), never opened directly in your context.
  All test evidence must come from synthetic fixtures.
- The generated `category_rules.yaml` is personal data: verify it is
  gitignored (`git check-ignore category_rules.yaml`) before finishing, and
  never print its contents.
- Do not delete the notebooks; the user retires them after verifying parity.
