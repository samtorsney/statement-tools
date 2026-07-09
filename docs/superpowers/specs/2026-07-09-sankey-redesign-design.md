# Design: Sankey redesign — readability and outflow correctness

*Status: approved 2026-07-09 (diagnosis and fix list validated in conversation
against a synthetic render with the real data's structural shape: 96 nodes,
~30 phantom leaves, invisible unpaired transfers). Build 7; touches
`charts/sankey.py` + CLI + tests only. The overview page inherits every fix
because it reuses the builder.*

## Problems being fixed (ranked)

1. **Phantom `(none)` leaves**: every parent category currently gets a
   4th-layer subcategory node, inventing `(none)` when no subcategory exists.
2. **No small-share aggregation**: sub-1% categories each get a node and a
   hairline ribbon (22 of 36 parents in the real data).
3. **Unpaired transfers are invisible — a correctness bug**: the builder only
   draws account→account ribbons for *paired* transfers and silently drops
   unpaired legs, so drawn outflow ≠ actual outflow.
4. **Meaningless color**: default palette cycles per node; links uniform gray.
5. **Bare labels, unsorted nodes, fixed height.**

## Required behaviour

### Layers and node construction

- Layers: income sources → accounts → parent categories → subcategories.
- A parent with **no subcategory rows terminates at the category layer** —
  no `(none)` nodes, ever.
- A parent whose subcategory rows exist flows to its subcategory leaves;
  rows of that parent *without* a subcategory flow to an implicit leaf named
  after the parent only if needed to conserve flow — otherwise terminate at
  the parent.

### Small-share aggregation

- Parent categories whose |spend| share of total non-transfer spend is below
  `min_share` (default **0.01**) merge into one **"Other"** parent node.
- Within a parent, subcategories below `min_share_sub` (default **0.005** of
  total spend) fold back into the parent (no leaf).
- Same rule applied to income sources (below `min_share` → "Other income").
- CLI: `--min-share` knob on `chart sankey` and `chart overview`, forwarded
  to the builder; defaults as above.

### Unpaired transfers

- Unpaired transfer legs aggregate into **one** node, "Transfers
  (unmatched)", at the parent-category layer: negative legs flow
  account → node; positive legs flow node → account (or as income-side
  inflow, whichever keeps the layout acyclic — pick one, implement
  consistently, and document it in the module docstring).
- Person/payee names must never become nodes.
- **Flow conservation test**: total ribbon value leaving the account layer ==
  non-transfer spend + |unmatched negative transfer legs| (and symmetrically
  for inflow). This is the regression test for problem 3.

### Color and labels (per the dataviz skill)

- One hue per parent category from a categorical palette, assigned in
  size order for stability; subcategory nodes inherit a lighter tint of
  their parent's hue; links tinted by their source node at low alpha;
  account nodes neutral gray; income family a single distinct hue;
  "(uncategorised)" and "Transfers (unmatched)" in warning styling.
- Node labels include compactly formatted amounts (e.g. `Groceries · 7.0k`,
  currency symbol when the frame's currency is uniform).
- Nodes sorted by size (descending) within each layer before building the
  figure so plotly's layout follows the order.
- Figure height computed from the maximum per-layer node count (with a
  floor), instead of one fixed height.

### Compatibility

- `build_sankey(frame)` keeps its signature with `min_share` /
  `min_share_sub` as keyword arguments with defaults — existing callers
  (overview) keep working and may pass the knob through.
- No change to netting, monthly, savings, insights.

## Testing

- Unit tests on the aggregation: threshold merging (parents and
  subcategories), no-`(none)`-labels invariant (assert no node label equals
  or contains "(none)"), person names absent from labels, "Other" appears
  only when something merged.
- **Flow conservation test** as specified above.
- A structural fixture generator `tests/fixtures/make_sankey_frame.py`
  producing a synthetic categorised frame with the problematic shape
  (many parents, long tail, person-name transfer subcategories, paired
  top-ups across two accounts, uncategorised rows) — used by the tests and
  by the visual gate.
- Node-count bound test: with defaults on the structural fixture, total
  node count must come out under 40 (vs 96 today).
- **Visual gate** (not CI; part of this build's verification): render the
  structural fixture through the OLD builder (git stash or pre-change
  commit) and the NEW builder to PNGs via kaleido, look at both, and confirm
  the new one is materially cleaner: no phantom leaves, no hairline haze,
  visible "Other" and "Transfers (unmatched)" nodes, coherent color.
  Save both PNGs to the scratchpad and report their paths.
- kaleido: add to `requirements-dev.txt` (dev/test only, not runtime).

## Out of scope

- Interactive filtering/drill-down, animation, node dragging persistence.
- Changes to categorisation or netting semantics.

## Build instructions (for the implementing agent)

- **Model: `sonnet`**. Load the `dataviz` skill (Skill tool) BEFORE writing
  any color/label/layout code.
- Read `CLAUDE.md` first; standing privacy rules and the traceback rule
  apply. Never open files under `reports/`.
- All tests green: `.venv\Scripts\python.exe -m pytest` (204 pre-existing +
  new; some existing sankey tests will legitimately change — update them to
  the new invariants rather than deleting).
- Final smoke run on real data, counts-only stdout: regenerate
  `reports/sankey.html` and `reports/overview.html` for 2025-01-01..2025-12-31.
- `git status --porcelain` before every commit; STOP if any sensitive file
  class appears trackable. Do NOT push. Usual trailer:
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BfyantzNe3P9S63HWNW1K4
