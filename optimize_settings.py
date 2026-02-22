#!/usr/bin/env python3
"""
P0 CRITICAL: Optimize Alert Settings for Consistent Weekly Profits

Uses the FIXED backtester (with actual P&L calculation) to systematically test
filter combinations and find settings that yield:
- Positive P&L every week
- High win rate (65%+)
- Acceptable drawdown (<20%)

Fixes over v1:
- Incremental results saved after EACH combo (crash-safe)
- gc.collect() between combos to reduce memory pressure
- Noisy ML loggers suppressed to WARNING
- Scoring: weekly_consistency first, then win_rate, then return
"""

import sys
import os
import gc
import copy
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from utils import load_config, setup_logging
from backtest.backtester_fixed import BacktesterFixed
from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from shared.data_cache import DataCache

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path('output/optimization_results.json')


def suppress_noisy_loggers():
    """Suppress ALL repetitive loggers to CRITICAL during optimization.

    The ml_pipeline WARNING (regime mismatch) and yfinance ERROR (no fundamentals)
    fire on every single weekly scan, generating thousands of lines per combo.
    """
    noisy_modules = [
        'ml.iv_analyzer',
        'ml.regime_detector',
        'ml.sentiment_scanner',
        'ml.feature_engine',
        'ml.signal_model',
        'ml.position_sizer',
        'ml.ml_pipeline',
        'strategy.spread_strategy',
        'strategy.technical_analysis',
        'strategy.options_analyzer',
        'strategy.polygon_provider',
        'strategy.tradier_provider',
        'shared.data_cache',
        'shared.indicators',
        'backtest.backtester_fixed',
        'yfinance',
        'urllib3',
        'peewee',
    ]
    for mod in noisy_modules:
        logging.getLogger(mod).setLevel(logging.CRITICAL)


def load_previous_results():
    """Load previously saved results for crash recovery."""
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, 'r') as f:
                data = json.load(f)
            return data.get('results', []), set(data.get('completed_keys', []))
        except (json.JSONDecodeError, KeyError):
            pass
    return [], set()


def save_results_incremental(all_results, completed_keys):
    """Save results incrementally after each combo."""
    OUTPUT_PATH.parent.mkdir(exist_ok=True, parents=True)
    payload = {
        'timestamp': datetime.now().isoformat(),
        'total_completed': len(all_results),
        'completed_keys': list(completed_keys),
        'results': all_results,
    }
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(payload, f, indent=2, default=str)


def variant_key(iv, score, dte_min, dte_max, width, credit_pct, trend, rsi):
    """Generate a unique key for a variant combo."""
    return f"IV{iv}_SC{score}_DTE{dte_min}-{dte_max}_W{width}_CR{credit_pct}_T{trend}_R{rsi}"


