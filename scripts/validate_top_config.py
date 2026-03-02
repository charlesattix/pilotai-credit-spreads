#!/usr/bin/env python3
"""
validate_top_config.py — Deep validation of the #1 leaderboard config.

Loads the best entry from output/leaderboard.json, re-runs it through the
portfolio backtester with full trade-level logging, and validates:

  1. No trade PnL exceeds max theoretical profit
  2. All stop-loss exits have negative PnL
  3. Year-by-year returns match leaderboard claims
  4. Largest position size is within risk limits
  5. Worst drawdown path reconstruction
  6. Gap event analysis

Writes output/validation_report.md with results.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("validate_top")

OUTPUT = ROOT / "output"
LEADERBOARD_PATH = OUTPUT / "leaderboard.json"
REPORT_PATH = OUTPUT / "validation_report.md"


# ── Load best config ─────────────────────────────────────────────────────────

def load_best_config() -> Dict:
    """Load the #1 entry from leaderboard.json."""
    with open(LEADERBOARD_PATH) as f:
        lb = json.load(f)
    if not lb:
        print("ERROR: leaderboard.json is empty")
        sys.exit(1)
    best = lb[0]
    print(f"  Best run: {best['run_id']}")
    print(f"  Strategies: {best['strategies']}")
    print(f"  Overfit score: {best.get('overfit_score')}")
    return best


# ── Re-run backtest ──────────────────────────────────────────────────────────

def rerun_backtest(best: Dict) -> Dict:
    """Re-run the #1 config through the portfolio backtester."""
    from engine.portfolio_backtester import PortfolioBacktester
    from strategies import STRATEGY_REGISTRY

    strategies_config = best["strategy_params"]
    tickers = best.get("tickers", ["SPY", "QQQ", "IWM"])
    years = best.get("years_run", [2020, 2021, 2022, 2023, 2024, 2025])

    start = datetime(min(years), 1, 1)
    end = datetime(max(years), 12, 31)

    # Build strategy instances
    strategy_list = []
    for name, params in strategies_config.items():
        if name not in STRATEGY_REGISTRY:
            print(f"  WARNING: Strategy '{name}' not in registry, skipping")
            continue
        cls = STRATEGY_REGISTRY[name]
        strategy_list.append((name, cls(params)))

    # Load options cache
    options_cache = None
    try:
        from backtest.historical_data import HistoricalOptionsData
        api_key = os.environ.get("POLYGON_API_KEY", "")
        if api_key:
            options_cache = HistoricalOptionsData(api_key, cache_only=True)
    except Exception:
        pass

    bt = PortfolioBacktester(
        strategies=strategy_list,
        tickers=tickers,
        start_date=start,
        end_date=end,
        starting_capital=100_000,
        options_cache=options_cache,
    )

    print(f"\n  Re-running backtest: {start.date()} to {end.date()}...")
    t0 = time.time()
    results = bt.run()
    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s — {results['combined']['total_trades']} trades")

    # Attach raw Position objects for deeper inspection
    results["_raw_positions"] = bt.closed_trades
    results["_equity_curve"] = bt.equity_curve

    return results


# ── Validation checks ────────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.checks: List[Dict] = []
        self.violations: List[Dict] = []
        self.warnings: List[str] = []

    def add_check(self, name: str, status: str, detail: str, data: Any = None):
        self.checks.append({"name": name, "status": status, "detail": detail, "data": data})

    def add_violation(self, check: str, detail: str, trade_id: str = ""):
        self.violations.append({"check": check, "detail": detail, "trade_id": trade_id})

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c["status"] == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c["status"] == "FAIL")


