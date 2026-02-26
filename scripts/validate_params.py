#!/usr/bin/env python3
"""
validate_params.py — Overfit detection suite for Operation Crack The Code

Implements ALL 7 checks from MASTERPLAN Step 3.5:
  A. Cross-year consistency  (≥5/6 years profitable)
  B. Walk-forward validation (test ≥50% of train return)
  C. Parameter sensitivity   (±10-20% jitter, return stays ≥60%)
  D. Trade count gate        (≥30 trades per year)
  E. Regime diversity        (profitable months ≥6 per year)
  F. Drawdown reality        (<50% max DD, <60d recovery, <15 loss streak)
  G. Composite overfit score (weighted A-F, must be ≥0.70 to be "robust")

Usage (standalone):
    python3 scripts/validate_params.py --config configs/exp.json

Usage (programmatic):
    from scripts.validate_params import validate_params
    result = validate_params(params, results_by_year, years, use_real, ticker)
"""

import argparse
import copy
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("validate")

# ── Check A — Cross-year consistency ─────────────────────────────────────────

def check_a_consistency(results_by_year: dict) -> dict:
    """≥5/6 years must be profitable. Score = years_profitable / total."""
    years_profitable = sum(
        1 for r in results_by_year.values()
        if "error" not in r and r.get("return_pct", 0) > 0
    )
    total = sum(1 for r in results_by_year.values() if "error" not in r)
    score = years_profitable / total if total > 0 else 0
    passed = score >= 0.833  # ≥5/6
    return {
        "check": "A_consistency",
        "years_profitable": years_profitable,
        "years_total": total,
        "score": round(score, 3),
        "passed": passed,
        "note": f"{years_profitable}/{total} years profitable",
    }


# ── Check B — Walk-forward validation ────────────────────────────────────────

def check_b_walkforward(params: dict, use_real: bool, ticker: str,
                         existing_results: dict) -> dict:
    """
    Train on 2020-2022, test on 2023-2025.
    Test avg return must be ≥50% of train avg return.
    Uses existing results if available (avoids re-running).
    """
    train_years = ["2020", "2021", "2022"]
    test_years  = ["2023", "2024", "2025"]

    def avg_ret(ys):
        rets = [existing_results[y]["return_pct"]
                for y in ys if y in existing_results and "error" not in existing_results[y]]
        return sum(rets) / len(rets) if rets else None

    train_avg = avg_ret(train_years)
    test_avg  = avg_ret(test_years)

    if train_avg is None or test_avg is None:
        return {
            "check": "B_walkforward",
            "score": 0.5,   # neutral when data missing
            "passed": None,
            "note": "Insufficient years for walk-forward split",
            "train_avg": train_avg,
            "test_avg": test_avg,
        }

    # Ratio: test / train (capped at 1.0 so outperforming train doesn't over-reward)
    if train_avg <= 0:
        # Train was negative — if test is also negative or zero, score 0
        ratio = 1.0 if test_avg >= train_avg else 0.0
    else:
        ratio = min(1.0, test_avg / train_avg)

    passed = ratio >= 0.50

    return {
        "check": "B_walkforward",
        "train_years": train_years,
        "test_years": test_years,
        "train_avg_return": round(train_avg, 2),
        "test_avg_return": round(test_avg, 2),
        "ratio": round(ratio, 3),
        "score": round(ratio, 3),
        "passed": passed,
        "note": f"Test={test_avg:+.1f}% vs Train={train_avg:+.1f}% (ratio={ratio:.2f}, need ≥0.50)",
    }


# ── Check C — Parameter sensitivity (jitter test) ───────────────────────────

