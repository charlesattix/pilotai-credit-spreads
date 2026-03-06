#!/usr/bin/env python3
"""
live_vs_backtest.py — Compare live paper-trading results against backtest expectations.

Reads closed paper trades from SQLite, runs the PortfolioBacktester for the same
date range using the champion config, and prints a side-by-side comparison report.

Usage:
  python scripts/live_vs_backtest.py                         # Auto-detect date range
  python scripts/live_vs_backtest.py --start 2026-03-05      # Override start date
  python scripts/live_vs_backtest.py --config configs/champion.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("live_vs_backtest")

DEFAULT_CONFIG = ROOT / "configs" / "champion.json"
STARTING_CAPITAL = 100_000

# Statuses that mean "not closed"
OPEN_STATUSES = {"open", "pending_open", "failed_open", "error"}


# ── 1. Load live metrics ────────────────────────────────────────────────────

def load_live_trades() -> List[Dict[str, Any]]:
    """Fetch closed paper trades from the DB."""
    from shared.database import get_trades
    all_trades = get_trades(source="scanner")
    closed = [t for t in all_trades if t.get("status", "") not in OPEN_STATUSES]
    return closed


def compute_live_metrics(trades: List[Dict]) -> Dict[str, Any]:
    """Compute performance metrics from live trade dicts."""
    if not trades:
        return {"total_trades": 0}

    pnls = [t.get("pnl", 0) or 0 for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    total_trades = len(trades)
    winning_trades = len(winners)
    losing_trades = len(losers)
    win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades else 0.0
    total_pnl = round(sum(pnls), 2)
    avg_win = round(sum(winners) / len(winners), 2) if winners else 0.0
    avg_loss = round(abs(sum(losers) / len(losers)), 2) if losers else 0.0

    winning_total = sum(winners) if winners else 0
    losing_total = abs(sum(losers)) if losers else 0
    if losing_total > 0:
        profit_factor = round(winning_total / losing_total, 2)
    elif winning_total > 0:
        profit_factor = 999.99
    else:
        profit_factor = 0.0

    return_pct = round((total_pnl / STARTING_CAPITAL) * 100, 2)

    # Max drawdown: walk equity curve by entry_date order
    max_drawdown = _compute_max_drawdown(trades)

    # Per-strategy breakdown
    per_strategy = _per_strategy_breakdown(trades)

    # Date range
    entry_dates = [t.get("entry_date", "") for t in trades if t.get("entry_date")]
    exit_dates = [t.get("exit_date", "") for t in trades if t.get("exit_date")]
    start_date = min(entry_dates) if entry_dates else None
    end_date = max(exit_dates) if exit_dates else None

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "return_pct": return_pct,
        "max_drawdown": max_drawdown,
        "per_strategy": per_strategy,
        "start_date": start_date,
        "end_date": end_date,
    }


def _compute_max_drawdown(trades: List[Dict]) -> float:
    """Walk cumulative PnL curve to find max drawdown as a % of capital."""
    sorted_trades = sorted(trades, key=lambda t: t.get("exit_date", "") or "")
    if not sorted_trades:
        return 0.0

    equity = STARTING_CAPITAL
    peak = equity
    max_dd = 0.0

    for t in sorted_trades:
        equity += t.get("pnl", 0) or 0
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return round(-max_dd, 2)  # negative to match backtest convention


def _per_strategy_breakdown(trades: List[Dict]) -> Dict[str, Dict]:
    """Compute per-strategy metrics."""
    by_strategy: Dict[str, List[Dict]] = {}
    for t in trades:
        stype = t.get("strategy_type", "unknown")
        by_strategy.setdefault(stype, []).append(t)

    result = {}
    for sname, strades in by_strategy.items():
        pnls = [t.get("pnl", 0) or 0 for t in strades]
        wins = [p for p in pnls if p > 0]
        total = len(strades)
        result[sname] = {
            "total_trades": total,
            "win_rate": round((len(wins) / total) * 100, 2) if total else 0.0,
            "total_pnl": round(sum(pnls), 2),
        }
    return result


# ── 2. Run backtest for range ───────────────────────────────────────────────

def run_backtest_for_range(
    config_path: Path,
    start: datetime,
    end: datetime,
) -> Dict[str, Any]:
    """Run the PortfolioBacktester for the given date range using champion config."""
    from engine.portfolio_backtester import PortfolioBacktester
    from strategies import STRATEGY_REGISTRY

    with open(config_path) as f:
        config = json.load(f)

    strategies_config = config["strategy_params"]
    tickers = ["SPY", "QQQ"]  # match paper trading tickers

    # Build strategy instances
    strategy_list = []
    for name, params in strategies_config.items():
        if name not in STRATEGY_REGISTRY:
            print(f"  WARNING: Strategy '{name}' not in registry, skipping")
            continue
        cls = STRATEGY_REGISTRY[name]
        strategy_list.append((name, cls(params)))

    # Load options cache (cache_only — no API calls)
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
        starting_capital=STARTING_CAPITAL,
        options_cache=options_cache,
    )

    print(f"  Running backtest: {start.date()} to {end.date()}...")
    t0 = time.time()
    results = bt.run()
    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s — {results['combined']['total_trades']} trades")

    return results


# ── 3. Compare metrics ──────────────────────────────────────────────────────

def compare_metrics(
    live: Dict[str, Any],
    backtest: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Compare live vs backtest metrics and assign PASS/WARN/FAIL status."""

    comparisons = []

    # Define metric comparisons: (name, live_key, bt_key, format, threshold_warn, threshold_fail, is_pp)
    # is_pp = True means percentage-point comparison instead of % deviation
    metric_defs = [
        ("Total Trades",   "total_trades",   "total_trades",   "d",     None,  None,  False),
        ("Win Rate",       "win_rate",       "win_rate",       ".1f%",  10,    20,    True),
        ("Total P&L",      "total_pnl",      "total_pnl",      "$,.2f", None,  None,  False),
        ("Avg Winner",     "avg_win",        "avg_win",        "$,.2f", 30,    60,    False),
        ("Avg Loser",      "avg_loss",       "avg_loss",       "$,.2f", 50,    100,   False),
        ("Profit Factor",  "profit_factor",  "profit_factor",  ".2f",   50,    100,   False),
        ("Max Drawdown",   "max_drawdown",   "max_drawdown",   ".2f%",  50,    100,   False),
        ("Return %",       "return_pct",     "return_pct",     ".2f%",  None,  None,  False),
    ]

    bt_combined = backtest.get("combined", {})

    for name, live_key, bt_key, fmt, warn_thresh, fail_thresh, is_pp in metric_defs:
        live_val = live.get(live_key, 0)
        bt_val = bt_combined.get(bt_key, 0)

        # Compute deviation
        if is_pp:
            deviation = live_val - bt_val  # percentage points
            dev_str = f"{deviation:+.1f}pp"
        elif bt_val != 0:
            deviation = ((live_val - bt_val) / abs(bt_val)) * 100
            dev_str = f"{deviation:+.1f}%"
        elif live_val != 0:
            deviation = 100.0  # bt is 0 but live isn't
            dev_str = "N/A"
        else:
            deviation = 0.0
            dev_str = "0.0%"

        # Determine status
        abs_dev = abs(deviation)
        if warn_thresh is None or fail_thresh is None:
            status = "INFO"
        elif abs_dev <= warn_thresh:
            status = "PASS"
        elif abs_dev <= fail_thresh:
            status = "WARN"
        else:
            status = "FAIL"

        # Format values for display
        live_str = _format_val(live_val, fmt)
        bt_str = _format_val(bt_val, fmt)

        comparisons.append({
            "metric": name,
            "live_value": live_val,
            "backtest_value": bt_val,
            "live_str": live_str,
            "backtest_str": bt_str,
            "deviation_str": dev_str,
            "deviation_pct": deviation,
            "status": status,
        })

    # Per-strategy comparisons
    bt_per_strategy = backtest.get("per_strategy", {})
    live_per_strategy = live.get("per_strategy", {})
    all_strategies = sorted(set(list(live_per_strategy.keys()) + list(bt_per_strategy.keys())))

    for sname in all_strategies:
        live_s = live_per_strategy.get(sname, {})
        bt_s = bt_per_strategy.get(sname, {})

        l_trades = live_s.get("total_trades", 0)
        b_trades = bt_s.get("total_trades", 0)
        l_wr = live_s.get("win_rate", 0)
        b_wr = bt_s.get("win_rate", 0)

        # Trade count
        comparisons.append({
            "metric": f"{sname} Trades",
            "live_value": l_trades,
            "backtest_value": b_trades,
            "live_str": str(l_trades),
            "backtest_str": str(b_trades),
            "deviation_str": f"{l_trades - b_trades:+d}",
            "deviation_pct": 0,
            "status": "INFO",
        })

        # Win rate
        wr_diff = l_wr - b_wr
        comparisons.append({
            "metric": f"{sname} WR",
            "live_value": l_wr,
            "backtest_value": b_wr,
            "live_str": f"{l_wr:.1f}%",
            "backtest_str": f"{b_wr:.1f}%",
            "deviation_str": f"{wr_diff:+.1f}pp",
            "deviation_pct": wr_diff,
            "status": "PASS" if abs(wr_diff) <= 15 else "WARN",
        })

    return comparisons


