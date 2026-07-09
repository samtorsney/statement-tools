# Build orchestration plan

*2026-07-09. Claude acts as orchestrator; each build is executed by a
subagent using the smallest model judged capable, per the "Build
instructions" section of its spec.*

## Sequence and model assignments

| # | Build | Spec | Model | Depends on |
|---|-------|------|-------|-----------|
| 1 | Legacy baseline & repo hygiene | `2026-07-09-legacy-baseline-hygiene-design.md` | **haiku** | — |
| 2 | Profile-driven parser abstraction | `2026-07-09-statement-parser-abstraction-design.md` | **sonnet** | 1 (parity baseline) |
| 3 | Categorisation rules engine | `2026-07-09-categorisation-rules-engine-design.md` | **sonnet** | 2 (canonical schema) |
| 4 | Reporting & charts | `2026-07-09-reporting-charts-design.md` | **sonnet** | 2, 3 |

Model rationale: `haiku` for mechanical, fully-specified diffs with runnable
acceptance commands; `sonnet` where multi-file design, geometry, or
correctness semantics (netting, precedence) need real reasoning. `opus` is
an escalation path only — a build escalates one tier after its verification
gates fail twice for design (not typo) reasons. Nothing here warrants
starting at `opus`.

## Orchestrator decisions of record

- **Notebook bugs (FINDINGS §2.2, §2.3) are not patched.** The notebooks are
  retired by build 3; the bugs die with them. No agent edits `.ipynb` files.
- **Balance validation is not added to the legacy script** (FINDINGS §9.2 as
  written). It lands in build 2's `validate.py` instead; the legacy script
  only gets crash fixes needed for the parity baseline.
- **Dedupe lives in build 2** (`validate.py`, full-row identity including
  balance), not in notebooks or the categorisation engine.
- Builds run sequentially, not in parallel — each consumes the previous
  build's output contract.

## Standing rules for every implementing agent

1. Read `CLAUDE.md` before any other action; its privacy rules override
   convenience. Never load non-redacted PDFs, real CSV/XLSX files,
   `redact_terms.txt`, notebook outputs, or generated reports into context.
2. All automated verification uses synthetic fixtures. Real-data checks are
   scripted comparisons that print only filenames, counts, and booleans.
3. Check `git status --porcelain` before every commit; if a sensitive file
   class appears trackable, stop and report instead of committing.
4. Verification gates run in spec order; a build is not done until its gates
   pass with observed output.
