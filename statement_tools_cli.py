"""Top-level `statements` console-script dispatcher.

Thin argv-forwarding wrapper around the existing package CLIs
(statement_parser, categorise, charts) plus the triage wizard. It does not
duplicate any subcommand's argument parsing -- it only recognises the
top-level command name (and, for `chart`, the chart-type name) and forwards
the remaining argv untouched to the owning module's `main`.

Mapping (see docs/superpowers/specs/2026-07-09-public-sharing-design.md §1):
    statements parse ...            -> statement_parser.cli main(["parse", ...])
    statements debug-layout ...      -> statement_parser.cli main(["debug-layout", ...])
    statements categorise ...        -> categorise.cli main(["run", ...])
    statements report ...            -> categorise.cli main(["report", ...])
    statements triage ...            -> triage.cli main([...])
    statements chart sankey|monthly|savings ...  -> charts.cli main([<type>, ...])
"""
from __future__ import annotations

import sys
from typing import List, Optional, Sequence

CHART_SUBCOMMANDS = ("sankey", "monthly", "savings")


def _usage() -> str:
    return (
        "usage: statements <command> [args...]\n"
        "\n"
        "commands:\n"
        "  parse                          extract canonical transactions from a statement\n"
        "  debug-layout                   show detected PDF layout for profile authoring\n"
        "  categorise                     apply categorisation rules to a canonical CSV\n"
        "  report                         write an uncategorised-rows report to file\n"
        "  triage                         interactive wizard for the uncategorised long tail\n"
        "  chart sankey|monthly|savings   render a chart from a categorised CSV\n"
        "\n"
        "run `statements <command> --help` for command-specific options."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        print(_usage(), file=sys.stderr)
        return 1
    if argv[0] in ("-h", "--help"):
        print(_usage())
        return 0

    command, rest = argv[0], argv[1:]

    if command == "parse":
        from statement_parser.cli import main as parser_main

        return parser_main(["parse", *rest])

    if command == "debug-layout":
        from statement_parser.cli import main as parser_main

        return parser_main(["debug-layout", *rest])

    if command == "categorise":
        from categorise.cli import main as categorise_main

        return categorise_main(["run", *rest])

    if command == "report":
        from categorise.cli import main as categorise_main

        return categorise_main(["report", *rest])

    if command == "triage":
        from triage.cli import main as triage_main

        return triage_main(rest)

    if command == "chart":
        if not rest or rest[0] in ("-h", "--help"):
            print(f"usage: statements chart {{{'|'.join(CHART_SUBCOMMANDS)}}} [args...]")
            return 0 if rest and rest[0] in ("-h", "--help") else 1

        chart_type, chart_rest = rest[0], rest[1:]
        if chart_type not in CHART_SUBCOMMANDS:
            print(
                f"error: unknown chart type {chart_type!r}; choose from "
                f"{', '.join(CHART_SUBCOMMANDS)}",
                file=sys.stderr,
            )
            return 1

        from charts.cli import main as charts_main

        return charts_main([chart_type, *chart_rest])

    print(f"error: unknown command {command!r}", file=sys.stderr)
    print(_usage(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
