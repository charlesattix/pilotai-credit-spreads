"""
html.py — Live dashboard HTML generation.

Adapts the CSS/structure from scripts/paper_trading_report.py into a
server-rendered live dashboard with auto-refresh and status indicators.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .data import BACKTEST_EXPECTATIONS, STARTING_EQUITY

VICTORY_WIN_RATE = 70.0
VICTORY_MAX_DD   = 20.0

# ---------------------------------------------------------------------------
# CSS — extended from paper_trading_report.py with live-dashboard additions
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 'Helvetica Neue', Arial, sans-serif;
    background: #f8fafc;
    color: #1e293b;
    font-size: 14px;
    line-height: 1.5;
}

/* ── Top status bar ── */
.top-bar {
    background: #0f172a;
    color: #94a3b8;
    font-size: 12px;
    padding: 8px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
}
.top-bar .brand { color: #f8fafc; font-weight: 700; letter-spacing: -0.3px; }
.top-bar .live-dot {
    display: inline-block;
    width: 7px; height: 7px;
    background: #22c55e;
    border-radius: 50%;
    margin-right: 5px;
    animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
.top-bar .refresh-info { display: flex; align-items: center; gap: 12px; }
.top-bar a.refresh-btn {
    color: #60a5fa; text-decoration: none; font-weight: 600;
    padding: 3px 10px; border: 1px solid #1e40af; border-radius: 5px;
    transition: background 0.15s;
}
.top-bar a.refresh-btn:hover { background: #1e3a5f; }

.page-wrapper { max-width: 1400px; margin: 0 auto; padding: 28px 24px 64px; }

/* ── Page header ── */
.header { margin-bottom: 28px; }
.header h1 {
    font-size: 26px; font-weight: 700; color: #0f172a; letter-spacing: -0.5px;
}
.header .subtitle { color: #64748b; font-size: 13px; margin-top: 6px; }
.header .subtitle b { color: #334155; }

/* ── Summary strip ── */
.summary-strip {
    display: flex; gap: 16px; flex-wrap: wrap;
    margin-bottom: 28px;
}
.summary-chip {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 10px 16px; flex: 1; min-width: 140px;
}
.summary-chip .chip-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.6px; color: #94a3b8;
}
.summary-chip .chip-val {
    font-size: 20px; font-weight: 700; color: #0f172a; margin-top: 2px;
}
.summary-chip .chip-val.up   { color: #059669; }
.summary-chip .chip-val.down { color: #dc2626; }

/* ── Section ── */
.section { margin-bottom: 36px; }
.section-title {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.8px; color: #94a3b8;
    margin-bottom: 14px; padding-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
}

/* ── Experiment cards ── */
.exp-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
    gap: 18px;
}
.exp-card {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px 22px 18px;
    position: relative;
    overflow: hidden;
    transition: box-shadow 0.15s;
}
.exp-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.07); }
.exp-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 3px;
}
.exp-card.color-0::before { background: #2563eb; }
.exp-card.color-1::before { background: #7c3aed; }
.exp-card.color-2::before { background: #0891b2; }
.exp-card.color-3::before { background: #d97706; }

.exp-card-header {
    display: flex; justify-content: space-between;
    align-items: flex-start; margin-bottom: 14px;
}
.exp-id   { font-size: 11px; font-weight: 700; color: #64748b;
            text-transform: uppercase; letter-spacing: 0.5px; }
.exp-name { font-size: 17px; font-weight: 700; color: #0f172a; margin-top: 2px; }
.exp-meta { font-size: 12px; color: #94a3b8; margin-top: 4px; }

.metric-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
    margin-bottom: 14px;
}
.metric-label {
    font-size: 10px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.6px; color: #94a3b8;
}
.metric-value {
    font-size: 21px; font-weight: 700; color: #0f172a;
    margin-top: 1px; line-height: 1.2;
}
.metric-value.up      { color: #059669; }
.metric-value.down    { color: #dc2626; }
.metric-value.neutral { color: #334155; }
.metric-sub { font-size: 11px; color: #94a3b8; margin-top: 1px; }

/* ── Badges ── */
.badge {
    display: inline-block; padding: 2px 8px;
    border-radius: 20px; font-size: 11px; font-weight: 700;
}
.badge-green  { background: #dcfce7; color: #166534; }
.badge-yellow { background: #fef9c3; color: #854d0e; }
.badge-red    { background: #fee2e2; color: #991b1b; }
.badge-gray   { background: #f1f5f9; color: #64748b; }
.badge-blue   { background: #dbeafe; color: #1e40af; }

/* ── Status bar ── */
.status-bar {
    padding: 7px 12px; border-radius: 7px; font-size: 12px; font-weight: 600;
    display: flex; align-items: center; gap: 6px; margin-top: 12px;
}
.status-pass    { background: #dcfce7; color: #166534; }
.status-pending { background: #f1f5f9; color: #64748b; }
.status-warn    { background: #fef9c3; color: #854d0e; }

/* ── Tables ── */
.table-wrap {
    background: #fff; border: 1px solid #e2e8f0;
    border-radius: 12px; overflow: hidden; margin-bottom: 16px;
}
.table-header {
    padding: 12px 18px; border-bottom: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; align-items: center;
}
.table-header-title { font-size: 14px; font-weight: 700; color: #0f172a; }
.table-header-sub   { font-size: 12px; color: #94a3b8; }

table { border-collapse: collapse; width: 100%; font-size: 13px; }
th {
    background: #f8fafc; color: #475569; text-align: left;
    padding: 9px 14px; font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.5px;
    border-bottom: 1px solid #e2e8f0;
}
td { padding: 9px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafafa; }
.pnl-up   { color: #059669; font-weight: 600; }
.pnl-down { color: #dc2626; font-weight: 600; }
.strategy-pill {
    display: inline-block; padding: 1px 7px; border-radius: 4px;
    font-size: 10px; font-weight: 600; background: #f1f5f9; color: #475569;
}
.no-data {
    padding: 28px 18px; color: #94a3b8; font-size: 13px; text-align: center;
}

/* ── Backtest row ── */
.bt-row { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 4px; }
.bt-item { flex: 1; min-width: 100px; }
.bt-label { font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
.bt-val   { font-size: 13px; font-weight: 600; color: #334155; margin-top: 1px; }
.bt-val.up { color: #059669; }

/* ── Ticker badge ── */
.ticker-badge {
    background: #0f172a; color: #f8fafc; font-size: 11px; font-weight: 700;
    padding: 2px 8px; border-radius: 4px; letter-spacing: 0.5px;
}
.ticker-badge.ibit { background: #d97706; }

.card-divider { border: none; border-top: 1px solid #f1f5f9; margin: 12px 0; }

/* ── Victory grid ── */
.victory-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
}
.victory-card {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 16px 18px;
}
.victory-exp { font-size: 11px; font-weight: 700; color: #64748b;
               text-transform: uppercase; letter-spacing: 0.5px; }
.victory-name { font-size: 14px; font-weight: 700; color: #0f172a; margin: 2px 0 10px; }

/* ── Footer ── */
.footer {
    margin-top: 48px; padding-top: 16px; border-top: 1px solid #e2e8f0;
    font-size: 11px; color: #94a3b8;
    display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
}

/* ── Responsive ── */
@media (max-width: 768px) {
    .page-wrapper { padding: 16px 14px 48px; }
    .exp-grid { grid-template-columns: 1fr; }
    .summary-strip { gap: 10px; }
    .top-bar { font-size: 11px; }
    .header h1 { font-size: 22px; }
    table { font-size: 12px; }
    th, td { padding: 7px 10px; }
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_pnl(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}${abs(val):,.2f}" if val < 0 else f"{sign}${val:,.2f}"


def _fmt_pct(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def _pnl_cls(val: float) -> str:
    return "up" if val > 0 else ("down" if val < 0 else "neutral")


def _days_live(live_since: str) -> str:
    try:
        d = datetime.strptime(live_since[:10], "%Y-%m-%d")
        delta = (datetime.utcnow() - d).days
        return f"{delta}d"
    except Exception:
        return "—"


def _wr_badge(win_rate: float, count: int) -> str:
    if count == 0:
        return '<span class="badge badge-gray">No trades</span>'
    if win_rate >= VICTORY_WIN_RATE:
        return f'<span class="badge badge-green">{win_rate:.1f}%</span>'
    if win_rate >= 50:
        return f'<span class="badge badge-yellow">{win_rate:.1f}%</span>'
    return f'<span class="badge badge-red">{win_rate:.1f}%</span>'


def _dd_badge(dd_pct: float, count: int) -> str:
    if count == 0:
        return '<span class="badge badge-gray">—</span>'
    if dd_pct <= VICTORY_MAX_DD:
        return f'<span class="badge badge-green">-{dd_pct:.1f}%</span>'
    if dd_pct <= 30:
        return f'<span class="badge badge-yellow">-{dd_pct:.1f}%</span>'
    return f'<span class="badge badge-red">-{dd_pct:.1f}%</span>'


def _victory_status(s: dict) -> tuple[str, str]:
    if s["total_closed"] == 0:
        return "Awaiting Trades", "status-pending"
    wr_ok = s["win_rate"] >= VICTORY_WIN_RATE
    dd_ok = s["max_dd"] < VICTORY_MAX_DD
    if wr_ok and dd_ok:
        return "On Track ✓", "status-pass"
    failing = []
    if not wr_ok:
        failing.append(f"WR {s['win_rate']:.1f}% < {VICTORY_WIN_RATE:.0f}%")
    if not dd_ok:
        failing.append(f"DD -{s['max_dd']:.1f}%")
    return f"⚠ {', '.join(failing)}", "status-warn"


def _ticker_badge(ticker: str) -> str:
    cls = "ibit" if ticker.upper() == "IBIT" else ""
    return f'<span class="ticker-badge {cls}">{ticker}</span>'


def _bt_panel(exp_id: str) -> str:
    bt = BACKTEST_EXPECTATIONS.get(exp_id, {})
    if not bt or all(v is None for v in bt.values()):
        return '<span style="color:#94a3b8;font-size:12px">BT expectations: TBD</span>'
    parts = ['<div class="bt-row">']
    if bt.get("avg_return") is not None:
        parts.append(f'<div class="bt-item"><div class="bt-label">BT Avg / yr</div>'
                     f'<div class="bt-val up">+{bt["avg_return"]:.1f}%</div></div>')
    if bt.get("max_dd") is not None:
        parts.append(f'<div class="bt-item"><div class="bt-label">BT Max DD</div>'
                     f'<div class="bt-val">{bt["max_dd"]:.1f}%</div></div>')
    if bt.get("robust") is not None:
        parts.append(f'<div class="bt-item"><div class="bt-label">Robust</div>'
                     f'<div class="bt-val">{bt["robust"]:.3f}</div></div>')
    parts.append('</div>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------

def _exp_card(s: dict, idx: int) -> str:
    color = f"color-{idx % 4}"
    status_txt, status_cls = _victory_status(s)
    days_live = _days_live(s["live_since"])
    pnl_cls   = _pnl_cls(s["total_pnl"])
    pnl_pct   = s["total_pnl"] / STARTING_EQUITY * 100
    pnl_disp  = _fmt_pnl(s["total_pnl"]) if s["total_closed"] > 0 else "—"
    pnl_pct_disp = _fmt_pct(pnl_pct) if s["total_closed"] > 0 else ""
    avg_disp  = _fmt_pnl(s["avg_pnl"]) if s["total_closed"] > 0 else "—"
    avg_cls   = _pnl_cls(s["avg_pnl"])
    wk_badge  = (f'<span class="badge badge-blue">{s["trades_week"]} this week</span>'
                 if s["trades_week"] > 0
                 else '<span class="badge badge-gray">0 this week</span>')
    err_html  = (f'<p style="color:#94a3b8;font-size:11px;margin-bottom:8px">ℹ {s["error"]}</p>'
                 if s.get("error") else "")

    return f"""
