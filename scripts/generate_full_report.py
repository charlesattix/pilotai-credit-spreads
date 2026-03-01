#!/usr/bin/env python3
"""
Comprehensive HTML Report Generator
====================================
Reads existing data sources (leaderboard, optimizer state, backtest results, logs)
and generates a publication-quality, self-contained HTML report at output/full_report.html.

No external dependencies — inline CSS, inline Canvas charts.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        print(f"  [WARN] Missing: {path}")
        return None
    with open(path) as f:
        return json.load(f)


def load_log_tail(path: Path, lines: int = 200) -> str:
    if not path.exists():
        return ""
    with open(path) as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


def find_latest_backtest() -> Path | None:
    """Find the most recent portfolio_backtest_*.json file."""
    candidates = sorted(OUTPUT.glob("portfolio_backtest_*.json"), reverse=True)
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Strategy metadata (hardcoded from codebase knowledge)
# ---------------------------------------------------------------------------

STRATEGY_META = {
    "credit_spread": {
        "class": "CreditSpreadStrategy",
        "name": "Credit Spread",
        "desc": "Bull put or bear call vertical spreads — the primary income strategy. "
                "Sells OTM options and buys further-OTM protection for defined risk.",
        "signal": "Trend MA filter + momentum confirmation. Scans on configurable weekday.",
        "entry": "Sell OTM put/call spread at target DTE (30-60 days), minimum credit fraction required.",
        "exit": "Profit target (% of max profit), stop-loss (multiplier of credit received), "
                "time decay exit, or expiration.",
        "risk": "max_risk_pct caps per-trade allocation. Spread width defines max loss.",
        "params": ["direction", "trend_ma_period", "target_dte", "min_dte", "otm_pct",
                   "spread_width", "credit_fraction", "profit_target_pct",
                   "stop_loss_multiplier", "momentum_filter_pct", "scan_weekday", "max_risk_pct"],
    },
    "iron_condor": {
        "class": "IronCondorStrategy",
        "name": "Iron Condor",
        "desc": "Simultaneous bull put + bear call spread — profits from range-bound markets. "
                "Dual premium collection with defined risk on both sides.",
        "signal": "Low-volatility regime detection. IV rank / percentile filter.",
        "entry": "Sell OTM put spread + OTM call spread at same expiration.",
        "exit": "Combined profit target, stop-loss on either wing, time-based exit.",
        "risk": "max_risk_pct per trade. Total risk = wider of the two spreads.",
        "params": ["target_dte", "min_dte", "put_otm_pct", "call_otm_pct",
                   "spread_width", "profit_target_pct", "stop_loss_multiplier", "max_risk_pct"],
    },
    "straddle_strangle": {
        "class": "StraddleStrangleStrategy",
        "name": "Straddle / Strangle",
        "desc": "Short straddles or strangles around earnings and economic events — "
                "profits from IV crush after the event passes.",
        "signal": "Event calendar detection (earnings, FOMC, CPI). IV boost threshold.",
        "entry": "Sell ATM straddle or OTM strangle days before event at elevated IV.",
        "exit": "IV crush profit target, stop-loss on adverse move, time exit post-event.",
        "risk": "max_risk_pct. Undefined risk managed by stop-loss.",
        "params": ["mode", "days_before_event", "target_dte", "otm_pct",
                   "event_iv_boost", "iv_crush_pct", "profit_target_pct",
                   "stop_loss_pct", "max_risk_pct", "event_types"],
    },
    "debit_spread": {
        "class": "DebitSpreadStrategy",
        "name": "Debit Spread",
        "desc": "Directional defined-risk trades — buy ITM/ATM option, sell OTM for cost reduction. "
                "Used for high-conviction directional plays.",
        "signal": "Strong trend confirmation with momentum and volatility filters.",
        "entry": "Buy ATM/ITM option, sell OTM option for reduced cost basis.",
        "exit": "Profit target, stop-loss, or time-based exit.",
        "risk": "max_risk_pct. Max loss = debit paid.",
        "params": ["direction", "target_dte", "min_dte", "spread_width",
                   "profit_target_pct", "stop_loss_pct", "max_risk_pct"],
    },
    "calendar_spread": {
        "class": "CalendarSpreadStrategy",
        "name": "Calendar Spread",
        "desc": "Theta harvesting across expirations — sell near-term, buy longer-term at same strike. "
                "Profits from faster time decay of the short leg.",
        "signal": "Low realized volatility, stable underlying price.",
        "entry": "Sell near-term option, buy same-strike longer-term option.",
        "exit": "Near-term expiration approach, profit target, or stop-loss.",
        "risk": "max_risk_pct. Max loss = net debit paid.",
        "params": ["target_dte_short", "target_dte_long", "strike_offset_pct",
                   "profit_target_pct", "stop_loss_pct", "max_risk_pct"],
    },
    "gamma_lotto": {
        "class": "GammaLottoStrategy",
        "name": "Gamma Lotto",
        "desc": "Asymmetric pre-catalyst plays — small allocation to cheap OTM options "
                "before known events for outsized payoff potential.",
        "signal": "Upcoming catalyst events (earnings, FDA, FOMC). Cheap OTM options available.",
        "entry": "Buy cheap OTM calls/puts days before catalyst event.",
        "exit": "Profit target multiple, event passage, or expiration.",
        "risk": "max_risk_pct (kept small, typically 1-2%). Max loss = premium paid.",
        "params": ["days_before_event", "price_min", "price_max", "min_otm_pct",
                   "max_otm_pct", "max_risk_pct", "profit_target_multiple",
                   "direction", "event_types", "hold_through_event"],
    },
    "momentum_swing": {
        "class": "MomentumSwingStrategy",
        "name": "Momentum Swing",
        "desc": "Trend-following and breakout trades on the underlying — "
                "uses EMA crossovers, RSI, ADX, and breakout detection.",
        "signal": "EMA cross (fast/slow), RSI momentum, ADX trend strength, price breakout.",
        "entry": "Enter on confirmed trend/breakout signal via long/short stock or options.",
        "exit": "Trailing stop, profit target, max hold days, or signal reversal.",
        "risk": "max_risk_pct. Trailing stop defines exit.",
        "params": ["mode", "ema_fast", "ema_slow", "min_adx", "rsi_period",
                   "breakout_lookback", "trailing_stop_pct", "max_hold_days",
                   "profit_target_pct", "max_risk_pct", "use_breakout", "use_ema_cross"],
    },
}

CLASS_TO_REGISTRY = {v["class"]: k for k, v in STRATEGY_META.items()}


# ---------------------------------------------------------------------------
# HTML generation helpers
# ---------------------------------------------------------------------------

def fmt_pct(val, decimals=2, plus=False):
    if val is None:
        return "N/A"
    s = f"{val:,.{decimals}f}%"
    if plus and val > 0:
        s = "+" + s
    return s


def fmt_num(val, decimals=2):
    if val is None:
        return "N/A"
    return f"{val:,.{decimals}f}"


def fmt_dollar(val, decimals=0):
    if val is None:
        return "N/A"
    prefix = "-" if val < 0 else ""
    return f"{prefix}${abs(val):,.{decimals}f}"


def color_class(val):
    if val is None:
        return ""
    return "positive" if val > 0 else ("negative" if val < 0 else "")


def fmt_verdict(v):
    if not v:
        return '<span class="neutral">N/A</span>'
    cls = {"ROBUST": "positive", "SUSPECT": "neutral", "OVERFIT": "negative"}.get(v, "")
    return f'<span class="{cls}">{v}</span>'


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def section_executive_summary(backtest: dict, opt_state: dict, leaderboard: list) -> str:
    c = backtest.get("combined", {}) if backtest else {}
    top = leaderboard[0] if leaderboard else {}
    top_summary = top.get("summary", {})
    top_strats = ", ".join(STRATEGY_META.get(s, {}).get("name", s) for s in top.get("strategies", []))

    return f"""
    <section id="executive-summary">
      <h2>1. Executive Summary</h2>
      <div class="card-grid">
        <div class="card">
          <h3>Credit Spread Backtest (2020–2025)</h3>
          <div class="stat-grid">
            <div class="stat"><span class="stat-value {color_class(c.get('return_pct'))}">{fmt_pct(c.get('return_pct'), 1, True)}</span><span class="stat-label">Total Return</span></div>
            <div class="stat"><span class="stat-value">{c.get('total_trades', 'N/A')}</span><span class="stat-label">Trades</span></div>
            <div class="stat"><span class="stat-value">{fmt_pct(c.get('win_rate'), 1)}</span><span class="stat-label">Win Rate</span></div>
            <div class="stat"><span class="stat-value">{fmt_num(c.get('sharpe_ratio'))}</span><span class="stat-label">Sharpe Ratio</span></div>
            <div class="stat"><span class="stat-value negative">{fmt_pct(c.get('max_drawdown'), 2)}</span><span class="stat-label">Max Drawdown</span></div>
            <div class="stat"><span class="stat-value">{fmt_num(c.get('profit_factor'))}</span><span class="stat-label">Profit Factor</span></div>
          </div>
        </div>
        <div class="card">
          <h3>Optimization Campaign</h3>
          <div class="stat-grid">
            <div class="stat"><span class="stat-value">{fmt_num(opt_state.get('total_runs', 0), 0)}</span><span class="stat-label">Total Runs</span></div>
            <div class="stat"><span class="stat-value">{len(leaderboard)}</span><span class="stat-label">Leaderboard Entries</span></div>
            <div class="stat"><span class="stat-value">{fmt_num(opt_state.get('best_overfit_score'))}</span><span class="stat-label">Best Overfit Score</span></div>
            <div class="stat"><span class="stat-value">{opt_state.get('current_phase', 'N/A')}</span><span class="stat-label">Current Phase</span></div>
          </div>
        </div>
        <div class="card full-width">
          <h3>Top Multi-Strategy Combo</h3>
          <p><strong>Run:</strong> {top.get('run_id', 'N/A')}</p>
          <p><strong>Strategies:</strong> {top_strats}</p>
          <p><strong>Avg Annual Return:</strong> <span class="{color_class(top_summary.get('avg_return'))}">{fmt_pct(top_summary.get('avg_return'), 1, True)}</span>
           &nbsp;|&nbsp; <strong>Min Year:</strong> {fmt_pct(top_summary.get('min_return'), 1, True)}
           &nbsp;|&nbsp; <strong>Worst DD:</strong> <span class="negative">{fmt_pct(top_summary.get('worst_dd'), 1)}</span>
           &nbsp;|&nbsp; <strong>Verdict:</strong> {fmt_verdict(top.get('verdict'))}</p>
        </div>
      </div>
    </section>
    """


def section_methodology() -> str:
    return """
    <section id="methodology">
      <h2>2. Full Methodology</h2>
      <div class="card">
        <h3>Day-by-Day Simulation Loop</h3>
        <div class="pipeline">
          <div class="pipeline-step">Market Snapshot<br><small>Price, IV, Greeks</small></div>
          <div class="pipeline-arrow">&rarr;</div>
          <div class="pipeline-step">Gap Check<br><small>Overnight gap stop</small></div>
          <div class="pipeline-arrow">&rarr;</div>
          <div class="pipeline-step">Assignment Risk<br><small>ITM short check</small></div>
          <div class="pipeline-arrow">&rarr;</div>
          <div class="pipeline-step">Process Exits<br><small>TP / SL / Expiry</small></div>
          <div class="pipeline-arrow">&rarr;</div>
          <div class="pipeline-step">Process Entries<br><small>Signal &rarr; Order</small></div>
          <div class="pipeline-arrow">&rarr;</div>
          <div class="pipeline-step">Update Equity<br><small>Mark-to-market</small></div>
        </div>
      </div>

      <div class="two-col">
        <div class="card">
          <h3>Options Pricing</h3>
          <ul>
            <li><strong>Black-Scholes</strong> with IV skew adjustment (OTM puts +skew, calls &minus;skew)</li>
            <li><strong>Greeks</strong>: Delta, gamma, theta, vega computed per leg</li>
            <li><strong>Bid-Ask Friction</strong>: VIX-scaled base spread, moneyness-adjusted. Higher friction for deep OTM, high-VIX environments</li>
          </ul>
        </div>
        <div class="card">
          <h3>Risk Modeling</h3>
          <ul>
            <li><strong>Gap Risk</strong>: Overnight gap detection at 0.5% threshold; positions stopped at open price</li>
            <li><strong>Assignment Risk</strong>: Force-close ITM short legs approaching expiration</li>
            <li><strong>Commission</strong>: $0.65 per leg per contract (industry standard)</li>
            <li><strong>Dynamic Risk-Free Rate</strong>: Fed Funds rate by year (0.25% in 2020 &rarr; 5.25% in 2023-24 &rarr; 4.50% in 2025)</li>
          </ul>
        </div>
      </div>
    </section>
    """


def section_position_sizing() -> str:
    return """
    <section id="position-sizing">
      <h2>3. Position Sizing &amp; Risk Management</h2>
      <div class="card">
        <table class="data-table">
          <thead><tr><th>Parameter</th><th>Value</th><th>Description</th></tr></thead>
          <tbody>
            <tr><td><code>max_risk_pct</code></td><td>Per strategy (1-10%)</td><td>Fraction of equity risked per trade. <code>contracts = floor(risk_budget / max_loss / 100)</code></td></tr>
            <tr><td>Portfolio Heat Cap</td><td>40%</td><td>Maximum total portfolio risk across all open positions</td></tr>
            <tr><td>Portfolio Delta Cap</td><td>|&delta;| &lt; 50</td><td>Net portfolio delta must stay within bounds</td></tr>
            <tr><td>Max Positions</td><td>10 total</td><td>Hard cap on simultaneous open positions</td></tr>
            <tr><td>Max Per Strategy</td><td>5</td><td>No single strategy dominates position count</td></tr>
            <tr><td>Reg-T Margin</td><td>Tracked</td><td>Buying power consumed by each position, with maintenance margin checks</td></tr>
            <tr><td>Commission</td><td>$0.65/leg</td><td>Per-contract, per-leg commission applied on entry and exit</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    """


def section_strategies() -> str:
    rows = ""
    for i, (key, meta) in enumerate(STRATEGY_META.items(), 1):
        rows += f"""
        <div class="card strategy-card">
          <h3>{i}. {meta['name']}</h3>
          <p>{meta['desc']}</p>
          <div class="strategy-details">
            <div><strong>Signal Logic:</strong> {meta['signal']}</div>
            <div><strong>Entry Rules:</strong> {meta['entry']}</div>
            <div><strong>Exit Rules:</strong> {meta['exit']}</div>
            <div><strong>Risk Cap:</strong> {meta['risk']}</div>
            <div><strong>Key Parameters:</strong> <code>{', '.join(meta['params'])}</code></div>
          </div>
        </div>
        """
    return f"""
    <section id="strategies">
      <h2>4. Strategy Descriptions (7 Strategies)</h2>
      {rows}
    </section>
    """


def section_leaderboard(leaderboard: list) -> str:
    if not leaderboard:
        return '<section id="leaderboard"><h2>5. Top 10 Leaderboard Results</h2><p>No leaderboard data available.</p></section>'

    top10 = leaderboard[:10]
    rows = ""
    for i, entry in enumerate(top10, 1):
        s = entry.get("summary", {})
        c = entry.get("combined", {})
        strats = ", ".join(STRATEGY_META.get(st, {}).get("name", st) for st in entry.get("strategies", []))
        rows += f"""<tr>
          <td>{i}</td>
          <td><code>{entry.get('run_id', 'N/A')[-12:]}</code></td>
          <td>{strats}</td>
          <td class="{color_class(s.get('avg_return'))}">{fmt_pct(s.get('avg_return'), 1, True)}</td>
          <td class="{color_class(s.get('min_return'))}">{fmt_pct(s.get('min_return'), 1, True)}</td>
          <td class="negative">{fmt_pct(s.get('worst_dd'), 1)}</td>
          <td>{fmt_pct(c.get('win_rate'), 1)}</td>
          <td>{fmt_num(entry.get('overfit_score'))}</td>
          <td>{fmt_verdict(entry.get('verdict'))}</td>
        </tr>"""

    # Expandable params for top 3
    param_details = ""
    for i, entry in enumerate(top10[:3], 1):
        sp = entry.get("strategy_params", {})
        param_rows = ""
        for strat_key, params in sp.items():
            strat_name = STRATEGY_META.get(strat_key, {}).get("name", strat_key)
            param_items = ", ".join(f"{k}={v}" for k, v in params.items())
            param_rows += f"<p><strong>{strat_name}:</strong> <code>{param_items}</code></p>"
        param_details += f"""
        <details class="param-details">
          <summary>#{i} Parameters — {entry.get('run_id', 'N/A')[-12:]}</summary>
          <div class="param-content">{param_rows}</div>
        </details>"""

    return f"""
    <section id="leaderboard">
      <h2>5. Top 10 Leaderboard Results</h2>
      <div class="card table-wrapper">
        <table class="data-table">
          <thead><tr>
            <th>#</th><th>Run ID</th><th>Strategies</th><th>Avg Return</th>
            <th>Min Return</th><th>Max DD</th><th>Win Rate</th><th>Overfit</th><th>Verdict</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <div class="card">
        <h3>Parameter Details (Top 3)</h3>
        {param_details}
      </div>
    </section>
    """


def section_walkforward(opt_state: dict, log_tail: str) -> str:
    wf_ratio = opt_state.get("last_wf_ratio")
    wf_oos = opt_state.get("last_wf_oos_return")
    wf_folds = opt_state.get("last_wf_folds_profitable", "N/A")

    # Extract validation checks from log if available
    checks_html = ""
    check_labels = {
        "A": "Cross-year consistency",
        "B": "Walk-forward validation",
        "C": "Parameter sensitivity",
        "D": "Trade count gate",
        "E": "Regime diversity",
        "F": "Drawdown reality",
    }

    import re
    check_pattern = re.compile(r"\[([A-F])\]\s+(.+?)\.\.\.\s+([\d.]+)\s+(pass|fail|skipped)")
    found_checks = {}
    for m in check_pattern.finditer(log_tail):
        letter, name, score, result = m.groups()
        found_checks[letter] = (name.strip(), score, result)

    if found_checks:
        check_rows = ""
        for letter in "ABCDEF":
            if letter in found_checks:
                name, score, result = found_checks[letter]
                result_cls = "positive" if result == "pass" else ("negative" if result == "fail" else "neutral")
                check_rows += f'<tr><td>[{letter}]</td><td>{name}</td><td>{score}</td><td class="{result_cls}">{result.upper()}</td></tr>'
            else:
                check_rows += f'<tr><td>[{letter}]</td><td>{check_labels[letter]}</td><td>—</td><td class="neutral">N/A</td></tr>'
        checks_html = f"""
        <h3>Validation Checks (Latest Run)</h3>
        <table class="data-table compact">
          <thead><tr><th>Check</th><th>Name</th><th>Score</th><th>Result</th></tr></thead>
          <tbody>{check_rows}</tbody>
        </table>"""

    return f"""
    <section id="walkforward">
      <h2>6. Walk-Forward Validation</h2>
      <div class="two-col">
        <div class="card">
          <h3>Expanding Window Method</h3>
          <ul>
            <li><strong>Folds:</strong> 3 (expanding train window, fixed test window)</li>
            <li><strong>Train:</strong> Years 1–N, <strong>Test:</strong> Year N+1</li>
            <li>Optimize on train set, evaluate on unseen test set</li>
            <li>Walk-forward ratio = OOS return / IS return (>0.5 = pass)</li>
          </ul>
        </div>
        <div class="card">
          <h3>Latest Results</h3>
          <div class="stat-grid">
            <div class="stat"><span class="stat-value">{fmt_num(wf_ratio)}</span><span class="stat-label">WF Ratio</span></div>
            <div class="stat"><span class="stat-value {color_class(wf_oos)}">{fmt_pct(wf_oos, 1, True)}</span><span class="stat-label">OOS Return</span></div>
            <div class="stat"><span class="stat-value positive">{wf_folds}</span><span class="stat-label">Folds Profitable</span></div>
          </div>
        </div>
      </div>
      <div class="card">
        <h3>7-Point Validation Framework</h3>
        <table class="data-table compact">
          <thead><tr><th>Check</th><th>Weight</th><th>Criteria</th></tr></thead>
          <tbody>
            <tr><td>[A] Cross-year consistency</td><td>25%</td><td>&ge;80% of years profitable</td></tr>
            <tr><td>[B] Walk-forward validation</td><td>30%</td><td>OOS/IS ratio &ge; 0.5</td></tr>
            <tr><td>[C] Parameter sensitivity</td><td>25%</td><td>Performance stable under &plusmn;perturbation</td></tr>
            <tr><td>[D] Trade count gate</td><td>10%</td><td>&ge;50 trades per year</td></tr>
            <tr><td>[E] Regime diversity</td><td>10%</td><td>Profitable across bull/bear/sideways</td></tr>
            <tr><td>[F] Drawdown reality</td><td>Gate</td><td>Max DD &le; 25% (violations cap score at 0.60)</td></tr>
          </tbody>
        </table>
        <p><strong>Composite score &ge; 0.70 required</strong> for ROBUST verdict.</p>
        {checks_html}
      </div>
    </section>
    """


def section_equity_curves(backtest: dict) -> str:
    if not backtest:
        return '<section id="equity"><h2>7. Equity Curves</h2><p>No backtest data available.</p></section>'

    combined = backtest.get("combined", {})
    equity_curve = combined.get("equity_curve", [])
    yearly = backtest.get("yearly", {})

    # Prepare equity curve data for Canvas
    eq_dates = json.dumps([pt["date"] for pt in equity_curve])
    eq_values = json.dumps([round(pt["equity"], 2) for pt in equity_curve])

    # Prepare yearly bar chart data
    sorted_years = sorted(yearly.keys())
    year_labels = json.dumps(sorted_years)
    year_returns = json.dumps([yearly[y].get("return_pct", 0) for y in sorted_years])

    return f"""
    <section id="equity">
      <h2>7. Equity Curves</h2>
      <div class="card">
        <h3>Portfolio Equity — Credit Spread Strategy (2020–2025)</h3>
        <canvas id="equityChart" width="900" height="350"></canvas>
      </div>
      <div class="card">
        <h3>Per-Year Returns</h3>
        <canvas id="yearlyChart" width="900" height="280"></canvas>
      </div>
    </section>

    <script>
    (function() {{
      // --- Equity Curve ---
      var dates = {eq_dates};
      var values = {eq_values};
      var canvas = document.getElementById('equityChart');
      if (!canvas || !values.length) return;
      var ctx = canvas.getContext('2d');
      var W = canvas.width, H = canvas.height;
      var pad = {{top: 30, right: 30, bottom: 50, left: 80}};
      var plotW = W - pad.left - pad.right;
      var plotH = H - pad.top - pad.bottom;

      var minV = Math.min.apply(null, values);
      var maxV = Math.max.apply(null, values);
      var rangeV = maxV - minV || 1;
      minV -= rangeV * 0.05;
      maxV += rangeV * 0.05;
      rangeV = maxV - minV;

      function xPos(i) {{ return pad.left + (i / (values.length - 1)) * plotW; }}
      function yPos(v) {{ return pad.top + plotH - ((v - minV) / rangeV) * plotH; }}

      // Grid
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 1;
      var nGridY = 5;
      ctx.font = '11px sans-serif';
      ctx.fillStyle = '#718096';
      ctx.textAlign = 'right';
      for (var g = 0; g <= nGridY; g++) {{
        var gv = minV + (rangeV * g / nGridY);
        var gy = yPos(gv);
        ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(W - pad.right, gy); ctx.stroke();
        ctx.fillText('$' + Math.round(gv).toLocaleString(), pad.left - 8, gy + 4);
      }}

      // X labels (years)
      ctx.textAlign = 'center';
      var seenYears = {{}};
      for (var i = 0; i < dates.length; i++) {{
        var yr = dates[i].substring(0, 4);
        if (!seenYears[yr]) {{
          seenYears[yr] = true;
          ctx.fillText(yr, xPos(i), H - pad.bottom + 20);
        }}
      }}

      // Line
      ctx.beginPath();
      ctx.strokeStyle = '#3182ce';
      ctx.lineWidth = 2;
      for (var i = 0; i < values.length; i++) {{
        var x = xPos(i), y = yPos(values[i]);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }}
      ctx.stroke();

      // Fill
      ctx.lineTo(xPos(values.length - 1), pad.top + plotH);
      ctx.lineTo(xPos(0), pad.top + plotH);
      ctx.closePath();
      ctx.fillStyle = 'rgba(49, 130, 206, 0.1)';
      ctx.fill();

      // --- Yearly Bar Chart ---
      var yLabels = {year_labels};
      var yReturns = {year_returns};
      var canvas2 = document.getElementById('yearlyChart');
      if (!canvas2 || !yReturns.length) return;
      var ctx2 = canvas2.getContext('2d');
      var W2 = canvas2.width, H2 = canvas2.height;
      var pad2 = {{top: 30, right: 30, bottom: 40, left: 70}};
      var plotW2 = W2 - pad2.left - pad2.right;
      var plotH2 = H2 - pad2.top - pad2.bottom;
      var n = yLabels.length;
      var barW = Math.min(plotW2 / n * 0.6, 60);
      var gap = (plotW2 - barW * n) / (n + 1);

      var maxR = Math.max.apply(null, yReturns.map(function(v) {{ return Math.abs(v); }}));
      maxR = Math.max(maxR, 1) * 1.2;

      var zeroY = pad2.top + plotH2 / 2;
      function yBar(v) {{ return zeroY - (v / maxR) * (plotH2 / 2); }}

      // Zero line
      ctx2.strokeStyle = '#a0aec0'; ctx2.lineWidth = 1;
      ctx2.beginPath(); ctx2.moveTo(pad2.left, zeroY); ctx2.lineTo(W2 - pad2.right, zeroY); ctx2.stroke();

      // Grid
      ctx2.strokeStyle = '#e2e8f0';
      ctx2.font = '11px sans-serif';
      ctx2.fillStyle = '#718096';
      ctx2.textAlign = 'right';
      var gridSteps = [maxR * 0.5, maxR, -maxR * 0.5, -maxR];
      for (var g = 0; g < gridSteps.length; g++) {{
        var gy2 = yBar(gridSteps[g]);
        ctx2.beginPath(); ctx2.moveTo(pad2.left, gy2); ctx2.lineTo(W2 - pad2.right, gy2); ctx2.stroke();
        ctx2.fillText(gridSteps[g].toFixed(0) + '%', pad2.left - 8, gy2 + 4);
      }}
      ctx2.fillText('0%', pad2.left - 8, zeroY + 4);

      // Bars
      ctx2.textAlign = 'center';
      for (var i = 0; i < n; i++) {{
        var x = pad2.left + gap + i * (barW + gap);
        var y = yBar(yReturns[i]);
        var h = Math.abs(y - zeroY);
        ctx2.fillStyle = yReturns[i] >= 0 ? '#38a169' : '#e53e3e';
        if (yReturns[i] >= 0) {{
          ctx2.fillRect(x, y, barW, h);
        }} else {{
          ctx2.fillRect(x, zeroY, barW, h);
        }}
        // Label
        ctx2.fillStyle = '#2d3748';
        ctx2.font = 'bold 12px sans-serif';
        var labelY = yReturns[i] >= 0 ? y - 6 : zeroY + h + 16;
        ctx2.fillText((yReturns[i] >= 0 ? '+' : '') + yReturns[i].toFixed(1) + '%', x + barW / 2, labelY);
        // Year
        ctx2.fillStyle = '#718096';
        ctx2.font = '12px sans-serif';
        ctx2.fillText(yLabels[i], x + barW / 2, H2 - pad2.bottom + 18);
      }}
    }})();
    </script>
    """


def section_risk_metrics(backtest: dict, leaderboard: list) -> str:
    if not backtest:
        return '<section id="risk"><h2>8. Risk Metrics</h2><p>No backtest data.</p></section>'

    c = backtest.get("combined", {})
    yearly = backtest.get("yearly", {})
    per_strat = backtest.get("per_strategy", {})

    # Yearly table
    yearly_rows = ""
    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        rp = y.get("return_pct", 0)
        yearly_rows += f"""<tr>
          <td>{yr}</td>
          <td class="{color_class(rp)}">{fmt_pct(rp, 1, True)}</td>
          <td>{y.get('trades', y.get('total_trades', 'N/A'))}</td>
          <td>{fmt_pct(y.get('win_rate'), 1)}</td>
          <td class="negative">{fmt_pct(y.get('max_drawdown'), 1)}</td>
          <td class="{color_class(y.get('total_pnl'))}">{fmt_dollar(y.get('total_pnl'))}</td>
        </tr>"""

    # Per-strategy table
    strat_rows = ""
    for cls_name, metrics in per_strat.items():
        reg = CLASS_TO_REGISTRY.get(cls_name, cls_name)
        display = STRATEGY_META.get(reg, {}).get("name", cls_name)
        pnl = metrics.get("total_pnl", 0)
        strat_rows += f"""<tr>
          <td>{display}</td>
          <td>{metrics.get('total_trades', 0)}</td>
          <td>{fmt_pct(metrics.get('win_rate'), 1)}</td>
          <td class="{color_class(pnl)}">{fmt_dollar(pnl)}</td>
          <td>{fmt_dollar(metrics.get('avg_win'))}</td>
          <td>{fmt_dollar(metrics.get('avg_loss'))}</td>
          <td>{fmt_num(metrics.get('profit_factor'))}</td>
        </tr>"""

    return f"""
    <section id="risk">
      <h2>8. Risk Metrics</h2>
      <div class="card">
        <h3>Overall Metrics</h3>
        <div class="stat-grid wide">
          <div class="stat"><span class="stat-value negative">{fmt_pct(c.get('max_drawdown'), 2)}</span><span class="stat-label">Max Drawdown</span></div>
          <div class="stat"><span class="stat-value">{fmt_num(c.get('sharpe_ratio'))}</span><span class="stat-label">Sharpe Ratio</span></div>
          <div class="stat"><span class="stat-value">{fmt_pct(c.get('win_rate'), 1)}</span><span class="stat-label">Win Rate</span></div>
          <div class="stat"><span class="stat-value">{fmt_num(c.get('profit_factor'))}</span><span class="stat-label">Profit Factor</span></div>
          <div class="stat"><span class="stat-value">{fmt_dollar(c.get('avg_win'))}</span><span class="stat-label">Avg Win</span></div>
          <div class="stat"><span class="stat-value">{fmt_dollar(c.get('avg_loss'))}</span><span class="stat-label">Avg Loss</span></div>
          <div class="stat"><span class="stat-value">{c.get('max_win_streak', 'N/A')}</span><span class="stat-label">Max Win Streak</span></div>
          <div class="stat"><span class="stat-value">{c.get('max_loss_streak', 'N/A')}</span><span class="stat-label">Max Loss Streak</span></div>
        </div>
      </div>

      <div class="card">
        <h3>Per-Year Breakdown</h3>
        <table class="data-table">
          <thead><tr><th>Year</th><th>Return</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>P&amp;L</th></tr></thead>
          <tbody>{yearly_rows}</tbody>
        </table>
      </div>

      <div class="card">
        <h3>Per-Strategy Breakdown</h3>
        <table class="data-table">
          <thead><tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>P&amp;L</th><th>Avg Win</th><th>Avg Loss</th><th>Profit Factor</th></tr></thead>
          <tbody>{strat_rows}</tbody>
        </table>
      </div>
    </section>
    """


def section_data_methodology() -> str:
    return """
    <section id="data">
      <h2>9. Data Methodology</h2>
      <div class="two-col">
        <div class="card">
          <h3>Data Source</h3>
          <ul>
            <li><strong>Provider:</strong> Polygon.io — real historical options data</li>
            <li><strong>Contracts Cached:</strong> 526,264 across SPY, QQQ, IWM (2020–2025)</li>
            <li><strong>Storage:</strong> SQLite database, OCC symbol format</li>
            <li><strong>No Synthetic Data:</strong> cache miss = skip trade (no interpolation)</li>
          </ul>
        </div>
        <div class="card">
          <h3>Cache-Only Mode</h3>
          <ul>
            <li>Zero API calls during backtest execution</li>
            <li>All option chains pre-fetched and stored locally</li>
            <li>Ensures reproducible results across runs</li>
            <li>Cache populated via separate data-fetching pipeline</li>
          </ul>
        </div>
      </div>
    </section>
    """


def section_architecture(opt_state: dict) -> str:
    # Phase run counts
    p1 = opt_state.get("phase1_history", {})
    p2 = opt_state.get("phase2_history", [])
    p3 = opt_state.get("phase3_history", [])
    p1_counts = ""
    for strat, runs in sorted(p1.items()):
        best = max((r.get("score", 0) for r in runs), default=0)
        name = STRATEGY_META.get(strat, {}).get("name", strat)
        p1_counts += f"<tr><td>{name}</td><td>{len(runs)}</td><td>{fmt_num(best, 4)}</td></tr>"

    return f"""
    <section id="architecture">
      <h2>10. Architecture &amp; Decisions</h2>

      <div class="card">
        <h3>System Architecture</h3>
        <pre class="ascii-diagram">