def run_variant(base_config, ml_pipeline, iv_min, score_thresh, min_dte, max_dte,
                spread_width, min_credit_pct, use_trend_filter, use_rsi_filter):
    """Run a single backtest variant."""
    config = copy.deepcopy(base_config)
    config['strategy']['min_iv_rank'] = iv_min
    config['strategy']['min_iv_percentile'] = iv_min
    config['strategy']['min_dte'] = min_dte
    config['strategy']['max_dte'] = max_dte
    config['strategy']['spread_width'] = spread_width
    config['strategy']['technical']['use_trend_filter'] = use_trend_filter
    config['strategy']['technical']['use_rsi_filter'] = use_rsi_filter
    config['risk']['min_credit_pct'] = min_credit_pct
    config['backtest']['score_threshold'] = score_thresh

    data_cache = DataCache()
    strategy = CreditSpreadStrategy(config)
    technical_analyzer = TechnicalAnalyzer(config)
    options_analyzer = OptionsAnalyzer(config, data_cache=data_cache)

    backtester = BacktesterFixed(
        config=config,
        strategy=strategy,
        technical_analyzer=technical_analyzer,
        options_analyzer=options_analyzer,
        ml_pipeline=ml_pipeline,
    )

    ticker = 'SPY'
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 12, 31)

    try:
        results = backtester.run_backtest(ticker, start_date, end_date)
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        return None

    if not results or results['total_trades'] == 0:
        return None

    # Calculate weekly P&L consistency
    trades = results.get('trades', [])
    if trades:
        trades_df = pd.DataFrame(trades)
        trades_df['entry_date'] = pd.to_datetime(trades_df['entry_date'])
        trades_df['week'] = trades_df['entry_date'].dt.isocalendar().week
        weekly_pnl = trades_df.groupby('week')['pnl'].sum()
        positive_weeks = int((weekly_pnl > 0).sum())
        total_weeks = len(weekly_pnl)
        weekly_consistency = positive_weeks / total_weeks if total_weeks > 0 else 0
    else:
        positive_weeks = 0
        total_weeks = 0
        weekly_consistency = 0

    return {
        'settings': {
            'iv_min': iv_min,
            'score_thresh': score_thresh,
            'min_dte': min_dte,
            'max_dte': max_dte,
            'spread_width': spread_width,
            'min_credit_pct': min_credit_pct,
            'use_trend_filter': use_trend_filter,
            'use_rsi_filter': use_rsi_filter,
        },
        'total_trades': results['total_trades'],
        'win_rate': results['win_rate'],
        'total_pnl': results['total_pnl'],
        'return_pct': results['return_pct'],
        'max_drawdown': results['max_drawdown'],
        'sharpe_ratio': results['sharpe_ratio'],
        'positive_weeks': positive_weeks,
        'total_weeks': total_weeks,
        'weekly_consistency': round(weekly_consistency * 100, 1),
    }


