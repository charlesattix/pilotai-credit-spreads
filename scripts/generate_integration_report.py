#!/usr/bin/env python3
"""
Generate a single-page HTML integration status report from analysis artifacts.

Reads:
  - analysis/*.md          (research documents)
  - analysis/benchmark_results.txt  (XGBoost model metrics)
  - test results           (via subprocess pytest run)

Writes:
  - analysis/integration_status_report.html

Usage:
    python scripts/generate_integration_report.py
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = Path("/home/node/.openclaw/workspace/analysis")
OUTPUT_HTML = ANALYSIS_DIR / "integration_status_report.html"
BENCHMARK_FILE = ANALYSIS_DIR / "benchmark_results.txt"


# ── Data collection ──────────────────────────────────────────────────────────

def collect_analysis_docs() -> list:
    """Scan analysis/ for markdown files and extract title + size."""
    docs = []
    for f in sorted(ANALYSIS_DIR.glob("*.md")):
        text = f.read_text(errors="replace")
        lines = text.strip().splitlines()
        title = "Untitled"
        for line in lines:
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                title = stripped
                break
        docs.append({
            "filename": f.name,
            "title": title,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "lines": len(lines),
        })
    return docs


def parse_benchmark() -> dict:
    """Parse benchmark_results.txt for key metrics."""
    result = {
        "model_type": "XGBClassifier",
        "n_features": 29,
        "n_estimators": 150,
        "trained_date": "",
        "walk_forward": [],
        "backtest_years": [],
        "quality_gates": [],
        "top_features": [],
        "avg_auc": 0.0,
        "avg_accuracy": 0.0,
        "total_trades": 0,
        "total_pnl": "",
        "aggregate_sharpe": 0.0,
    }

    if not BENCHMARK_FILE.exists():
        return result

    text = BENCHMARK_FILE.read_text(errors="replace")

    # Trained date
    m = re.search(r"Trained\s*:\s*(\S+)", text)
    if m:
        result["trained_date"] = m.group(1)[:10]

    # Walk-forward rows
    for m in re.finditer(
        r"^\s*(20\d{2})\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+%)",
        text, re.MULTILINE,
    ):
        result["walk_forward"].append({
            "year": m.group(1),
            "n_train": int(m.group(2)),
            "n_test": int(m.group(3)),
            "auc": float(m.group(4)),
            "acc": float(m.group(5)),
            "prec": float(m.group(6)),
            "recall": float(m.group(7)),
            "wr_test": m.group(8),
        })

    # Backtest per-year rows
    for m in re.finditer(
        r"^\s*(20\d{2}(?:_ytd)?)\s+(\d+)\s+([\d.]+%)\s+\$?([-\d,]+)\s+([-\d.]+%)\s+([-\d.]+%)\s+([-\d.]+)\s+([\d.]+%)",
        text, re.MULTILINE,
    ):
        pnl_str = m.group(4).replace(",", "")
        result["backtest_years"].append({
            "year": m.group(1),
            "trades": int(m.group(2)),
            "win_pct": m.group(3),
            "pnl": int(pnl_str),
            "return_pct": m.group(5),
            "max_dd": m.group(6),
            "sharpe": float(m.group(7)),
            "consistency": m.group(8),
        })

    # Quality gates
    for m in re.finditer(r"([✓✗])\s+(g\d+_\w+)\s+(PASS|FAIL)", text):
        result["quality_gates"].append({
            "name": m.group(2),
            "status": m.group(3),
        })

    # Top features
    for m in re.finditer(
        r"^\s*\d+\.\s+([\w]+)\s+([\d.]+)\s+█", text, re.MULTILINE,
    ):
        result["top_features"].append({
            "name": m.group(1),
            "importance": float(m.group(2)),
        })

    # Averages
    m = re.search(r"Avg AUC\s*:\s*([\d.]+)", text)
    if m:
        result["avg_auc"] = float(m.group(1))
    m = re.search(r"Avg Accuracy\s*:\s*([\d.]+)", text)
    if m:
        result["avg_accuracy"] = float(m.group(1))

    # Totals
    m = re.search(r"TOTAL\s+(\d+)\s+\$?([-\d,]+)", text)
    if m:
        result["total_trades"] = int(m.group(1))
        result["total_pnl"] = m.group(2)
    m = re.search(r"TOTAL\s+\d+.*?([\d.]+)\s*$", text, re.MULTILINE)
    if m:
        result["aggregate_sharpe"] = float(m.group(1))

    return result


def run_tests() -> dict:
    """Run the ML-related test suites and capture results."""
    test_files = [
        "tests/test_stress_test.py",
        "tests/test_ensemble_signal_model.py",
        "tests/test_ml_strategy.py",
        "tests/test_ml_strategy_v2.py",
    ]

    existing = [f for f in test_files if (REPO_ROOT / f).exists()]
    if not existing:
        return {"passed": 0, "failed": 0, "errors": 0, "total": 0, "suites": [], "duration": "0s"}

    cmd = [
        sys.executable, "-m", "pytest",
        *existing,
        "--tb=no", "--no-header", "-q", "--no-cov",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
    )
    output = proc.stdout + proc.stderr

    passed = failed = errors = 0
    duration = "0s"

    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", output)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) error", output)
    if m:
        errors = int(m.group(1))
    m = re.search(r"in ([\d.]+s)", output)
    if m:
        duration = m.group(1)

    suites = []
    for f in existing:
        name = Path(f).stem
        # Count tests per file from verbose output
        file_passed = output.count(f"{name}::") if f"{name}::" in output else 0
        suites.append({"name": name, "file": f})

    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
        "duration": duration,
        "suites": suites,
        "raw_output": output[-500:] if len(output) > 500 else output,
    }


# ── Integration roadmap ─────────────────────────────────────────────────────

ROADMAP = [
    {
        "phase": "Phase 1",
        "title": "Research & Analysis",
        "status": "complete",
        "items": [
            ("COMPASS deep dive (macro, regime, events)", "complete"),
            ("Strategy framework analysis", "complete"),
            ("ML components mapping (features, models, gating)", "complete"),
            ("Infrastructure review (IronVault, data, DB)", "complete"),
            ("Cross-system integration analysis", "complete"),
        ],
    },
    {
        "phase": "Phase 2",
        "title": "Component Development",
        "status": "complete",
        "items": [
            ("Portfolio optimizer (max_sharpe, risk_parity, ERC, min_var)", "complete"),
            ("Stress test suite (Monte Carlo, crisis scenarios, sensitivity)", "complete"),
            ("Ensemble signal model (XGB + RF + ExtraTrees)", "complete"),
            ("ML V2 aggressive strategy wrapper", "complete"),
            ("Comprehensive test coverage (147 tests passing)", "complete"),
        ],
    },
    {
        "phase": "Phase 3",
        "title": "Integration Planning",
        "status": "complete",
        "items": [
            ("Live pipeline analysis (main.py → strategy_factory → scanner)", "complete"),
            ("Integration plan: strategy_factory.py wiring", "complete"),
            ("A/B test architecture (EXP-701 vs EXP-702 vs control)", "complete"),
            ("Config schema for model_type selection", "complete"),
            ("Shadow mode design for safe rollout", "complete"),
        ],
    },
    {
        "phase": "Phase 4",
        "title": "Backtest Validation",
        "status": "not_started",
        "items": [
            ("Train ensemble on full historical trade data", "not_started"),
            ("Walk-forward validation: ensemble vs XGBoost single", "not_started"),
            ("End-to-end backtest with ML gating enabled", "not_started"),
            ("Compare Sharpe/DD/win-rate vs EXP-400 baseline", "not_started"),
            ("Calibration gate fix (g3 currently FAILS)", "not_started"),
        ],
    },
    {
        "phase": "Phase 5",
        "title": "Paper Trading Deployment",
        "status": "not_started",
        "items": [
            ("Shadow mode: log ML predictions alongside EXP-400 (1 week)", "not_started"),
            ("Launch EXP-701 (XGBoost gating) on fresh Alpaca account", "not_started"),
            ("Launch EXP-702 (Ensemble gating) on fresh Alpaca account", "not_started"),
            ("Daily monitoring via Telegram + deviation tracking", "not_started"),
            ("30-day statistical comparison → promote winner", "not_started"),
        ],
    },
]


# ── HTML generation ──────────────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    colors = {
        "complete": ("#16a34a", "#dcfce7"),
        "in_progress": ("#ca8a04", "#fef9c3"),
        "not_started": ("#6b7280", "#f3f4f6"),
        "blocked": ("#dc2626", "#fee2e2"),
    }
    fg, bg = colors.get(status, ("#6b7280", "#f3f4f6"))
    label = status.replace("_", " ").title()
    return f'<span style="background:{bg};color:{fg};padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600;">{label}</span>'


def _item_icon(status: str) -> str:
    if status == "complete":
        return '<span style="color:#16a34a;">&#10003;</span>'
    if status == "in_progress":
        return '<span style="color:#ca8a04;">&#9679;</span>'
    return '<span style="color:#d1d5db;">&#9675;</span>'


def _pnl_color(value: int) -> str:
    if value > 0:
        return "color:#16a34a;"
    if value < 0:
        return "color:#dc2626;"
    return ""


def _gate_badge(status: str) -> str:
    if status == "PASS":
        return '<span style="background:#dcfce7;color:#16a34a;padding:1px 8px;border-radius:8px;font-size:12px;font-weight:600;">PASS</span>'
    return '<span style="background:#fee2e2;color:#dc2626;padding:1px 8px;border-radius:8px;font-size:12px;font-weight:600;">FAIL</span>'


def generate_html(docs: list, benchmark: dict, tests: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Compute progress
    total_items = sum(len(p["items"]) for p in ROADMAP)
    done_items = sum(1 for p in ROADMAP for _, s in p["items"] if s == "complete")
    progress_pct = round(done_items / total_items * 100) if total_items else 0

    # ── Document table rows
    doc_rows = ""
    for d in docs:
        doc_rows += f"""
        <tr>
            <td style="font-weight:500;">{d['filename']}</td>
            <td>{d['title']}</td>
            <td style="text-align:right;">{d['lines']}</td>
            <td style="text-align:right;">{d['size_kb']} KB</td>
        </tr>"""

    # ── Walk-forward rows
    wf_rows = ""
    for wf in benchmark["walk_forward"]:
        auc_bar_w = int(wf["auc"] * 100)
        wf_rows += f"""
        <tr>
            <td style="font-weight:500;">{wf['year']}</td>
            <td style="text-align:right;">{wf['n_train']}</td>
            <td style="text-align:right;">{wf['n_test']}</td>
            <td>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="background:#e0e7ff;border-radius:4px;width:120px;height:18px;">
                        <div style="background:#4f46e5;border-radius:4px;height:18px;width:{auc_bar_w}%;"></div>
                    </div>
                    <span style="font-weight:600;">{wf['auc']:.4f}</span>
                </div>
            </td>
            <td style="text-align:right;">{wf['acc']:.4f}</td>
            <td style="text-align:right;">{wf['prec']:.4f}</td>
            <td style="text-align:right;">{wf['recall']:.4f}</td>
        </tr>"""

    # ── Backtest year rows
    bt_rows = ""
    for by in benchmark["backtest_years"]:
        pnl_style = _pnl_color(by["pnl"])
        bt_rows += f"""
        <tr>
            <td style="font-weight:500;">{by['year']}</td>
            <td style="text-align:right;">{by['trades']}</td>
            <td style="text-align:right;">{by['win_pct']}</td>
            <td style="text-align:right;{pnl_style}font-weight:600;">${by['pnl']:,}</td>
            <td style="text-align:right;">{by['return_pct']}</td>
            <td style="text-align:right;">{by['max_dd']}</td>
            <td style="text-align:right;">{by['sharpe']:.2f}</td>
        </tr>"""

    # ── Quality gates
    gate_rows = ""
    for g in benchmark["quality_gates"]:
        gate_rows += f"""
        <tr>
            <td style="font-weight:500;">{g['name']}</td>
            <td>{_gate_badge(g['status'])}</td>
        </tr>"""

    # ── Top features
    feat_rows = ""
    max_imp = benchmark["top_features"][0]["importance"] if benchmark["top_features"] else 1
    for feat in benchmark["top_features"][:10]:
        bar_w = int(feat["importance"] / max_imp * 100)
        feat_rows += f"""
        <tr>
            <td style="font-weight:500;font-family:monospace;font-size:13px;">{feat['name']}</td>
            <td>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="background:#fef3c7;border-radius:4px;width:180px;height:16px;">
                        <div style="background:#f59e0b;border-radius:4px;height:16px;width:{bar_w}%;"></div>
                    </div>
                    <span>{feat['importance']:.4f}</span>
                </div>
            </td>
        </tr>"""

    # ── Roadmap
    roadmap_html = ""
    for phase in ROADMAP:
        items_html = ""
        for item_text, item_status in phase["items"]:
            items_html += f'<div style="padding:4px 0 4px 8px;">{_item_icon(item_status)} {item_text}</div>\n'
        roadmap_html += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div>
                    <span style="font-size:13px;color:#6b7280;font-weight:600;">{phase['phase']}</span>
                    <span style="font-size:16px;font-weight:700;margin-left:8px;">{phase['title']}</span>
                </div>
                {_status_badge(phase['status'])}
            </div>
            <div style="font-size:14px;line-height:1.8;">
                {items_html}
            </div>
        </div>"""

    # ── Test results badge
    if tests["total"] == 0:
        test_badge = '<span style="color:#6b7280;">No tests found</span>'
    elif tests["failed"] == 0 and tests["errors"] == 0:
        test_badge = f'<span style="background:#dcfce7;color:#16a34a;padding:4px 14px;border-radius:12px;font-weight:700;font-size:18px;">{tests["passed"]} PASSED</span>'
    else:
        test_badge = f'<span style="background:#fee2e2;color:#dc2626;padding:4px 14px;border-radius:12px;font-weight:700;font-size:18px;">{tests["failed"]} FAILED / {tests["passed"]} passed</span>'

    # ── Ensemble vs XGBoost comparison placeholder
    ensemble_comparison = """
        <div style="border:2px dashed #d1d5db;border-radius:8px;padding:32px;text-align:center;color:#9ca3af;">
            <div style="font-size:40px;margin-bottom:8px;">&#9881;</div>
            <div style="font-size:16px;font-weight:600;color:#6b7280;margin-bottom:4px;">Ensemble Benchmark Pending</div>
            <div style="font-size:14px;">
                Train the ensemble model and run <code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;">scripts/benchmark_models.py --ensemble</code>
                to populate this comparison.
            </div>
            <div style="margin-top:16px;">
                <table style="margin:0 auto;border-collapse:collapse;font-size:14px;text-align:left;">
                    <tr>
                        <td style="padding:4px 16px;font-weight:600;">Metric</td>
                        <td style="padding:4px 16px;font-weight:600;">XGBoost (Current)</td>
                        <td style="padding:4px 16px;font-weight:600;color:#9ca3af;">Ensemble (Target)</td>
                    </tr>
                    <tr>
                        <td style="padding:4px 16px;">Avg OOS AUC</td>
                        <td style="padding:4px 16px;">0.8094</td>
                        <td style="padding:4px 16px;color:#9ca3af;">&gt; 0.82</td>
                    </tr>
                    <tr>
                        <td style="padding:4px 16px;">Worst-Fold AUC</td>
                        <td style="padding:4px 16px;">0.7648</td>
                        <td style="padding:4px 16px;color:#9ca3af;">&gt; 0.78</td>
                    </tr>
                    <tr>
                        <td style="padding:4px 16px;">Calibration (g3)</td>
                        <td style="padding:4px 16px;color:#dc2626;">FAIL</td>
                        <td style="padding:4px 16px;color:#9ca3af;">PASS</td>
                    </tr>
                    <tr>
                        <td style="padding:4px 16px;">Aggregate Sharpe</td>
                        <td style="padding:4px 16px;">0.70</td>
                        <td style="padding:4px 16px;color:#9ca3af;">&gt; 0.80</td>
                    </tr>
                </table>
            </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PilotAI Integration Status Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fff; color: #1f2937; line-height: 1.5; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px; }}
  h1 {{ font-size: 28px; font-weight: 800; margin-bottom: 4px; }}
  h2 {{ font-size: 20px; font-weight: 700; margin: 32px 0 16px 0; padding-bottom: 8px; border-bottom: 2px solid #e5e7eb; }}
  h3 {{ font-size: 16px; font-weight: 600; margin: 20px 0 10px 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align: left; padding: 10px 12px; background: #f9fafb; border-bottom: 2px solid #e5e7eb; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #f3f4f6; }}
  tr:hover {{ background: #f9fafb; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
  .stat-card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }}
  .stat-value {{ font-size: 28px; font-weight: 800; }}
  .stat-label {{ font-size: 13px; color: #6b7280; margin-top: 2px; }}
  .progress-bar {{ background: #e5e7eb; border-radius: 8px; height: 20px; margin: 8px 0; overflow: hidden; }}
  .progress-fill {{ background: linear-gradient(90deg, #4f46e5, #7c3aed); height: 100%; border-radius: 8px; transition: width 0.5s; }}
  code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
  .section {{ margin-bottom: 32px; }}
  .timestamp {{ font-size: 13px; color: #9ca3af; margin-bottom: 24px; }}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<h1>PilotAI Ensemble ML Integration</h1>
<div class="timestamp">Generated {now} &mdash; pilotai-credit-spreads @ maximus/ensemble-ml</div>

<!-- Progress Dashboard -->
<h2>Overall Progress</h2>
<div class="stats-grid">
    <div class="stat-card">
        <div class="stat-value" style="color:#4f46e5;">{progress_pct}%</div>
        <div class="stat-label">Roadmap Complete</div>
        <div class="progress-bar"><div class="progress-fill" style="width:{progress_pct}%;"></div></div>
        <div style="font-size:12px;color:#9ca3af;">{done_items}/{total_items} items done</div>
    </div>
    <div class="stat-card">
        <div class="stat-value" style="color:#16a34a;">{tests['passed']}</div>
        <div class="stat-label">Tests Passing</div>
        <div style="font-size:12px;color:#9ca3af;">{tests['total']} total &middot; {tests['duration']}</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{len(docs)}</div>
        <div class="stat-label">Analysis Documents</div>
        <div style="font-size:12px;color:#9ca3af;">{sum(d['lines'] for d in docs):,} lines total</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{benchmark['total_trades']}</div>
        <div class="stat-label">Backtest Trades</div>
        <div style="font-size:12px;color:#9ca3af;">Sharpe {benchmark['aggregate_sharpe']:.2f} &middot; ${benchmark['total_pnl']} PnL</div>
    </div>
</div>

<!-- Test Results -->
<h2>Test Results</h2>
<div style="display:flex;align-items:center;gap:16px;margin-bottom:16px;">
    {test_badge}
    <span style="font-size:14px;color:#6b7280;">{tests['failed']} failed &middot; {tests['errors']} errors &middot; {tests['duration']}</span>
</div>
<table>
    <thead><tr><th>Test Suite</th><th>File</th></tr></thead>
    <tbody>
    {"".join(f'<tr><td style="font-weight:500;">{s["name"]}</td><td><code>{s["file"]}</code></td></tr>' for s in tests["suites"])}
    </tbody>
</table>

<!-- XGBoost Baseline -->
<h2>XGBoost Baseline Model</h2>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
    <div>
        <h3>Walk-Forward Validation (Out-of-Sample)</h3>
        <table>
            <thead><tr><th>Year</th><th style="text-align:right;">Train</th><th style="text-align:right;">Test</th><th>AUC</th><th style="text-align:right;">Accuracy</th><th style="text-align:right;">Precision</th><th style="text-align:right;">Recall</th></tr></thead>
            <tbody>{wf_rows}</tbody>
            <tfoot>
                <tr style="font-weight:700;background:#f9fafb;">
                    <td colspan="3">Average</td>
                    <td><span style="font-weight:700;">{benchmark['avg_auc']:.4f}</span></td>
                    <td style="text-align:right;">{benchmark['avg_accuracy']:.4f}</td>
                    <td colspan="2"></td>
                </tr>
            </tfoot>
        </table>
    </div>
    <div>
        <h3>Quality Gates</h3>
        <table>
            <thead><tr><th>Gate</th><th>Status</th></tr></thead>
            <tbody>{gate_rows}</tbody>
        </table>
        <h3 style="margin-top:20px;">Top Features</h3>
        <table>
            <thead><tr><th>Feature</th><th>Importance</th></tr></thead>
            <tbody>{feat_rows}</tbody>
        </table>
    </div>
</div>

<h3 style="margin-top:24px;">Backtest Performance (Per Year, Real Polygon Data)</h3>
<table>
    <thead><tr><th>Year</th><th style="text-align:right;">Trades</th><th style="text-align:right;">Win %</th><th style="text-align:right;">P&amp;L</th><th style="text-align:right;">Return</th><th style="text-align:right;">Max DD</th><th style="text-align:right;">Sharpe</th></tr></thead>
    <tbody>{bt_rows}</tbody>
    <tfoot>
        <tr style="font-weight:700;background:#f9fafb;">
            <td>Total</td>
            <td style="text-align:right;">{benchmark['total_trades']}</td>
            <td></td>
            <td style="text-align:right;color:#16a34a;font-weight:700;">${benchmark['total_pnl']}</td>
            <td colspan="2"></td>
            <td style="text-align:right;">{benchmark['aggregate_sharpe']:.2f}</td>
        </tr>
    </tfoot>
</table>

<!-- Ensemble vs XGBoost -->
<h2>Ensemble vs XGBoost Comparison</h2>
{ensemble_comparison}

<!-- Analysis Documents -->
<h2>Analysis Documents</h2>
<table>
    <thead><tr><th>File</th><th>Title</th><th style="text-align:right;">Lines</th><th style="text-align:right;">Size</th></tr></thead>
    <tbody>{doc_rows}</tbody>
</table>

<!-- Integration Roadmap -->
<h2>Integration Roadmap</h2>
{roadmap_html}

</div>
</body>
</html>"""
    return html


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Collecting analysis documents...")
    docs = collect_analysis_docs()
    print(f"  Found {len(docs)} documents")

    print("Parsing benchmark results...")
    benchmark = parse_benchmark()
    print(f"  Model: {benchmark['model_type']}, {benchmark['total_trades']} trades, Sharpe {benchmark['aggregate_sharpe']:.2f}")

    print("Running test suites...")
    tests = run_tests()
    print(f"  {tests['passed']} passed, {tests['failed']} failed, {tests['errors']} errors ({tests['duration']})")

    print("Generating HTML report...")
    html = generate_html(docs, benchmark, tests)

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html)
    print(f"  Written to {OUTPUT_HTML}")
    print(f"  Size: {OUTPUT_HTML.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
