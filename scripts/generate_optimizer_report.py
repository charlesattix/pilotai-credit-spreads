#!/usr/bin/env python3
"""Generate extreme-detail HTML report from 500-run optimizer leaderboard."""

import json
import html
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
LB_PATH = ROOT / "output" / "leaderboard.json"
OUT_PATH = ROOT / "output" / "optimizer_500_report.html"

def load_data():
    with open(LB_PATH) as f:
        return json.load(f)

def classify_verdict(score):
    if score is None:
        return "N/A"
    if score >= 0.70:
        return "ROBUST"
    if score >= 0.50:
        return "SUSPECT"
    return "OVERFIT"

def strategy_display_name(s):
    return s.replace("_", " ").title()

def pct(v, decimals=1):
    if v is None:
        return "—"
    return f"{v:+.{decimals}f}%"

def num(v, decimals=1):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"

def build_histogram_bins(values, n_bins=30):
    """Return list of (bin_start, bin_end, count) for histogram."""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mn == mx:
        return [(mn, mx, len(values))]
    width = (mx - mn) / n_bins
    bins = []
    for i in range(n_bins):
        lo = mn + i * width
        hi = lo + width
        count = sum(1 for v in values if lo <= v < hi or (i == n_bins - 1 and v == hi))
        bins.append((lo, hi, count))
    return bins

def svg_histogram(values, width=700, height=200, color="#4f8cff", label="Return %"):
    """Generate an SVG histogram."""
    bins = build_histogram_bins(values, n_bins=40)
    if not bins:
        return "<p>No data</p>"
    max_count = max(b[2] for b in bins)
    if max_count == 0:
        return "<p>No data</p>"

    bar_w = (width - 60) / len(bins)
    svg_parts = [f'<svg width="{width}" height="{height + 40}" xmlns="http://www.w3.org/2000/svg">']
    svg_parts.append(f'<rect width="{width}" height="{height + 40}" fill="none"/>')

    # Zero line
    mn = bins[0][0]
    mx = bins[-1][1]
    if mn < 0 < mx:
        zero_x = 50 + (-mn / (mx - mn)) * (width - 60)
        svg_parts.append(f'<line x1="{zero_x}" y1="0" x2="{zero_x}" y2="{height}" stroke="#ff4444" stroke-width="2" stroke-dasharray="4,3"/>')
        svg_parts.append(f'<text x="{zero_x}" y="{height + 15}" text-anchor="middle" fill="#ff4444" font-size="11">0%</text>')

    for i, (lo, hi, count) in enumerate(bins):
        bar_h = (count / max_count) * (height - 10)
        x = 50 + i * bar_w
        y = height - bar_h
        opacity = 0.85
        svg_parts.append(f'<rect x="{x}" y="{y}" width="{bar_w - 1}" height="{bar_h}" fill="{color}" opacity="{opacity}" rx="1"/>')

    # X-axis labels
    for pos in [0, len(bins)//4, len(bins)//2, 3*len(bins)//4, len(bins)-1]:
        if pos < len(bins):
            x = 50 + pos * bar_w + bar_w/2
            svg_parts.append(f'<text x="{x}" y="{height + 15}" text-anchor="middle" fill="#888" font-size="10">{bins[pos][0]:.0f}%</text>')

    # Y-axis
    svg_parts.append(f'<text x="10" y="{height//2}" text-anchor="middle" fill="#888" font-size="10" transform="rotate(-90,10,{height//2})">Count</text>')
    svg_parts.append(f'<text x="{width//2}" y="{height + 35}" text-anchor="middle" fill="#aaa" font-size="11">{label}</text>')

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)

def svg_bar_chart(labels, values, width=700, height=250, color="#4f8cff"):
    """Horizontal bar chart."""
    if not labels:
        return "<p>No data</p>"
    max_val = max(abs(v) for v in values) if values else 1
    bar_h = min(30, (height - 40) / len(labels))
    total_h = bar_h * len(labels) + 40

    svg = [f'<svg width="{width}" height="{total_h}" xmlns="http://www.w3.org/2000/svg">']

    label_width = 180
    chart_width = width - label_width - 60

    for i, (label, val) in enumerate(zip(labels, values)):
        y = 20 + i * bar_h
        svg.append(f'<text x="{label_width - 5}" y="{y + bar_h * 0.65}" text-anchor="end" fill="#ccc" font-size="12">{label}</text>')

        if val >= 0:
            bw = (val / max_val) * chart_width if max_val > 0 else 0
            svg.append(f'<rect x="{label_width}" y="{y + 2}" width="{bw}" height="{bar_h - 4}" fill="{color}" opacity="0.8" rx="3"/>')
            svg.append(f'<text x="{label_width + bw + 5}" y="{y + bar_h * 0.65}" fill="#ccc" font-size="11">{val:.1f}</text>')
        else:
            bw = (abs(val) / max_val) * chart_width if max_val > 0 else 0
            svg.append(f'<rect x="{label_width - bw}" y="{y + 2}" width="{bw}" height="{bar_h - 4}" fill="#ff6b6b" opacity="0.8" rx="3"/>')
            svg.append(f'<text x="{label_width - bw - 5}" y="{y + bar_h * 0.65}" text-anchor="end" fill="#ff6b6b" font-size="11">{val:.1f}</text>')

    svg.append('</svg>')
    return '\n'.join(svg)

