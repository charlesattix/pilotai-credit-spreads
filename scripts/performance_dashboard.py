#!/usr/bin/env python3
"""Performance dashboard — self-contained HTML report with Chart.js charts.

Generates a dark-theme HTML report tracking paper-trading performance:
cumulative P&L, rolling win rate, strategy breakdown, and deviation trends.

Can be run standalone or called from the scheduler (main.py daily report slot).
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from shared.database import get_trades  # noqa: E402
from shared.deviation_tracker import get_deviation_history  # noqa: E402

logger = logging.getLogger(__name__)

CLOSED_STATUSES = {"closed_profit", "closed_loss", "closed_expiry", "closed_manual"}


# ── Data aggregation (pure, testable) ────────────────────────────────────────


def load_closed_trades(source: str = "scanner") -> List[Dict]:
    """Load closed trades from DB, sorted by exit_date ascending."""
    trades = get_trades(source=source)
    closed = [t for t in trades if t.get("status") in CLOSED_STATUSES]
    closed.sort(key=lambda t: t.get("exit_date") or "")
    return closed


def compute_cumulative_pnl(
    trades: List[Dict], account_size: float = 100_000
) -> List[Dict]:
    """Walk trades in exit_date order, returning cumulative P&L per day."""
    if not trades:
        return []

    daily: Dict[str, float] = {}
    for t in trades:
        date = (t.get("exit_date") or "")[:10]
        if not date:
            continue
        daily[date] = daily.get(date, 0) + (t.get("pnl") or 0)

    cumulative = 0.0
    result = []
    for date in sorted(daily):
        cumulative += daily[date]
        result.append({
            "date": date,
            "cumulative_pnl": round(cumulative, 2),
            "balance": round(account_size + cumulative, 2),
        })
    return result


def compute_rolling_win_rate(
    trades: List[Dict], window: int = 20
) -> List[Dict]:
    """Rolling win rate over the last *window* trades (emits once window is full)."""
    if len(trades) < window:
        return []

    result = []
    for i in range(window, len(trades) + 1):
        chunk = trades[i - window : i]
        wins = sum(1 for t in chunk if (t.get("pnl") or 0) > 0)
        last_trade = chunk[-1]
        result.append({
            "date": (last_trade.get("exit_date") or "")[:10],
            "win_rate": round(wins / window * 100, 1),
            "trade_num": i,
        })
    return result


def compute_strategy_breakdown(trades: List[Dict]) -> List[Dict]:
    """Per-strategy stats: count, wins, win_rate, total_pnl, avg_pnl."""
    by_strat: Dict[str, List[Dict]] = defaultdict(list)
    for t in trades:
        key = t.get("strategy_type") or "unknown"
        by_strat[key].append(t)

    result = []
    for strat, strades in sorted(by_strat.items()):
        wins = sum(1 for t in strades if (t.get("pnl") or 0) > 0)
        total_pnl = sum(t.get("pnl") or 0 for t in strades)
        count = len(strades)
        result.append({
            "strategy": strat,
            "count": count,
            "wins": wins,
            "win_rate": round(wins / count * 100, 1) if count else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / count, 2) if count else 0,
        })
    return result


def compute_avg_credit_comparison(trades: List[Dict]) -> Dict[str, float]:
    """Average credit per strategy type."""
    sums: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    for t in trades:
        key = t.get("strategy_type") or "unknown"
        credit = t.get("credit") or 0
        sums[key] += credit
        counts[key] += 1
    return {
        k: round(sums[k] / counts[k], 2) if counts[k] else 0
        for k in sorted(sums)
    }


# ── KPI helpers ──────────────────────────────────────────────────────────────


def _compute_kpis(trades: List[Dict], account_size: float) -> Dict[str, Any]:
    """Derive headline KPIs from closed trades."""
    if not trades:
        return {
            "total_pnl": 0, "win_rate": 0, "profit_factor": 0,
            "max_drawdown": 0, "avg_pnl": 0, "trade_count": 0,
        }

    pnls = [t.get("pnl") or 0 for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    total_pnl = sum(pnls)

    # Max drawdown from cumulative curve
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else float("inf"),
        "max_drawdown": round(max_dd, 2),
        "avg_pnl": round(total_pnl / len(pnls), 2) if pnls else 0,
        "trade_count": len(pnls),
    }


# ── CSS (reused dark theme) ──────────────────────────────────────────────────


def _css() -> str:
    return """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           background: #0d1117; color: #c9d1d9; line-height: 1.6; padding: 20px; }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { color: #58a6ff; margin-bottom: 10px; font-size: 1.8em; }
    h2 { color: #58a6ff; margin: 30px 0 15px; font-size: 1.3em;
         border-bottom: 1px solid #30363d; padding-bottom: 8px; }
    .header { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
              padding: 20px; margin-bottom: 20px; }
    .meta { color: #8b949e; font-size: 0.9em; }
    .badge { display: inline-block; padding: 3px 10px; border-radius: 12px;
             font-size: 0.8em; font-weight: 600; margin-left: 8px; }
    .badge-green { background: #1b4332; color: #3fb950; border: 1px solid #3fb950; }
    .badge-yellow { background: #3d2e00; color: #d29922; border: 1px solid #d29922; }
    .badge-red { background: #4a1c1c; color: #f85149; border: 1px solid #f85149; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px; margin: 15px 0; }
    .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                 padding: 15px; text-align: center; }
    .stat-card .value { font-size: 1.8em; font-weight: bold; }
    .stat-card .label { color: #8b949e; font-size: 0.85em; margin-top: 5px; }
    .positive { color: #3fb950; }
    .negative { color: #f85149; }
    .neutral { color: #d29922; }
    .muted { color: #8b949e; }
    table { width: 100%; border-collapse: collapse; margin: 10px 0;
            background: #161b22; border-radius: 8px; overflow: hidden; }
    th { background: #21262d; color: #8b949e; padding: 10px 12px; text-align: left;
         font-weight: 600; font-size: 0.85em; text-transform: uppercase; }
    td { padding: 8px 12px; border-top: 1px solid #21262d; font-size: 0.95em; }
    tr:hover { background: #1c2128; }
    .chart-container { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                       padding: 20px; margin: 15px 0; }
    .empty-state { text-align: center; color: #8b949e; padding: 40px; font-size: 1.1em; }
    .footer { text-align: center; color: #484f58; margin-top: 40px; padding: 20px;
              border-top: 1px solid #21262d; font-size: 0.85em; }
    """


# ── HTML generation ──────────────────────────────────────────────────────────


def generate_dashboard(
    report_date: Optional[str] = None,
    account_size: float = 100_000,
) -> str:
    """Build the full HTML dashboard string."""
    if report_date is None:
        report_date = datetime.now().strftime("%Y-%m-%d")

    trades = load_closed_trades()
    open_trades = [t for t in get_trades(source="scanner") if t.get("status") == "open"]

    kpis = _compute_kpis(trades, account_size)
    cum_pnl = compute_cumulative_pnl(trades, account_size)
    rolling_wr = compute_rolling_win_rate(trades)
    strat_breakdown = compute_strategy_breakdown(trades)
    deviation_history = get_deviation_history(days=90)

    # Days since first trade
    first_date = trades[0].get("entry_date", "")[:10] if trades else ""
    if first_date:
        try:
            days_active = (datetime.now() - datetime.strptime(first_date, "%Y-%m-%d")).days
        except ValueError:
            days_active = 0
    else:
        days_active = 0

    return _build_html(
        report_date=report_date,
        account_size=account_size,
        kpis=kpis,
        cum_pnl=cum_pnl,
        rolling_wr=rolling_wr,
        strat_breakdown=strat_breakdown,
        deviation_history=deviation_history,
        open_count=len(open_trades),
        days_active=days_active,
    )


def _build_html(
    *,
    report_date: str,
    account_size: float,
    kpis: Dict,
    cum_pnl: List[Dict],
    rolling_wr: List[Dict],
    strat_breakdown: List[Dict],
    deviation_history: List[Dict],
    open_count: int,
    days_active: int,
) -> str:
    """Assemble the HTML string from pre-computed data."""
    pnl_cls = "positive" if kpis["total_pnl"] >= 0 else "negative"
    pf_display = f"{kpis['profit_factor']:.2f}" if kpis["profit_factor"] != float("inf") else "∞"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Paper Trading Dashboard — {report_date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>{_css()}</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>Paper Trading Dashboard</h1>
    <div class="meta">
        {report_date} | {days_active} days active | {kpis['trade_count']} closed trades |
        Account: ${account_size:,.0f}
    </div>
</div>
"""

    if kpis["trade_count"] == 0:
        html += '<div class="empty-state">No closed trades yet. Dashboard will populate as trades close.</div>'
    else:
        # KPI cards
        html += f"""
<h2>Key Metrics</h2>
<div class="grid">
    <div class="stat-card">
        <div class="value {pnl_cls}">${kpis['total_pnl']:+,.0f}</div>
        <div class="label">Total P&L</div>
    </div>
    <div class="stat-card">
        <div class="value">{kpis['win_rate']:.1f}%</div>
        <div class="label">Win Rate</div>
    </div>
    <div class="stat-card">
        <div class="value">{pf_display}</div>
        <div class="label">Profit Factor</div>
    </div>
    <div class="stat-card">
        <div class="value">{open_count}</div>
        <div class="label">Open Positions</div>
    </div>
    <div class="stat-card">
        <div class="value negative">${kpis['max_drawdown']:,.0f}</div>
        <div class="label">Max Drawdown</div>
    </div>
    <div class="stat-card">
        <div class="value {pnl_cls}">${kpis['avg_pnl']:+,.0f}</div>
        <div class="label">Avg Trade P&L</div>
    </div>
</div>
"""

        # Cumulative P&L chart
        if cum_pnl:
            pnl_dates = json.dumps([p["date"] for p in cum_pnl])
            pnl_balances = json.dumps([p["balance"] for p in cum_pnl])
            html += f"""
<h2>Cumulative P&L</h2>
<div class="chart-container">
    <canvas id="pnlChart"></canvas>
</div>
<script>
new Chart(document.getElementById('pnlChart'), {{
    type: 'line',
    data: {{
        labels: {pnl_dates},
        datasets: [{{
            label: 'Balance',
            data: {pnl_balances},
            borderColor: '#58a6ff',
            backgroundColor: 'rgba(88,166,255,0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
        }}, {{
            label: 'Baseline',
            data: Array({len(cum_pnl)}).fill({account_size}),
            borderColor: '#484f58',
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ labels: {{ color: '#8b949e' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 10 }}, grid: {{ color: '#21262d' }} }},
            y: {{ ticks: {{ color: '#8b949e', callback: v => '$' + v.toLocaleString() }}, grid: {{ color: '#21262d' }} }}
        }}
    }}
}});
</script>
"""

        # Rolling win rate chart
        if rolling_wr:
            wr_labels = json.dumps([f"#{r['trade_num']}" for r in rolling_wr])
            wr_values = json.dumps([r["win_rate"] for r in rolling_wr])
            html += f"""
<h2>Rolling Win Rate (20-trade)</h2>
<div class="chart-container">
    <canvas id="wrChart"></canvas>
</div>
<script>
new Chart(document.getElementById('wrChart'), {{
    type: 'line',
    data: {{
        labels: {wr_labels},
        datasets: [{{
            label: 'Win Rate %',
            data: {wr_values},
            borderColor: '#3fb950',
            backgroundColor: 'rgba(63,185,80,0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
        }}, {{
            label: '50% Reference',
            data: Array({len(rolling_wr)}).fill(50),
            borderColor: '#d29922',
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ labels: {{ color: '#8b949e' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 10 }}, grid: {{ color: '#21262d' }} }},
            y: {{ min: 0, max: 100, ticks: {{ color: '#8b949e', callback: v => v + '%' }}, grid: {{ color: '#21262d' }} }}
        }}
    }}
}});
</script>
"""

        # Strategy breakdown table
        if strat_breakdown:
            html += """
<h2>Strategy Breakdown</h2>
<table>
    <thead>
        <tr><th>Strategy</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>Total P&L</th><th>Avg P&L</th></tr>
    </thead>
    <tbody>
"""
            for s in strat_breakdown:
                cls = "positive" if s["total_pnl"] >= 0 else "negative"
                html += f"""        <tr>
            <td>{s['strategy']}</td>
            <td>{s['count']}</td>
            <td>{s['wins']}</td>
            <td>{s['win_rate']:.1f}%</td>
            <td class="{cls}">${s['total_pnl']:+,.0f}</td>
            <td class="{cls}">${s['avg_pnl']:+,.0f}</td>
        </tr>
"""
            html += "    </tbody>\n</table>\n"

    # Deviation trend chart
    if deviation_history:
        # Reverse to chronological order
        dev_sorted = sorted(deviation_history, key=lambda d: d.get("snapshot_date", ""))
        dev_dates = json.dumps([d["snapshot_date"] for d in dev_sorted])
        dev_live_wr = json.dumps([d.get("live_win_rate") for d in dev_sorted])
        dev_bt_wr = json.dumps([d.get("bt_win_rate") for d in dev_sorted])
        html += f"""
<h2>Deviation Trend (Live vs Backtest Win Rate)</h2>
<div class="chart-container">
    <canvas id="devChart"></canvas>
</div>
<script>
new Chart(document.getElementById('devChart'), {{
    type: 'line',
    data: {{
        labels: {dev_dates},
        datasets: [{{
            label: 'Live Win Rate',
            data: {dev_live_wr},
            borderColor: '#58a6ff',
            tension: 0.3,
            pointRadius: 3,
        }}, {{
            label: 'Backtest Win Rate',
            data: {dev_bt_wr},
            borderColor: '#d29922',
            borderDash: [5, 5],
            tension: 0.3,
            pointRadius: 3,
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ labels: {{ color: '#8b949e' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }},
            y: {{ ticks: {{ color: '#8b949e', callback: v => v + '%' }}, grid: {{ color: '#21262d' }} }}
        }}
    }}
}});
</script>
"""

        # Deviation status table (latest snapshot)
        latest = dev_sorted[-1]
        status = latest.get("overall_status", "INFO")
        badge_cls = {
            "PASS": "badge-green", "WARN": "badge-yellow", "FAIL": "badge-red",
        }.get(status, "badge-yellow")

        html += f"""
<h2>Latest Deviation Snapshot
    <span class="badge {badge_cls}">{status}</span>
</h2>
<table>
    <thead>
        <tr><th>Metric</th><th>Live</th><th>Backtest</th></tr>
    </thead>
    <tbody>
        <tr><td>Trades</td><td>{latest.get('live_trades', '—')}</td><td>{latest.get('bt_trades', '—')}</td></tr>
        <tr><td>Win Rate</td><td>{_fmt_pct(latest.get('live_win_rate'))}</td><td>{_fmt_pct(latest.get('bt_win_rate'))}</td></tr>
        <tr><td>Total P&L</td><td>{_fmt_dollar(latest.get('live_pnl'))}</td><td>{_fmt_dollar(latest.get('bt_pnl'))}</td></tr>
        <tr><td>Profit Factor</td><td>{_fmt_num(latest.get('live_profit_factor'))}</td><td>{_fmt_num(latest.get('bt_profit_factor'))}</td></tr>
        <tr><td>Max Drawdown</td><td>{_fmt_pct(latest.get('live_max_dd'))}</td><td>{_fmt_pct(latest.get('bt_max_dd'))}</td></tr>
    </tbody>
</table>
"""

    html += f"""
<div class="footer">
    PilotAI Paper Trading Dashboard — {report_date}<br>
    Auto-generated. Past performance does not guarantee future results.
</div>

</div>
</body>
</html>"""

    return html


def _fmt_pct(val: Any) -> str:
    if val is None:
        return "—"
    return f"{val:.1f}%"


def _fmt_dollar(val: Any) -> str:
    if val is None:
        return "—"
    return f"${val:+,.0f}"


def _fmt_num(val: Any) -> str:
    if val is None:
        return "—"
    return f"{val:.2f}"


# ── File output ──────────────────────────────────────────────────────────────


def save_dashboard(
    report_date: Optional[str] = None,
    account_size: float = 100_000,
) -> Path:
    """Generate and write dashboard HTML to reports/ directory."""
    if report_date is None:
        report_date = datetime.now().strftime("%Y-%m-%d")

    html = generate_dashboard(report_date=report_date, account_size=account_size)

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    out_path = reports_dir / f"dashboard_{report_date}.html"
    out_path.write_text(html)
    logger.info("Dashboard written to %s", out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = save_dashboard()
    print(f"Dashboard saved: {path}")