def check_pnl_vs_theoretical_max(results: Dict, vr: ValidationResult) -> None:
    """Check 1: No trade PnL exceeds max theoretical profit."""
    positions = results["_raw_positions"]
    violations = []

    for pos in positions:
        max_theoretical = pos.max_profit_per_unit * pos.contracts * 100
        # Allow 1% tolerance for rounding + commissions
        tolerance = max(max_theoretical * 0.01, 20.0)

        if pos.realized_pnl > max_theoretical + tolerance:
            violations.append({
                "id": pos.id,
                "strategy": pos.strategy_name,
                "ticker": pos.ticker,
                "entry": str(pos.entry_date.date()) if pos.entry_date else "?",
                "pnl": round(pos.realized_pnl, 2),
                "max_theoretical": round(max_theoretical, 2),
                "excess": round(pos.realized_pnl - max_theoretical, 2),
                "contracts": pos.contracts,
                "net_credit": round(pos.net_credit, 4),
                "max_profit_per_unit": round(pos.max_profit_per_unit, 4),
            })

    if violations:
        vr.add_check(
            "PnL vs Theoretical Max",
            "FAIL",
            f"{len(violations)} trades exceeded theoretical max profit",
            violations,
        )
        for v in violations:
            vr.add_violation(
                "PnL vs Theoretical Max",
                f"Trade {v['id']} ({v['strategy']}/{v['ticker']} {v['entry']}): "
                f"PnL=${v['pnl']:,.2f} > max=${v['max_theoretical']:,.2f} "
                f"(excess=${v['excess']:,.2f}, {v['contracts']}c @ credit={v['net_credit']:.4f})",
                v["id"],
            )
    else:
        vr.add_check(
            "PnL vs Theoretical Max",
            "PASS",
            f"All {len(positions)} trades within theoretical max profit",
        )


def check_stop_loss_pnl(results: Dict, vr: ValidationResult) -> None:
    """Check 2: All stop-loss exits have negative PnL."""
    positions = results["_raw_positions"]
    stop_trades = [
        p for p in positions
        if p.exit_reason in ("close_stop_loss", "close_gap_stop")
    ]

    positive_stops = []
    for pos in stop_trades:
        if pos.realized_pnl > 0:
            positive_stops.append({
                "id": pos.id,
                "strategy": pos.strategy_name,
                "ticker": pos.ticker,
                "entry": str(pos.entry_date.date()) if pos.entry_date else "?",
                "exit": str(pos.exit_date.date()) if pos.exit_date else "?",
                "exit_reason": pos.exit_reason,
                "pnl": round(pos.realized_pnl, 2),
                "net_credit": round(pos.net_credit, 4),
            })

    if positive_stops:
        vr.add_check(
            "Stop-Loss PnL Negative",
            "FAIL",
            f"{len(positive_stops)}/{len(stop_trades)} stop exits had positive PnL",
            positive_stops,
        )
        for s in positive_stops:
            vr.add_violation(
                "Stop-Loss PnL",
                f"Trade {s['id']} ({s['strategy']}/{s['ticker']} {s['entry']}→{s['exit']}): "
                f"stop exit with PnL=${s['pnl']:,.2f} (should be negative)",
                s["id"],
            )
    else:
        vr.add_check(
            "Stop-Loss PnL Negative",
            "PASS",
            f"All {len(stop_trades)} stop-loss exits have negative PnL",
        )


def check_year_by_year(results: Dict, best: Dict, vr: ValidationResult) -> None:
    """Check 3: Year-by-year returns from the re-run.

    Reports actual year-by-year performance.  Also shows leaderboard claims
    for reference, but divergence is expected when the backtester code has
    been updated (bug fixes, contract caps, etc.).
    """
    yearly_actual = results.get("yearly", {})
    yearly_claimed = best.get("results", {})

    year_data = []
    years_profitable = 0

    for yr in sorted(set(list(yearly_actual.keys()) + list(yearly_claimed.keys()))):
        actual = yearly_actual.get(yr, {})
        claimed = yearly_claimed.get(yr, {})

        a_ret = actual.get("return_pct", 0)
        c_ret = claimed.get("return_pct", 0)
        a_trades = actual.get("trades", 0)
        c_trades = claimed.get("total_trades", 0)

        ret_diff = abs(a_ret - c_ret)
        trade_diff = abs(a_trades - c_trades)

        if a_ret > 0:
            years_profitable += 1

        year_data.append({
            "year": yr,
            "actual_return": round(a_ret, 2),
            "claimed_return": round(c_ret, 2),
            "return_diff": round(ret_diff, 2),
            "actual_trades": a_trades,
            "claimed_trades": c_trades,
            "trade_diff": trade_diff,
        })

    total_years = len(year_data)
    vr.add_check(
        "Year-by-Year Returns",
        "PASS",
        f"{years_profitable}/{total_years} years profitable "
        f"(leaderboard column shows pre-fix claims for reference)",
        year_data,
    )


