"""Combined overview report: page assembly only.

Reuses the three existing pure figure builders (`charts.sankey`,
`charts.monthly`, `charts.savings`) and the pure computations in
`charts.insights` unchanged; this module's only job is turning typed
values into one self-contained HTML page.

Netting runs exactly once (`net_transfers`, called from `build_overview`)
and its result feeds the Sankey, the stat tiles, the rankings/movers/
notables tables, and the health panel -- so every section agrees on what
counts as a matched transfer. Each Plotly figure is rendered as an
`to_html(full_html=False, include_plotlyjs=False)` fragment; `plotly.js`
itself is inlined exactly once via `plotly.offline.get_plotlyjs()`.

No template engine, no new dependency: string assembly plus one
handwritten CSS block (see the `dataviz` skill for the design system this
follows -- palette, mark specs, table/tile/warning styling).
"""
from __future__ import annotations

import dataclasses
import html as html_lib
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import pandas as pd
import plotly.offline

from .insights import (
    AccountCoverage,
    CategoryAmount,
    CategoryDelta,
    Health,
    MerchantAmount,
    Movers,
    NoPriorCoverage,
    Notable,
    Rankings,
    Tiles,
    health,
    movers,
    notables,
    rankings,
    stat_tiles,
)
from .monthly import build_monthly_bar
from .netting import DEFAULT_WINDOW_DAYS, NettingResult, net_transfers
from .sankey import DEFAULT_MIN_SHARE, build_sankey
from .savings import build_savings_chart

MULTI_MONTH_THRESHOLD = 2


@dataclasses.dataclass
class OverviewResult:
    html: str
    netting: NettingResult
    #: Same shape as the other chart subcommands' counts dict, for the
    #: CLI's counts-only stdout line.
    counts: Dict[str, int]


def _month_span(date_from: Date, date_to: Date) -> int:
    """Number of distinct calendar months `[date_from, date_to]` touches
    (inclusive on both ends)."""
    return (date_to.year - date_from.year) * 12 + (date_to.month - date_from.month) + 1


def _filter_range(frame: pd.DataFrame, date_from: Date, date_to: Date) -> pd.DataFrame:
    mask = frame["date"].map(lambda d: d is not None and date_from <= d <= date_to)
    return frame[mask].reset_index(drop=True)


def build_overview(
    full_frame: pd.DataFrame,
    date_from: Date,
    date_to: Date,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    generated_at: Optional[datetime] = None,
    min_share: Decimal = DEFAULT_MIN_SHARE,
) -> OverviewResult:
    """Assemble the overview page. `full_frame` is the whole categorised
    frame (already coerced to real dtypes, NOT pre-filtered to the date
    range) -- `movers` needs rows outside the range for its comparison
    window, so this function does its own range filtering rather than
    accepting an already-filtered frame. `min_share` forwards to the
    Sankey builder's small-share aggregation threshold (see
    `charts.sankey`)."""
    in_range = _filter_range(full_frame, date_from, date_to)

    netting_result = net_transfers(in_range, window_days=window_days)
    netted = netting_result.netted

    tiles = stat_tiles(netted)
    rank = rankings(netted)
    mover_result = movers(full_frame, date_from, date_to)
    notable_rows = notables(netted)
    health_result = health(netted, netting_result.unmatched)

    accounts = sorted({str(a) for a in netted["account"]}) if len(netted) else []

    span_months = _month_span(date_from, date_to)
    monthly_fragment = None
    if span_months >= MULTI_MONTH_THRESHOLD and len(netted):
        monthly_fragment = build_monthly_bar(netted).to_html(
            full_html=False, include_plotlyjs=False
        )
    savings_fragment = build_savings_chart(netted).to_html(full_html=False, include_plotlyjs=False)
    sankey_fragment = build_sankey(netted, min_share=min_share).to_html(
        full_html=False, include_plotlyjs=False
    )

    page_html = _render_page(
        date_from=date_from,
        date_to=date_to,
        accounts=accounts,
        generated_at=generated_at or datetime.now(),
        tiles=tiles,
        sankey_fragment=sankey_fragment,
        rankings_result=rank,
        movers_result=mover_result,
        monthly_fragment=monthly_fragment,
        savings_fragment=savings_fragment,
        notable_rows=notable_rows,
        health_result=health_result,
    )

    counts = {
        "total_rows": int(len(full_frame)),
        "in_range_rows": int(len(in_range)),
        "uncategorised": health_result.uncategorised_count,
        "unmatched_transfers": health_result.unmatched_transfer_count,
    }
    return OverviewResult(html=page_html, netting=netting_result, counts=counts)


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------