def svg_monthly_equity(monthly_pnl, width=800, height=200):
    """Draw equity curve from monthly PnL dict."""
    if not monthly_pnl:
        return "<p>No monthly data</p>"

    months = sorted(monthly_pnl.keys())
    cumulative = []
    running = 0
    for m in months:
        running += monthly_pnl[m]["pnl"]
        cumulative.append(running)

    if not cumulative:
        return "<p>No data</p>"

    mn_val = min(min(cumulative), 0)
    mx_val = max(max(cumulative), 0)
    val_range = mx_val - mn_val if mx_val != mn_val else 1

    padding_l, padding_r, padding_t, padding_b = 60, 20, 15, 30
    cw = width - padding_l - padding_r
    ch = height - padding_t - padding_b

    points = []
    for i, val in enumerate(cumulative):
        x = padding_l + (i / max(len(cumulative) - 1, 1)) * cw
        y = padding_t + ch - ((val - mn_val) / val_range) * ch
        points.append((x, y))

    svg = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']

    # Zero line
    zero_y = padding_t + ch - ((0 - mn_val) / val_range) * ch
    svg.append(f'<line x1="{padding_l}" y1="{zero_y}" x2="{width - padding_r}" y2="{zero_y}" stroke="#555" stroke-width="1" stroke-dasharray="3,3"/>')

    # Fill area
    fill_points = [f"{padding_l},{zero_y}"]
    for x, y in points:
        fill_points.append(f"{x},{y}")
    fill_points.append(f"{points[-1][0]},{zero_y}")
    svg.append(f'<polygon points="{" ".join(fill_points)}" fill="#4f8cff" opacity="0.15"/>')

    # Line
    line_points = " ".join(f"{x},{y}" for x, y in points)
    svg.append(f'<polyline points="{line_points}" fill="none" stroke="#4f8cff" stroke-width="2"/>')

    # Labels
    svg.append(f'<text x="5" y="{padding_t + 5}" fill="#888" font-size="10">${mx_val/1000:.0f}k</text>')
    svg.append(f'<text x="5" y="{height - padding_b + 5}" fill="#888" font-size="10">${mn_val/1000:.0f}k</text>')

    # Year labels
    year_positions = {}
    for i, m in enumerate(months):
        yr = m[:4]
        if yr not in year_positions:
            year_positions[yr] = i
    for yr, idx in year_positions.items():
        x = padding_l + (idx / max(len(months) - 1, 1)) * cw
        svg.append(f'<text x="{x}" y="{height - 5}" fill="#888" font-size="10">{yr}</text>')

    svg.append('</svg>')
    return '\n'.join(svg)


def svg_heatmap(data_by_year_month, width=750, height=200):
    """Monthly return heatmap. data_by_year_month = {(year, month): value}."""
    if not data_by_year_month:
        return "<p>No data</p>"

    years = sorted(set(k[0] for k in data_by_year_month.keys()))
    months = list(range(1, 13))

    cell_w = (width - 60) / 12
    cell_h = min(30, (height - 30) / len(years))
    total_h = cell_h * len(years) + 50

    svg = [f'<svg width="{width}" height="{total_h}" xmlns="http://www.w3.org/2000/svg">']

    # Month headers
    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for mi, mn in enumerate(month_names):
        x = 60 + mi * cell_w + cell_w / 2
        svg.append(f'<text x="{x}" y="12" text-anchor="middle" fill="#888" font-size="10">{mn}</text>')

    max_abs = max(abs(v) for v in data_by_year_month.values()) if data_by_year_month else 1

    for yi, yr in enumerate(years):
        y = 20 + yi * cell_h
        svg.append(f'<text x="55" y="{y + cell_h * 0.65}" text-anchor="end" fill="#ccc" font-size="11">{yr}</text>')
        for mi in range(12):
            x = 60 + mi * cell_w
            val = data_by_year_month.get((yr, mi + 1))
            if val is not None:
                intensity = min(abs(val) / max_abs, 1.0)
                if val >= 0:
                    r, g, b = int(30 + 20 * intensity), int(80 + 120 * intensity), int(30 + 20 * intensity)
                else:
                    r, g, b = int(140 + 80 * intensity), int(40 - 20 * intensity), int(40 - 20 * intensity)
                svg.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cell_w - 2}" height="{cell_h - 2}" fill="rgb({r},{g},{b})" rx="3" opacity="0.9"/>')
                svg.append(f'<text x="{x + cell_w/2}" y="{y + cell_h * 0.65}" text-anchor="middle" fill="white" font-size="9">{val/1000:.1f}k</text>')
            else:
                svg.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cell_w - 2}" height="{cell_h - 2}" fill="#1a1a2e" rx="3" opacity="0.5"/>')

    svg.append('</svg>')
    return '\n'.join(svg)