def _format_val(val: Any, fmt: str) -> str:
    """Format a numeric value for display."""
    if fmt == "d":
        return str(int(val))
    elif fmt.startswith("$"):
        actual_fmt = fmt[1:]  # strip leading $
        return f"${val:{actual_fmt}}"
    elif fmt.endswith("%"):
        actual_fmt = fmt[:-1]
        return f"{val:{actual_fmt}}%"
    else:
        return f"{val:{fmt}}"


# ── 4. Print report ────────────────────────────────────────────────────────

def print_report(
    live: Dict[str, Any],
    backtest: Optional[Dict[str, Any]],
    comparisons: Optional[List[Dict]],
) -> None:
    """Print formatted comparison report."""
    start = str(live.get("start_date", "?"))[:10]
    end = str(live.get("end_date", "?"))[:10]

    print()
    print("=" * 68)
    print(f"  LIVE vs BACKTEST COMPARISON — {start} to {end}")
    print("=" * 68)

    if comparisons and backtest:
        # Split into main metrics and strategy breakdown
        # Strategy metrics have names like "iron_condor Trades" / "iron_condor WR"
        strat_names = set(live.get("per_strategy", {}).keys()) | set((backtest or {}).get("per_strategy", {}).keys())
        strat_metrics = [c for c in comparisons if any(c["metric"].startswith(s) for s in strat_names)]
        main_metrics = [c for c in comparisons if c not in strat_metrics]

        # Main metrics table
        print()
        print(f"  {'Metric':<20s} {'Live':>10s}  {'Backtest':>10s}  {'Deviation':>10s}  {'Status':>6s}")
        print(f"  {'─' * 20} {'─' * 10}  {'─' * 10}  {'─' * 10}  {'─' * 6}")

        for c in main_metrics:
            status_icon = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL", "INFO": "INFO"}[c["status"]]
            print(f"  {c['metric']:<20s} {c['live_str']:>10s}  {c['backtest_str']:>10s}  {c['deviation_str']:>10s}  {status_icon:>6s}")

        # Strategy breakdown
        if strat_metrics:
            print()
            print("  STRATEGY BREAKDOWN:")
            print(f"  {'Metric':<20s} {'Live':>10s}  {'Backtest':>10s}  {'Deviation':>10s}  {'Status':>6s}")
            print(f"  {'─' * 20} {'─' * 10}  {'─' * 10}  {'─' * 10}  {'─' * 6}")
            for c in strat_metrics:
                print(f"  {c['metric']:<20s} {c['live_str']:>10s}  {c['backtest_str']:>10s}  {c['deviation_str']:>10s}  {c['status']:>6s}")

    else:
        # Live-only report (no backtest run)
        print()
        print("  LIVE METRICS ONLY (backtest skipped — see warning below)")
        print()
        print(f"  Total Trades:    {live['total_trades']}")
        print(f"  Win Rate:        {live['win_rate']:.1f}%")
        print(f"  Total P&L:       ${live['total_pnl']:,.2f}")
        print(f"  Avg Winner:      ${live['avg_win']:,.2f}")
        print(f"  Avg Loser:       ${live['avg_loss']:,.2f}")
        print(f"  Profit Factor:   {live['profit_factor']:.2f}")
        print(f"  Max Drawdown:    {live['max_drawdown']:.2f}%")
        print(f"  Return %:        {live['return_pct']:.2f}%")

        if live.get("per_strategy"):
            print()
            print("  STRATEGY BREAKDOWN:")
            for sname, sdata in live["per_strategy"].items():
                print(f"    {sname}: {sdata['total_trades']} trades, {sdata['win_rate']:.1f}% WR, ${sdata['total_pnl']:,.2f} PnL")

    # Sample size warning
    n = live.get("total_trades", 0)
    print()
    if n < 50:
        print(f"  SAMPLE SIZE WARNING: Only {n} live trades — comparison has")
        print(f"  low statistical significance. Recommend 50+ trades.")
    else:
        print(f"  Sample size: {n} trades (adequate for directional comparison).")

    print("=" * 68)
    print()


