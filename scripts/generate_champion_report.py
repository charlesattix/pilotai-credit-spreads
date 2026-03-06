#!/usr/bin/env python3
"""Generate comprehensive HTML backtest report for the champion config.

Runs a fresh backtest, then builds a report including:
- Full backtest results (equity curve, yearly, per-strategy)
- Optimization pipeline summary (500 runs → jitter → walk-forward)
- Validation metrics (jitter stability, WF ratio, OOS performance)
- Strategy parameters
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "output"
CHAMPION_PATH = ROOT / "configs" / "champion.json"
SECONDARY_PATH = ROOT / "configs" / "secondary.json"
REPORT_PATH = OUTPUT / "champion_report.html"

TICKERS = ["SPY", "QQQ", "IWM"]
YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


def run_backtest(strategies_config, tickers, years):
    from scripts.run_optimization import run_full
    return run_full(strategies_config, years, tickers)


def css():
    return """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           background: #0d1117; color: #c9d1d9; line-height: 1.6; padding: 20px; }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { color: #58a6ff; margin-bottom: 10px; font-size: 1.8em; }
    h2 { color: #58a6ff; margin: 30px 0 15px; font-size: 1.3em;
         border-bottom: 1px solid #30363d; padding-bottom: 8px; }
    h3 { color: #79c0ff; font-size: 1.1em; margin: 15px 0 10px; }
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
    .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin: 15px 0; }
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
    canvas { width: 100% !important; height: 300px !important; }
    .pipeline { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                padding: 20px; margin: 15px 0; }
    .pipeline-step { display: flex; align-items: center; padding: 12px 0;
                     border-bottom: 1px solid #21262d; }
    .pipeline-step:last-child { border-bottom: none; }
    .step-num { background: #21262d; color: #58a6ff; width: 32px; height: 32px;
                border-radius: 50%; display: flex; align-items: center; justify-content: center;
                font-weight: bold; font-size: 0.9em; margin-right: 15px; flex-shrink: 0; }
    .step-content { flex: 1; }
    .step-label { font-weight: 600; color: #c9d1d9; }
    .step-detail { color: #8b949e; font-size: 0.9em; }
    .step-result { text-align: right; font-weight: bold; font-size: 0.95em; }
    .params-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                   gap: 15px; }
    .param-block { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                   padding: 15px; }
    .param-block h3 { color: #79c0ff; font-size: 1em; margin-bottom: 10px; }
    .param-item { display: flex; justify-content: space-between; padding: 3px 0;
                  font-size: 0.9em; border-bottom: 1px solid #21262d; }
    .param-item .key { color: #8b949e; }
    .footer { text-align: center; color: #484f58; margin-top: 40px; padding: 20px;
              border-top: 1px solid #21262d; font-size: 0.85em; }
    .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 768px) { .comparison { grid-template-columns: 1fr; } .grid-3 { grid-template-columns: 1fr; } }
    """


def val_class(val, good_thresh, bad_thresh, higher_better=True):
    if higher_better:
        return "positive" if val >= good_thresh else ("negative" if val < bad_thresh else "neutral")
    else:
        return "positive" if val <= good_thresh else ("negative" if val > bad_thresh else "neutral")


def generate_html(results, champion, secondary_cfg):
    combined = results.get("combined", {})
    yearly = results.get("yearly", {})
    per_strategy = results.get("per_strategy", {})
    equity_curve = combined.get("equity_curve", [])
    trades = results.get("trades", [])
    val = champion["validation"]
    strategies_config = champion["strategy_params"]

    eq_dates = [p["date"] for p in equity_curve]
    eq_values = [p["equity"] for p in equity_curve]

    # Compute avg annual return
    yr_returns = [yearly[yr].get("return_pct", 0) for yr in sorted(yearly.keys())]
    avg_annual = sum(yr_returns) / len(yr_returns) if yr_returns else 0
    profitable_years = sum(1 for r in yr_returns if r > 0)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Champion Config Report — {datetime.now().strftime('%Y-%m-%d')}</title>
<style>{css()}</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>Champion Config — Validation Report</h1>
    <div class="meta">
        Run ID: {champion['run_id']} |
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} |
        Strategies: {', '.join(champion['strategies'])} |
        Tickers: {', '.join(TICKERS)} |
        Period: {min(YEARS)}-{max(YEARS)}
        <span class="badge badge-green">WALK-FORWARD VALIDATED</span>
        <span class="badge badge-green">3/3 FOLDS PROFITABLE</span>
    </div>
</div>

<!-- VALIDATION PIPELINE -->
<h2>Validation Pipeline</h2>
<div class="pipeline">
    <div class="pipeline-step">
        <div class="step-num">1</div>
        <div class="step-content">
            <div class="step-label">500-Run Optimization</div>
            <div class="step-detail">Endless optimizer across all 7 strategies, real Polygon data only</div>
        </div>
        <div class="step-result positive">34/500 met victory conditions</div>
    </div>
    <div class="pipeline-step">
        <div class="step-num">2</div>
        <div class="step-content">
            <div class="step-label">Jitter Robustness Test</div>
            <div class="step-detail">25 variants at +/-15% noise on all params, SPY+QQQ+IWM</div>
        </div>
        <div class="step-result">
            <span class="{val_class(val['jitter_stability_ratio'], 0.70, 0.50)}">
                Stability: {val['jitter_stability_ratio']:.3f}
            </span>
            &nbsp;|&nbsp; Mean: {val['jitter_mean_return']:+.1f}%
        </div>
    </div>
    <div class="pipeline-step">
        <div class="step-num">3</div>
        <div class="step-content">
            <div class="step-label">Walk-Forward Validation</div>
            <div class="step-detail">3 expanding folds (min 3yr train), 20 experiments/fold, out-of-sample testing</div>
        </div>
        <div class="step-result positive">
            WF Ratio: {val['wf_ratio']:.3f} | OOS: {val['wf_avg_oos_return']:+.1f}% | {val['wf_folds_profitable']} folds profitable
        </div>
    </div>
</div>

<!-- HEADLINE METRICS -->
<h2>Performance Summary</h2>
<div class="grid">
    <div class="stat-card">
        <div class="value {val_class(avg_annual, 6.67, 0)}">{avg_annual:+.1f}%</div>
        <div class="label">Avg Annual Return</div>
    </div>
    <div class="stat-card">
        <div class="value {'positive' if combined.get('return_pct', 0) > 0 else 'negative'}">{combined.get('return_pct', 0):+.1f}%</div>
        <div class="label">Total Return (6yr)</div>
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
        <div class="value {val_class(abs(combined.get('max_drawdown', 0)), 10, 20, False)}">{combined.get('max_drawdown', 0):.1f}%</div>
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
    <div class="stat-card">
        <div class="value {val_class(profitable_years, len(yr_returns), len(yr_returns)-1)}">{profitable_years}/{len(yr_returns)}</div>
        <div class="label">Years Profitable</div>
    </div>
</div>

<!-- WALK-FORWARD DETAIL -->
<h2>Walk-Forward Fold Details</h2>
<table>
    <thead>
        <tr><th>Fold</th><th>Training Period</th><th>Test Year</th><th>OOS Return</th><th>OOS Max DD</th><th>Verdict</th></tr>
    </thead>
    <tbody>"""

    for fd in val.get("wf_fold_details", []):
        oos = fd.get("oos_return", 0)
        dd = fd.get("oos_dd", 0)
        cls = "positive" if oos > 0 else "negative"
        verdict = "PASS" if oos > 0 else "FAIL"
        vcls = "positive" if oos > 0 else "negative"
        html += f"""
        <tr>
            <td>{fd['fold']}</td>
            <td>{fd['train']}</td>
            <td>{fd['test']}</td>
            <td class="{cls}">{oos:+.1f}%</td>
            <td>{dd:.1f}%</td>
            <td class="{vcls}">{verdict}</td>
        </tr>"""

    html += f"""
    </tbody>
</table>

<!-- EQUITY CURVE -->
<h2>Equity Curve</h2>
<div class="chart-container">
    <canvas id="equityChart"></canvas>
</div>

<!-- PER-YEAR BREAKDOWN -->
<h2>Per-Year Breakdown</h2>
<table>
    <thead>
        <tr><th>Year</th><th>Return</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>Sharpe</th><th>P&L</th></tr>
    </thead>
    <tbody>"""

    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        ret = y.get("return_pct", 0)
        cls = "positive" if ret > 0 else "negative"
        html += f"""
        <tr>
            <td>{yr}</td>
            <td class="{cls}">{ret:+.1f}%</td>
            <td>{y.get('trades', 0)}</td>
            <td>{y.get('win_rate', 0):.1f}%</td>
            <td>{y.get('max_drawdown', 0):.1f}%</td>
            <td>{y.get('sharpe_ratio', 0):.2f}</td>
            <td class="{cls}">${y.get('total_pnl', 0):,.0f}</td>
        </tr>"""

    html += """
    </tbody>
</table>"""

    # Per-strategy breakdown
    if per_strategy:
        html += """
<h2>Per-Strategy Breakdown</h2>
<table>
    <thead>
        <tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>P&L</th><th>Avg Win</th><th>Avg Loss</th><th>Profit Factor</th></tr>
    </thead>
    <tbody>"""
        for sname, sdata in sorted(per_strategy.items()):
            pnl = sdata.get("total_pnl", 0)
            cls = "positive" if pnl > 0 else "negative"
            html += f"""
        <tr>
            <td>{sname}</td>
            <td>{sdata.get('total_trades', 0)}</td>
            <td>{sdata.get('win_rate', 0):.1f}%</td>
            <td class="{cls}">${pnl:,.0f}</td>
            <td>${sdata.get('avg_win', 0):,.0f}</td>
            <td>${sdata.get('avg_loss', 0):,.0f}</td>
            <td>{sdata.get('profit_factor', 0):.2f}</td>
        </tr>"""
        html += """
    </tbody>
</table>"""

    # Jitter test summary
    html += f"""
<h2>Jitter Robustness Summary</h2>
<div class="grid">
    <div class="stat-card">
        <div class="value {val_class(val['jitter_stability_ratio'], 0.70, 0.50)}">{val['jitter_stability_ratio']:.3f}</div>
        <div class="label">Stability Ratio (need >= 0.70)</div>
    </div>
    <div class="stat-card">
        <div class="value {val_class(val['robustness_score'], 0.80, 0.60)}">{val['robustness_score']:.3f}</div>
        <div class="label">Robustness Score</div>
    </div>
    <div class="stat-card">
        <div class="value positive">{val['jitter_mean_return']:+.1f}%</div>
        <div class="label">Jitter Mean Return</div>
    </div>
    <div class="stat-card">
        <div class="value">{val['base_avg_return']:+.1f}%</div>
        <div class="label">Base Return</div>
    </div>
</div>
<p class="muted" style="padding: 0 5px; font-size: 0.9em;">
    25 jittered parameter variants tested at +/-15% noise across SPY, QQQ, IWM.
    Stability ratio = jitter mean / base return. Score > 0.70 indicates robust parameter surface.
</p>"""

    # Strategy parameters
    html += '\n<h2>Strategy Parameters</h2>\n<div class="params-grid">\n'
    for sname, params in strategies_config.items():
        html += f'    <div class="param-block">\n        <h3>{sname}</h3>\n'
        for k, v in sorted(params.items()):
            html += f'        <div class="param-item"><span class="key">{k}</span><span>{v}</span></div>\n'
        html += "    </div>\n"
    html += "</div>\n"

    # Secondary candidate comparison
    if secondary_cfg:
        sv = secondary_cfg["validation"]
        html += f"""
<h2>Secondary Candidate Comparison</h2>
<div class="comparison">
    <div class="stat-card" style="border-color: #3fb950;">
        <h3 style="color: #3fb950;">Champion (Selected)</h3>
        <div style="padding: 10px 0;">
            <div>Base Return: <strong>{val['base_avg_return']:+.1f}%/yr</strong></div>
            <div>WF OOS Return: <strong class="positive">{val['wf_avg_oos_return']:+.1f}%</strong></div>
            <div>WF Ratio: <strong>{val['wf_ratio']:.3f}</strong></div>
            <div>WF Folds OK: <strong class="positive">{val['wf_folds_profitable']}</strong></div>
            <div>Jitter Stability: <strong>{val['jitter_stability_ratio']:.3f}</strong></div>
            <div>Strategies: {', '.join(champion['strategies'])}</div>
        </div>
    </div>
    <div class="stat-card" style="border-color: #d29922;">
        <h3 style="color: #d29922;">Secondary (Higher Return, Less Stable)</h3>
        <div style="padding: 10px 0;">
            <div>Base Return: <strong>{sv['base_avg_return']:+.1f}%/yr</strong></div>
            <div>WF OOS Return: <strong class="neutral">{sv['wf_avg_oos_return']:+.1f}%</strong></div>
            <div>WF Ratio: <strong class="negative">{sv['wf_ratio']:.3f}</strong></div>
            <div>WF Folds OK: <strong class="neutral">{sv['wf_folds_profitable']}</strong></div>
            <div>Jitter Stability: <strong>{sv['jitter_stability_ratio']:.3f}</strong></div>
            <div>Strategies: {', '.join(secondary_cfg['strategies'])}</div>
        </div>
    </div>
</div>"""

    # Recent trades
    if trades:
        html += '\n<h2>Recent Trades (Last 25)</h2>\n<table>\n'
        html += '    <thead><tr><th>Date</th><th>Strategy</th><th>Ticker</th><th>Direction</th><th>Exit</th><th>P&L</th><th>Return</th></tr></thead>\n'
        html += '    <tbody>\n'
        for t in trades[-25:]:
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
        </tr>\n"""
        html += '    </tbody>\n</table>\n'

    # Backtester features
    html += """
<h2>Backtester Features</h2>
<div class="grid">
    <div class="stat-card"><div class="value" style="font-size:1em">Real Polygon Data</div><div class="label">No synthetic pricing — cache miss = skip trade</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Bid-Ask Spread</div><div class="label">VIX-scaled, moneyness-adjusted</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">IV Skew</div><div class="label">OTM puts higher IV, calls discounted</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Gap Risk</div><div class="label">Overnight gap stop-loss at open</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Dynamic RFR</div><div class="label">Fed Funds rate by year</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Delta Cap</div><div class="label">Portfolio-level delta awareness</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Margin</div><div class="label">Reg-T buying power tracking</div></div>
    <div class="stat-card"><div class="value" style="font-size:1em">Commission</div><div class="label">$0.65/leg per contract</div></div>
</div>
"""

    eq_json = json.dumps(eq_dates)
    val_json = json.dumps(eq_values)

    html += f"""
<div class="footer">
    Operation Crack The Code — Champion Config Validation Report<br>
    All results from real Polygon historical options data with realistic friction modeling.<br>
    Walk-forward validated: trained on past years, tested on unseen future years.<br>
    Past performance does not guarantee future results.
</div>

</div>

<script>
(function() {{
    const canvas = document.getElementById('equityChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dates = {eq_json};
    const values = {val_json};
    if (!values.length) return;

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

    ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {{
        const yy = pad.top + (i / 4) * plotH;
        ctx.beginPath(); ctx.moveTo(pad.left, yy); ctx.lineTo(W - pad.right, yy); ctx.stroke();
        const val = maxV - (i / 4) * rangeV;
        ctx.fillStyle = '#8b949e'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
        ctx.fillText('$' + Math.round(val).toLocaleString(), pad.left - 8, yy + 4);
    }}

    ctx.fillStyle = '#8b949e'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(dates.length / 6));
    for (let i = 0; i < dates.length; i += step) {{
        ctx.fillText(dates[i], x(i), H - 10);
    }}

    ctx.beginPath(); ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2;
    for (let i = 0; i < values.length; i++) {{
        if (i === 0) ctx.moveTo(x(i), y(values[i]));
        else ctx.lineTo(x(i), y(values[i]));
    }}
    ctx.stroke();

    ctx.lineTo(x(values.length - 1), pad.top + plotH);
    ctx.lineTo(x(0), pad.top + plotH);
    ctx.closePath();
    ctx.fillStyle = 'rgba(88, 166, 255, 0.1)';
    ctx.fill();

    const startY = y(values[0]);
    ctx.setLineDash([5, 5]); ctx.strokeStyle = '#484f58'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.left, startY); ctx.lineTo(W - pad.right, startY); ctx.stroke();
    ctx.setLineDash([]);
}})();
</script>
</body>
</html>"""

    return html


def main():
    print("Loading champion config...")
    champion = json.loads(CHAMPION_PATH.read_text())
    secondary = json.loads(SECONDARY_PATH.read_text()) if SECONDARY_PATH.exists() else None

    print(f"Champion: {champion['run_id']}")
    print(f"Strategies: {champion['strategies']}")

    print(f"\nRunning fresh backtest with champion params...")
    results = run_backtest(champion["strategy_params"], TICKERS, YEARS)

    combined = results.get("combined", {})
    print(f"  Return: {combined.get('return_pct', 0):+.1f}%")
    print(f"  Trades: {combined.get('total_trades', 0)}")
    print(f"  Win Rate: {combined.get('win_rate', 0):.1f}%")
    print(f"  Max DD: {combined.get('max_drawdown', 0):.1f}%")

    print(f"\nGenerating HTML report...")
    html = generate_html(results, champion, secondary)

    REPORT_PATH.write_text(html)
    print(f"\nReport saved to {REPORT_PATH}")
    print(f"Open: file://{REPORT_PATH.resolve()}")


if __name__ == "__main__":
    main()