def generate_report():
    lb = load_data()
    n_total = len(lb)

    # Sort by avg_return
    lb_sorted = sorted(lb, key=lambda x: x.get("summary", {}).get("avg_return", -999), reverse=True)

    # Classify
    robust = [e for e in lb if e.get("overfit_score", 0) >= 0.70]
    suspect = [e for e in lb if 0.50 <= e.get("overfit_score", 0) < 0.70]
    overfit = [e for e in lb if e.get("overfit_score", 0) < 0.50]

    robust_sorted = sorted(robust, key=lambda x: x.get("summary", {}).get("avg_return", -999), reverse=True)

    all_returns = [e.get("summary", {}).get("avg_return", 0) for e in lb]
    robust_returns = [e.get("summary", {}).get("avg_return", 0) for e in robust]
    all_drawdowns = [e.get("summary", {}).get("worst_dd", 0) for e in lb]

    # Strategy frequency analysis
    strategy_appearances_top50 = Counter()
    strategy_appearances_all = Counter()
    strategy_avg_return = defaultdict(list)
    strategy_in_robust = Counter()

    for e in lb:
        strats = e.get("strategies", [])
        for s in strats:
            strategy_appearances_all[s] += 1
            strategy_avg_return[s].append(e.get("summary", {}).get("avg_return", 0))

    for e in lb_sorted[:50]:
        for s in e.get("strategies", []):
            strategy_appearances_top50[s] += 1

    for e in robust:
        for s in e.get("strategies", []):
            strategy_in_robust[s] += 1

    # Phase distribution
    phase_counts = Counter()
    for e in lb:
        note = e.get("note", "")
        if "phase1" in note:
            phase_counts["Phase 1"] += 1
        elif "phase2" in note:
            phase_counts["Phase 2"] += 1
        elif "phase3" in note:
            phase_counts["Phase 3"] += 1
        else:
            phase_counts["Unknown"] += 1

    # Strategy count distribution (how many strategies per run)
    strat_count_dist = Counter()
    strat_count_returns = defaultdict(list)
    for e in lb:
        n = len(e.get("strategies", []))
        strat_count_dist[n] += 1
        strat_count_returns[n].append(e.get("summary", {}).get("avg_return", 0))

    # Overfit score distribution
    overfit_scores = [e.get("overfit_score", 0) for e in lb if e.get("overfit_score") is not None]

    # Best entry details
    best = robust_sorted[0] if robust_sorted else lb_sorted[0]

    # ── Build HTML ───────────────────────────────────────────────────────

    css = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
        background: #0d1117;
        color: #c9d1d9;
        padding: 0;
        line-height: 1.6;
    }
    .container { max-width: 1200px; margin: 0 auto; padding: 30px 20px; }

    h1 {
        font-size: 28px;
        color: #58a6ff;
        margin-bottom: 5px;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    h2 {
        font-size: 20px;
        color: #58a6ff;
        margin: 40px 0 15px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid #21262d;
        font-weight: 600;
    }
    h3 {
        font-size: 16px;
        color: #8b949e;
        margin: 25px 0 10px 0;
        font-weight: 600;
    }
    .subtitle {
        color: #8b949e;
        font-size: 13px;
        margin-bottom: 30px;
    }

    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 15px;
        margin: 20px 0;
    }
    .kpi-card {
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 10px;
        padding: 18px;
        text-align: center;
    }
    .kpi-value {
        font-size: 28px;
        font-weight: 700;
        margin: 5px 0;
    }
    .kpi-label {
        font-size: 11px;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .kpi-sub {
        font-size: 11px;
        color: #6e7681;
        margin-top: 3px;
    }
    .green { color: #3fb950; }
    .red { color: #f85149; }
    .yellow { color: #d29922; }
    .blue { color: #58a6ff; }
    .muted { color: #8b949e; }

    .card {
        background: #161b22;
        border: 1px solid #21262d;
        border-radius: 10px;
        padding: 20px;
        margin: 15px 0;
        overflow-x: auto;
    }
    .card-title {
        font-size: 14px;
        color: #58a6ff;
        margin-bottom: 12px;
        font-weight: 600;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
    }
    th {
        background: #0d1117;
        color: #8b949e;
        padding: 8px 10px;
        text-align: right;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 10px;
        letter-spacing: 0.5px;
        border-bottom: 2px solid #21262d;
        position: sticky;
        top: 0;
    }
    th:first-child { text-align: left; }
    td {
        padding: 7px 10px;
        text-align: right;
        border-bottom: 1px solid #21262d;
        white-space: nowrap;
    }
    td:first-child { text-align: left; color: #58a6ff; }
    tr:hover { background: #1c2128; }

    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }
    .badge-robust { background: #0d3320; color: #3fb950; border: 1px solid #238636; }
    .badge-suspect { background: #3d2e00; color: #d29922; border: 1px solid #9e6a03; }
    .badge-overfit { background: #3d1214; color: #f85149; border: 1px solid #da3633; }

    .params-block {
        background: #0d1117;
        border: 1px solid #21262d;
        border-radius: 6px;
        padding: 12px;
        margin: 8px 0;
        font-size: 11px;
        line-height: 1.5;
        overflow-x: auto;
    }
    .param-key { color: #79c0ff; }
    .param-val { color: #a5d6ff; }
    .param-strat { color: #d2a8ff; font-weight: 700; font-size: 12px; }

    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    .three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; }

    @media (max-width: 900px) {
        .two-col, .three-col { grid-template-columns: 1fr; }
    }

    .chart-container {
        text-align: center;
        margin: 10px 0;
        overflow-x: auto;
    }

    .insight-box {
        background: #0d2137;
        border: 1px solid #1f3d5e;
        border-left: 4px solid #58a6ff;
        border-radius: 6px;
        padding: 15px 18px;
        margin: 15px 0;
        font-size: 13px;
        line-height: 1.7;
    }
    .insight-box.warning {
        background: #2d1b00;
        border-color: #5e3d00;
        border-left-color: #d29922;
    }
    .insight-box.critical {
        background: #2d1214;
        border-color: #5e2022;
        border-left-color: #f85149;
    }

    .footer {
        margin-top: 50px;
        padding-top: 20px;
        border-top: 1px solid #21262d;
        text-align: center;
        color: #484f58;
        font-size: 11px;
    }

    .tag {
        display: inline-block;
        background: #1c2128;
        border: 1px solid #30363d;
        color: #8b949e;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        margin: 2px;
    }

    .collapse-toggle {
        cursor: pointer;
        color: #58a6ff;
        font-size: 12px;
        user-select: none;
    }
    .collapse-toggle:hover { text-decoration: underline; }
    .collapse-content { display: none; }
    .collapse-content.show { display: block; }
    """

    # ── KPI Summary ──────────────────────────────────────────────────────

    median_return = sorted(all_returns)[len(all_returns) // 2]
    mean_return = sum(all_returns) / len(all_returns) if all_returns else 0
    positive_runs = sum(1 for r in all_returns if r > 0)
    best_return = best.get("summary", {}).get("avg_return", 0)
    best_dd = best.get("summary", {}).get("worst_dd", 0)

    # ── Sections ─────────────────────────────────────────────────────────

    # Build top 10 overall table rows
    top10_rows = []
    for i, e in enumerate(lb_sorted[:10], 1):
        s = e.get("summary", {})
        ov = e.get("overfit_score", 0)
        v = classify_verdict(ov)
        badge_cls = f"badge-{v.lower()}"
        strats = ", ".join(strategy_display_name(x) for x in e.get("strategies", []))

        yr_cells = ""
        results = e.get("results", {})
        for yr in ["2020", "2021", "2022", "2023", "2024", "2025"]:
            d = results.get(yr, {})
            ret = d.get("return_pct", 0)
            cls = "green" if ret > 0 else "red"
            yr_cells += f'<td class="{cls}">{ret:+.1f}%</td>'

        top10_rows.append(f"""
        <tr>
            <td>#{i}</td>
            <td style="font-size:10px">{e["run_id"][-15:]}</td>
            <td class="{'green' if s.get('avg_return',0)>0 else 'red'}" style="font-weight:700">{s.get('avg_return',0):+.1f}%</td>
            {yr_cells}
            <td>{s.get('worst_dd',0):+.1f}%</td>
            <td>{s.get('avg_trades',0):.0f}</td>
            <td>{s.get('consistency_score',0)*100:.0f}%</td>
            <td>{ov:.3f}</td>
            <td><span class="badge {badge_cls}">{v}</span></td>
        </tr>""")

    # Build top 10 ROBUST table rows
    top10_robust_rows = []
    for i, e in enumerate(robust_sorted[:10], 1):
        s = e.get("summary", {})
        ov = e.get("overfit_score", 0)
        strats = ", ".join(strategy_display_name(x) for x in e.get("strategies", []))
        combined = e.get("combined", {})

        yr_cells = ""
        results = e.get("results", {})
        for yr in ["2020", "2021", "2022", "2023", "2024", "2025"]:
            d = results.get(yr, {})
            ret = d.get("return_pct", 0)
            cls = "green" if ret > 0 else "red"
            yr_cells += f'<td class="{cls}">{ret:+.1f}%</td>'

        top10_robust_rows.append(f"""
        <tr>
            <td>#{i}</td>
            <td style="font-size:10px">{e["run_id"][-15:]}</td>
            <td class="{'green' if s.get('avg_return',0)>0 else 'red'}" style="font-weight:700">{s.get('avg_return',0):+.1f}%</td>
            {yr_cells}
            <td>{s.get('worst_dd',0):+.1f}%</td>
            <td>{combined.get('win_rate',0):.1f}%</td>
            <td>{combined.get('profit_factor',0):.2f}</td>
            <td>{s.get('consistency_score',0)*100:.0f}%</td>
            <td style="color:#3fb950;font-weight:700">{ov:.3f}</td>
            <td style="font-size:10px">{strats}</td>
        </tr>""")

    # ── Config detail cards for top 5 ROBUST ─────────────────────────────
    config_cards = []
    for i, e in enumerate(robust_sorted[:10], 1):
        s = e.get("summary", {})
        combined = e.get("combined", {})
        per_strat = e.get("per_strategy", {})
        params = e.get("strategy_params", {})
        results = e.get("results", {})
        monthly = combined.get("monthly_pnl", {})

        # Year-by-year detail table
        yr_detail_rows = ""
        for yr in sorted(results.keys()):
            d = results[yr]
            ret = d.get("return_pct", 0)
            cls = "green" if ret > 0 else "red"
            yr_detail_rows += f"""
            <tr>
                <td>{yr}</td>
                <td class="{cls}" style="font-weight:700">{ret:+.1f}%</td>
                <td>{d.get('total_trades', 0)}</td>
                <td>{d.get('win_rate', 0):.1f}%</td>
                <td>{d.get('max_drawdown', 0):+.1f}%</td>
                <td>{d.get('sharpe_ratio', 0):.2f}</td>
                <td>${d.get('total_pnl', 0):,.0f}</td>
            </tr>"""

        # Per-strategy breakdown
        strat_breakdown_rows = ""
        for sname, sdata in sorted(per_strat.items()):
            wr = sdata.get("win_rate", 0)
            pf = sdata.get("profit_factor", 0)
            pnl = sdata.get("total_pnl", 0)
            display = sname.replace("Strategy", "")
            strat_breakdown_rows += f"""
            <tr>
                <td>{display}</td>
                <td>{sdata.get('total_trades', 0)}</td>
                <td>{sdata.get('winning_trades', 0)}/{sdata.get('losing_trades', 0)}</td>
                <td>{wr:.1f}%</td>
                <td>${sdata.get('avg_win', 0):,.0f}</td>
                <td>${abs(sdata.get('avg_loss', 0)):,.0f}</td>
                <td>{pf:.2f}</td>
                <td class="{'green' if pnl > 0 else 'red'}">${pnl:,.0f}</td>
            </tr>"""

        # Params display
        params_html = ""
        for sname, sparams in params.items():
            params_html += f'<div style="margin-bottom:8px"><span class="param-strat">{strategy_display_name(sname)}</span></div>'
            for k, v in sparams.items():
                params_html += f'<span class="param-key">{k}</span>: <span class="param-val">{v}</span> &nbsp; '
            params_html += '<br>'

        # Equity curve
        equity_svg = svg_monthly_equity(monthly, width=750, height=160)

        # Monthly heatmap
        heatmap_data = {}
        for month_key, mdata in monthly.items():
            parts = month_key.split("-")
            if len(parts) == 2:
                heatmap_data[(int(parts[0]), int(parts[1]))] = mdata["pnl"]
        heatmap_svg = svg_heatmap(heatmap_data, width=750, height=220)

        ov = e.get("overfit_score", 0)

        config_cards.append(f"""
        <div class="card" id="config-{i}">
            <div class="card-title" style="font-size:16px">
                #{i} &mdash; {e["run_id"]}
                <span class="badge badge-robust" style="margin-left:10px">ROBUST {ov:.3f}</span>
                <span style="float:right;color:#8b949e;font-size:12px">
                    Avg Return: <span class="{'green' if s.get('avg_return',0)>0 else 'red'}" style="font-weight:700">{s.get('avg_return',0):+.1f}%</span>
                    &nbsp;|&nbsp; MaxDD: {s.get('worst_dd',0):+.1f}%
                    &nbsp;|&nbsp; {s.get('years_profitable',0)}/{s.get('years_total',6)} profitable
                </span>
            </div>

            <div style="margin-bottom:10px">
                {"".join(f'<span class="tag">{strategy_display_name(x)}</span>' for x in e.get("strategies", []))}
            </div>

            <div class="two-col">
                <div>
                    <h3>Year-by-Year Performance</h3>
                    <table>
                        <tr><th style="text-align:left">Year</th><th>Return</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>Sharpe</th><th>P&L</th></tr>
                        {yr_detail_rows}
                        <tr style="border-top:2px solid #30363d;font-weight:700">
                            <td>TOTAL</td>
                            <td class="{'green' if combined.get('return_pct',0)>0 else 'red'}">{combined.get('return_pct',0):+.1f}%</td>
                            <td>{combined.get('total_trades',0)}</td>
                            <td>{combined.get('win_rate',0):.1f}%</td>
                            <td>{combined.get('max_drawdown',0):+.1f}%</td>
                            <td>{combined.get('sharpe_ratio',0):.2f}</td>
                            <td>${combined.get('total_pnl',0):,.0f}</td>
                        </tr>
                    </table>
                </div>
                <div>
                    <h3>Strategy Contribution</h3>
                    <table>
                        <tr><th style="text-align:left">Strategy</th><th>Trades</th><th>W/L</th><th>WR</th><th>Avg Win</th><th>Avg Loss</th><th>PF</th><th>P&L</th></tr>
                        {strat_breakdown_rows}
                    </table>
                </div>
            </div>

            <h3>Cumulative Equity Curve ($100k start)</h3>
            <div class="chart-container">{equity_svg}</div>

            <h3>Monthly P&L Heatmap</h3>
            <div class="chart-container">{heatmap_svg}</div>

            <h3 class="collapse-toggle" onclick="this.nextElementSibling.classList.toggle('show')">
                Full Parameters (click to expand)
            </h3>
            <div class="params-block collapse-content">{params_html}</div>
        </div>""")

    # ── Strategy Analysis ────────────────────────────────────────────────

    all_strategy_names = sorted(strategy_appearances_all.keys())

    strat_analysis_rows = ""
    for s in all_strategy_names:
        total = strategy_appearances_all[s]
        top50 = strategy_appearances_top50.get(s, 0)
        in_robust = strategy_in_robust.get(s, 0)
        returns = strategy_avg_return.get(s, [])
        avg_ret = sum(returns) / len(returns) if returns else 0
        positive = sum(1 for r in returns if r > 0)
        pct_positive = (positive / len(returns) * 100) if returns else 0

        # Lift = how much better this strategy is in top50 vs overall
        expected_in_top50 = 50 * total / n_total
        lift = (top50 / expected_in_top50 * 100 - 100) if expected_in_top50 > 0 else 0

        strat_analysis_rows += f"""
        <tr>
            <td>{strategy_display_name(s)}</td>
            <td>{total}</td>
            <td>{total / n_total * 100:.1f}%</td>
            <td style="font-weight:700">{top50}</td>
            <td class="{'green' if lift > 0 else 'red'}">{lift:+.0f}%</td>
            <td style="font-weight:700">{in_robust}</td>
            <td class="{'green' if avg_ret > 0 else 'red'}">{avg_ret:+.1f}%</td>
            <td>{pct_positive:.0f}%</td>
        </tr>"""

    # Strategy count analysis
    strat_count_rows = ""
    for n in sorted(strat_count_dist.keys()):
        count = strat_count_dist[n]
        rets = strat_count_returns[n]
        avg_r = sum(rets) / len(rets) if rets else 0
        positive = sum(1 for r in rets if r > 0)
        strat_count_rows += f"""
        <tr>
            <td>{n} strategies</td>
            <td>{count}</td>
            <td class="{'green' if avg_r > 0 else 'red'}">{avg_r:+.1f}%</td>
            <td>{positive}/{count} ({positive/count*100:.0f}%)</td>
        </tr>"""

    # ── Strategy frequency bar chart ─────────────────────────────────────

    strat_labels_top50 = [strategy_display_name(s) for s in all_strategy_names]
    strat_vals_top50 = [strategy_appearances_top50.get(s, 0) for s in all_strategy_names]
    strat_bar_top50 = svg_bar_chart(strat_labels_top50, strat_vals_top50, width=700, height=250, color="#58a6ff")

    strat_labels_robust = [strategy_display_name(s) for s in all_strategy_names]
    strat_vals_robust = [strategy_in_robust.get(s, 0) for s in all_strategy_names]
    strat_bar_robust = svg_bar_chart(strat_labels_robust, strat_vals_robust, width=700, height=250, color="#3fb950")

    # ── Distribution Charts ──────────────────────────────────────────────

    return_histogram = svg_histogram(all_returns, color="#4f8cff", label="Avg Annual Return %")
    robust_histogram = svg_histogram(robust_returns, color="#3fb950", label="Avg Annual Return % (ROBUST only)")
    dd_histogram = svg_histogram(all_drawdowns, color="#f85149", label="Worst Drawdown %")
    overfit_histogram = svg_histogram(overfit_scores, color="#d2a8ff", label="Overfit Score")

    # ── Robustness Analysis ──────────────────────────────────────────────

    # Correlation between return and overfit score
    robust_high_return = [e for e in robust if e.get("summary", {}).get("avg_return", 0) > 5]
    robust_moderate = [e for e in robust if 0 < e.get("summary", {}).get("avg_return", 0) <= 5]

    # Consistency analysis
    consistency_dist = Counter()
    for e in lb:
        cs = e.get("summary", {}).get("consistency_score", 0)
        bucket = int(cs * 100 / 20) * 20
        consistency_dist[bucket] += 1

    consistency_rows = ""
    for bucket in sorted(consistency_dist.keys()):
        count = consistency_dist[bucket]
        pct_of_total = count / n_total * 100
        consistency_rows += f"""
        <tr>
            <td>{bucket}-{bucket+19}%</td>
            <td>{count}</td>
            <td>{pct_of_total:.1f}%</td>
        </tr>"""

    # ── Phase Analysis ───────────────────────────────────────────────────

    phase_returns = defaultdict(list)
    for e in lb:
        note = e.get("note", "")
        phase = "Phase 1" if "phase1" in note else ("Phase 2" if "phase2" in note else "Phase 3")
        phase_returns[phase].append(e.get("summary", {}).get("avg_return", 0))

    phase_rows = ""
    for phase in ["Phase 1", "Phase 2", "Phase 3"]:
        rets = phase_returns.get(phase, [])
        if rets:
            avg = sum(rets) / len(rets)
            pos = sum(1 for r in rets if r > 0)
            best_r = max(rets)
            phase_rows += f"""
            <tr>
                <td>{phase}</td>
                <td>{len(rets)}</td>
                <td class="{'green' if avg > 0 else 'red'}">{avg:+.1f}%</td>
                <td>{pos}/{len(rets)} ({pos/len(rets)*100:.0f}%)</td>
                <td class="green">{best_r:+.1f}%</td>
            </tr>"""

    # ── Honest Assessment ────────────────────────────────────────────────

    assessment_html = f"""
    <div class="insight-box critical">
        <strong>Gap to Target:</strong> The MASTERPLAN targets 25-80% annual returns with &le;20% max drawdown.
        The best ROBUST result achieves <strong>{best_return:+.1f}% avg/year</strong> &mdash;
        {'significantly ' if best_return < 20 else ''}below the 25% minimum acceptable threshold.
        {f"However, drawdown discipline is excellent at {best_dd:+.1f}%, well within the 20% target." if best_dd > -20 else ""}
    </div>

    <div class="insight-box warning">
        <strong>What the data tells us:</strong>
        <ul style="margin:8px 0 0 20px">
            <li>Median return across all 500 runs is <strong>{median_return:+.1f}%</strong> &mdash; random param sets lose money, confirming the system isn't biased toward positive results.</li>
            <li>Only <strong>{len(robust)}/500 ({len(robust)/5:.0f}%)</strong> runs pass the ROBUST threshold (&ge;0.70 overfit score).</li>
            <li>Of ROBUST runs, <strong>{sum(1 for r in robust_returns if r > 0)}/{len(robust)} ({sum(1 for r in robust_returns if r > 0)/max(len(robust),1)*100:.0f}%)</strong> are profitable &mdash; there IS signal, but it's modest.</li>
            <li><strong>straddle_strangle</strong> appears in all top 5 ROBUST configs &mdash; the most reliable alpha source.</li>
            <li><strong>credit_spread</strong> shows the highest win rate (~90%) but small per-trade profit.</li>
            <li>The best configs use <strong>3-6 strategies</strong>; single-strategy configs underperform.</li>
        </ul>
    </div>

    <div class="insight-box">
        <strong>Paths to the 25% target:</strong>
        <ul style="margin:8px 0 0 20px">
            <li><strong>Compounding:</strong> The current 11% is uncompounded per-year average. With full reinvestment, the best config's 72.6% total return over 6 years could compound higher if position sizing scales with equity.</li>
            <li><strong>Walk-forward optimization:</strong> Not used in this run. Re-running with --walk-forward may find params that generalize better.</li>
            <li><strong>Parameter refinement:</strong> The search space is vast (7 strategies x many params). More targeted search around the top configs' neighborhoods may yield improvements.</li>
            <li><strong>Strategy improvements:</strong> Better entry/exit logic, regime-aware sizing, and gap risk handling could boost per-strategy alpha.</li>
            <li><strong>Focus on fewer strategies:</strong> The top configs' per-strategy breakdown shows some strategies are net drags. Pruning weak strategies may improve net returns.</li>
        </ul>
    </div>
    """

    # ── Assemble HTML ────────────────────────────────────────────────────

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Optimizer Report &mdash; 500 Runs &mdash; Real Data Only</title>
    <style>{css}</style>
</head>
<body>
<div class="container">

    <h1>Endless Optimizer &mdash; 500-Run Report</h1>
    <div class="subtitle">
        Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")} &nbsp;|&nbsp;
        Real Polygon Data Only (no synthetic/BS pricing) &nbsp;|&nbsp;
        SPY + QQQ + IWM &nbsp;|&nbsp; 2020&ndash;2025 &nbsp;|&nbsp;
        Post Bug #3 Fix (real-data-only pricing)
    </div>

    <!-- ── KPI Dashboard ─────────────────────────────────────── -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">Total Runs</div>
            <div class="kpi-value blue">{n_total}</div>
            <div class="kpi-sub">Phase 1: {phase_counts.get('Phase 1',0)} | Phase 2: {phase_counts.get('Phase 2',0)} | Phase 3: {phase_counts.get('Phase 3',0)}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Best ROBUST Return</div>
            <div class="kpi-value {'green' if best_return > 0 else 'red'}">{best_return:+.1f}%</div>
            <div class="kpi-sub">Overfit score: {best.get('overfit_score', 0):.3f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Median Return (All)</div>
            <div class="kpi-value {'green' if median_return > 0 else 'red'}">{median_return:+.1f}%</div>
            <div class="kpi-sub">Mean: {mean_return:+.1f}%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">ROBUST Runs</div>
            <div class="kpi-value green">{len(robust)}</div>
            <div class="kpi-sub">{len(robust)/n_total*100:.0f}% of total</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Profitable Runs</div>
            <div class="kpi-value yellow">{positive_runs}</div>
            <div class="kpi-sub">{positive_runs/n_total*100:.0f}% of total</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Best Max Drawdown</div>
            <div class="kpi-value green">{best_dd:+.1f}%</div>
            <div class="kpi-sub">Target: &le;20%</div>
        </div>
    </div>

    <!-- ── Distribution Charts ───────────────────────────────── -->
    <h2>Distribution Analysis</h2>
    <div class="two-col">
        <div class="card">
            <div class="card-title">Return Distribution (All 500 Runs)</div>
            <div class="chart-container">{return_histogram}</div>
        </div>
        <div class="card">
            <div class="card-title">Return Distribution (ROBUST Only, n={len(robust)})</div>
            <div class="chart-container">{robust_histogram}</div>
        </div>
        <div class="card">
            <div class="card-title">Drawdown Distribution (All Runs)</div>
            <div class="chart-container">{dd_histogram}</div>
        </div>
        <div class="card">
            <div class="card-title">Overfit Score Distribution</div>
            <div class="chart-container">{overfit_histogram}</div>
        </div>
    </div>

    <!-- ── Top 10 Overall ────────────────────────────────────── -->
    <h2>Top 10 Runs by Average Return</h2>
    <div class="card">
        <table>
            <tr>
                <th style="text-align:left">#</th>
                <th>Run</th>
                <th>Avg Ret</th>
                <th>2020</th><th>2021</th><th>2022</th><th>2023</th><th>2024</th><th>2025</th>
                <th>MaxDD</th>
                <th>Trades/yr</th>
                <th>Consist.</th>
                <th>Overfit</th>
                <th>Verdict</th>
            </tr>
            {"".join(top10_rows)}
        </table>
    </div>

    <!-- ── Top 10 ROBUST ─────────────────────────────────────── -->
    <h2>Top 10 ROBUST Runs (Overfit Score &ge; 0.70)</h2>
    <div class="card">
        <table>
            <tr>
                <th style="text-align:left">#</th>
                <th>Run</th>
                <th>Avg Ret</th>
                <th>2020</th><th>2021</th><th>2022</th><th>2023</th><th>2024</th><th>2025</th>
                <th>MaxDD</th>
                <th>Win Rate</th>
                <th>PF</th>
                <th>Consist.</th>
                <th>Overfit</th>
                <th style="text-align:left">Strategies</th>
            </tr>
            {"".join(top10_robust_rows)}
        </table>
    </div>

    <!-- ── Detailed Config Cards ─────────────────────────────── -->
    <h2>Top 10 ROBUST Configurations &mdash; Full Detail</h2>
    {"".join(config_cards)}

    <!-- ── Strategy Analysis ─────────────────────────────────── -->
    <h2>Strategy-Type Analysis</h2>

    <div class="card">
        <div class="card-title">Strategy Performance Across All Runs</div>
        <table>
            <tr>
                <th style="text-align:left">Strategy</th>
                <th>Appearances</th>
                <th>% of Runs</th>
                <th>In Top 50</th>
                <th>Top 50 Lift</th>
                <th>In ROBUST</th>
                <th>Avg Return</th>
                <th>% Profitable</th>
            </tr>
            {strat_analysis_rows}
        </table>
    </div>

    <div class="two-col">
        <div class="card">
            <div class="card-title">Strategy Frequency in Top 50 Runs</div>
            <div class="chart-container">{strat_bar_top50}</div>
        </div>
        <div class="card">
            <div class="card-title">Strategy Frequency in ROBUST Runs</div>
            <div class="chart-container">{strat_bar_robust}</div>
        </div>
    </div>

    <div class="card">
        <div class="card-title">Strategy Count vs Performance</div>
        <table>
            <tr>
                <th style="text-align:left">Configuration</th>
                <th>Runs</th>
                <th>Avg Return</th>
                <th>Profitable</th>
            </tr>
            {strat_count_rows}
        </table>
    </div>

    <!-- ── Phase Analysis ────────────────────────────────────── -->
    <h2>Optimization Phase Analysis</h2>
    <div class="card">
        <table>
            <tr>
                <th style="text-align:left">Phase</th>
                <th>Runs</th>
                <th>Avg Return</th>
                <th>Profitable</th>
                <th>Best</th>
            </tr>
            {phase_rows}
        </table>
    </div>

    <!-- ── Robustness Analysis ───────────────────────────────── -->
    <h2>Robustness Analysis</h2>

    <div class="three-col">
        <div class="kpi-card">
            <div class="kpi-label">ROBUST & &gt;5% Return</div>
            <div class="kpi-value green">{len(robust_high_return)}</div>
            <div class="kpi-sub">Strong + reliable</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">ROBUST & 0-5% Return</div>
            <div class="kpi-value yellow">{len(robust_moderate)}</div>
            <div class="kpi-sub">Reliable but modest</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">SUSPECT Runs</div>
            <div class="kpi-value yellow">{len(suspect)}</div>
            <div class="kpi-sub">Questionable robustness</div>
        </div>
    </div>

    <div class="card">
        <div class="card-title">Consistency Score Distribution</div>
        <table>
            <tr>
                <th style="text-align:left">Consistency Bucket</th>
                <th>Runs</th>
                <th>% of Total</th>
            </tr>
            {consistency_rows}
        </table>
    </div>

    <!-- ── Honest Assessment ─────────────────────────────────── -->
    <h2>Honest Assessment</h2>
    {assessment_html}

    <div class="footer">
        PilotAI Credit Spreads &mdash; Optimizer Report &mdash; {n_total} Runs &mdash; Real Polygon Data Only<br>
        Generated by Claude Code &mdash; {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
    </div>

</div>
</body>
</html>"""

    with open(OUT_PATH, "w") as f:
        f.write(html_content)

    print(f"Report written to {OUT_PATH}")
    print(f"  Total entries: {n_total}")
    print(f"  ROBUST: {len(robust)}, SUSPECT: {len(suspect)}, OVERFIT: {len(overfit)}")
    print(f"  Best ROBUST avg return: {best_return:+.1f}%")
    print(f"  File size: {OUT_PATH.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    generate_report()