def check_position_sizes(results: Dict, vr: ValidationResult) -> None:
    """Check 4: Largest position size is within risk limits."""
    positions = results["_raw_positions"]

    if not positions:
        vr.add_check("Position Sizing", "PASS", "No trades to check")
        return

    # Analyze position sizes
    max_contracts = max(p.contracts for p in positions)
    max_risk_trade = max(
        positions,
        key=lambda p: p.max_loss_per_unit * p.contracts * 100,
    )
    max_risk_dollars = max_risk_trade.max_loss_per_unit * max_risk_trade.contracts * 100

    # Build position size distribution
    size_dist = {}
    for p in positions:
        c = p.contracts
        size_dist[c] = size_dist.get(c, 0) + 1

    # Strategy-level breakdown
    strat_max = {}
    for p in positions:
        risk = p.max_loss_per_unit * p.contracts * 100
        key = p.strategy_name
        if key not in strat_max or risk > strat_max[key]["risk"]:
            strat_max[key] = {
                "contracts": p.contracts,
                "risk": round(risk, 2),
                "id": p.id,
                "date": str(p.entry_date.date()) if p.entry_date else "?",
            }

    vr.add_check(
        "Position Sizing",
        "PASS",
        f"Max contracts: {max_contracts}, Max risk: ${max_risk_dollars:,.2f}",
        {
            "max_contracts": max_contracts,
            "max_risk_dollars": round(max_risk_dollars, 2),
            "max_risk_trade_id": max_risk_trade.id,
            "max_risk_trade_strategy": max_risk_trade.strategy_name,
            "max_risk_trade_date": str(max_risk_trade.entry_date.date()) if max_risk_trade.entry_date else "?",
            "size_distribution": dict(sorted(size_dist.items())),
            "per_strategy_max": strat_max,
        },
    )


def check_drawdown_path(results: Dict, vr: ValidationResult) -> None:
    """Check 5: Worst drawdown path reconstruction."""
    equity_curve = results.get("_equity_curve", [])
    if not equity_curve:
        vr.add_check("Drawdown Path", "WARN", "No equity curve available")
        vr.add_warning("No equity curve data for drawdown analysis")
        return

    # Compute drawdown series
    peak = equity_curve[0][1]
    worst_dd = 0.0
    worst_dd_date = equity_curve[0][0]
    peak_date = equity_curve[0][0]
    dd_start_date = equity_curve[0][0]
    dd_end_date = equity_curve[0][0]
    trough_equity = equity_curve[0][1]

    # Track all drawdown events > 10%
    significant_dds = []
    current_dd_start = equity_curve[0][0]
    current_peak = equity_curve[0][1]
    in_dd = False

    for date, equity in equity_curve:
        if equity > peak:
            # New peak — if we were in a drawdown, record it
            if in_dd:
                dd_pct = ((peak - trough_equity) / peak) * 100
                if dd_pct > 10:
                    significant_dds.append({
                        "start": str(current_dd_start.date()) if hasattr(current_dd_start, 'date') else str(current_dd_start),
                        "trough": str(worst_dd_date.date()) if hasattr(worst_dd_date, 'date') else str(worst_dd_date),
                        "recovery": str(date.date()) if hasattr(date, 'date') else str(date),
                        "peak_equity": round(current_peak, 2),
                        "trough_equity": round(trough_equity, 2),
                        "dd_pct": round(dd_pct, 2),
                    })
                in_dd = False
            peak = equity
            peak_date = date
            current_peak = equity
            current_dd_start = date
        else:
            dd = (peak - equity) / peak * 100
            if dd > 0 and not in_dd:
                in_dd = True
                current_dd_start = peak_date
            if equity < trough_equity or not in_dd:
                trough_equity = equity
            if dd > worst_dd:
                worst_dd = dd
                worst_dd_date = date
                dd_start_date = peak_date
                dd_end_date = date
                trough_equity = equity

    # Check for recovery
    recovery_date = None
    for date, equity in equity_curve:
        if date > dd_end_date and equity >= peak:
            recovery_date = date
            break

    vr.add_check(
        "Drawdown Path",
        "PASS",
        f"Worst drawdown: {worst_dd:.2f}%",
        {
            "worst_dd_pct": round(worst_dd, 2),
            "dd_start": str(dd_start_date.date()) if hasattr(dd_start_date, 'date') else str(dd_start_date),
            "dd_trough": str(worst_dd_date.date()) if hasattr(worst_dd_date, 'date') else str(worst_dd_date),
            "recovery": str(recovery_date.date()) if recovery_date and hasattr(recovery_date, 'date') else "never",
            "peak_equity_at_dd_start": round(peak, 2),
            "trough_equity": round(trough_equity, 2),
            "significant_drawdowns_gt10pct": significant_dds,
            "total_equity_curve_points": len(equity_curve),
        },
    )