def _esc(text: object) -> str:
    return html_lib.escape(str(text), quote=True)


def _fmt_money(value: Decimal, currency: Optional[str]) -> str:
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    text = f"{magnitude:,.2f}"
    if currency:
        return f"{sign}{_esc(currency)}&nbsp;{text}"
    return f"{sign}{text}"


def _fmt_percent(rate: Optional[Decimal]) -> str:
    if rate is None:
        return "—"  # em dash: zero-income sentinel
    return f"{rate * 100:.1f}%"


def _fmt_date(d: Optional[Date]) -> str:
    return d.isoformat() if d is not None else "—"


# --------------------------------------------------------------------------
# Page assembly
# --------------------------------------------------------------------------


def _render_page(
    *,
    date_from: Date,
    date_to: Date,
    accounts: List[str],
    generated_at: datetime,
    tiles: Tiles,
    sankey_fragment: str,
    rankings_result: Rankings,
    movers_result,
    monthly_fragment: Optional[str],
    savings_fragment: str,
    notable_rows: List[Notable],
    health_result: Health,
) -> str:
    plotly_js = plotly.offline.get_plotlyjs()

    body = "\n".join(
        [
            _render_header(date_from, date_to, accounts, generated_at, tiles),
            _render_tiles(tiles),
            _render_sankey(sankey_fragment),
            _render_rankings_movers(rankings_result, movers_result, tiles.currency),
            _render_trends(monthly_fragment, savings_fragment),
            _render_notables(notable_rows, tiles.currency),
            _render_health(health_result, movers_result, tiles.currency),
        ]
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Spending overview: {_esc(date_from.isoformat())} to {_esc(date_to.isoformat())}</title>
<script type="text/javascript">{plotly_js}</script>
<style>{CSS}</style>
</head>
<body class="viz-root">
<main class="page">
{body}
</main>
</body>
</html>
"""


def _render_header(
    date_from: Date, date_to: Date, accounts: List[str], generated_at: datetime, tiles: Tiles
) -> str:
    accounts_text = ", ".join(_esc(a) for a in accounts) if accounts else "(none)"
    currency_note = ""
    if tiles.currency is None:
        currency_note = (
            '<p class="note">Amounts shown without a currency symbol: the rows in '
            "this range use more than one currency, or none is recorded.</p>"
        )
    return f"""<header id="header" class="section">
  <h1>Spending overview</h1>
  <p class="range">{_esc(date_from.isoformat())} to {_esc(date_to.isoformat())}</p>
  <p class="meta">Accounts: {accounts_text}</p>
  <p class="meta">Generated {_esc(generated_at.strftime("%Y-%m-%d %H:%M"))}</p>
  {currency_note}
</header>"""


def _render_tiles(tiles: Tiles) -> str:
    def tile(label: str, value_html: str) -> str:
        return f"""<div class="tile">
      <p class="tile-label">{_esc(label)}</p>
      <p class="tile-value">{value_html}</p>
    </div>"""

    tiles_html = "\n    ".join(
        [
            tile("Income", _fmt_money(tiles.income, tiles.currency)),
            tile("Spend", _fmt_money(tiles.spend, tiles.currency)),
            tile("Net", _fmt_money(tiles.net, tiles.currency)),
            tile("Savings rate", _fmt_percent(tiles.savings_rate)),
        ]
    )
    return f"""<section id="stat-tiles" class="section">
  <h2>Headline numbers</h2>
  <div class="tile-row">
    {tiles_html}
  </div>
</section>"""


def _render_sankey(sankey_fragment: str) -> str:
    return f"""<section id="sankey" class="section">
  <h2>Money flow</h2>
  <div class="figure-card">
    {sankey_fragment}
  </div>
</section>"""


def _render_rankings_movers(rankings_result: Rankings, movers_result, currency: Optional[str]) -> str:
    def category_rows(items: List[CategoryAmount]) -> str:
        if not items:
            return '<tr><td colspan="2" class="empty">No spend in range.</td></tr>'
        return "\n".join(
            f"<tr><td>{_esc(c.category)}</td><td class=\"num\">{_fmt_money(c.amount, currency)}</td></tr>"
            for c in items
        )

    def merchant_rows(items: List[MerchantAmount]) -> str:
        if not items:
            return '<tr><td colspan="2" class="empty">No spend in range.</td></tr>'
        return "\n".join(
            f"<tr><td>{_esc(m.description)}</td><td class=\"num\">{_fmt_money(m.amount, currency)}</td></tr>"
            for m in items
        )

    if isinstance(movers_result, NoPriorCoverage):
        movers_html = (
            '<p class="empty">No data in the preceding comparison window -- '
            "movers cannot be computed.</p>"
        )
    else:
        movers_html = _render_movers_table(movers_result, currency)

    return f"""<section id="rankings-movers" class="section">
  <h2>Rankings and movers</h2>
  <div class="table-row">
    <div class="table-card">
      <h3>Top categories by spend</h3>
      <table>
        <thead><tr><th>Category</th><th class="num">Spend</th></tr></thead>
        <tbody>
        {category_rows(rankings_result.top_categories)}
        </tbody>
      </table>
    </div>
    <div class="table-card">
      <h3>Top merchants by spend</h3>
      <table>
        <thead><tr><th>Merchant</th><th class="num">Spend</th></tr></thead>
        <tbody>
        {merchant_rows(rankings_result.top_merchants)}
        </tbody>
      </table>
    </div>
    <div class="table-card" id="movers">
      <h3>Movers vs preceding period</h3>
      {movers_html}
    </div>
  </div>
</section>"""


def _render_movers_table(movers_result: Movers, currency: Optional[str]) -> str:
    def delta_row(d: CategoryDelta, status: str, icon: str) -> str:
        return (
            f'<tr><td>{_esc(d.category)}</td>'
            f'<td class="num status-{status}">{icon} {_fmt_money(d.delta, currency)}</td></tr>'
        )

    up_rows = "\n".join(delta_row(d, "serious", "▲") for d in movers_result.increases)
    down_rows = "\n".join(delta_row(d, "good", "▼") for d in movers_result.decreases)
    if not up_rows:
        up_rows = '<tr><td colspan="2" class="empty">No increases.</td></tr>'
    if not down_rows:
        down_rows = '<tr><td colspan="2" class="empty">No decreases.</td></tr>'

    return f"""<p class="meta">vs. the preceding {movers_result.window_days} day(s)</p>
      <table>
        <thead><tr><th colspan="2">Spend up</th></tr></thead>
        <tbody>
        {up_rows}
        </tbody>
        <thead><tr><th colspan="2">Spend down</th></tr></thead>
        <tbody>
        {down_rows}
        </tbody>
      </table>"""


def _render_trends(monthly_fragment: Optional[str], savings_fragment: str) -> str:
    monthly_html = ""
    if monthly_fragment is not None:
        monthly_html = f"""<div class="figure-card" id="monthly-trend">
    <h3>Monthly spend by category</h3>
    {monthly_fragment}
  </div>"""
    return f"""<section id="trends" class="section">
  <h2>Trends</h2>
  {monthly_html}
  <div class="figure-card" id="savings-trend">
    <h3>Cumulative savings and balances</h3>
    {savings_fragment}
  </div>
</section>"""


def _render_notables(notable_rows: List[Notable], currency: Optional[str]) -> str:
    if not notable_rows:
        rows_html = '<tr><td colspan="5" class="empty">No notable transactions in range.</td></tr>'
    else:
        rows_html = "\n".join(
            "<tr><td>{date}</td><td>{account}</td><td>{description}</td>"
            '<td>{category}</td><td class="num">{amount}</td></tr>'.format(
                date=_esc(_fmt_date(n.date)),
                account=_esc(n.account),
                description=_esc(n.description),
                category=_esc(n.category),
                amount=_fmt_money(n.amount, currency),
            )
            for n in notable_rows
        )
    return f"""<section id="notables" class="section">
  <h2>Notable transactions</h2>
  <table>
    <thead><tr><th>Date</th><th>Account</th><th>Description</th><th>Category</th><th class="num">Amount</th></tr></thead>
    <tbody>
    {rows_html}
    </tbody>
  </table>
</section>"""


def _render_health(health_result: Health, movers_result, currency: Optional[str]) -> str:
    def status_item(label: str, value: str, is_warning: bool) -> str:
        cls = "status-warning" if is_warning else "status-neutral"
        icon = "⚠" if is_warning else "✓"
        return f'<li class="health-item {cls}"><span class="icon">{icon}</span> {_esc(label)}: {value}</li>'

    items = [
        status_item(
            "Uncategorised rows",
            f"{health_result.uncategorised_count} ({_fmt_money(health_result.uncategorised_total_abs, currency)})",
            health_result.uncategorised_count > 0,
        ),
        status_item(
            "Unmatched transfer legs",
            str(health_result.unmatched_transfer_count),
            health_result.unmatched_transfer_count > 0,
        ),
    ]
    if isinstance(movers_result, NoPriorCoverage):
        items.append(
            status_item(
                "Movers comparison",
                "skipped -- no data in the preceding window",
                True,
            )
        )

    accounts_rows = "\n".join(
        f"<tr><td>{_esc(a.account)}</td><td>{_esc(_fmt_date(a.first_date))}</td>"
        f"<td>{_esc(_fmt_date(a.last_date))}</td><td class=\"num\">{a.row_count}</td></tr>"
        for a in health_result.accounts
    ) or '<tr><td colspan="4" class="empty">No accounts in range.</td></tr>'

    return f"""<section id="data-health" class="section">
  <h2>Data health</h2>
  <ul class="health-list">
    {''.join(items)}
  </ul>
  <table>
    <thead><tr><th>Account</th><th>First date</th><th>Last date</th><th class="num">Rows</th></tr></thead>
    <tbody>
    {accounts_rows}
    </tbody>
  </table>
</section>"""


# --------------------------------------------------------------------------
# CSS -- one handwritten block, following the dataviz skill: CSS custom
# properties for surfaces/ink/status so light and dark mode share one
# source of truth; tabular figures in tables, proportional in tiles;
# status color always paired with an icon + label, never color alone.
# --------------------------------------------------------------------------

CSS = """
.viz-root {
  --surface-1:      #fcfcfb;
  --page-plane:     #f9f9f7;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --text-muted:     #898781;
  --gridline:       #e1e0d9;
  --border:         rgba(11,11,11,0.10);
  --status-good:       #0ca30c;
  --status-warning:    #fab219;
  --status-serious:    #ec835a;
  --status-critical:   #d03b3b;
}
@media (prefers-color-scheme: dark) {
  .viz-root {
    --surface-1:      #1a1a19;
    --page-plane:     #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --border:         rgba(255,255,255,0.10);
    --status-good:       #0ca30c;
    --status-warning:    #fab219;
    --status-serious:    #ec835a;
    --status-critical:   #d03b3b;
  }
}
:root[data-theme="dark"] .viz-root {
  --surface-1:      #1a1a19;
  --page-plane:     #0d0d0d;
  --text-primary:   #ffffff;
  --text-secondary: #c3c2b7;
  --gridline:       #2c2c2a;
  --border:         rgba(255,255,255,0.10);
}
:root[data-theme="light"] .viz-root {
  --surface-1:      #fcfcfb;
  --page-plane:     #f9f9f7;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --gridline:       #e1e0d9;
  --border:         rgba(11,11,11,0.10);
}

* { box-sizing: border-box; }

.viz-root {
  background: var(--page-plane);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  margin: 0;
  padding: 0;
}

.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 20px 64px;
}

