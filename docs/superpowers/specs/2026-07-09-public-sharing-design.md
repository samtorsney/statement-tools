# Design: Public sharing — packaging, README, interactive triage

*Status: approved 2026-07-09 (design validated in conversation). Build 5 in the
orchestration sequence; depends on Builds 1–4 all being complete.*

## Goal

Make the tool usable by other people: installable with one command, runnable
through one CLI entry point, documented in a README, MIT-licensed, and with an
interactive terminal wizard for categorising the uncategorised long tail.

## 1. Packaging

- Root `pyproject.toml` defining one distribution, working name
  `statement-tools`, containing the three existing packages
  (`statement_parser`, `categorise`, `charts`) **unchanged in place** — no
  `src/` restructure, no import changes.
- Runtime dependencies move into `pyproject.toml` (pinned as `>=` floors, not
  `==`): pdfplumber, pandas, numpy, pypdfium2, pillow, pyyaml, plotly.
  `pikepdf` and `reportlab` are dev/test-only; keep them in
  `requirements-dev.txt` along with pytest. `requirements.txt` may remain for
  reproducible local dev but README points newcomers at `pip install .`.
- One console script, `statements`, a thin dispatcher (new module
  `statement_tools_cli.py` or similar) that maps subcommands onto the existing
  CLI mains without duplicating their argument parsing:
  - `statements parse …`        → statement_parser.cli parse
  - `statements debug-layout …` → statement_parser.cli debug-layout
  - `statements categorise …`   → categorise.cli run
  - `statements report …`       → categorise.cli report
  - `statements triage …`       → new (section 2)
  - `statements chart sankey|monthly|savings …` → charts.cli
- Acceptance: in a **fresh venv**, `pip install .` succeeds; `statements
  --help` lists all subcommands; a synthetic-fixture end-to-end run
  (parse → categorise → chart sankey) works via the installed entry point.

## 2. Interactive triage — `statements triage`

Terminal wizard for turning uncategorised descriptions into rules.

- Input: canonical CSV (`--in`) + personal rules path (`--rules`, created if
  missing). Runs categorisation in memory; groups uncategorised rows by
  description, sorted by total |amount| descending.
- Per description, display: the description, transaction count, and total
  amount. (This is the end user's own data on their own terminal — showing
  amounts is correct here, unlike agent/stdout contexts.)
- Per-item actions:
  - type a category: numbered menu of categories already present in the
    user's rules files (personal + builtin), plus free text for new ones;
    '/'-separated paths allowed
  - match type: exact (default), or contains / prefix via a shortcut
  - `t` toggle `transfer: true` on the pending rule
  - `s` skip this description
  - `q` quit and save what's been accepted so far
- On accept: append the rule to the personal rules file. Before the first
  write of a session, copy the existing file to a timestamped `.bak` backup.
- On exit: re-run categorisation and print before/after uncategorised counts.
- Implementation: stdlib only — no prompt_toolkit/questionary dependency.
  The interactive loop takes injected input/output streams (`io.TextIOBase`)
  so tests drive it with scripted input and assert on output and the
  resulting rules file. No `input()` calls that bypass the injected streams.
- Edge cases: empty uncategorised set (print that, exit 0); Ctrl-C behaves
  like `q` (save accepted rules, no partial writes); invalid menu input
  re-prompts.

## 3. README

`README.md` at repo root covering, in order:

1. What it does: bank statements (PDF via layout profiles, CSV via column
   maps) → one canonical transaction CSV → declarative categorisation rules
   → Sankey / monthly / savings charts.
2. Quickstart (5 minutes): install, parse a statement with a shipped profile,
   categorise, triage, chart. Every command shown is the `statements` form.
3. Adding a bank: the profile YAML format by example, with `statements
   debug-layout` presented as the profile-authoring tool. Link to the design
   spec for the full schema.
4. Categorisation model: builtin vs personal rules, first-match-wins,
   precedence, transfer flagging and why it matters for the Sankey.
5. **Privacy model (prominent):** everything runs locally, no network calls;
   which file classes are gitignored and why; personal rules and reports are
   local-only; a warning to check `git status` before committing if they
   modify the ignore rules. Honest note that redaction tooling
   (`redact_pdf.py`) exists for sharing statement excerpts safely.
6. Development: running tests, adding profiles, contributing.

## 4. License and repo hygiene

- `LICENSE`: MIT, current year, the repo owner's name (from git config).
- **Delete the legacy `boi_statement_parser.py`** — parity with the new
  engine was proven in Build 2; keeping it in a public repo is confusing.
  Also delete `scripts/parity_check.py` (its purpose is served) and remove
  references to both from FINDINGS.md is NOT required — FINDINGS.md is a
  historical document; leave it as is.
- Notebooks (`*.ipynb`) were never committed and stay untracked; no action.
- `CLAUDE.md` stays — it documents the privacy workflow honestly.

## Out of scope

- PyPI publishing, versioning/release automation.
- LLM-assisted categorisation suggestions.
- Any change to engine/categorisation/chart behaviour.

## Build instructions (for the implementing agent)

- **Model: `sonnet`** — README prose quality for a public audience and a
  testable interactive loop both need judgement; no need for `opus`.
- Read `CLAUDE.md` first. Hard privacy rules as in all prior builds: never
  read non-redacted PDFs, real CSV/XLSX files (including anything under
  `reports/`), `redact_terms.txt`, `category_rules.yaml` contents, or
  notebooks. The traceback rule applies: no raw input text in error messages.
- All tests green (`.venv\Scripts\python.exe -m pytest`): the pre-existing
  136 plus the new triage/dispatcher tests.
- Fresh-venv acceptance gate (section 1) must be demonstrated with observed
  output (counts/exit codes only).
- The triage wizard must NOT be exercised against real data by the agent —
  synthetic fixtures only.
- `git status --porcelain` before every commit; stop if any sensitive file
  class appears. Commit per section, referencing this spec, with the usual
  trailer:
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BfyantzNe3P9S63HWNW1K4