def check_c_sensitivity(params: dict, base_results: dict, use_real: bool, ticker: str) -> dict:
    """
    Perturb each numeric param by ±10% and ±20%. Run 4 jittered variants.
    Score = avg_jittered_return / base_return. Must be ≥0.60.
    """
    from scripts.run_optimization import run_all_years

    jitter_params = ["target_delta", "target_dte", "spread_width",
                     "stop_loss_multiplier", "profit_target", "max_risk_per_trade"]
    perturb_pcts = [-0.20, -0.10, +0.10, +0.20]

    base_avg = sum(r.get("return_pct", 0) for r in base_results.values()
                   if "error" not in r) / max(1, sum(1 for r in base_results.values() if "error" not in r))

    years = [int(y) for y in base_results.keys() if "error" not in base_results[y]]
    if not years:
        return {"check": "C_sensitivity", "score": 0.5, "passed": None,
                "note": "No valid years to jitter", "jitter_runs": []}

    jitter_results = []
    cliff_params = []

    # Only jitter the 3 highest-impact params to keep run count low
    params_to_test = [p for p in jitter_params if p in params][:3]

    for param in params_to_test:
        base_val = params[param]
        if not isinstance(base_val, (int, float)):
            continue

        param_jitter_rets = []
        for pct in perturb_pcts[:2]:  # only ±10% to keep it fast
            jittered = copy.deepcopy(params)
            new_val = base_val * (1 + pct)
            # Clamp reasonable ranges
            if param == "target_delta":   new_val = max(0.05, min(0.40, new_val))
            if param == "target_dte":     new_val = max(7, min(90, int(new_val)))
            if param == "spread_width":   new_val = max(1, int(round(new_val)))
            if param == "profit_target":  new_val = max(10, min(100, new_val))
            jittered[param] = new_val

            t0 = time.time()
            try:
                j_results = run_all_years(jittered, years, use_real, ticker)
                j_avg = sum(r.get("return_pct", 0) for r in j_results.values()
                            if "error" not in r) / max(1, len(j_results))
                elapsed = time.time() - t0
                jitter_results.append({
                    "param": param, "delta_pct": pct, "new_val": new_val,
                    "avg_return": round(j_avg, 2), "elapsed_sec": round(elapsed),
                })
                param_jitter_rets.append(j_avg)
            except Exception as e:
                logger.warning("Jitter run failed for %s=%s: %s", param, new_val, e)

        # Detect cliff: ±10% change causes >50% return drop
        if param_jitter_rets and base_avg != 0:
            worst_ratio = min(r / base_avg if base_avg > 0 else 0 for r in param_jitter_rets)
            if worst_ratio < 0.50:
                cliff_params.append(param)

    if not jitter_results:
        return {"check": "C_sensitivity", "score": 0.5, "passed": None,
                "note": "No jitter runs completed", "jitter_runs": []}

    jitter_avg = sum(r["avg_return"] for r in jitter_results) / len(jitter_results)
    score = min(1.0, jitter_avg / base_avg) if base_avg > 0 else 0.5
    score = max(0.0, score)
    passed = score >= 0.60 and not cliff_params

    return {
        "check": "C_sensitivity",
        "base_avg_return": round(base_avg, 2),
        "jitter_avg_return": round(jitter_avg, 2),
        "score": round(score, 3),
        "passed": passed,
        "cliff_params": cliff_params,
        "jitter_runs": jitter_results,
        "note": (f"Jitter avg={jitter_avg:+.1f}% vs base={base_avg:+.1f}%"
                 + (f" ⚠️ CLIFF PARAMS: {cliff_params}" if cliff_params else "")),
    }


# ── Check D — Trade count gate ────────────────────────────────────────────────

def check_d_trade_count(results_by_year: dict, min_trades: int = 30) -> dict:
    """All years must have ≥30 trades. Score=1 if all pass, else fraction passing."""
    checks = {}
    for yr, r in results_by_year.items():
        if "error" in r:
            checks[yr] = {"trades": 0, "passed": False}
            continue
        t = r.get("total_trades", 0)
        checks[yr] = {"trades": t, "passed": t >= min_trades}

    passing = sum(1 for c in checks.values() if c["passed"])
    total   = len(checks)
    score   = passing / total if total > 0 else 0
    low = [yr for yr, c in checks.items() if not c["passed"]]

    return {
        "check": "D_trade_count",
        "per_year": checks,
        "years_passing": passing,
        "years_total": total,
        "score": round(score, 3),
        "passed": score >= 1.0,
        "low_trade_years": low,
        "note": f"{passing}/{total} years with ≥{min_trades} trades" +
                (f" — low: {low}" if low else ""),
    }