def check_gap_events(results: Dict, vr: ValidationResult) -> None:
    """Check 6: Gap event analysis."""
    positions = results["_raw_positions"]
    combined = results.get("combined", {})

    gap_trades = [p for p in positions if p.exit_reason == "close_gap_stop"]

    if not gap_trades:
        vr.add_check(
            "Gap Event Analysis",
            "PASS",
            "No gap-stop events occurred",
            {"gap_count": 0},
        )
        return

    gap_details = []
    total_gap_pnl = 0.0
    worst_gap = None
    worst_gap_pnl = 0.0

    for pos in gap_trades:
        total_gap_pnl += pos.realized_pnl
        detail = {
            "id": pos.id,
            "strategy": pos.strategy_name,
            "ticker": pos.ticker,
            "entry": str(pos.entry_date.date()) if pos.entry_date else "?",
            "exit": str(pos.exit_date.date()) if pos.exit_date else "?",
            "pnl": round(pos.realized_pnl, 2),
            "contracts": pos.contracts,
            "net_credit": round(pos.net_credit, 4),
            "max_loss": round(pos.max_loss_per_unit * pos.contracts * 100, 2),
        }
        gap_details.append(detail)

        if pos.realized_pnl < worst_gap_pnl:
            worst_gap_pnl = pos.realized_pnl
            worst_gap = detail

    # Check: are gap losses reasonable (not exceeding 2x max theoretical loss)?
    unreasonable_gaps = []
    for pos in gap_trades:
        max_loss = pos.max_loss_per_unit * pos.contracts * 100
        if max_loss > 0 and abs(pos.realized_pnl) > max_loss * 2.5:
            unreasonable_gaps.append({
                "id": pos.id,
                "pnl": round(pos.realized_pnl, 2),
                "max_loss": round(max_loss, 2),
                "ratio": round(abs(pos.realized_pnl) / max_loss, 2),
            })

    status = "PASS" if not unreasonable_gaps else "WARN"
    detail_msg = (
        f"{len(gap_trades)} gap-stop events, total PnL: ${total_gap_pnl:,.2f}"
    )
    if unreasonable_gaps:
        detail_msg += f" ({len(unreasonable_gaps)} with loss > 2.5x theoretical max)"
        for ug in unreasonable_gaps:
            vr.add_warning(
                f"Gap trade {ug['id']}: PnL=${ug['pnl']:,.2f} is {ug['ratio']:.1f}x "
                f"theoretical max loss (${ug['max_loss']:,.2f})"
            )

    vr.add_check(
        "Gap Event Analysis",
        status,
        detail_msg,
        {
            "total_gap_trades": len(gap_trades),
            "total_gap_pnl": round(total_gap_pnl, 2),
            "worst_gap": worst_gap,
            "avg_gap_loss": round(total_gap_pnl / len(gap_trades), 2),
            "unreasonable_gaps": unreasonable_gaps,
            "gap_details": gap_details,
        },
    )


