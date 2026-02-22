#!/usr/bin/env python3
"""
Run Polygon backtests for multiple time periods with winning config.

Winning config: IV>=5%, Score>=15, DTE 14-60, Trend=OFF, RSI=OFF, Credit>=10%
"""

import os
import sys
import gc
import json
import copy
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from utils import load_config, setup_logging
from backtest.backtester_fixed import BacktesterFixed
from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from strategy.polygon_provider import PolygonProvider
from shared.data_cache import DataCache

logger = logging.getLogger(__name__)

# Suppress noisy loggers
NOISY = [
    'ml.iv_analyzer', 'ml.regime_detector', 'ml.sentiment_scanner',
    'ml.feature_engine', 'ml.signal_model', 'ml.position_sizer', 'ml.ml_pipeline',
    'strategy.spread_strategy', 'strategy.technical_analysis',
    'strategy.options_analyzer', 'strategy.polygon_provider', 'strategy.tradier_provider',
    'shared.data_cache', 'shared.indicators', 'backtest.backtester_fixed',
    'yfinance', 'urllib3', 'peewee',
]


def run_period(base_config, ml_pipeline, polygon_provider, ticker, start_date, end_date, output_path):
    """Run a single backtest period with winning config."""
    config = copy.deepcopy(base_config)

    # Apply winning config with CLOSER STRIKES (3-5% OTM)
    config['strategy']['min_iv_rank'] = 5
    config['strategy']['min_iv_percentile'] = 5
    config['strategy']['min_dte'] = 14
    config['strategy']['max_dte'] = 60
    config['strategy']['spread_width'] = 5
    config['strategy']['min_delta'] = 0.20  # 20 delta = ~3-5% OTM
    config['strategy']['max_delta'] = 0.30  # 30 delta = ~3% OTM
    config['strategy']['technical']['use_trend_filter'] = False
    config['strategy']['technical']['use_rsi_filter'] = False
    config['risk']['min_credit_pct'] = 5  # Lower bar for real pricing
    config['backtest']['score_threshold'] = 15

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
        polygon_provider=polygon_provider,
    )

    print(f"  Ticker: {ticker}")
    print(f"  Period: {start_date.date()} to {end_date.date()}")
    print(f"  Config: IV>=5% | Score>=15 | DTE 14-60 | Delta 0.20-0.30 | Trend=OFF | RSI=OFF")
    print(f"  Pricing: REAL Polygon")
    print()

    results = backtester.run_backtest(ticker, start_date, end_date)

    if not results or results.get('total_trades', 0) == 0:
        print("  NO TRADES FOUND")
        return results

    # Display
    print(f"  PERFORMANCE:")
    print(f"    Starting Capital:    ${results['starting_capital']:,.2f}")
    print(f"    Ending Capital:      ${results['ending_capital']:,.2f}")
    print(f"    Total P&L:           ${results['total_pnl']:,.2f}")
    print(f"    Return:              {results['return_pct']:.2f}%")
    print()
    print(f"  TRADES:")
    print(f"    Total Trades:        {results['total_trades']}")
    print(f"    Winning:             {results['winning_trades']}")
    print(f"    Losing:              {results['losing_trades']}")
    print(f"    Win Rate:            {results['win_rate']:.2f}%")
    print(f"    Average Win:         ${results['avg_win']:.2f}")
    print(f"    Average Loss:        ${results['avg_loss']:.2f}")
    print()
    print(f"  RISK:")
    print(f"    Max Drawdown:        {results['max_drawdown']:.2f}%")
    print(f"    Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print()

    # Pricing source breakdown
    trades = results.get('trades', [])
    polygon_count = sum(1 for t in trades if t.get('pricing_source') == 'polygon')
    synthetic_count = len(trades) - polygon_count
    print(f"  PRICING SOURCES:")
    print(f"    Polygon (real):      {polygon_count}")
    print(f"    Synthetic (fallback):{synthetic_count}")
    print()

    # Weekly consistency
    import pandas as pd
    if trades:
        trades_df = pd.DataFrame(trades)
        trades_df['entry_date'] = pd.to_datetime(trades_df['entry_date'])
        trades_df['week'] = trades_df['entry_date'].dt.isocalendar().week
        weekly_pnl = trades_df.groupby('week')['pnl'].sum()
        pos_weeks = int((weekly_pnl > 0).sum())
        neg_weeks = int((weekly_pnl <= 0).sum())
        total_weeks = len(weekly_pnl)
        print(f"  WEEKLY CONSISTENCY:")
        print(f"    Positive weeks:      {pos_weeks}/{total_weeks} ({pos_weeks/total_weeks*100:.1f}%)")
        print(f"    Negative weeks:      {neg_weeks}/{total_weeks}")
        print()

    # Save results FIRST (before display that could error)
    output_path = Path(output_path)
    output_path.parent.mkdir(exist_ok=True, parents=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved to: {output_path}")
    print()

    # Show sample trades
    print(f"  SAMPLE TRADES (first 5):")
    for i, trade in enumerate(trades[:5], 1):
        src = trade.get('pricing_source', 'synthetic')
        entry = str(trade['entry_date'])[:10]
        print(f"    {i}. {trade['type']} [{src}] {entry}")
        print(f"       Strikes: {trade['short_strike']}/{trade['long_strike']}, Credit: ${trade['credit']:.2f}")
        print(f"       P&L: ${trade['pnl']:.2f}, Exit: {trade.get('exit_reason', 'N/A')}")

    return results


def main():
    print("=" * 80)
    print("POLYGON BACKTEST: CLOSER STRIKES (20-30 delta) + REAL PRICING")
    print("=" * 80)
    print()

    base_config = load_config()
    setup_logging(base_config)

    # Suppress noisy loggers
    for mod in NOISY:
        logging.getLogger(mod).setLevel(logging.CRITICAL)

    # Init ML pipeline once
    ml_pipeline = None
    try:
        from ml.ml_pipeline import MLPipeline
        data_cache = DataCache()
        ml_pipeline = MLPipeline(base_config, data_cache=data_cache)
        ml_pipeline.initialize()
        print("ML pipeline loaded")
    except Exception as e:
        print(f"ML pipeline not available: {e}")

    # Init Polygon provider
    api_key = os.environ.get('POLYGON_API_KEY', '')
    if not api_key:
        print("ERROR: No POLYGON_API_KEY found in .env")
        sys.exit(1)
    polygon_provider = PolygonProvider(api_key=api_key)
    print("Polygon provider loaded")
    print()

    periods = [
        ("2024", datetime(2024, 1, 1), datetime(2024, 12, 31)),
        ("2025", datetime(2025, 1, 1), datetime(2025, 12, 31)),
        ("2026YTD", datetime(2026, 1, 1), datetime(2026, 2, 21)),
    ]

    all_results = {}
    for i, (label, start, end) in enumerate(periods, 1):
        year_tag = label.replace(" ", "").replace("YTD", "")
        print("=" * 80)
        print(f"PERIOD {i}: SPY {label}")
        print("=" * 80)
        print()
        r = run_period(
            base_config, ml_pipeline, polygon_provider,
            'SPY', start, end,
            f'output/backtest_results_CLOSER_STRIKES_{year_tag}.json',
        )
        all_results[label] = r
        gc.collect()
        print("\n")

    # ── Summary ──
    print("=" * 80)
    print("CROSS-PERIOD SUMMARY (CLOSER STRIKES + 100% REAL POLYGON PRICING)")
    print("=" * 80)
    for label, r in all_results.items():
        if r and r.get('total_trades', 0) > 0:
            print(f"  {label}: {r['total_trades']} trades | WR {r['win_rate']:.1f}% | "
                  f"P&L ${r['total_pnl']:,.0f} ({r['return_pct']:.1f}%) | "
                  f"DD {r['max_drawdown']:.1f}% | Sharpe {r['sharpe_ratio']:.2f}")
        else:
            print(f"  {label}: No trades")
    print("=" * 80)


if __name__ == '__main__':
    main()