┌─────────────────────────────────────────────────────────────────┐
│                      PilotAI Credit Spreads                     │
├──────────────┬──────────────┬──────────────┬────────────────────┤
│  Data Layer  │   Backtest   │  Optimizer   │    Validation      │
│              │   Engine     │              │                    │
│ Polygon.io   │ Portfolio    │ 3-Phase      │ Walk-Forward       │
│ SQLite Cache │ Backtester   │ Heuristic    │ Sensitivity        │
│ Options DB   │ Day-by-Day   │ Optimization │ Regime Diversity   │
│              │ Simulation   │              │ Overfit Score      │
├──────────────┴──────────────┴──────────────┴────────────────────┤
│                    7 Pluggable Strategies                        │
│  Credit Spread │ Iron Condor │ Straddle │ Debit │ Calendar │ ...│
├─────────────────────────────────────────────────────────────────┤
│                    Output / Reporting                            │
│  Leaderboard │ HTML Reports │ Optimizer Logs │ Backtest JSON     │
└─────────────────────────────────────────────────────────────────┘
        </pre>
      </div>

      <div class="two-col">
        <div class="card">
          <h3>Victory Conditions (from MASTERPLAN)</h3>
          <table class="data-table compact">
            <thead><tr><th>Metric</th><th>Target</th></tr></thead>
            <tbody>
              <tr><td>Annual Return</td><td>40–80%</td></tr>
              <tr><td>Max Drawdown</td><td>&le; 20%</td></tr>
              <tr><td>Win Rate</td><td>60–80%</td></tr>
              <tr><td>Sharpe Ratio</td><td>&ge; 1.0</td></tr>
              <tr><td>Profit Factor</td><td>&ge; 1.3</td></tr>
              <tr><td>WF Decay</td><td>&le; 30%</td></tr>
            </tbody>
          </table>
        </div>
        <div class="card">
          <h3>3-Phase Optimization</h3>
          <ol>
            <li><strong>Phase 1 — Single Strategy:</strong> Tune each strategy independently</li>
            <li><strong>Phase 2 — Blending:</strong> Find optimal multi-strategy combos ({len(p2)} runs)</li>
            <li><strong>Phase 3 — Regime-Aware:</strong> Fine-tune for market regimes ({len(p3)} runs)</li>
          </ol>
        </div>
      </div>

      <div class="card">
        <h3>Phase 1: Per-Strategy Optimization Results</h3>
        <table class="data-table compact">
          <thead><tr><th>Strategy</th><th>Runs</th><th>Best Score</th></tr></thead>
          <tbody>{p1_counts}</tbody>
        </table>
      </div>

      <div class="card">
        <h3>Key Files</h3>
        <table class="data-table compact">
          <thead><tr><th>Path</th><th>Purpose</th></tr></thead>
          <tbody>
            <tr><td><code>engine/portfolio_backtester.py</code></td><td>Core day-by-day simulation engine</td></tr>
            <tr><td><code>strategies/*.py</code></td><td>7 pluggable strategy implementations</td></tr>
            <tr><td><code>strategies/pricing.py</code></td><td>Black-Scholes pricing with IV skew</td></tr>
            <tr><td><code>backtest/historical_data.py</code></td><td>Polygon.io data pipeline &amp; SQLite cache</td></tr>
            <tr><td><code>scripts/run_optimization.py</code></td><td>Optimization harness, leaderboard, validation</td></tr>
            <tr><td><code>scripts/endless_optimizer.py</code></td><td>3-phase endless optimization loop</td></tr>
            <tr><td><code>scripts/generate_report.py</code></td><td>Single-strategy HTML report generator</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    """


# ---------------------------------------------------------------------------
# Main HTML template
# ---------------------------------------------------------------------------

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: #ffffff; color: #1a1a2e; line-height: 1.6;
  max-width: 1100px; margin: 0 auto; padding: 24px 32px;
}
h1 { font-size: 2rem; color: #1a1a2e; margin-bottom: 4px; }
h2 {
  font-size: 1.5rem; color: #2d3748; margin: 48px 0 20px;
  padding-bottom: 8px; border-bottom: 2px solid #3182ce;
}
h3 { font-size: 1.1rem; color: #2d3748; margin-bottom: 12px; }
.subtitle { color: #718096; font-size: 0.95rem; margin-bottom: 32px; }
a { color: #3182ce; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Navigation */
nav { background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }
nav a { margin-right: 16px; font-size: 0.85rem; font-weight: 500; white-space: nowrap; }

