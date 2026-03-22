"""
html.py — Live dashboard HTML generation (minimal v1).
"""

from __future__ import annotations
from datetime import datetime, timezone
from .data import STARTING_EQUITY

# ---------------------------------------------------------------------------
_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f8fafc; color: #1e293b; font-size: 14px; line-height: 1.5;
}
.top-bar {
    background: #0f172a; color: #94a3b8; font-size: 12px;
    padding: 10px 24px; display: flex; justify-content: space-between;
    align-items: center; flex-wrap: wrap; gap: 12px;
}
.top-bar .brand { color: #f8fafc; font-weight: 700; }
.live-dot {
    display: inline-block; width: 7px; height: 7px;
    background: #22c55e; border-radius: 50%; margin-right: 4px;
    animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.page { max-width: 900px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: #64748b; font-size: 13px; margin-bottom: 28px; }

/* Summary cards */
.summary { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 32px; }
.s-card {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 14px 20px; flex: 1; min-width: 160px;
}
.s-label { font-size: 10px; font-weight: 700; text-transform: uppercase;
           letter-spacing: 0.6px; color: #94a3b8; }
.s-val { font-size: 22px; font-weight: 700; margin-top: 2px; }
.s-sub { font-size: 11px; color: #94a3b8; margin-top: 1px; }
.up { color: #059669; } .down { color: #dc2626; } .neutral { color: #334155; }

/* Experiment rows */
.exp-list { display: flex; flex-direction: column; gap: 12px; }
.exp-row {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 18px 22px; display: flex; justify-content: space-between;
    align-items: center; flex-wrap: wrap; gap: 14px;
    transition: box-shadow 0.15s;
}
.exp-row:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.exp-left { min-width: 200px; }
.exp-id { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; }
.exp-name { font-size: 16px; font-weight: 700; color: #0f172a; margin-top: 1px; }
.exp-meta { font-size: 12px; color: #94a3b8; margin-top: 3px; }
.ticker {
    background: #0f172a; color: #f8fafc; font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 3px; letter-spacing: 0.5px;
}
.ticker.ibit { background: #d97706; }
.exp-stats { display: flex; gap: 24px; flex-wrap: wrap; align-items: center; }
.stat { text-align: center; min-width: 70px; }
.stat-val { font-size: 18px; font-weight: 700; }
.stat-label { font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.4px; }
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; font-weight: 700;
}
.badge-green { background: #dcfce7; color: #166534; }
.badge-yellow { background: #fef9c3; color: #854d0e; }
.badge-red { background: #fee2e2; color: #991b1b; }
.badge-gray { background: #f1f5f9; color: #64748b; }

.footer {
    margin-top: 48px; padding-top: 14px; border-top: 1px solid #e2e8f0;
    font-size: 11px; color: #94a3b8; display: flex;
    justify-content: space-between; flex-wrap: wrap; gap: 8px;
}
@media (max-width: 640px) {
    .page { padding: 20px 14px 48px; }
    .exp-row { flex-direction: column; align-items: flex-start; }
    .exp-stats { width: 100%; justify-content: space-between; }
}
"""

_JS = """
<script>
(function(){
  var I=300,r=I,el=document.getElementById('cd');
  function t(){r--;if(r<=0){location.reload();return;}
  if(el)el.textContent=r+'s';setTimeout(t,1000);}
  setTimeout(t,1000);
  document.addEventListener('keydown',function(e){if(e.key==='r'||e.key==='R')location.reload();});
})();
</script>
"""

# ---------------------------------------------------------------------------

def _fmt_pnl(v):
    s = "+" if v >= 0 else ""
    return f"{s}${abs(v):,.0f}"

def _pnl_cls(v):
    return "up" if v > 0 else ("down" if v < 0 else "neutral")

def _wr_badge(wr, count):
    if count == 0:
        return '<span class="badge badge-gray">—</span>'
    if wr >= 70:
        return f'<span class="badge badge-green">{wr:.0f}%</span>'
    if wr >= 50:
        return f'<span class="badge badge-yellow">{wr:.0f}%</span>'
    return f'<span class="badge badge-red">{wr:.0f}%</span>'

def _ticker_cls(t):
    return "ibit" if t.upper() == "IBIT" else ""

# ---------------------------------------------------------------------------

def render_dashboard(all_stats: list[dict]) -> str:
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    total_pnl = sum(s["total_pnl"] for s in all_stats)
    total_closed = sum(s["total_closed"] for s in all_stats)
    total_open = sum(s["open_count"] for s in all_stats)
    total_wins = sum(s["wins"] for s in all_stats)
    wr = (total_wins / total_closed * 100) if total_closed else 0

    # Build experiment rows
    rows = []
    for s in all_stats:
        pnl_display = _fmt_pnl(s["total_pnl"]) if s["total_closed"] > 0 else "—"
        pnl_c = _pnl_cls(s["total_pnl"]) if s["total_closed"] > 0 else "neutral"
        tc = _ticker_cls(s["ticker"])
        rows.append(f"""
<div class="exp-row">
  <div class="exp-left">
    <div class="exp-id">{s['id']}</div>
    <div class="exp-name">{s['name']}</div>
    <div class="exp-meta">
      <span class="ticker {tc}">{s['ticker']}</span>
      &nbsp; by {s.get('creator','—')} &nbsp;&bull;&nbsp; since {s.get('live_since','—')}
    </div>
  </div>
  <div class="exp-stats">
    <div class="stat">
      <div class="stat-val {pnl_c}">{pnl_display}</div>
      <div class="stat-label">P&L</div>
    </div>
    <div class="stat">
      <div class="stat-val neutral">{s['total_closed']}</div>
      <div class="stat-label">Trades</div>
    </div>
    <div class="stat">
      <div class="stat-val neutral">{s['open_count']}</div>
      <div class="stat-label">Open</div>
    </div>
    <div class="stat">
      <div>{_wr_badge(s['win_rate'], s['total_closed'])}</div>
      <div class="stat-label">Win Rate</div>
    </div>
  </div>
</div>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PilotAI Dashboard</title>
  <style>{_CSS}</style>
</head>
<body>
<div class="top-bar">
  <div><span class="brand">PilotAI</span> &nbsp; <span class="live-dot"></span> Live Paper Trading</div>
  <div>Updated {now_str} &nbsp;&bull;&nbsp; Refresh in <span id="cd">300s</span></div>
</div>
<div class="page">
  <h1>Paper Trading Dashboard</h1>
  <p class="subtitle">Credit Spreads &bull; 8-week gate: Mar 16 → May 11, 2026</p>

  <div class="summary">
    <div class="s-card">
      <div class="s-label">Combined P&L</div>
      <div class="s-val {_pnl_cls(total_pnl)}">{_fmt_pnl(total_pnl)}</div>
      <div class="s-sub">{total_pnl/STARTING_EQUITY*100:+.1f}% of $100K</div>
    </div>
    <div class="s-card">
      <div class="s-label">Trades</div>
      <div class="s-val neutral">{total_closed}</div>
      <div class="s-sub">{total_wins}W / {total_closed - total_wins}L</div>
    </div>
    <div class="s-card">
      <div class="s-label">Win Rate</div>
      <div class="s-val {'up' if wr >= 70 else 'neutral'}">{wr:.0f}%</div>
    </div>
    <div class="s-card">
      <div class="s-label">Open</div>
      <div class="s-val neutral">{total_open}</div>
      <div class="s-sub">{len(all_stats)} experiments</div>
    </div>
  </div>

  <div class="exp-list">
    {"".join(rows)}
  </div>

  <div class="footer">
    <span>PilotAI Credit Spreads</span>
    <span>{now_str}</span>
  </div>
</div>
{_JS}
</body>
</html>"""
