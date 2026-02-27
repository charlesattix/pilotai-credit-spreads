"""
Walk-Forward Optimizer — Expanding-window validation integrated into the optimizer loop.

The optimizer ONLY sees train-period scores. Out-of-sample performance is
recorded but never guides parameter search. This prevents look-ahead bias
that occurs when optimizing on all years simultaneously.

Usage:
    wfo = WalkForwardOptimizer(all_years=[2020,2021,2022,2023,2024,2025])
    results = wfo.run(
        strategy_names=["credit_spread"],
        tickers=["SPY"],
        n_experiments_per_fold=20,
    )
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class WalkForwardOptimizer:
    """Expanding-window walk-forward optimization.

    Generates folds like:
        Fold 1: train=[2020,2021,2022], test=[2023]
        Fold 2: train=[2020,2021,2022,2023], test=[2024]
        Fold 3: train=[2020,2021,2022,2023,2024], test=[2025]

    For each fold, runs N optimizer experiments scoring ONLY on train years,
    then evaluates the best params out-of-sample on the test year.
    """

    def __init__(self, all_years: List[int], min_train_years: int = 3):
        self.all_years = sorted(all_years)
        self.min_train_years = min_train_years

    def generate_folds(self) -> List[Tuple[List[int], List[int]]]:
        """Generate expanding-window (train, test) year splits.

        Returns:
            List of (train_years, test_years) tuples.
        """
        folds = []
        for i in range(self.min_train_years, len(self.all_years)):
            train = self.all_years[:i]
            test = [self.all_years[i]]
            folds.append((train, test))
        return folds

    def run(
        self,
        strategy_names: List[str],
        tickers: List[str],
        n_experiments_per_fold: int = 20,
        base_overrides: Optional[Dict[str, Dict]] = None,
    ) -> Dict:
        """Run walk-forward optimization across all folds.

        For each fold:
          1. Create fresh Optimizer per strategy (clean history)
          2. Run N experiments, scoring on TRAIN years only
          3. Best params -> run on TEST years -> OOS results
          4. Record both train and OOS performance

        Args:
            strategy_names: List of strategy names to optimize.
            tickers: Tickers to backtest.
            n_experiments_per_fold: Number of optimizer experiments per fold.
            base_overrides: Fixed param overrides applied on top of optimizer suggestions.

        Returns:
            Dict with per-fold results, aggregate OOS stats, and WF ratio.
        """
        from engine.optimizer import Optimizer
        from scripts.run_optimization import (
            build_strategies_config,
            run_full,
            extract_yearly_results,
            compute_summary,
        )

        folds = self.generate_folds()
        if not folds:
            logger.warning("Not enough years for walk-forward (need >%d)", self.min_train_years)
            return {"error": "insufficient_years", "folds": []}

        fold_results = []
        t0 = time.time()

        for fold_idx, (train_years, test_years) in enumerate(folds):
            print(f"\n{'='*72}")
            print(f"  WALK-FORWARD FOLD {fold_idx+1}/{len(folds)}")
            print(f"  Train: {train_years}  |  Test: {test_years}")
            print(f"{'='*72}")

            # Fresh optimizer per strategy for this fold
            optimizers = {name: Optimizer(strategy_name=name) for name in strategy_names}
            history: List[Dict] = []
            best_score = float("-inf")
            best_params: Optional[Dict[str, Dict]] = None

            # Run N experiments, scoring on TRAIN years only
            for exp_idx in range(n_experiments_per_fold):
                # Generate params per strategy
                strategies_config: Dict[str, Dict] = {}
                for name in strategy_names:
                    opt = optimizers[name]
                    strat_history = [
                        {"params": h["params"].get(name, {}), "score": h["score"]}
                        for h in history
                    ]
                    params = opt.suggest(strat_history)
                    if base_overrides and name in base_overrides:
                        params.update(base_overrides[name])
                    strategies_config[name] = params

                # Run backtest on TRAIN years only
                print(f"  Fold {fold_idx+1} experiment {exp_idx+1}/{n_experiments_per_fold}:", end=" ")
                results = run_full(strategies_config, train_years, tickers)
                score = Optimizer.compute_score(results)

                history.append({"params": strategies_config, "score": score})

                if score > best_score:
                    best_score = score
                    best_params = strategies_config

            # Best params found — now evaluate OOS on test years
            if best_params is None:
                best_params = build_strategies_config(strategy_names, base_overrides)

            print(f"\n  Best train score: {best_score:.4f}")
            print(f"  Running OOS on {test_years}...")

            # Separate train and OOS backtests (no data leak)
            train_results = run_full(best_params, train_years, tickers)
            oos_results = run_full(best_params, test_years, tickers)

            train_by_year = extract_yearly_results(train_results)
            oos_by_year = extract_yearly_results(oos_results)
            train_summary = compute_summary(train_by_year)
            oos_summary = compute_summary(oos_by_year)

            fold_result = {
                "fold": fold_idx + 1,
                "train": train_years,
                "test": test_years,
                "n_experiments": n_experiments_per_fold,
                "best_params": best_params,
                "best_train_score": round(best_score, 4),
                "train_return": train_summary["avg_return"],
                "train_sharpe": train_results.get("combined", {}).get("sharpe_ratio", 0),
                "train_max_dd": train_summary["worst_dd"],
                "oos_return": oos_summary["avg_return"],
                "oos_sharpe": oos_results.get("combined", {}).get("sharpe_ratio", 0),
                "oos_max_dd": oos_summary["worst_dd"],
                "oos_trades": oos_summary["avg_trades"],
                "oos_win_rate": oos_results.get("combined", {}).get("win_rate", 0),
            }
            fold_results.append(fold_result)

            # Print fold summary
            print(f"\n  Fold {fold_idx+1} results:")
            print(f"    Train: {fold_result['train_return']:+.1f}% avg return, "
                  f"Sharpe {fold_result['train_sharpe']:.2f}, "
                  f"MaxDD {fold_result['train_max_dd']:.1f}%")
            print(f"    OOS:   {fold_result['oos_return']:+.1f}% avg return, "
                  f"Sharpe {fold_result['oos_sharpe']:.2f}, "
                  f"MaxDD {fold_result['oos_max_dd']:.1f}%")

        elapsed = time.time() - t0

        # Aggregate results
        oos_returns = [f["oos_return"] for f in fold_results]
        train_returns = [f["train_return"] for f in fold_results]

        avg_oos = sum(oos_returns) / len(oos_returns) if oos_returns else 0
        avg_train = sum(train_returns) / len(train_returns) if train_returns else 0
        wf_ratio = avg_oos / avg_train if avg_train != 0 else 0

        aggregate = {
            "mode": "walk_forward",
            "strategies": strategy_names,
            "tickers": tickers,
            "all_years": self.all_years,
            "min_train_years": self.min_train_years,
            "n_experiments_per_fold": n_experiments_per_fold,
            "elapsed_sec": round(elapsed),
            "walk_forward": {
                "folds": fold_results,
                "avg_oos_annual_return": round(avg_oos, 2),
                "avg_train_annual_return": round(avg_train, 2),
                "wf_ratio": round(wf_ratio, 3),
                "oos_returns_by_fold": [round(r, 2) for r in oos_returns],
                "folds_profitable": sum(1 for r in oos_returns if r > 0),
                "total_folds": len(fold_results),
            },
        }

        # Print final summary
        print(f"\n{'='*72}")
        print("  WALK-FORWARD SUMMARY")
        print(f"{'='*72}")
        print(f"  Folds: {len(fold_results)}")
        print(f"  Avg train return: {avg_train:+.1f}%")
        print(f"  Avg OOS return:   {avg_oos:+.1f}%")
        print(f"  WF ratio:         {wf_ratio:.3f}")
        print(f"  OOS profitable:   {aggregate['walk_forward']['folds_profitable']}/{len(fold_results)}")
        print(f"  Duration:         {elapsed/60:.1f} minutes")
        print(f"{'='*72}\n")

        return aggregate
