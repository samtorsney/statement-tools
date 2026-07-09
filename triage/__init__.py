"""Interactive triage wizard: turns uncategorised canonical-CSV descriptions
into personal categorisation rules via a stdlib-only terminal loop.

See docs/superpowers/specs/2026-07-09-public-sharing-design.md §2 for the
design this package implements. The interactive loop (``wizard.py``) takes
injected input/output streams so it can be driven entirely by tests with
scripted streams and synthetic fixtures -- it must never be run by an
automated agent against real data.
"""
