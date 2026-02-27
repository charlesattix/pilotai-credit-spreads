#!/usr/bin/env python3
"""
generate_report.py — Generate an HTML backtest report.

Runs a fresh backtest with the best leaderboard params (or provided config),
then generates a self-contained HTML report with equity curves, per-year
tables, strategy breakdowns, and configuration details.

Usage:
    python3 scripts/generate_report.py                          # use best leaderboard params
    python3 scripts/generate_report.py --strategies credit_spread
    python3 scripts/generate_report.py --config configs/best.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)


def run_report_backtest(
    strategies_config: Dict[str, Dict],
    tickers: List[str],
    years: List[int],
    capital: float = 100_000,
) -> Dict:
    """Run a full backtest and return results."""
    from scripts.run_optimization import run_full
    return run_full(strategies_config, years, tickers, capital)


def generate_html(
    results: Dict,
    strategies_config: Dict[str, Dict],
    tickers: List[str],
    years: List[int],
    note: str = "",
) -> str:
    """Generate a self-contained HTML report."""
    combined = results.get("combined", {})
    yearly = results.get("yearly", {})
    per_strategy = results.get("per_strategy", {})
    equity_curve = combined.get("equity_curve", [])
    monthly_pnl = combined.get("monthly_pnl", {})
    trades = results.get("trades", [])

    # Equity curve data for chart
    eq_dates = [p["date"] for p in equity_curve]
    eq_values = [p["equity"] for p in equity_curve]

    # Monthly returns heatmap data
    monthly_data = {}
    for key, val in monthly_pnl.items():
        monthly_data[key] = val.get("pnl", 0)

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report — {datetime.now().strftime('%Y-%m-%d')}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           background: #0d1117; color: #c9d1d9; line-height: 1.6; padding: 20px; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ color: #58a6ff; margin-bottom: 10px; font-size: 1.8em; }}
    h2 {{ color: #58a6ff; margin: 30px 0 15px; font-size: 1.3em;
          border-bottom: 1px solid #30363d; padding-bottom: 8px; }}
    .header {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
               padding: 20px; margin-bottom: 20px; }}
    .meta {{ color: #8b949e; font-size: 0.9em; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
             gap: 15px; margin: 15px 0; }}
    .stat-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                  padding: 15px; text-align: center; }}
    .stat-card .value {{ font-size: 1.8em; font-weight: bold; }}
    .stat-card .label {{ color: #8b949e; font-size: 0.85em; margin-top: 5px; }}
    .positive {{ color: #3fb950; }}
    .negative {{ color: #f85149; }}
    .neutral {{ color: #d29922; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0;
             background: #161b22; border-radius: 8px; overflow: hidden; }}
    th {{ background: #21262d; color: #8b949e; padding: 10px 12px; text-align: left;
          font-weight: 600; font-size: 0.85em; text-transform: uppercase; }}
    td {{ padding: 8px 12px; border-top: 1px solid #21262d; font-size: 0.95em; }}
    tr:hover {{ background: #1c2128; }}
    .chart-container {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                        padding: 20px; margin: 15px 0; }}
    canvas {{ width: 100% !important; height: 300px !important; }}
    .params-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 15px; }}
    .param-block {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                    padding: 15px; }}
    .param-block h3 {{ color: #79c0ff; font-size: 1em; margin-bottom: 10px; }}
    .param-item {{ display: flex; justify-content: space-between; padding: 3px 0;
                   font-size: 0.9em; border-bottom: 1px solid #21262d; }}
    .param-item .key {{ color: #8b949e; }}
    .footer {{ text-align: center; color: #484f58; margin-top: 40px; padding: 20px;
               border-top: 1px solid #21262d; font-size: 0.85em; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>Operation Crack The Code — Backtest Report</h1>
    <div class="meta">
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} |
        Strategies: {', '.join(strategies_config.keys())} |
        Tickers: {', '.join(tickers)} |
        Period: {min(years)}-{max(years)}
        {f' | Note: {note}' if note else ''}
    </div>
</div>

<h2>Summary</h2>
<div class="grid">
    <div class="stat-card">
        <div class="value {'positive' if combined.get('return_pct', 0) > 0 else 'negative'}">{combined.get('return_pct', 0):+.1f}%</div>
        <div class="label">Total Return</div>
    </div>
    <div class="stat-card">
        <div class="value">{combined.get('total_trades', 0)}</div>
        <div class="label">Total Trades</div>
    </div>
    <div class="stat-card">
        <div class="value">{combined.get('win_rate', 0):.1f}%</div>
        <div class="label">Win Rate</div>
    </div>
    <div class="stat-card">
        <div class="value {'negative' if combined.get('max_drawdown', 0) < -10 else 'neutral'}">{combined.get('max_drawdown', 0):.1f}%</div>
        <div class="label">Max Drawdown</div>
    </div>
    <div class="stat-card">
        <div class="value">{combined.get('sharpe_ratio', 0):.2f}</div>
        <div class="label">Sharpe Ratio</div>
    </div>
    <div class="stat-card">
        <div class="value">{combined.get('profit_factor', 0):.2f}</div>
        <div class="label">Profit Factor</div>
    </div>
</div>

<h2>Equity Curve</h2>
<div class="chart-container">
    <canvas id="equityChart"></canvas>
</div>

<h2>Per-Year Breakdown</h2>
<table>
    <thead>
        <tr><th>Year</th><th>Return</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>P&L</th></tr>
    </thead>
    <tbody>
"""

    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        ret = y.get("return_pct", 0)
        cls = "positive" if ret > 0 else "negative"
        html += f"""        <tr>
            <td>{yr}</td>
            <td class="{cls}">{ret:+.1f}%</td>
            <td>{y.get('trades', 0)}</td>
            <td>{y.get('win_rate', 0):.1f}%</td>
            <td>{y.get('max_drawdown', 0):.1f}%</td>
            <td class="{cls}">${y.get('total_pnl', 0):,.0f}</td>
        </tr>
"""

    html += """    </tbody>
</table>
"""

    # Per-strategy breakdown
    if per_strategy:
        html += "\n<h2>Per-Strategy Breakdown</h2>\n<table>\n"
        html += "    <thead><tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>P&L</th><th>Avg Win</th><th>Avg Loss</th><th>Profit Factor</th></tr></thead>\n"
        html += "    <tbody>\n"
        for sname, sdata in sorted(per_strategy.items()):
            pnl = sdata.get("total_pnl", 0)
            cls = "positive" if pnl > 0 else "negative"
            html += f"""        <tr>
            <td>{sname}</td>
            <td>{sdata.get('total_trades', 0)}</td>
            <td>{sdata.get('win_rate', 0):.1f}%</td>
            <td class="{cls}">${pnl:,.0f}</td>
            <td>${sdata.get('avg_win', 0):,.0f}</td>
            <td>${sdata.get('avg_loss', 0):,.0f}</td>
            <td>{sdata.get('profit_factor', 0):.2f}</td>
        </tr>
"""
        html += "    </tbody>\n</table>\n"

    # Parameters
    html += "\n<h2>Strategy Parameters</h2>\n<div class=\"params-grid\">\n"
    for sname, params in strategies_config.items():
        html += f'    <div class="param-block">\n        <h3>{sname}</h3>\n'
        for k, v in sorted(params.items()):
            html += f'        <div class="param-item"><span class="key">{k}</span><span>{v}</span></div>\n'
        html += "    </div>\n"
    html += "</div>\n"

    # Recent trades table (last 20)
    if trades:
        html += "\n<h2>Recent Trades (Last 20)</h2>\n<table>\n"
        html += "    <thead><tr><th>Date</th><th>Strategy</th><th>Ticker</th><th>Direction</th><th>Exit</th><th>P&L</th><th>Return</th></tr></thead>\n"
        html += "    <tbody>\n"
        for t in trades[-20:]:
            pnl = t.get("pnl", 0)
            cls = "positive" if pnl > 0 else "negative"
            html += f"""        <tr>
            <td>{t.get('exit_date', '')}</td>
            <td>{t.get('strategy', '')}</td>
            <td>{t.get('ticker', '')}</td>
            <td>{t.get('direction', '')}</td>
            <td>{t.get('exit_reason', '')}</td>
            <td class="{cls}">${pnl:,.0f}</td>
            <td class="{cls}">{t.get('return_pct', 0):+.1f}%</td>
        </tr>
"""
        html += "    </tbody>\n</table>\n"

    # Backtester features list
    html += """
<h2>Backtester Features</h2>
<div class="grid">
    <div class="stat-card"><div class="value" style="font-size:1em">Bid-Ask Spread</div><div class="label">VIX-scaled, moneyness-adjusted</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">IV Skew</div><div class="label">OTM puts higher IV, calls discounted</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Gap Risk</div><div class="label">Overnight gap stop-loss at open</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Dynamic RFR</div><div class="label">Fed Funds rate by year (2020-2026)</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Delta Cap</div><div class="label">Portfolio-level delta awareness</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Margin</div><div class="label">Reg-T buying power tracking</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Assignment Risk</div><div class="label">Force-close ITM shorts near expiry</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Commission</div><div class="label">$0.65/leg per contract</div></div>
</div>
"""

    # Chart JS (lightweight inline)
    eq_json = json.dumps(eq_dates)
    val_json = json.dumps(eq_values)

    html += f"""
<div class="footer">
    Generated by Operation Crack The Code backtesting engine.<br>
    All results are from synthetic Black-Scholes pricing with realistic friction modeling.<br>
    Past performance does not guarantee future results.
</div>

</div>

<script>
// Simple canvas equity chart (no external libraries)
(function() {{
    const canvas = document.getElementById('equityChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dates = {eq_json};
    const values = {val_json};
    if (!values.length) return;

    // Set canvas size
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width - 40;
    canvas.height = 300;
    const W = canvas.width, H = canvas.height;
    const pad = {{top: 20, right: 20, bottom: 40, left: 70}};
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    const minV = Math.min(...values) * 0.98;
    const maxV = Math.max(...values) * 1.02;
    const rangeV = maxV - minV || 1;

    function x(i) {{ return pad.left + (i / (values.length - 1)) * plotW; }}
    function y(v) {{ return pad.top + plotH - ((v - minV) / rangeV) * plotH; }}

    // Grid
    ctx.strokeStyle = '#21262d';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {{
        const yy = pad.top + (i / 4) * plotH;
        ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(W - pad.right, yy); ctx.stroke();
        const val = maxV - (i / 4) * rangeV;
        ctx.fillStyle = '#8b949e'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
        ctx.fillText('$' + Math.round(val).toLocaleString(), pad.left - 8, yy + 4);
    }}

    // Date labels
    ctx.fillStyle = '#8b949e'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(dates.length / 6));
    for (let i = 0; i < dates.length; i += step) {{
        ctx.fillText(dates[i], x(i), H - 10);
    }}

    // Line
    ctx.beginPath();
    ctx.strokeStyle = '#58a6ff';
    ctx.lineWidth = 2;
    for (let i = 0; i < values.length; i++) {{
        if (i === 0) ctx.moveTo(x(i), y(values[i]));
        else ctx.lineTo(x(i), y(values[i]));
    }}
    ctx.stroke();

    // Fill under
    ctx.lineTo(x(values.length - 1), pad.top + plotH);
    ctx.lineTo(x(0), pad.top + plotH);
    ctx.closePath();
    ctx.fillStyle = 'rgba(88, 166, 255, 0.1)';
    ctx.fill();

    // Starting capital line
    const startY = y(values[0]);
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = '#484f58';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.left, startY); ctx.lineTo(W - pad.right, startY); ctx.stroke();
    ctx.setLineDash([]);
}})();
</script>
</body>
</html>"""

    return html