<div class="exp-card {color}">
  <div class="exp-card-header">
    <div>
      <div class="exp-id">{s['id']}</div>
      <div class="exp-name">{s['name']}</div>
      <div class="exp-meta">
        {_ticker_badge(s['ticker'])}
        &nbsp;by <b>{s['creator']}</b>
        &nbsp;&bull;&nbsp;Live {days_live}
        &nbsp;&bull;&nbsp;since {s['live_since']}
      </div>
    </div>
  </div>
  {err_html}
  <div class="metric-grid">
    <div>
      <div class="metric-label">Total P&L</div>
      <div class="metric-value {pnl_cls}">{pnl_disp}</div>
      <div class="metric-sub">{pnl_pct_disp}</div>
    </div>
    <div>
      <div class="metric-label">Closed Trades</div>
      <div class="metric-value neutral">{s['total_closed']}</div>
      <div class="metric-sub">{s['wins']}W / {s['losses']}L</div>
    </div>
    <div>
      <div class="metric-label">Win Rate</div>
      <div class="metric-value" style="font-size:15px;padding-top:3px">{_wr_badge(s['win_rate'], s['total_closed'])}</div>
    </div>
    <div>
      <div class="metric-label">Max Drawdown</div>
      <div class="metric-value" style="font-size:15px;padding-top:3px">{_dd_badge(s['max_dd'], s['total_closed'])}</div>
    </div>
    <div>
      <div class="metric-label">Open Positions</div>
      <div class="metric-value neutral">{s['open_count']}</div>
    </div>
    <div>
      <div class="metric-label">Avg P&L / Trade</div>
      <div class="metric-value {avg_cls}" style="font-size:16px">{avg_disp}</div>
    </div>
  </div>
  <div style="margin-bottom:10px">{wk_badge}</div>
  <hr class="card-divider">
  <div style="margin-bottom:4px">
    <div class="metric-label" style="margin-bottom:6px">Backtest Expectations</div>
    {_bt_panel(s['id'])}
  </div>
  <div class="status-bar {status_cls}">{status_txt}</div>