def main():
    print("=" * 80)
    print("P0: OPTIMIZE ALERT SETTINGS FOR CONSISTENT WEEKLY PROFITS")
    print("=" * 80)
    print()

    base_config = load_config()
    setup_logging(base_config)

    # Suppress noisy loggers AFTER setup_logging
    suppress_noisy_loggers()

    # Initialize ML pipeline once (shared across all variants)
    ml_pipeline = None
    try:
        from ml.ml_pipeline import MLPipeline
        data_cache = DataCache()
        ml_pipeline = MLPipeline(base_config, data_cache=data_cache)
        ml_pipeline.initialize()
        print("ML pipeline loaded")
    except Exception as e:
        print(f"ML pipeline not available: {e}")

    # Load previous results for crash recovery
    all_results, completed_keys = load_previous_results()
    if completed_keys:
        print(f"Resuming: {len(completed_keys)} combos already completed")

    # ── Test Matrix ──────────────────────────────────────────────
    variants = []

    iv_options = [5, 10, 15, 20]
    score_options = [20, 25, 30, 35, 40]
    dte_options = [(14, 45), (21, 45), (30, 60)]
    width_options = [5]
    credit_pct_options = [15, 20]
    trend_options = [True, False]
    rsi_options = [True, False]

    # Phase 1: Test IV + Score + Trend filter (most impactful)
    for iv in iv_options:
        for score in score_options:
            for trend in trend_options:
                variants.append((iv, score, 21, 45, 5, 20, trend, True))

    # Phase 2: Test DTE ranges with best IV/score combos
    for dte_min, dte_max in dte_options:
        for credit_pct in credit_pct_options:
            variants.append((10, 25, dte_min, dte_max, 5, credit_pct, False, True))
            variants.append((10, 30, dte_min, dte_max, 5, credit_pct, True, True))

    # Phase 3: No filters at all (maximum opportunity)
    variants.append((5, 20, 14, 60, 5, 15, False, False))
    variants.append((5, 15, 14, 60, 5, 10, False, False))

    # Deduplicate
    variants = list(set(variants))

    total = len(variants)
    remaining = [(i, v) for i, v in enumerate(variants, 1)
                 if variant_key(*v) not in completed_keys]

    print(f"\nTotal variants: {total}, remaining: {len(remaining)}\n")

    for seq, (i, (iv, score, dte_min, dte_max, width, credit_pct, trend, rsi)) in enumerate(remaining, 1):
        key = variant_key(iv, score, dte_min, dte_max, width, credit_pct, trend, rsi)
        label = (f"IV={iv}% Score={score} DTE={dte_min}-{dte_max} "
                 f"Trend={'Y' if trend else 'N'} RSI={'Y' if rsi else 'N'} Credit={credit_pct}%")
        print(f"[{len(completed_keys)+1}/{total}] {label}", end=" ... ", flush=True)

        result = run_variant(
            base_config, ml_pipeline,
            iv, score, dte_min, dte_max, width, credit_pct, trend, rsi
        )

        completed_keys.add(key)

        if result:
            print(f"OK {result['total_trades']} trades, WR={result['win_rate']}%, "
                  f"P&L=${result['total_pnl']:,.0f}, DD={result['max_drawdown']:.1f}%, "
                  f"Weekly={result['weekly_consistency']}%")
            all_results.append(result)
        else:
            print("0 trades")

        # Incremental save + garbage collect after each combo
        save_results_incremental(all_results, completed_keys)
        gc.collect()

    # ── Results Analysis ─────────────────────────────────────────
    print("\n" + "=" * 80)
    print("RESULTS ANALYSIS")
    print("=" * 80)

    if not all_results:
        print("\nNO CONFIGURATIONS PRODUCED TRADES")
        return

    # Score by: weekly_consistency (primary), win_rate (secondary), return (tertiary)
    for r in all_results:
        r['composite'] = (
            r['weekly_consistency'] * 3       # Primary: weekly consistency
            + r['win_rate'] * 1               # Secondary: win rate
            + min(r['return_pct'], 300) / 10  # Tertiary: return (capped)
            - abs(r['max_drawdown']) / 2      # Penalize drawdown
        )

    all_results.sort(key=lambda x: x['composite'], reverse=True)

    print(f"\n{len(all_results)} configurations produced trades.\n")
    print("TOP 10 CONFIGURATIONS (scored by weekly consistency > win rate > return):\n")

    for i, r in enumerate(all_results[:10], 1):
        s = r['settings']
        print(f"#{i} (Composite: {r['composite']:.1f})")
        print(f"  Settings: IV>={s['iv_min']}% | Score>={s['score_thresh']} | "
              f"DTE {s['min_dte']}-{s['max_dte']} | Trend={'ON' if s['use_trend_filter'] else 'OFF'} | "
              f"RSI={'ON' if s['use_rsi_filter'] else 'OFF'} | Credit>={s['min_credit_pct']}%")
        print(f"  Performance: {r['total_trades']} trades | WR {r['win_rate']}% | "
              f"P&L ${r['total_pnl']:,.0f} ({r['return_pct']}%) | "
              f"DD {r['max_drawdown']:.1f}% | Sharpe {r['sharpe_ratio']:.2f}")
        print(f"  Weekly: {r['positive_weeks']}/{r['total_weeks']} weeks positive ({r['weekly_consistency']}%)")
        print()

    # Final save with sorted results
    save_results_incremental(all_results, completed_keys)
    print(f"Full results saved to: {OUTPUT_PATH}")

    # Show the winner
    winner = all_results[0]
    ws = winner['settings']
    print("\n" + "=" * 80)
    print("WINNING CONFIGURATION")
    print("=" * 80)
    print(f"\n  IV Rank Minimum:   {ws['iv_min']}%")
    print(f"  Score Threshold:   {ws['score_thresh']}")
    print(f"  DTE Range:         {ws['min_dte']}-{ws['max_dte']} days")
    print(f"  Spread Width:      ${ws['spread_width']}")
    print(f"  Min Credit:        {ws['min_credit_pct']}%")
    print(f"  Trend Filter:      {'ON' if ws['use_trend_filter'] else 'OFF'}")
    print(f"  RSI Filter:        {'ON' if ws['use_rsi_filter'] else 'OFF'}")
    print(f"\n  Annual Return:     {winner['return_pct']}%")
    print(f"  Win Rate:          {winner['win_rate']}%")
    print(f"  Total Trades:      {winner['total_trades']}")
    print(f"  Max Drawdown:      {winner['max_drawdown']:.1f}%")
    print(f"  Sharpe Ratio:      {winner['sharpe_ratio']:.2f}")
    print(f"  Weekly Consistency: {winner['positive_weeks']}/{winner['total_weeks']} ({winner['weekly_consistency']}%)")
    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