# ── Main ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare live paper-trading results against backtest expectations.",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Override start date (YYYY-MM-DD). Auto-detected from DB if omitted.",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Override end date (YYYY-MM-DD). Auto-detected from DB if omitted.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(DEFAULT_CONFIG),
        help=f"Path to champion config JSON (default: {DEFAULT_CONFIG})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("=" * 68)
    print("  LIVE vs BACKTEST — Paper Trading Validation")
    print("=" * 68)

    # Step 1: Load live trades
    print("\n[1/3] Loading live paper trades...")
    trades = load_live_trades()
    live = compute_live_metrics(trades)
    n = live.get("total_trades", 0)
    print(f"  Found {n} closed trades")

    if n == 0:
        print("  ERROR: No closed paper trades found. Nothing to compare.")
        return 1

    # Determine date range
    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    elif live.get("start_date"):
        start_dt = datetime.strptime(live["start_date"][:10], "%Y-%m-%d")
    else:
        print("  ERROR: Cannot determine start date. Use --start.")
        return 1

    if args.end:
        end_dt = datetime.strptime(args.end, "%Y-%m-%d")
    elif live.get("end_date"):
        end_dt = datetime.strptime(live["end_date"][:10], "%Y-%m-%d")
    else:
        end_dt = datetime.now()

    print(f"  Date range: {start_dt.date()} to {end_dt.date()}")

    # Step 2: Run backtest (skip if < 5 trades)
    backtest = None
    comparisons = None

    if n < 5:
        print(f"\n[2/3] Skipping backtest — only {n} trades (need >= 5)")
        print("  Showing live-only metrics.")
    else:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"  ERROR: Config not found: {config_path}")
            return 1

        print(f"\n[2/3] Running backtest with {config_path.name}...")
        try:
            backtest = run_backtest_for_range(config_path, start_dt, end_dt)
        except Exception as e:
            print(f"  ERROR: Backtest failed: {e}")
            print("  Falling back to live-only report.")

    # Step 3: Compare and report
    print("\n[3/3] Generating comparison report...")
    if backtest:
        comparisons = compare_metrics(live, backtest)

    print_report(live, backtest, comparisons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