</div>"""


def _comparison_table(all_stats: list[dict]) -> str:
    rows = []
    for s in all_stats:
        if s["total_closed"] == 0:
            pnl_h = avg_h = '<span style="color:#94a3b8">—</span>'
            wr_h = dd_h  = '<span style="color:#94a3b8">—</span>'
        else:
            pc  = _pnl_cls(s["total_pnl"])
            pct = s["total_pnl"] / STARTING_EQUITY * 100
            pnl_h = (f'<span class="pnl-{pc}">{_fmt_pnl(s["total_pnl"])}</span>'
                     f'<span style="color:#94a3b8;font-size:11px"> ({_fmt_pct(pct)})</span>')
            wr_h = _wr_badge(s["win_rate"], s["total_closed"])
            dd_h = _dd_badge(s["max_dd"], s["total_closed"])
            ac   = _pnl_cls(s["avg_pnl"])
            avg_h = f'<span class="pnl-{ac}">{_fmt_pnl(s["avg_pnl"])}</span>'

        bt  = BACKTEST_EXPECTATIONS.get(s["id"], {})
        bt_r = f'+{bt["avg_return"]:.1f}%' if bt.get("avg_return") else "TBD"
        stxt, scls = _victory_status(s)

        rows.append(f"""
  <tr>
    <td style="font-weight:700">{s['id']}
      <span style="font-size:10px;color:#94a3b8;display:block">{s['name']}</span>
    </td>
    <td>{_ticker_badge(s['ticker'])}</td>
    <td>{s['total_closed']}</td>
    <td>{pnl_h}</td>
    <td>{wr_h}</td>
    <td>{dd_h}</td>
    <td>{s['open_count']}</td>
    <td>{avg_h}</td>
    <td style="color:#64748b;font-size:12px">{s['trades_week']}</td>
    <td style="color:#64748b;font-size:12px">{bt_r}</td>
    <td><span class="status-bar {scls}" style="padding:4px 10px;margin:0;display:inline-flex">{stxt}</span></td>
  </tr>""")

    return f"""