def main():
    parser = argparse.ArgumentParser(description="Generate HTML backtest report")
    parser.add_argument("--strategies", help="Comma-separated strategy names")
    parser.add_argument("--config", help="JSON file with strategy params")
    parser.add_argument("--from-leaderboard", action="store_true",
                        help="Use best leaderboard params")
    parser.add_argument("--tickers", default="SPY,QQQ,IWM")
    parser.add_argument("--years", default="2020,2021,2022,2023,2024,2025")
    parser.add_argument("--note", default="")
    parser.add_argument("--output", default="output/backtest_report.html")
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",")]
    years = [int(y.strip()) for y in args.years.split(",")]

    from scripts.run_optimization import build_strategies_config

    if args.config:
        with open(args.config) as f:
            param_overrides = json.load(f)
        strategy_names = list(param_overrides.keys())
        strategies_config = build_strategies_config(strategy_names, param_overrides)
    elif args.from_leaderboard:
        lb = json.loads((OUTPUT / "leaderboard.json").read_text())
        best = max(lb, key=lambda e: e["summary"]["avg_return"])
        strategies_config = best.get("strategy_params", {})
        strategy_names = list(strategies_config.keys())
        # Rebuild with defaults + overrides
        strategies_config = build_strategies_config(strategy_names, strategies_config)
        print(f"Using leaderboard best: {best['run_id']}")
    else:
        strategy_names = [s.strip() for s in args.strategies.split(",")] if args.strategies else ["credit_spread", "iron_condor"]
        strategies_config = build_strategies_config(strategy_names)

    print(f"\nGenerating report: {', '.join(strategies_config.keys())}")
    print(f"Tickers: {tickers}  |  Years: {years}")

    results = run_report_backtest(strategies_config, tickers, years)

    html = generate_html(results, strategies_config, tickers, years, args.note)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"\nReport saved to {out_path}")
    print(f"Open in browser: file://{out_path.resolve()}")


if __name__ == "__main__":
    main()