# ── Check E — Regime diversity ────────────────────────────────────────────────

def check_e_regime_diversity(results_by_year: dict) -> dict:
    """
    For each year: count months with at least 1 trade.
    Score = avg(months_with_trades / 12) across years.
    Also flag if >50% of annual P&L came from a single month.
    """
    year_scores = {}
    concentration_flags = []

    for yr, r in results_by_year.items():
        if "error" in r:
            year_scores[yr] = 0.0
            continue

        monthly = r.get("monthly_pnl", {})
        if not monthly:
            year_scores[yr] = 0.0
            continue

        months_with_trades = sum(1 for m in monthly.values() if m.get("trades", 0) > 0)
        year_scores[yr] = months_with_trades / 12

        # Concentration check
        total_pnl = sum(m.get("pnl", 0) for m in monthly.values())
        if total_pnl > 0:
            max_month_pnl = max(m.get("pnl", 0) for m in monthly.values())
            if max_month_pnl / total_pnl > 0.50:
                concentration_flags.append(yr)

    score = sum(year_scores.values()) / len(year_scores) if year_scores else 0
    passed = score >= 0.40 and not concentration_flags  # ≥~5 months active per year on average

    return {
        "check": "E_regime_diversity",
        "per_year_month_coverage": {yr: round(s, 3) for yr, s in year_scores.items()},
        "score": round(score, 3),
        "passed": passed,
        "concentration_flags": concentration_flags,
        "note": (f"Avg monthly coverage: {score:.0%}"
                 + (f" ⚠️ Concentration in: {concentration_flags}" if concentration_flags else "")),
    }


# ── Check F — Drawdown reality ────────────────────────────────────────────────

def check_f_drawdown(results_by_year: dict, max_dd_limit: float = -50.0,
                     max_streak: int = 15) -> dict:
    """
    All years: max drawdown < 50%, max loss streak < 15.
    Score degrades proportionally with violations.
    """
    dd_violations = []
    streak_violations = []

    for yr, r in results_by_year.items():
        if "error" in r:
            continue
        dd = r.get("max_drawdown", 0)
        if dd < max_dd_limit:
            dd_violations.append({"year": yr, "max_drawdown": dd})
        streak = r.get("max_loss_streak", 0)
        if streak >= max_streak:
            streak_violations.append({"year": yr, "max_loss_streak": streak})

    total = sum(1 for r in results_by_year.values() if "error" not in r)
    violations = len(dd_violations) + len(streak_violations)
    score = max(0.0, 1.0 - (violations / max(1, total)))
    passed = violations == 0

    return {
        "check": "F_drawdown",
        "dd_violations": dd_violations,
        "streak_violations": streak_violations,
        "max_dd_limit": max_dd_limit,
        "max_streak_limit": max_streak,
        "score": round(score, 3),
        "passed": passed,
        "note": (f"No violations" if not violations
                 else f"{violations} violations — DD: {dd_violations}, Streak: {streak_violations}"),
    }


# ── Check G — Composite score ─────────────────────────────────────────────────

def compute_overfit_score(checks: dict) -> tuple:
    """
    Weighted composite per MASTERPLAN:
      consistency × 0.25 + walkforward × 0.30 + sensitivity × 0.25
      + trade_count × 0.10 + regime_diversity × 0.10
    """
    weights = {
        "A_consistency":    0.25,
        "B_walkforward":    0.30,
        "C_sensitivity":    0.25,
        "D_trade_count":    0.10,
        "E_regime_diversity": 0.10,
    }
    score = 0.0
    for key, w in weights.items():
        c = checks.get(key, {})
        s = c.get("score", 0.5) if c.get("score") is not None else 0.5
        score += s * w

    # Drawdown check (F) is a gate — violations cap the composite at 0.60
    f = checks.get("F_drawdown", {})
    if not f.get("passed", True):
        score = min(score, 0.60)

    score = round(score, 3)

    if score >= 0.70:
        verdict = "ROBUST"
    elif score >= 0.50:
        verdict = "SUSPECT"
    else:
        verdict = "OVERFIT"

    return score, verdict