<div class="table-wrap">
<table>
  <thead><tr>
    <th>Experiment</th><th>Ticker</th><th>Closed</th>
    <th>Total P&L</th><th>Win Rate</th><th>Max DD</th>
    <th>Open</th><th>Avg/Trade</th><th>This Wk</th>
    <th>BT Expect</th><th>Status</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
</div>"""


def _open_positions_section(all_stats: list[dict]) -> str:
    any_open = any(s.get("open_trades") for s in all_stats)
    if not any_open:
        return '<div class="no-data" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px">No open positions across any experiment.</div>'

    parts = []
    for s in all_stats:
        open_trades = s.get("open_trades", [])
        if not open_trades:
            continue
        parts.append(f"""
<div class="table-wrap">
  <div class="table-header">
    <div class="table-header-title">{s['id']} — {s['name']}</div>
    <div class="table-header-sub">{len(open_trades)} open &nbsp; {_ticker_badge(s['ticker'])}</div>
  </div>
  <table>
    <tr><th>Entry</th><th>Ticker</th><th>Strategy</th>
        <th>Strikes</th><th>Expiry</th><th>Contracts</th><th>Credit</th></tr>""")
        for t in open_trades:
            ss = t.get("short_strike") or 0
            ls = t.get("long_strike") or 0
            st = (t.get("strategy_type") or "—").replace("_", " ").title()
            parts.append(f"""
    <tr>
      <td>{str(t.get("entry_date") or "—")[:10]}</td>
      <td><b>{t.get("ticker","?")}</b></td>
      <td><span class="strategy-pill">{st}</span></td>
      <td style="font-size:12px;color:#64748b">${ss:.0f}/${ls:.0f}</td>
      <td style="font-size:12px;color:#64748b">{str(t.get("expiration") or "—")[:10]}</td>
      <td style="text-align:center">{t.get("contracts",1) or 1}</td>
      <td>${float(t.get("credit") or 0):.2f}</td>
    </tr>""")
        parts.append("</table></div>")
    return "\n".join(parts)


def _recent_trades_section(all_stats: list[dict]) -> str:
    parts = []
    for s in all_stats:
        trades = s.get("recent_trades", [])
        parts.append(f"""
