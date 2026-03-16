"""
HTMLReportGenerator — self-contained HTML report with equity curve, drawdown
chart, yearly summary, and trade log.  Pure Python + inline SVG; no plotly
or matplotlib required.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class HTMLReportGenerator:
    """Generate a self-contained HTML report for a backtest experiment.

    Usage::

        gen = HTMLReportGenerator()
        gen.generate(entry, output_path="/tmp/report.html")
    """

    def generate(self, entry: dict, output_path: str | Path) -> Path:
        """Write a self-contained HTML file.

        Args:
            entry:       Leaderboard entry dict (from LeaderboardManager.get()).
            output_path: File path for the output HTML.

        Returns:
            Path to the written file.
        """
        output_path = Path(output_path)
        html = self._build_html(entry)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    # ------------------------------------------------------------------
    # HTML construction
    # ------------------------------------------------------------------

    def _build_html(self, entry: dict) -> str:
        run_id = entry.get("run_id", "unknown")
        summary = entry.get("summary", {})
        per_year = entry.get("per_year", {})
        overfit_score = entry.get("overfit_score") or 0.0
        verdict = entry.get("verdict", "UNKNOWN")
        params = entry.get("params", {})
        timestamp = entry.get("timestamp", datetime.now().isoformat())

        yearly_summary = self._build_yearly_table(per_year)
        equity_svg = self._build_equity_svg(per_year)
        dd_svg = self._build_dd_svg(per_year)
        params_section = self._build_params_section(params)

        score_color = "#22c55e" if overfit_score >= 0.70 else ("#f59e0b" if overfit_score >= 0.50 else "#ef4444")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest Report: {run_id}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 0; padding: 24px; background: #0f172a; color: #e2e8f0; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
  .meta {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr));
           gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 8px; padding: 16px; }}
  .card-label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; }}
  .card-value {{ font-size: 1.6rem; font-weight: 700; margin-top: 4px; }}
  .positive {{ color: #22c55e; }}
  .negative {{ color: #ef4444; }}
  .neutral  {{ color: #e2e8f0; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
  th {{ background: #1e293b; padding: 8px 12px; text-align: right;
        font-size: 0.8rem; color: #94a3b8; border-bottom: 1px solid #334155; }}
  th:first-child {{ text-align: left; }}
  td {{ padding: 8px 12px; text-align: right; border-bottom: 1px solid #1e293b;
        font-size: 0.9rem; }}
  td:first-child {{ text-align: left; font-weight: 500; }}
  tr:hover td {{ background: #1e293b33; }}
  .section-title {{ font-size: 1rem; font-weight: 600; margin: 20px 0 8px;
                    color: #cbd5e1; border-bottom: 1px solid #334155; padding-bottom: 4px; }}
  svg {{ width: 100%; height: 200px; background: #1e293b; border-radius: 8px;
         margin-bottom: 24px; display: block; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 700px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  pre {{ background: #1e293b; padding: 16px; border-radius: 8px; overflow-x: auto;
         font-size: 0.8rem; color: #cbd5e1; }}
</style>
</head>
<body>
<h1>Backtest Report: {run_id}</h1>
<div class="meta">Generated {timestamp[:19]} &nbsp;|&nbsp;
  Verdict: <span style="color:{score_color};font-weight:600">{verdict}</span>
  &nbsp;|&nbsp; Overfit score: <span style="color:{score_color}">{overfit_score:.3f}</span>
</div>

<div class="grid">
  {self._stat_card("Avg Annual Return", summary.get("avg_return", 0), "%", is_pct=True)}
  {self._stat_card("Worst DD", summary.get("worst_dd", 0), "%", is_pct=True)}
  {self._stat_card("Profitable Years", f"{summary.get('years_profitable',0)}/{summary.get('years_total',0)}", "")}
  {self._stat_card("Avg Trades/Yr", summary.get("avg_trades", 0), "")}
  {self._stat_card("Best Year", summary.get("max_return", 0), "%", is_pct=True)}
  {self._stat_card("Worst Year", summary.get("min_return", 0), "%", is_pct=True)}
</div>

<div class="section-title">Annual Returns &amp; Drawdown</div>
<div class="charts">
  {equity_svg}
  {dd_svg}
</div>

<div class="section-title">Year-by-Year Summary</div>
{yearly_summary}

<div class="section-title">Parameters</div>
{params_section}

</body>
</html>
"""

    def _stat_card(self, label: str, value, unit: str, is_pct: bool = False) -> str:
        if isinstance(value, (int, float)):
            if is_pct:
                color = "positive" if value > 0 else ("negative" if value < 0 else "neutral")
                display = f"{value:+.1f}{unit}"
            else:
                color = "neutral"
                display = f"{value}{unit}"
        else:
            color = "neutral"
            display = f"{value}{unit}"

        return f"""<div class="card">
  <div class="card-label">{label}</div>
  <div class="card-value {color}">{display}</div>
</div>"""

    def _build_yearly_table(self, per_year: Dict) -> str:
        if not per_year:
            return "<p>No yearly data.</p>"

        rows = []
        for yr in sorted(per_year.keys()):
            r = per_year[yr]
            if "error" in r:
                rows.append(f"<tr><td>{yr}</td><td colspan='5' style='color:#ef4444'>ERROR: {r['error']}</td></tr>")
                continue
            ret = r.get("return_pct", 0)
            dd = r.get("max_drawdown", 0)
            trades = r.get("total_trades", 0)
            wr = r.get("win_rate", 0)
            sharpe = r.get("sharpe_ratio", 0)
            ret_color = "#22c55e" if ret > 0 else "#ef4444"
            rows.append(
                f"<tr><td>{yr}</td>"
                f"<td style='color:{ret_color}'>{ret:+.1f}%</td>"
                f"<td style='color:#f59e0b'>{dd:.1f}%</td>"
                f"<td>{trades}</td>"
                f"<td>{wr:.1f}%</td>"
                f"<td>{sharpe:.2f}</td></tr>"
            )

        return f"""<table>
<thead><tr>
  <th>Year</th><th>Return</th><th>Max DD</th>
  <th>Trades</th><th>Win Rate</th><th>Sharpe</th>
</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>"""

    def _build_equity_svg(self, per_year: Dict) -> str:
        """Bar chart of annual returns."""
        years = sorted(per_year.keys())
        if not years:
            return "<svg><text x='50%' y='50%' fill='#94a3b8' text-anchor='middle'>No data</text></svg>"

        returns = [per_year[y].get("return_pct", 0) for y in years]
        max_val = max(abs(r) for r in returns) or 1.0

        W, H = 400, 180
        pad_x, pad_y = 40, 20
        chart_w = W - 2 * pad_x
        chart_h = H - 2 * pad_y
        zero_y = pad_y + chart_h * max_val / (2 * max_val)

        n = len(years)
        bar_w = max(4, chart_w / n * 0.7)
        bars = []
        labels = []
        for i, (yr, ret) in enumerate(zip(years, returns)):
            cx = pad_x + (i + 0.5) * chart_w / n
            bar_h = abs(ret) / max_val * (chart_h / 2)
            color = "#22c55e" if ret >= 0 else "#ef4444"
            y = zero_y - bar_h if ret >= 0 else zero_y
            bars.append(f'<rect x="{cx - bar_w/2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="2"/>')
            labels.append(f'<text x="{cx:.1f}" y="{H - 4}" text-anchor="middle" font-size="9" fill="#94a3b8">{yr[2:]}</text>')
            val_y = (y - 3) if ret >= 0 else (y + bar_h + 10)
            bars.append(f'<text x="{cx:.1f}" y="{val_y:.1f}" text-anchor="middle" font-size="8" fill="{color}">{ret:+.0f}%</text>')

        zero_line = f'<line x1="{pad_x}" y1="{zero_y:.1f}" x2="{W - pad_x}" y2="{zero_y:.1f}" stroke="#475569" stroke-width="1"/>'
        title = f'<text x="{W/2}" y="14" text-anchor="middle" font-size="10" fill="#94a3b8">Annual Returns</text>'

        return f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">{title}{zero_line}{"".join(bars)}{"".join(labels)}</svg>'

    def _build_dd_svg(self, per_year: Dict) -> str:
        """Bar chart of max drawdowns per year."""
        years = sorted(per_year.keys())
        if not years:
            return "<svg><text x='50%' y='50%' fill='#94a3b8' text-anchor='middle'>No data</text></svg>"

        dds = [per_year[y].get("max_drawdown", 0) for y in years]
        min_dd = min(dds) if dds else -1.0
        max_abs = abs(min_dd) or 1.0

        W, H = 400, 180
        pad_x, pad_y = 40, 20
        chart_w = W - 2 * pad_x
        chart_h = H - 2 * pad_y
        base_y = pad_y

        n = len(years)
        bar_w = max(4, chart_w / n * 0.7)
        bars = []
        labels = []
        for i, (yr, dd) in enumerate(zip(years, dds)):
            cx = pad_x + (i + 0.5) * chart_w / n
            bar_h = abs(dd) / max_abs * chart_h
            bars.append(f'<rect x="{cx - bar_w/2:.1f}" y="{base_y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="#ef4444" rx="2" opacity="0.8"/>')
            labels.append(f'<text x="{cx:.1f}" y="{H - 4}" text-anchor="middle" font-size="9" fill="#94a3b8">{yr[2:]}</text>')
            bars.append(f'<text x="{cx:.1f}" y="{base_y + bar_h + 10:.1f}" text-anchor="middle" font-size="8" fill="#fca5a5">{dd:.0f}%</text>')

        title = f'<text x="{W/2}" y="14" text-anchor="middle" font-size="10" fill="#94a3b8">Max Drawdown per Year</text>'
        return f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">{title}{"".join(bars)}{"".join(labels)}</svg>'

    def _build_params_section(self, params: dict) -> str:
        if not params:
            return "<p style='color:#94a3b8'>No params stored.</p>"
        import json
        return f"<pre>{json.dumps(params, indent=2, default=str)}</pre>"
