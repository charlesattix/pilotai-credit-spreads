#!/usr/bin/env python3
"""
run_optimization.py — Optimization harness for Operation Crack The Code

Usage:
    python3 scripts/run_optimization.py                          # run baseline
    python3 scripts/run_optimization.py --config configs/exp.json
    python3 scripts/run_optimization.py --years 2022,2023       # subset
    python3 scripts/run_optimization.py --dry-run               # show params, don't run
    python3 scripts/run_optimization.py --heuristic             # fast mode (no Polygon)
    python3 scripts/run_optimization.py --note "Testing wider DTE"

Writes results to output/leaderboard.json and output/optimization_log.json.
Calls validate_params.py automatically after each run.
"""

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ── paths ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)

LEADERBOARD_PATH = OUTPUT / "leaderboard.json"
OPT_LOG_PATH     = OUTPUT / "optimization_log.json"
STATE_PATH       = OUTPUT / "optimization_state.json"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("opt")

# ── Default baseline params ──────────────────────────────────────────────────
BASELINE_PARAMS = {
    # Strike selection
    "target_delta":      0.12,
    "use_delta_selection": True,
    "otm_pct":           0.03,   # used when use_delta_selection=False
    "target_dte":        35,
    "min_dte":           25,
    # Spread structure
    "spread_width":      5,
    "min_credit_pct":    10,
    # Risk
    "stop_loss_multiplier": 2.5,
    "profit_target":     50,      # % of credit received
    "max_risk_per_trade": 2.0,    # % of starting capital
    "max_contracts":     5,
    # Mode
    "direction":         "both",  # both | bull_put | bear_call
}

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


# ── I/O helpers ──────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def load_leaderboard():
    return _load_json(LEADERBOARD_PATH, [])


def load_opt_log():
    return _load_json(OPT_LOG_PATH, [])


def load_state():
    return _load_json(STATE_PATH, {
        "current_phase": "Phase 0",
        "total_runs": 0,
        "best_run_id": None,
        "best_avg_return": None,
        "best_overfit_score": None,
        "last_updated": None,
    })


def save_state(state: dict):
    state["last_updated"] = datetime.utcnow().isoformat()
    _save_json(STATE_PATH, state)


def get_current_best(leaderboard: list):
    robust = [r for r in leaderboard if (r.get("overfit_score") or 0) >= 0.70]
    if not robust:
        return None
    return max(robust, key=lambda r: r["summary"]["avg_return"])


# ── Backtester runner ────────────────────────────────────────────────────────

def _build_config(params: dict) -> dict:
    """Merge params into a config dict the Backtester accepts."""
    return {
        "strategy": {
            "target_delta":        params.get("target_delta", 0.12),
            "use_delta_selection": params.get("use_delta_selection", True),
            "target_dte":          params.get("target_dte", 35),
            "min_dte":             params.get("min_dte", 25),
            "spread_width":        params.get("spread_width", 5),
            "min_credit_pct":      params.get("min_credit_pct", 10),
            "direction":           params.get("direction", "both"),
            "trend_ma_period":     params.get("trend_ma_period", 20),
            "momentum_filter_pct": params.get("momentum_filter_pct", None),
            "iron_condor":         {"enabled": False},
        },
        "risk": {
            "stop_loss_multiplier": params.get("stop_loss_multiplier", 2.5),
            "profit_target":        params.get("profit_target", 50),
            "max_risk_per_trade":   params.get("max_risk_per_trade", 2.0),
            "max_contracts":        params.get("max_contracts", 5),
            "max_positions":        50,
        },
        "backtest": {
            "starting_capital":   100_000,
            "commission_per_contract": 0.65,
            "slippage":           0.05,
            "exit_slippage":      0.10,
        },
    }