<div class="table-wrap">
  <div class="table-header">
    <div class="table-header-title">{s['id']} — {s['name']}</div>
    <div class="table-header-sub">{_ticker_badge(s['ticker'])}</div>
  </div>""")
        if not trades:
            parts.append(f'<div class="no-data">{s.get("error") or "No closed trades yet"}</div>')
        else:
            parts.append("""<table>
    <tr><th>Exit Date</th><th>Ticker</th><th>Strategy</th>
        <th>Strikes</th><th>Contracts</th><th>P&L</th><th>Exit Reason</th></tr>""")
            for t in trades:
                pnl = float(t.get("pnl") or 0)
                pc  = "pnl-up" if pnl > 0 else "pnl-down"
                ss  = t.get("short_strike") or 0
                ls  = t.get("long_strike") or 0
                st  = (t.get("strategy_type") or "—").replace("_", " ").title()
                rs  = (t.get("exit_reason") or "—").replace("_", " ").title()
                parts.append(f"""
    <tr>
      <td>{str(t.get("exit_date") or "—")[:10]}</td>
      <td><b>{t.get("ticker","?")}</b></td>
      <td><span class="strategy-pill">{st}</span></td>
      <td style="font-size:12px;color:#64748b">${ss:.0f}/${ls:.0f}</td>
      <td style="text-align:center">{t.get("contracts",1) or 1}</td>
      <td class="{pc}">{_fmt_pnl(pnl)}</td>
      <td style="font-size:12px;color:#64748b">{rs}</td>
    </tr>""")
            parts.append("</table>")
        parts.append("</div>")
    return "\n".join(parts)


def _strategy_breakdown_section(all_stats: list[dict]) -> str:
    rows = []
    for s in all_stats:
        for st_name, d in sorted(s.get("strategy_breakdown", {}).items()):
            wr  = d["wins"] / d["count"] * 100 if d["count"] else 0
            pc  = "pnl-up" if d["pnl"] >= 0 else "pnl-down"
            rows.append(f"""
  <tr>
    <td style="color:#64748b;font-size:12px">{s['id']}</td>
    <td><span class="strategy-pill">{st_name}</span></td>
    <td>{d['count']}</td>
    <td>{d['wins']}</td>
    <td>{wr:.1f}%</td>
    <td class="{pc}">{_fmt_pnl(d['pnl'])}</td>
  </tr>""")
    if not rows:
        return '<div class="no-data" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px">No closed trades to break down yet.</div>'
    return f"""