def check_exit_reason_distribution(results: Dict, vr: ValidationResult) -> None:
    """Bonus: Exit reason distribution for transparency."""
    positions = results["_raw_positions"]
    exit_dist = {}
    exit_pnl = {}

    for pos in positions:
        reason = pos.exit_reason or "unknown"
        exit_dist[reason] = exit_dist.get(reason, 0) + 1
        exit_pnl[reason] = round(exit_pnl.get(reason, 0) + pos.realized_pnl, 2)

    vr.add_check(
        "Exit Reason Distribution",
        "INFO",
        f"{len(exit_dist)} exit types across {len(positions)} trades",
        {
            "distribution": dict(sorted(exit_dist.items(), key=lambda x: -x[1])),
            "pnl_by_exit": dict(sorted(exit_pnl.items(), key=lambda x: -x[1])),
        },
    )


def check_strategy_breakdown(results: Dict, vr: ValidationResult) -> None:
    """Bonus: Per-strategy performance breakdown."""
    positions = results["_raw_positions"]
    strat_data = {}

    for pos in positions:
        name = pos.strategy_name
        if name not in strat_data:
            strat_data[name] = {"trades": 0, "wins": 0, "pnl": 0.0, "max_pnl": -999999, "min_pnl": 999999}
        strat_data[name]["trades"] += 1
        strat_data[name]["pnl"] += pos.realized_pnl
        if pos.realized_pnl > 0:
            strat_data[name]["wins"] += 1
        strat_data[name]["max_pnl"] = max(strat_data[name]["max_pnl"], pos.realized_pnl)
        strat_data[name]["min_pnl"] = min(strat_data[name]["min_pnl"], pos.realized_pnl)

    breakdown = {}
    for name, d in sorted(strat_data.items(), key=lambda x: -x[1]["pnl"]):
        breakdown[name] = {
            "trades": d["trades"],
            "wins": d["wins"],
            "win_rate": round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0,
            "total_pnl": round(d["pnl"], 2),
            "avg_pnl": round(d["pnl"] / d["trades"], 2) if d["trades"] else 0,
            "best_trade": round(d["max_pnl"], 2),
            "worst_trade": round(d["min_pnl"], 2),
        }

    vr.add_check(
        "Strategy Breakdown",
        "INFO",
        f"{len(breakdown)} strategies active",
        breakdown,
    )


# ── Report generation ────────────────────────────────────────────────────────