def run_year(ticker: str, year: int, params: dict, use_real_data: bool) -> dict:
    """Run a single-year backtest and return the results dict."""
    from backtest.backtester import Backtester

    config = _build_config(params)
    start = datetime(year, 1, 1)
    end   = datetime(year, 12, 31)

    hd = None
    if use_real_data:
        try:
            from backtest.historical_data import HistoricalOptionsData
            hd_config = {"polygon": {"api_key": os.getenv("POLYGON_API_KEY", "")},
                         "backtest": config["backtest"]}
            hd = HistoricalOptionsData(hd_config)
        except Exception as e:
            logger.warning("Could not init HistoricalOptionsData: %s — falling back to heuristic", e)

    bt = Backtester(config, historical_data=hd, otm_pct=params.get("otm_pct", 0.05))
    result = bt.run_backtest(ticker, start, end)
    result = result or {}

    # Enrich with year label
    result["year"] = year
    result["ticker"] = ticker
    result["mode"] = "real" if hd else "heuristic"
    return result


def _monthly_diversity_score(monthly_pnl: dict) -> float:
    """
    What fraction of months had at least one trade?
    Returns 0.0-1.0.
    """
    if not monthly_pnl:
        return 0.0
    months_with_trades = sum(1 for v in monthly_pnl.values() if v.get("trades", 0) > 0)
    return months_with_trades / 12


def run_all_years(params: dict, years: list, use_real_data: bool, ticker: str = "SPY") -> dict:
    """Run backtest for all requested years. Returns dict keyed by year string."""
    results = {}
    for year in years:
        t0 = time.time()
        print(f"  Running {year}...", end=" ", flush=True)
        try:
            r = run_year(ticker, year, params, use_real_data)
            elapsed = time.time() - t0
            ret = r.get("return_pct", 0)
            trades = r.get("total_trades", 0)
            print(f"{ret:+.1f}%  {trades} trades  ({elapsed:.0f}s)")
            results[str(year)] = r
        except Exception as e:
            print(f"ERROR: {e}")
            logger.exception("Year %d failed", year)
            results[str(year)] = {"year": year, "error": str(e), "return_pct": 0,
                                  "total_trades": 0, "max_drawdown": 0, "win_rate": 0,
                                  "sharpe_ratio": 0, "monthly_pnl": {}}
    return results


# ── Summary & leaderboard ────────────────────────────────────────────────────

def compute_summary(results_by_year: dict) -> dict:
    rets   = [r.get("return_pct", 0)   for r in results_by_year.values() if "error" not in r]
    dds    = [r.get("max_drawdown", 0) for r in results_by_year.values() if "error" not in r]
    trades = [r.get("total_trades", 0) for r in results_by_year.values() if "error" not in r]

    years_profitable = sum(1 for x in rets if x > 0)
    consistency_score = years_profitable / len(rets) if rets else 0

    return {
        "avg_return":         round(sum(rets) / len(rets), 2)  if rets else 0,
        "min_return":         round(min(rets), 2)               if rets else 0,
        "max_return":         round(max(rets), 2)               if rets else 0,
        "total_return":       round(sum(rets), 2)               if rets else 0,
        "worst_dd":           round(min(dds), 2)                if dds else 0,
        "avg_trades":         round(sum(trades) / len(trades))  if trades else 0,
        "years_profitable":   years_profitable,
        "years_total":        len(rets),
        "consistency_score":  round(consistency_score, 3),
    }


def append_to_leaderboard(entry: dict):
    lb = load_leaderboard()
    lb.append(entry)
    # Sort by avg_return descending (robust runs first)
    lb.sort(key=lambda x: (
        (x.get("overfit_score") or 0) >= 0.70,
        x["summary"]["avg_return"]
    ), reverse=True)
    _save_json(LEADERBOARD_PATH, lb)


def append_to_opt_log(entry: dict):
    log = load_opt_log()
    log.append(entry)
    _save_json(OPT_LOG_PATH, log)


# ── Print table ──────────────────────────────────────────────────────────────