<div class="table-wrap"><table>
  <thead><tr>
    <th>Experiment</th><th>Strategy</th><th>Trades</th>
    <th>Wins</th><th>Win Rate</th><th>Total P&L</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table></div>"""


def _victory_section(all_stats: list[dict]) -> str:
    """Per-experiment victory condition cards."""
    cards = []
    for s in all_stats:
        stxt, scls = _victory_status(s)
        wr_h = _wr_badge(s["win_rate"], s["total_closed"])
        dd_h = _dd_badge(s["max_dd"], s["total_closed"])
        cards.append(f"""
<div class="victory-card">
  <div class="victory-exp">{s['id']}</div>
  <div class="victory-name">{s['name']}</div>
  <table style="font-size:12px;width:auto">
    <tr>
      <td style="color:#94a3b8;padding:3px 12px 3px 0">Win Rate (&gt;70%)</td>
      <td>{wr_h}</td>
    </tr>
    <tr>
      <td style="color:#94a3b8;padding:3px 12px 3px 0">Max DD (&lt;20%)</td>
      <td>{dd_h}</td>
    </tr>
  </table>
  <div class="status-bar {scls}" style="margin-top:10px">{stxt}</div>
</div>""")
    return f'<div class="victory-grid">{"".join(cards)}</div>'


def _summary_strip(all_stats: list[dict]) -> str:
    total_pnl    = sum(s["total_pnl"]    for s in all_stats)
    total_closed = sum(s["total_closed"] for s in all_stats)
    total_open   = sum(s["open_count"]   for s in all_stats)
    total_wins   = sum(s["wins"]         for s in all_stats)
    combined_wr  = (total_wins / total_closed * 100) if total_closed else 0.0
    pnl_pct      = total_pnl / STARTING_EQUITY * 100
    pnl_cls      = _pnl_cls(total_pnl)

    return f"""
<div class="summary-strip">
  <div class="summary-chip">
    <div class="chip-label">Combined P&L</div>
    <div class="chip-val {pnl_cls}">{_fmt_pnl(total_pnl)}</div>
    <div style="font-size:11px;color:#94a3b8">{_fmt_pct(pnl_pct)} of $100K</div>
  </div>
  <div class="summary-chip">
    <div class="chip-label">Total Closed</div>
    <div class="chip-val neutral">{total_closed}</div>
    <div style="font-size:11px;color:#94a3b8">{total_wins}W / {total_closed - total_wins}L</div>
  </div>
  <div class="summary-chip">
    <div class="chip-label">Combined Win Rate</div>
    <div class="chip-val {'up' if combined_wr >= VICTORY_WIN_RATE else ('neutral' if combined_wr >= 50 else 'down')}">{combined_wr:.1f}%</div>
    <div style="font-size:11px;color:#94a3b8">target &gt;70%</div>
  </div>
  <div class="summary-chip">
    <div class="chip-label">Open Positions</div>
    <div class="chip-val neutral">{total_open}</div>
    <div style="font-size:11px;color:#94a3b8">across {len(all_stats)} experiments</div>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Auto-refresh JavaScript
# ---------------------------------------------------------------------------