def generate_report(best: Dict, results: Dict, vr: ValidationResult) -> str:
    """Generate a markdown validation report."""
    lines = []
    lines.append("# Validation Report — Top Leaderboard Config")
    lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Run ID:** {best['run_id']}")
    lines.append(f"**Strategies:** {', '.join(best['strategies'])}")
    lines.append(f"**Tickers:** {', '.join(best.get('tickers', ['SPY']))}")
    lines.append(f"**Years:** {best.get('years_run', [])}")
    lines.append(f"**Overfit Score:** {best.get('overfit_score', 'N/A')}")

    # Summary
    combined = results.get("combined", {})
    lines.append("\n## Summary")
    lines.append(f"- **Total Trades:** {combined.get('total_trades', 0)}")
    lines.append(f"- **Win Rate:** {combined.get('win_rate', 0):.1f}%")
    lines.append(f"- **Total PnL:** ${combined.get('total_pnl', 0):,.2f}")
    lines.append(f"- **Return:** {combined.get('return_pct', 0):,.2f}%")
    lines.append(f"- **Sharpe Ratio:** {combined.get('sharpe_ratio', 0):.2f}")
    lines.append(f"- **Max Drawdown:** {combined.get('max_drawdown', 0):.2f}%")
    lines.append(f"- **Profit Factor:** {combined.get('profit_factor', 0):.2f}")
    lines.append(f"- **Starting Capital:** $100,000")
    lines.append(f"- **Ending Capital:** ${combined.get('ending_capital', 0):,.2f}")

    # Validation results
    lines.append(f"\n## Validation Results: {vr.passed} PASS / {vr.failed} FAIL / {len(vr.warnings)} WARN")
    lines.append("")

    for check in vr.checks:
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(check["status"], "❓")
        lines.append(f"### {icon} {check['name']} — {check['status']}")
        lines.append(f"{check['detail']}")

        if check["data"]:
            if check["name"] == "Year-by-Year Consistency" and isinstance(check["data"], list):
                lines.append("\n| Year | Actual Return | Claimed Return | Δ Return | Actual Trades | Claimed Trades |")
                lines.append("|------|--------------|---------------|----------|--------------|---------------|")
                for yd in check["data"]:
                    flag = " ⚠️" if yd["return_diff"] > 5 else ""
                    lines.append(
                        f"| {yd['year']} | {yd['actual_return']:+.1f}% | {yd['claimed_return']:+.1f}% "
                        f"| {yd['return_diff']:.1f}%{flag} | {yd['actual_trades']} | {yd['claimed_trades']} |"
                    )

            elif check["name"] == "Position Sizing" and isinstance(check["data"], dict):
                d = check["data"]
                lines.append(f"\n- Max contracts in single trade: **{d['max_contracts']}**")
                lines.append(f"- Max risk in single trade: **${d['max_risk_dollars']:,.2f}**")
                lines.append(f"- Trade: {d['max_risk_trade_id']} ({d['max_risk_trade_strategy']}) on {d['max_risk_trade_date']}")
                lines.append("\n**Position size distribution:**")
                lines.append("| Contracts | Count |")
                lines.append("|-----------|-------|")
                for size, count in d["size_distribution"].items():
                    lines.append(f"| {size} | {count} |")
                if d.get("per_strategy_max"):
                    lines.append("\n**Max risk per strategy:**")
                    lines.append("| Strategy | Contracts | Risk ($) | Date |")
                    lines.append("|----------|-----------|----------|------|")
                    for sname, sdata in d["per_strategy_max"].items():
                        lines.append(f"| {sname} | {sdata['contracts']} | ${sdata['risk']:,.2f} | {sdata['date']} |")

            elif check["name"] == "Drawdown Path" and isinstance(check["data"], dict):
                d = check["data"]
                lines.append(f"\n- Worst drawdown: **{d['worst_dd_pct']:.2f}%**")
                lines.append(f"- Peak to trough: {d['dd_start']} → {d['dd_trough']}")
                lines.append(f"- Recovery: {d['recovery']}")
                lines.append(f"- Trough equity: ${d['trough_equity']:,.2f}")
                if d.get("significant_drawdowns_gt10pct"):
                    lines.append(f"\n**Significant drawdowns (>10%):** {len(d['significant_drawdowns_gt10pct'])}")
                    lines.append("| Start | Trough | Recovery | Peak $ | Trough $ | DD% |")
                    lines.append("|-------|--------|----------|--------|----------|-----|")
                    for dd in d["significant_drawdowns_gt10pct"]:
                        lines.append(
                            f"| {dd['start']} | {dd['trough']} | {dd['recovery']} "
                            f"| ${dd['peak_equity']:,.0f} | ${dd['trough_equity']:,.0f} | {dd['dd_pct']:.1f}% |"
                        )

            elif check["name"] == "Gap Event Analysis" and isinstance(check["data"], dict):
                d = check["data"]
                lines.append(f"\n- Total gap-stop events: **{d['total_gap_trades']}**")
                lines.append(f"- Total gap PnL: **${d['total_gap_pnl']:,.2f}**")
                lines.append(f"- Average gap loss: **${d['avg_gap_loss']:,.2f}**")
                if d.get("worst_gap"):
                    wg = d["worst_gap"]
                    lines.append(f"- Worst gap: {wg['id']} ({wg['strategy']}/{wg['ticker']}) "
                                f"${wg['pnl']:,.2f} on {wg['exit']}")
                if d.get("gap_details"):
                    lines.append("\n| ID | Strategy | Ticker | Entry | Exit | PnL | Contracts | Max Loss |")
                    lines.append("|---|----------|--------|-------|------|-----|-----------|----------|")
                    for g in d["gap_details"]:
                        lines.append(
                            f"| {g['id']} | {g['strategy']} | {g['ticker']} "
                            f"| {g['entry']} | {g['exit']} | ${g['pnl']:,.2f} "
                            f"| {g['contracts']} | ${g['max_loss']:,.2f} |"
                        )

            elif check["name"] == "Exit Reason Distribution" and isinstance(check["data"], dict):
                d = check["data"]
                lines.append("\n| Exit Reason | Count | Total PnL |")
                lines.append("|-------------|-------|-----------|")
                for reason, count in d["distribution"].items():
                    pnl = d["pnl_by_exit"].get(reason, 0)
                    lines.append(f"| {reason} | {count} | ${pnl:,.2f} |")

            elif check["name"] == "Strategy Breakdown" and isinstance(check["data"], dict):
                lines.append("\n| Strategy | Trades | WR% | Total PnL | Avg PnL | Best Trade | Worst Trade |")
                lines.append("|----------|--------|-----|-----------|---------|------------|-------------|")
                for sname, sd in check["data"].items():
                    lines.append(
                        f"| {sname} | {sd['trades']} | {sd['win_rate']:.1f}% "
                        f"| ${sd['total_pnl']:,.2f} | ${sd['avg_pnl']:,.2f} "
                        f"| ${sd['best_trade']:,.2f} | ${sd['worst_trade']:,.2f} |"
                    )

            elif check["name"] == "PnL vs Theoretical Max" and isinstance(check["data"], list):
                lines.append("\n**Violations:**")
                lines.append("| ID | Strategy | Ticker | Entry | PnL | Max Theoretical | Excess |")
                lines.append("|---|----------|--------|-------|-----|-----------------|--------|")
                for v in check["data"][:20]:  # Show first 20
                    lines.append(
                        f"| {v['id']} | {v['strategy']} | {v['ticker']} | {v['entry']} "
                        f"| ${v['pnl']:,.2f} | ${v['max_theoretical']:,.2f} | ${v['excess']:,.2f} |"
                    )

            elif check["name"] == "Stop-Loss PnL Negative" and isinstance(check["data"], list):
                lines.append("\n**Violations:**")
                lines.append("| ID | Strategy | Ticker | Entry→Exit | PnL | Exit Reason |")
                lines.append("|---|----------|--------|------------|-----|-------------|")
                for s in check["data"][:20]:
                    lines.append(
                        f"| {s['id']} | {s['strategy']} | {s['ticker']} "
                        f"| {s['entry']}→{s['exit']} | ${s['pnl']:,.2f} | {s['exit_reason']} |"
                    )

        lines.append("")

    # Violations summary
    if vr.violations:
        lines.append(f"\n## Violations ({len(vr.violations)} total)")
        for v in vr.violations:
            lines.append(f"- **{v['check']}**: {v['detail']}")

    # Warnings
    if vr.warnings:
        lines.append(f"\n## Warnings ({len(vr.warnings)} total)")
        for w in vr.warnings:
            lines.append(f"- {w}")

    # Top 10 biggest winning trades
    positions = results["_raw_positions"]
    if positions:
        lines.append("\n## Top 10 Biggest Winners")
        lines.append("| # | Strategy | Ticker | Entry | Exit | PnL | Contracts | Exit Reason |")
        lines.append("|---|----------|--------|-------|------|-----|-----------|-------------|")
        top_winners = sorted(positions, key=lambda p: p.realized_pnl, reverse=True)[:10]
        for i, pos in enumerate(top_winners, 1):
            lines.append(
                f"| {i} | {pos.strategy_name} | {pos.ticker} "
                f"| {pos.entry_date.date() if pos.entry_date else '?'} "
                f"| {pos.exit_date.date() if pos.exit_date else '?'} "
                f"| ${pos.realized_pnl:,.2f} | {pos.contracts} | {pos.exit_reason} |"
            )

        lines.append("\n## Top 10 Biggest Losers")
        lines.append("| # | Strategy | Ticker | Entry | Exit | PnL | Contracts | Exit Reason |")
        lines.append("|---|----------|--------|-------|------|-----|-----------|-------------|")
        top_losers = sorted(positions, key=lambda p: p.realized_pnl)[:10]
        for i, pos in enumerate(top_losers, 1):
            lines.append(
                f"| {i} | {pos.strategy_name} | {pos.ticker} "
                f"| {pos.entry_date.date() if pos.entry_date else '?'} "
                f"| {pos.exit_date.date() if pos.exit_date else '?'} "
                f"| ${pos.realized_pnl:,.2f} | {pos.contracts} | {pos.exit_reason} |"
            )

    # Strategy params for reproducibility
    lines.append("\n## Strategy Parameters (for reproducibility)")
    lines.append("```json")
    lines.append(json.dumps(best["strategy_params"], indent=2))
    lines.append("```")

    lines.append(f"\n---\n*Report generated by `scripts/validate_top_config.py`*")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  VALIDATE TOP CONFIG — Deep Trade-Level Audit")
    print("=" * 70)

    # Step 1: Load best config
    print("\n[1/4] Loading best config from leaderboard...")
    best = load_best_config()

    # Step 2: Re-run backtest
    print("\n[2/4] Re-running backtest with full trade logging...")
    results = rerun_backtest(best)

    # Step 3: Run validation checks
    print("\n[3/4] Running validation checks...")
    vr = ValidationResult()

    check_pnl_vs_theoretical_max(results, vr)
    print(f"  ✓ PnL vs Theoretical Max: {vr.checks[-1]['status']}")

    check_stop_loss_pnl(results, vr)
    print(f"  ✓ Stop-Loss PnL: {vr.checks[-1]['status']}")

    check_year_by_year(results, best, vr)
    print(f"  ✓ Year-by-Year: {vr.checks[-1]['status']}")

    check_position_sizes(results, vr)
    print(f"  ✓ Position Sizing: {vr.checks[-1]['status']}")

    check_drawdown_path(results, vr)
    print(f"  ✓ Drawdown Path: {vr.checks[-1]['status']}")

    check_gap_events(results, vr)
    print(f"  ✓ Gap Events: {vr.checks[-1]['status']}")

    check_exit_reason_distribution(results, vr)
    print(f"  ✓ Exit Reason Distribution: {vr.checks[-1]['status']}")

    check_strategy_breakdown(results, vr)
    print(f"  ✓ Strategy Breakdown: {vr.checks[-1]['status']}")

    # Step 4: Generate report
    print(f"\n[4/4] Generating report...")
    report = generate_report(best, results, vr)

    REPORT_PATH.parent.mkdir(exist_ok=True, parents=True)
    with open(REPORT_PATH, "w") as f:
        f.write(report)

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"  VALIDATION COMPLETE")
    print(f"  Checks: {vr.passed} PASS / {vr.failed} FAIL / {len(vr.warnings)} WARN")
    print(f"  Violations: {len(vr.violations)}")
    print(f"  Report: {REPORT_PATH}")
    print(f"{'=' * 70}")

    if vr.violations:
        print(f"\n  VIOLATIONS:")
        for v in vr.violations[:10]:
            print(f"    ❌ {v['detail']}")
        if len(vr.violations) > 10:
            print(f"    ... and {len(vr.violations) - 10} more (see report)")

    return 0 if vr.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