def print_results_table(run_id: str, params: dict, results_by_year: dict, summary: dict,
                         overfit_score: float = None, verdict: str = None):
    print()
    print("═" * 72)
    print(f"  Run: {run_id}")
    print(f"  Params: delta={params.get('target_delta')}  dte={params.get('target_dte')}/{params.get('min_dte')}"
          f"  width=${params.get('spread_width')}  credit≥{params.get('min_credit_pct')}%"
          f"  sl={params.get('stop_loss_multiplier')}x  pt={params.get('profit_target')}%"
          f"  risk={params.get('max_risk_per_trade')}%")
    print("─" * 72)
    print(f"  {'Year':<8} {'Return':>9} {'Trades':>8} {'WR':>7} {'Sharpe':>8} {'MaxDD':>8}")
    print("─" * 72)
    for yr, r in sorted(results_by_year.items()):
        if "error" in r:
            print(f"  {yr:<8} {'ERROR':>9}")
            continue
        ret     = r.get("return_pct", 0)
        trades  = r.get("total_trades", 0)
        wr      = r.get("win_rate", 0)
        sharpe  = r.get("sharpe_ratio", 0)
        dd      = r.get("max_drawdown", 0)
        flag    = " 🏆" if ret >= 200 else (" ✓" if ret > 0 else " ✗")
        print(f"  {yr:<8} {ret:>+8.1f}%  {trades:>6}  {wr:>6.1f}%  {sharpe:>7.2f}  {dd:>7.1f}%{flag}")
    print("─" * 72)
    print(f"  {'AVG':>8} {summary['avg_return']:>+8.1f}%  {summary['avg_trades']:>6}  "
          f"  {'—':>6}    {'—':>6}   {summary['worst_dd']:>7.1f}%")
    print(f"  Profitable years: {summary['years_profitable']}/{summary['years_total']}  "
          f"Consistency: {summary['consistency_score']:.0%}")
    if overfit_score is not None:
        icon = "✅" if overfit_score >= 0.70 else ("⚠️ " if overfit_score >= 0.50 else "❌")
        print(f"  Overfit score: {overfit_score:.3f}  {icon} {verdict or ''}")
    print("═" * 72)
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run credit spread optimization experiment")
    parser.add_argument("--config",     help="JSON file with params (overrides baseline)")
    parser.add_argument("--years",      help="Comma-separated years, e.g. 2022,2023")
    parser.add_argument("--dry-run",    action="store_true", help="Show params without running")
    parser.add_argument("--heuristic",  action="store_true", help="Fast heuristic mode (no Polygon)")
    parser.add_argument("--note",       default="", help="Experiment note for the log")
    parser.add_argument("--hypothesis", default="", help="Pre-run hypothesis")
    parser.add_argument("--ticker",     default="SPY", help="Ticker to backtest (default SPY)")
    parser.add_argument("--no-validate", action="store_true", help="Skip overfit validation")
    parser.add_argument("--run-id",     help="Override auto-generated run ID")
    args = parser.parse_args()

    # Load params
    params = dict(BASELINE_PARAMS)
    if args.config:
        with open(args.config) as f:
            params.update(json.load(f))

    # Years to run
    if args.years:
        years = [int(y.strip()) for y in args.years.split(",")]
    else:
        years = YEARS

    use_real = not args.heuristic

    run_id = args.run_id or f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    print()
    print("═" * 72)
    print("  OPERATION CRACK THE CODE — Optimization Run")
    print(f"  Run ID  : {run_id}")
    print(f"  Mode    : {'heuristic (fast)' if not use_real else 'real data (Polygon)'}")
    print(f"  Years   : {years}")
    print(f"  Ticker  : {args.ticker}")
    print(f"  Note    : {args.note or '(none)'}")
    print("═" * 72)
    print()

    if args.dry_run:
        print("Params:")
        for k, v in params.items():
            print(f"  {k}: {v}")
        return

    # Log hypothesis before running (MASTERPLAN rule: log before every run)
    hypothesis = args.hypothesis or f"Baseline run with params: {params}"
    exp_id = f"exp_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    pre_log = {
        "experiment_id": exp_id,
        "run_id":        run_id,
        "timestamp":     datetime.utcnow().isoformat(),
        "phase":         "Phase 0 — Harness",
        "hypothesis":    hypothesis,
        "note":          args.note,
        "params":        params,
        "status":        "running",
    }
    append_to_opt_log(pre_log)

    t_total = time.time()
    print("Running backtests...")
    results_by_year = run_all_years(params, years, use_real, ticker=args.ticker)
    elapsed_total = time.time() - t_total

    summary = compute_summary(results_by_year)

    # Run overfit validation
    overfit_score = None
    verdict = None
    validation_detail = {}

    if not args.no_validate and len(years) >= 4:
        print("Running overfit validation...")
        try:
            from scripts.validate_params import validate_params
            val = validate_params(params, results_by_year, years, use_real, args.ticker)
            overfit_score = val["overfit_score"]
            verdict       = val["verdict"]
            validation_detail = val
        except Exception as e:
            logger.warning("Validation failed: %s", e)
            overfit_score = None
            verdict = "VALIDATION_ERROR"

    print_results_table(run_id, params, results_by_year, summary, overfit_score, verdict)

    # Build leaderboard entry (strip trades/equity_curve to keep file small)
    def _slim(r):
        slim = {k: v for k, v in r.items()
                if k not in ("trades", "equity_curve")}
        return slim

    entry = {
        "run_id":           run_id,
        "experiment_id":    exp_id,
        "timestamp":        datetime.utcnow().isoformat(),
        "params":           params,
        "ticker":           args.ticker,
        "mode":             "real" if use_real else "heuristic",
        "years_run":        years,
        "results":          {yr: _slim(r) for yr, r in results_by_year.items()},
        "summary":          summary,
        "overfit_score":    overfit_score,
        "verdict":          verdict,
        "validation":       validation_detail,
        "elapsed_sec":      round(elapsed_total),
        "note":             args.note,
    }
    append_to_leaderboard(entry)

    # Update opt log with outcome
    opt_log = load_opt_log()
    for item in reversed(opt_log):
        if item.get("run_id") == run_id:
            item["status"] = "complete"
            item["outcome"] = (
                f"avg_return={summary['avg_return']:+.1f}%  "
                f"years_profitable={summary['years_profitable']}/{summary['years_total']}  "
                f"overfit_score={overfit_score}"
            )
            item["overfit_score"] = overfit_score
            item["verdict"] = verdict
            break
    _save_json(OPT_LOG_PATH, opt_log)

    # Update state
    state = load_state()
    state["total_runs"] = state.get("total_runs", 0) + 1
    lb = load_leaderboard()
    best = get_current_best(lb)
    if best:
        state["best_run_id"]       = best["run_id"]
        state["best_avg_return"]   = best["summary"]["avg_return"]
        state["best_overfit_score"] = best.get("overfit_score")
    save_state(state)

    print(f"  Results saved → output/leaderboard.json  (total runs: {state['total_runs']})")
    if overfit_score is not None:
        if overfit_score >= 0.70:
            print(f"  ✅ ROBUST — overfit_score={overfit_score:.3f}")
        elif overfit_score >= 0.50:
            print(f"  ⚠️  SUSPECT — overfit_score={overfit_score:.3f}, investigate before accepting")
        else:
            print(f"  ❌ OVERFIT — overfit_score={overfit_score:.3f}, rejected")
    print()

    # Signal if any year hit 200%+
    for yr, r in results_by_year.items():
        if r.get("return_pct", 0) >= 200:
            print(f"  🏆 BREAKTHROUGH: {yr} returned {r['return_pct']:+.1f}% !")
    if summary["avg_return"] >= 200:
        print(f"  🏆🏆 MISSION COMPLETE: avg return across all years = {summary['avg_return']:+.1f}%!")

    return entry


if __name__ == "__main__":
    main()
