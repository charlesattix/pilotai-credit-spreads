#!/usr/bin/env python3
"""
run_optimization.py — Multi-strategy optimization harness

Usage:
    python3 scripts/run_optimization.py                                   # baseline, all strategies
    python3 scripts/run_optimization.py --strategies credit_spread        # single strategy
    python3 scripts/run_optimization.py --strategies credit_spread,iron_condor
    python3 scripts/run_optimization.py --heuristic                       # fast mode (no Polygon)
    python3 scripts/run_optimization.py --heuristic --auto 5              # 5 auto-experiments
    python3 scripts/run_optimization.py --config configs/exp.json
    python3 scripts/run_optimization.py --strategy-params '{"credit_spread": {"otm_pct": 0.04}}'
    python3 scripts/run_optimization.py --years 2022,2023
    python3 scripts/run_optimization.py --dry-run
    python3 scripts/run_optimization.py --note "Testing wider DTE"

Writes results to output/leaderboard.json and output/optimization_log.json.
Calls validate_params.py automatically after each run.
"""

import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
DEFAULT_TICKERS = ["SPY"]
STARTING_CAPITAL = 100_000


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
        "current_phase": "Phase 0.4",
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


# ── PortfolioBacktester runner ──────────────────────────────────────────────

def build_strategies_config(
    strategy_names: List[str],
    param_overrides: Optional[Dict[str, Dict]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build a {strategy_name: params} dict using defaults + overrides."""
    from strategies import STRATEGY_REGISTRY

    overrides = param_overrides or {}
    config: Dict[str, Dict[str, Any]] = {}

    for name in strategy_names:
        if name not in STRATEGY_REGISTRY:
            raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
        cls = STRATEGY_REGISTRY[name]
        params = cls.get_default_params()
        if name in overrides:
            params.update(overrides[name])
        config[name] = params

    return config


def run_backtest(
    strategies_config: Dict[str, Dict],
    tickers: List[str],
    start: datetime,
    end: datetime,
    capital: float = STARTING_CAPITAL,
) -> Dict:
    """Run PortfolioBacktester with given strategy configs."""
    from engine.portfolio_backtester import PortfolioBacktester
    from strategies import STRATEGY_REGISTRY

    strategy_list = []
    for name, params in strategies_config.items():
        cls = STRATEGY_REGISTRY[name]
        strategy_list.append((name, cls(params)))

    bt = PortfolioBacktester(
        strategies=strategy_list,
        tickers=tickers,
        start_date=start,
        end_date=end,
        starting_capital=capital,
    )
    return bt.run()


def run_full(
    strategies_config: Dict[str, Dict],
    years: List[int],
    tickers: List[str],
    capital: float = STARTING_CAPITAL,
) -> Dict:
    """Run PortfolioBacktester over the full date range and return results."""
    start = datetime(min(years), 1, 1)
    end = datetime(max(years), 12, 31)

    t0 = time.time()
    print(f"  Running {start.year}-{end.year}...", end=" ", flush=True)
    try:
        results = run_backtest(strategies_config, tickers, start, end, capital)
        elapsed = time.time() - t0
        combined = results.get("combined", {})
        ret = combined.get("return_pct", 0)
        trades = combined.get("total_trades", 0)
        print(f"{ret:+.1f}%  {trades} trades  ({elapsed:.0f}s)")
        return results
    except Exception as e:
        elapsed = time.time() - t0
        print(f"ERROR: {e}  ({elapsed:.0f}s)")
        logger.exception("Backtest failed")
        return {
            "combined": {"return_pct": 0, "total_trades": 0, "max_drawdown": 0,
                         "win_rate": 0, "sharpe_ratio": 0, "total_pnl": 0},
            "yearly": {},
            "per_strategy": {},
            "trades": [],
            "error": str(e),
        }


# ── Extract per-year results for validation ──────────────────────────────────

def extract_yearly_results(results: Dict) -> Dict[str, Dict]:
    """Convert PortfolioBacktester yearly breakdown to validate_params format.

    The yearly dict from PortfolioBacktester has: total_pnl, trades, return_pct,
    win_rate, max_drawdown.  Checks A-F need: return_pct, total_trades,
    max_drawdown, win_rate, sharpe_ratio, monthly_pnl.
    """
    yearly = results.get("yearly", {})
    combined = results.get("combined", {})
    monthly_pnl = combined.get("monthly_pnl", {})

    results_by_year: Dict[str, Dict] = {}
    for yr_str, yr_data in yearly.items():
        # Filter monthly_pnl to this year
        year_monthly = {
            k: v for k, v in monthly_pnl.items() if k.startswith(yr_str)
        }

        results_by_year[yr_str] = {
            "return_pct": yr_data.get("return_pct", 0),
            "total_trades": yr_data.get("trades", 0),
            "max_drawdown": yr_data.get("max_drawdown", 0),
            "win_rate": yr_data.get("win_rate", 0),
            "sharpe_ratio": combined.get("sharpe_ratio", 0),
            "monthly_pnl": year_monthly,
            "total_pnl": yr_data.get("total_pnl", 0),
        }

    return results_by_year


# ── Summary & leaderboard ────────────────────────────────────────────────────

def compute_summary(results_by_year: dict) -> dict:
    """Compute summary stats from per-year results dict."""
    rets   = [r.get("return_pct", 0)   for r in results_by_year.values() if "error" not in r]
    dds    = [r.get("max_drawdown", 0) for r in results_by_year.values() if "error" not in r]
    trades = [r.get("total_trades", r.get("trades", 0))
              for r in results_by_year.values() if "error" not in r]

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

def print_results_table(run_id: str, strategies_config: dict, results_by_year: dict,
                        summary: dict, overfit_score: float = None, verdict: str = None):
    strat_names = list(strategies_config.keys())
    print()
    print("=" * 72)
    print(f"  Run: {run_id}")
    print(f"  Strategies: {', '.join(strat_names)}")
    # Show key params for first strategy (or top-level summary)
    if len(strat_names) == 1:
        params = strategies_config[strat_names[0]]
        parts = []
        for key in ["otm_pct", "target_dte", "spread_width", "profit_target_pct",
                     "stop_loss_multiplier", "max_risk_pct"]:
            if key in params:
                parts.append(f"{key}={params[key]}")
        if parts:
            print(f"  Params: {', '.join(parts)}")
    print("-" * 72)
    print(f"  {'Year':<8} {'Return':>9} {'Trades':>8} {'WR':>7} {'MaxDD':>8}")
    print("-" * 72)
    for yr, r in sorted(results_by_year.items()):
        if "error" in r:
            print(f"  {yr:<8} {'ERROR':>9}")
            continue
        ret    = r.get("return_pct", 0)
        trades = r.get("total_trades", r.get("trades", 0))
        wr     = r.get("win_rate", 0)
        dd     = r.get("max_drawdown", 0)
        flag   = " !" if ret >= 200 else (" +" if ret > 0 else " -")
        print(f"  {yr:<8} {ret:>+8.1f}%  {trades:>6}  {wr:>6.1f}%  {dd:>7.1f}%{flag}")
    print("-" * 72)
    print(f"  {'AVG':>8} {summary['avg_return']:>+8.1f}%  {summary['avg_trades']:>6}  "
          f"  {'--':>6}   {summary['worst_dd']:>7.1f}%")
    print(f"  Profitable years: {summary['years_profitable']}/{summary['years_total']}  "
          f"Consistency: {summary['consistency_score']:.0%}")
    if overfit_score is not None:
        label = "ROBUST" if overfit_score >= 0.70 else ("SUSPECT" if overfit_score >= 0.50 else "OVERFIT")
        print(f"  Overfit score: {overfit_score:.3f}  -> {label} {verdict or ''}")
    print("=" * 72)
    print()


# ── Auto-optimization loop ───────────────────────────────────────────────────

def run_auto_experiments(
    n_experiments: int,
    strategy_names: List[str],
    years: List[int],
    tickers: List[str],
    base_overrides: Optional[Dict[str, Dict]] = None,
    no_validate: bool = False,
    note: str = "",
):
    """Run N auto-experiments using Optimizer to suggest params."""
    from engine.optimizer import Optimizer

    # Build one optimizer per strategy
    optimizers = {name: Optimizer(strategy_name=name) for name in strategy_names}
    history: List[Dict] = []

    for i in range(n_experiments):
        run_id = f"auto_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        print(f"\n{'='*72}")
        print(f"  AUTO EXPERIMENT {i+1}/{n_experiments}  (run_id={run_id})")
        print(f"{'='*72}")

        # Generate params per strategy
        strategies_config: Dict[str, Dict] = {}
        for name in strategy_names:
            opt = optimizers[name]
            # Filter history for this strategy
            strat_history = [
                {"params": h["params"].get(name, {}), "score": h["score"]}
                for h in history
            ]
            params = opt.suggest(strat_history)
            # Apply any base overrides
            if base_overrides and name in base_overrides:
                params.update(base_overrides[name])
            strategies_config[name] = params

        # Run
        results = run_full(strategies_config, years, tickers)
        results_by_year = extract_yearly_results(results)
        summary = compute_summary(results_by_year)

        # Score
        score = Optimizer.compute_score(results)

        # Validation
        overfit_score = None
        verdict = None
        validation_detail = {}
        if not no_validate and len(years) >= 4:
            try:
                from scripts.validate_params import validate_params
                flat_params = _flatten_params(strategies_config)
                val = validate_params(
                    flat_params, results_by_year, years,
                    use_real=False, ticker=tickers[0], skip_jitter=True,
                )
                overfit_score = val["overfit_score"]
                verdict = val["verdict"]
                validation_detail = val
            except Exception as e:
                logger.warning("Validation failed: %s", e)

        print_results_table(run_id, strategies_config, results_by_year,
                            summary, overfit_score, verdict)

        # Record
        history.append({"params": strategies_config, "score": score})

        # Save to leaderboard
        entry = _build_entry(
            run_id, strategies_config, results, results_by_year,
            summary, overfit_score, verdict, validation_detail,
            tickers, years, note=f"auto {i+1}/{n_experiments} {note}",
        )
        append_to_leaderboard(entry)

    print(f"\n  Auto-optimization complete: {n_experiments} experiments run.")
    if history:
        best = max(history, key=lambda h: h["score"])
        print(f"  Best score: {best['score']:.4f}")


def _flatten_params(strategies_config: Dict[str, Dict]) -> Dict[str, Any]:
    """Flatten multi-strategy params into a single dict for validation.

    For single-strategy, just return the params. For multi-strategy,
    prefix with strategy name.
    """
    if len(strategies_config) == 1:
        return dict(next(iter(strategies_config.values())))
    flat = {}
    for name, params in strategies_config.items():
        for k, v in params.items():
            flat[f"{name}.{k}"] = v
    return flat


def _build_entry(
    run_id: str,
    strategies_config: Dict[str, Dict],
    results: Dict,
    results_by_year: Dict[str, Dict],
    summary: Dict,
    overfit_score: Optional[float],
    verdict: Optional[str],
    validation_detail: Dict,
    tickers: List[str],
    years: List[int],
    note: str = "",
    elapsed_sec: float = 0,
) -> Dict:
    """Build a leaderboard entry."""
    def _slim(r):
        return {k: v for k, v in r.items()
                if k not in ("trades", "equity_curve")}

    return {
        "run_id":           run_id,
        "experiment_id":    f"exp_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        "timestamp":        datetime.utcnow().isoformat(),
        "strategies":       list(strategies_config.keys()),
        "strategy_params":  strategies_config,
        "tickers":          tickers,
        "mode":             "heuristic",
        "years_run":        years,
        "results":          {yr: _slim(r) for yr, r in results_by_year.items()},
        "combined":         _slim(results.get("combined", {})),
        "per_strategy":     results.get("per_strategy", {}),
        "summary":          summary,
        "overfit_score":    overfit_score,
        "verdict":          verdict,
        "validation":       validation_detail,
        "elapsed_sec":      round(elapsed_sec),
        "note":             note,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Multi-strategy optimization harness")
    parser.add_argument("--config",         help="JSON file with strategy params overrides")
    parser.add_argument("--strategies",     help="Comma-separated strategy names (default: all)")
    parser.add_argument("--strategy-params", help="JSON string with per-strategy param overrides")
    parser.add_argument("--years",          help="Comma-separated years, e.g. 2022,2023")
    parser.add_argument("--tickers",        help="Comma-separated tickers (default: SPY)")
    parser.add_argument("--dry-run",        action="store_true", help="Show params without running")
    parser.add_argument("--heuristic",      action="store_true", help="Fast heuristic mode")
    parser.add_argument("--note",           default="", help="Experiment note for the log")
    parser.add_argument("--hypothesis",     default="", help="Pre-run hypothesis")
    parser.add_argument("--no-validate",    action="store_true", help="Skip overfit validation")
    parser.add_argument("--run-id",         help="Override auto-generated run ID")
    parser.add_argument("--auto",           type=int, default=0,
                        help="Run N auto-experiments using Optimizer")
    args = parser.parse_args()

    from strategies import STRATEGY_REGISTRY

    # Resolve strategy names
    if args.strategies:
        strategy_names = [s.strip() for s in args.strategies.split(",")]
    else:
        strategy_names = list(STRATEGY_REGISTRY.keys())

    # Parse per-strategy param overrides
    param_overrides: Optional[Dict[str, Dict]] = None
    if args.strategy_params:
        param_overrides = json.loads(args.strategy_params)
    elif args.config:
        with open(args.config) as f:
            param_overrides = json.load(f)
            # If the config is a flat dict (old-style), wrap for first strategy
            if param_overrides and not any(isinstance(v, dict) for v in param_overrides.values()):
                param_overrides = {strategy_names[0]: param_overrides}

    # Build strategies config
    strategies_config = build_strategies_config(strategy_names, param_overrides)

    # Years and tickers
    years = [int(y.strip()) for y in args.years.split(",")] if args.years else YEARS
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else DEFAULT_TICKERS

    run_id = args.run_id or f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    print()
    print("=" * 72)
    print("  OPERATION CRACK THE CODE -- Optimization Run")
    print(f"  Run ID     : {run_id}")
    print(f"  Strategies : {', '.join(strategy_names)}")
    print(f"  Mode       : {'heuristic (fast)' if args.heuristic else 'real data'}")
    print(f"  Years      : {years}")
    print(f"  Tickers    : {tickers}")
    print(f"  Note       : {args.note or '(none)'}")
    print("=" * 72)
    print()

    if args.dry_run:
        print("Strategy params:")
        for name, params in strategies_config.items():
            print(f"\n  [{name}]")
            for k, v in params.items():
                print(f"    {k}: {v}")
        return

    # Auto-optimization mode
    if args.auto > 0:
        run_auto_experiments(
            n_experiments=args.auto,
            strategy_names=strategy_names,
            years=years,
            tickers=tickers,
            base_overrides=param_overrides,
            no_validate=args.no_validate,
            note=args.note,
        )
        return

    # Log hypothesis before running
    hypothesis = args.hypothesis or f"Run with strategies: {strategy_names}"
    exp_id = f"exp_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    pre_log = {
        "experiment_id": exp_id,
        "run_id":        run_id,
        "timestamp":     datetime.utcnow().isoformat(),
        "phase":         "Phase 0.4 -- Optimizer",
        "hypothesis":    hypothesis,
        "note":          args.note,
        "strategies":    strategy_names,
        "strategy_params": strategies_config,
        "status":        "running",
    }
    append_to_opt_log(pre_log)

    t_total = time.time()
    print("Running portfolio backtest...")
    results = run_full(strategies_config, years, tickers)
    elapsed_total = time.time() - t_total

    results_by_year = extract_yearly_results(results)
    summary = compute_summary(results_by_year)

    # Run overfit validation
    overfit_score = None
    verdict = None
    validation_detail = {}

    if not args.no_validate and len(years) >= 4:
        print("Running overfit validation...")
        try:
            from scripts.validate_params import validate_params
            flat_params = _flatten_params(strategies_config)
            val = validate_params(
                flat_params, results_by_year, years,
                use_real=not args.heuristic, ticker=tickers[0],
            )
            overfit_score = val["overfit_score"]
            verdict       = val["verdict"]
            validation_detail = val
        except Exception as e:
            logger.warning("Validation failed: %s", e)
            overfit_score = None
            verdict = "VALIDATION_ERROR"

    print_results_table(run_id, strategies_config, results_by_year,
                        summary, overfit_score, verdict)

    # Build leaderboard entry
    entry = _build_entry(
        run_id, strategies_config, results, results_by_year,
        summary, overfit_score, verdict, validation_detail,
        tickers, years, args.note, elapsed_total,
    )
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

    print(f"  Results saved -> output/leaderboard.json  (total runs: {state['total_runs']})")
    if overfit_score is not None:
        if overfit_score >= 0.70:
            print(f"  ROBUST -- overfit_score={overfit_score:.3f}")
        elif overfit_score >= 0.50:
            print(f"  SUSPECT -- overfit_score={overfit_score:.3f}, investigate before accepting")
        else:
            print(f"  OVERFIT -- overfit_score={overfit_score:.3f}, rejected")
    print()

    # Signal if any year hit 200%+
    for yr, r in results_by_year.items():
        if r.get("return_pct", 0) >= 200:
            print(f"  BREAKTHROUGH: {yr} returned {r['return_pct']:+.1f}% !")
    if summary["avg_return"] >= 200:
        print(f"  MISSION COMPLETE: avg return across all years = {summary['avg_return']:+.1f}%!")

    return entry


if __name__ == "__main__":
    main()