.section {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px 24px;
  margin-bottom: 20px;
}

h1 { font-size: 28px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 0 0 16px; color: var(--text-primary); }
h3 { font-size: 14px; margin: 0 0 8px; color: var(--text-secondary); }

.range { font-size: 16px; color: var(--text-secondary); margin: 0 0 4px; }
.meta { font-size: 13px; color: var(--text-muted); margin: 2px 0; }
.note { font-size: 13px; color: var(--text-muted); margin: 8px 0 0; font-style: italic; }

.tile-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
}
.tile {
  background: var(--page-plane);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 14px 16px;
}
.tile-label {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0 0 6px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.tile-value {
  font-size: 28px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}

.figure-card {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 16px;
  overflow-x: auto;
}

.table-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  align-items: start;
}
.table-card {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 14px;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}
th, td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--gridline);
}
th { color: var(--text-muted); font-weight: 600; font-size: 12px; }
td.num, th.num { text-align: right; }
td.empty { color: var(--text-muted); font-style: italic; text-align: left; }

.status-good { color: var(--status-good); }
.status-warning { color: var(--status-warning); }
.status-serious { color: var(--status-serious); }
.status-critical { color: var(--status-critical); }

.health-list {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
}
.health-item {
  padding: 6px 0;
  font-size: 14px;
  border-bottom: 1px solid var(--gridline);
}
.health-item .icon { display: inline-block; width: 1.2em; text-align: center; }
.health-item.status-neutral { color: var(--text-secondary); }
.health-item.status-neutral .icon { color: var(--status-good); }
.health-item.status-warning { color: var(--text-primary); }
.health-item.status-warning .icon { color: var(--status-warning); }
"""