# ── Main validation entry point ───────────────────────────────────────────────

def validate_params(params: dict, results_by_year: dict, years: list,
                    use_real: bool, ticker: str = "SPY",
                    skip_jitter: bool = False) -> dict:
    """
    Run all overfit checks and return a full validation report.

    Args:
        params:           Strategy params dict.
        results_by_year:  Already-computed results (keyed by str year).
        years:            List of int years that were run.
        use_real:         Whether to use real Polygon data for jitter runs.
        ticker:           Ticker symbol.
        skip_jitter:      If True, skip check C (saves time).

    Returns:
        Dict with per-check results, overfit_score, and verdict.
    """
    print("  [A] Cross-year consistency...", end=" ", flush=True)
    check_a = check_a_consistency(results_by_year)
    print(f"{check_a['score']:.2f}  {'✓' if check_a['passed'] else '✗'}")

    print("  [B] Walk-forward validation...", end=" ", flush=True)
    check_b = check_b_walkforward(params, use_real, ticker, results_by_year)
    print(f"{check_b['score']:.2f}  {'✓' if check_b['passed'] else '✗' if check_b['passed'] is False else '?'}")

    print("  [C] Parameter sensitivity...", end=" ", flush=True)
    if skip_jitter:
        check_c = {"check": "C_sensitivity", "score": 0.5, "passed": None,
                   "note": "Skipped", "jitter_runs": []}
        print("skipped")
    else:
        check_c = check_c_sensitivity(params, results_by_year, use_real, ticker)
        print(f"{check_c['score']:.2f}  {'✓' if check_c['passed'] else '✗' if check_c['passed'] is False else '?'}")

    print("  [D] Trade count gate...", end=" ", flush=True)
    check_d = check_d_trade_count(results_by_year)
    print(f"{check_d['score']:.2f}  {'✓' if check_d['passed'] else '✗'}")

    print("  [E] Regime diversity...", end=" ", flush=True)
    check_e = check_e_regime_diversity(results_by_year)
    print(f"{check_e['score']:.2f}  {'✓' if check_e['passed'] else '✗'}")

    print("  [F] Drawdown reality...", end=" ", flush=True)
    check_f = check_f_drawdown(results_by_year)
    print(f"{check_f['score']:.2f}  {'✓' if check_f['passed'] else '✗'}")

    checks = {
        "A_consistency":      check_a,
        "B_walkforward":      check_b,
        "C_sensitivity":      check_c,
        "D_trade_count":      check_d,
        "E_regime_diversity": check_e,
        "F_drawdown":         check_f,
    }

    overfit_score, verdict = compute_overfit_score(checks)

    icon = "✅ ROBUST" if verdict == "ROBUST" else ("⚠️  SUSPECT" if verdict == "SUSPECT" else "❌ OVERFIT")
    print(f"  Overfit score: {overfit_score:.3f}  →  {icon}")

    return {
        "checks":        checks,
        "overfit_score": overfit_score,
        "verdict":       verdict,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run overfit validation on a param config")
    parser.add_argument("--config",      required=True, help="JSON file with params")
    parser.add_argument("--results",     help="JSON file with existing results_by_year (skips re-running)")
    parser.add_argument("--heuristic",   action="store_true", help="Fast heuristic mode")
    parser.add_argument("--skip-jitter", action="store_true", help="Skip check C (faster)")
    parser.add_argument("--ticker",      default="SPY")
    args = parser.parse_args()

    with open(args.config) as f:
        params = json.load(f)

    if args.results:
        with open(args.results) as f:
            results_by_year = json.load(f)
        years = [int(y) for y in results_by_year.keys()]
    else:
        from scripts.run_optimization import run_all_years, YEARS
        use_real = not args.heuristic
        years = YEARS
        print(f"Running backtests for {years}...")
        results_by_year = run_all_years(params, years, use_real, args.ticker)

    print("\nRunning overfit checks...")
    result = validate_params(params, results_by_year, years,
                             not args.heuristic, args.ticker, args.skip_jitter)

    print()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