_JS = """
<script>
(function() {
  var INTERVAL = 300; // seconds
  var remaining = INTERVAL;
  var el = document.getElementById('countdown');
  var bar = document.getElementById('refresh-bar');
  function tick() {
    remaining--;
    if (remaining <= 0) { window.location.reload(); return; }
    if (el) el.textContent = remaining + 's';
    if (bar) bar.style.width = ((INTERVAL - remaining) / INTERVAL * 100) + '%';
    setTimeout(tick, 1000);
  }
  setTimeout(tick, 1000);
  // R key forces refresh
  document.addEventListener('keydown', function(e) {
    if (e.key === 'r' || e.key === 'R') window.location.reload();
  });
})();
</script>
"""

# ---------------------------------------------------------------------------
# Full page
# ---------------------------------------------------------------------------

def render_dashboard(all_stats: list[dict]) -> str:
    now_utc  = datetime.now(timezone.utc)
    now_str  = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    date_str = now_utc.strftime("%Y-%m-%d")
    total_exp  = len(all_stats)
    total_open = sum(s["open_count"] for s in all_stats)
    total_closed = sum(s["total_closed"] for s in all_stats)
    cards_html = "\n".join(_exp_card(s, i) for i, s in enumerate(all_stats))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PilotAI Paper Trading Dashboard</title>
  <style>{_CSS}</style>
</head>
<body>

<!-- ── Top status bar ── -->
<div class="top-bar">
  <div>
    <span class="brand">PilotAI</span>
    &nbsp;&nbsp;
    <span class="live-dot"></span>
    <span>Live Paper Trading</span>
    &nbsp;&bull;&nbsp;
    <span>{total_exp} experiments &bull; {total_closed} closed &bull; {total_open} open</span>
  </div>
  <div class="refresh-info">
    <span>Updated {now_str}</span>
    <span style="color:#475569">Auto-refresh in <span id="countdown">300s</span></span>
    <a class="refresh-btn" href="/">↻ Refresh</a>
  </div>
</div>

<!-- ── Refresh progress bar ── -->
<div style="height:2px;background:#1e293b">
  <div id="refresh-bar" style="height:100%;width:0%;background:#3b82f6;transition:width 1s linear"></div>
</div>

<div class="page-wrapper">

  <!-- ── Header ── -->
  <div class="header">
    <h1>Paper Trading Dashboard</h1>
    <p class="subtitle">
      <b>PilotAI Credit Spreads</b>
      &bull; {date_str}
      &bull; 8-week gate: Mar 16 → May 11, 2026
      &bull; Press <kbd style="background:#f1f5f9;padding:1px 5px;border-radius:3px;border:1px solid #e2e8f0">R</kbd> to refresh
    </p>
  </div>

  <!-- ── Summary strip ── -->
  {_summary_strip(all_stats)}

  <!-- ── Experiment Cards ── -->
  <div class="section">
    <div class="section-title">Live Experiments</div>
    <div class="exp-grid">{cards_html}</div>
  </div>

  <!-- ── Comparison table ── -->
  <div class="section">
    <div class="section-title">Side-by-Side Comparison</div>
    {_comparison_table(all_stats)}
  </div>

  <!-- ── Open Positions ── -->
  <div class="section">
    <div class="section-title">Open Positions</div>
    {_open_positions_section(all_stats)}
  </div>

  <!-- ── Strategy Breakdown ── -->
  <div class="section">
    <div class="section-title">Strategy Breakdown</div>
    {_strategy_breakdown_section(all_stats)}
  </div>

  <!-- ── Recent Trades ── -->
  <div class="section">
    <div class="section-title">Recent Closed Trades (last 10 per experiment)</div>
    {_recent_trades_section(all_stats)}
  </div>

  <!-- ── Victory Conditions ── -->
  <div class="section">
    <div class="section-title">Victory Conditions — 8-week gate (Mar 16 → May 11, 2026)</div>
    {_victory_section(all_stats)}
  </div>

  <!-- ── Footer ── -->
  <div class="footer">
    <span>PilotAI Credit Spreads &bull; Paper Trading Dashboard</span>
    <span>Generated {now_str}</span>
  </div>

</div>

{_JS}
</body>
</html>"""