/* Cards */
.card {
  background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 8px;
  padding: 20px 24px; margin-bottom: 16px;
}
.card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.card.full-width { grid-column: 1 / -1; }

/* Stats */
.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.stat-grid.wide { grid-template-columns: repeat(4, 1fr); }
.stat { text-align: center; }
.stat-value { display: block; font-size: 1.6rem; font-weight: 700; color: #2d3748; }
.stat-label { display: block; font-size: 0.8rem; color: #718096; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }

/* Colors */
.positive { color: #38a169 !important; }
.negative { color: #e53e3e !important; }
.neutral  { color: #d69e2e !important; }

/* Tables */
.table-wrapper { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.data-table th {
  background: #edf2f7; color: #2d3748; font-weight: 600;
  padding: 10px 14px; text-align: left; border-bottom: 2px solid #cbd5e0;
}
.data-table td { padding: 8px 14px; border-bottom: 1px solid #e2e8f0; }
.data-table tbody tr:nth-child(even) { background: #f7fafc; }
.data-table tbody tr:nth-child(odd) { background: #ffffff; }
.data-table.compact th, .data-table.compact td { padding: 6px 10px; }
code { background: #edf2f7; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; }

/* Two column layout */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

/* Pipeline diagram */
.pipeline { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 4px; padding: 12px 0; }
.pipeline-step {
  background: #ebf4ff; border: 1px solid #90cdf4; border-radius: 6px;
  padding: 10px 14px; text-align: center; font-size: 0.85rem; font-weight: 500; color: #2b6cb0;
}
.pipeline-arrow { font-size: 1.4rem; color: #a0aec0; }

/* Strategy cards */
.strategy-card { }
.strategy-details { font-size: 0.9rem; }
.strategy-details div { margin-bottom: 4px; }

/* Details / expandable */
details.param-details { margin: 8px 0; }
details.param-details summary {
  cursor: pointer; font-weight: 600; color: #3182ce; padding: 6px 0;
}
.param-content { padding: 8px 16px; background: #ffffff; border-radius: 4px; margin-top: 4px; }
.param-content p { margin: 4px 0; font-size: 0.85rem; word-break: break-all; }

/* ASCII diagram */
.ascii-diagram {
  background: #1a1a2e; color: #a0d2db; padding: 20px;
  border-radius: 8px; overflow-x: auto; font-size: 0.82rem;
  line-height: 1.4;
}

/* Canvas */
canvas { width: 100%; height: auto; display: block; }

/* Footer */
footer { margin-top: 48px; padding: 20px 0; border-top: 1px solid #e2e8f0; color: #a0aec0; font-size: 0.8rem; text-align: center; }

/* Print */
@media print {
  body { max-width: 100%; padding: 0; }
  .card { break-inside: avoid; }
  nav { display: none; }
}

/* Responsive */
@media (max-width: 768px) {
  .card-grid, .two-col, .stat-grid, .stat-grid.wide { grid-template-columns: 1fr; }
  .pipeline { flex-direction: column; }
  .pipeline-arrow { transform: rotate(90deg); }
}
"""


def build_html(sections: list[str], generated_at: str) -> str:
    nav_links = [
        ("executive-summary", "1. Executive Summary"),
        ("methodology", "2. Methodology"),
        ("position-sizing", "3. Position Sizing"),
        ("strategies", "4. Strategies"),
        ("leaderboard", "5. Leaderboard"),
        ("walkforward", "6. Walk-Forward"),
        ("equity", "7. Equity Curves"),
        ("risk", "8. Risk Metrics"),
        ("data", "9. Data"),
        ("architecture", "10. Architecture"),
    ]
    nav_html = " ".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in nav_links)
    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PilotAI Credit Spreads — Full Backtest Report</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <h1>PilotAI Credit Spreads</h1>
    <p class="subtitle">Comprehensive Backtest &amp; Optimization Report &mdash; Generated {generated_at}</p>
  </header>

  <nav>{nav_html}</nav>

  {body}

  <footer>
    PilotAI Credit Spreads &mdash; Report generated {generated_at}
  </footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  PilotAI — Full Report Generator")
    print("=" * 60)

    # Load data sources
    print("\nLoading data sources...")
    leaderboard = load_json(OUTPUT / "leaderboard.json") or []
    opt_state = load_json(OUTPUT / "optimization_state.json") or {}

    bt_path = find_latest_backtest()
    if bt_path:
        print(f"  Backtest: {bt_path.name}")
        backtest = load_json(bt_path) or {}
    else:
        print("  [WARN] No portfolio_backtest_*.json found")
        backtest = {}

    log_tail = load_log_tail(OUTPUT / "optimizer_run.log")
    print(f"  Leaderboard: {len(leaderboard)} entries")
    print(f"  Optimizer state: phase={opt_state.get('current_phase', 'N/A')}, "
          f"runs={opt_state.get('total_runs', 0)}")

    # Build sections
    print("\nBuilding report sections...")
    sections = [
        section_executive_summary(backtest, opt_state, leaderboard),
        section_methodology(),
        section_position_sizing(),
        section_strategies(),
        section_leaderboard(leaderboard),
        section_walkforward(opt_state, log_tail),
        section_equity_curves(backtest),
        section_risk_metrics(backtest, leaderboard),
        section_data_methodology(),
        section_architecture(opt_state),
    ]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = build_html(sections, generated_at)

    # Write output
    out_path = OUTPUT / "full_report.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)

    size_kb = out_path.stat().st_size / 1024
    print(f"\n  Report written to: {out_path}")
    print(f"  Size: {size_kb:.1f} KB")
    print(f"  Sections: {len(sections)}")
    print("  Done.")


if __name__ == "__main__":
    main()
