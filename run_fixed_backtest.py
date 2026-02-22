#!/usr/bin/env python3
"""
Run Fixed Backtest with REAL Strategy Logic + REAL Polygon Option Prices

Uses the properly integrated backtester that calls
strategy.evaluate_spread_opportunity() for signal generation, and
Polygon.io historical option prices for REAL P&L calculation.

Author: Charles
Date: 2026-02-21
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from utils import load_config, setup_logging
from backtest.backtester_fixed import BacktesterFixed
from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from strategy.polygon_provider import PolygonProvider
from shared.data_cache import DataCache

logger = logging.getLogger(__name__)


def main():
    """Run fixed backtest with real Polygon option prices."""
    # Check for --synthetic flag
    use_synthetic = '--synthetic' in sys.argv

    print("=" * 80)
    if use_synthetic:
        print("BACKTEST: REAL STRATEGY + SYNTHETIC OPTION PRICING")
    else:
        print("BACKTEST: REAL STRATEGY + REAL POLYGON OPTION PRICES")
    print("=" * 80)
    print()

    # Load config
    config = load_config()
    setup_logging(config)

    # Initialize strategy components
    logger.info("Initializing strategy components...")
    data_cache = DataCache()
    strategy = CreditSpreadStrategy(config)
    technical_analyzer = TechnicalAnalyzer(config)
    options_analyzer = OptionsAnalyzer(config, data_cache=data_cache)

    # Initialize ML pipeline (optional)
    ml_pipeline = None
    try:
        from ml.ml_pipeline import MLPipeline
        ml_pipeline = MLPipeline(config, data_cache=data_cache)
        ml_pipeline.initialize()
        print("ML pipeline loaded")
    except Exception as e:
        print(f"ML pipeline not available: {e}")

    # Initialize Polygon provider for real option prices
    polygon_provider = None
    if not use_synthetic:
        api_key = os.environ.get('POLYGON_API_KEY', '')
        if api_key:
            polygon_provider = PolygonProvider(api_key=api_key)
            print("Polygon provider loaded (REAL option prices)")
        else:
            print("WARNING: No POLYGON_API_KEY found, falling back to synthetic pricing")

    # Create backtester
    backtester = BacktesterFixed(
        config=config,
        strategy=strategy,
        technical_analyzer=technical_analyzer,
        options_analyzer=options_analyzer,
        ml_pipeline=ml_pipeline,
        polygon_provider=polygon_provider,
    )

    # Run backtest — support multiple tickers from config
    tickers = config.get('tickers', ['SPY'])
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 12, 31)

    # Allow CLI override: python run_fixed_backtest.py 2025 or 2026
    for arg in sys.argv[1:]:
        if arg.startswith('20') and len(arg) == 4:
            year = int(arg)
            start_date = datetime(year, 1, 1)
            end_date = min(datetime(year, 12, 31), datetime.now())

    pricing_mode = "SYNTHETIC" if use_synthetic else "REAL POLYGON"
    print(f"\nTickers: {tickers}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Pricing: {pricing_mode}")
    print(f"Score threshold: {backtester.score_threshold}")
    scan_days = config.get('risk', {}).get('scan_days', [0, 2, 4])
    print(f"Scan days: {scan_days} (0=Mon, 2=Wed, 4=Fri)")
    print(f"Max positions: {config['risk']['max_positions']}, per ticker: {config['risk'].get('max_positions_per_ticker', 2)}")
    print()

    # Run backtest with all tickers
    results = backtester.run_backtest(tickers, start_date, end_date)

    # Display results
    print("\n" + "=" * 80)
    print(f"BACKTEST RESULTS ({pricing_mode} PRICING)")
    print("=" * 80)
    print(f"Tickers: {tickers}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Score Threshold: {backtester.score_threshold}")
    print()

    print("PERFORMANCE METRICS:")
    print(f"  Starting Capital:    ${results['starting_capital']:,.2f}")
    print(f"  Ending Capital:      ${results['ending_capital']:,.2f}")
    print(f"  Total P&L:           ${results['total_pnl']:,.2f}")
    print(f"  Return:              {results['return_pct']:.2f}%")
    print()

    print("TRADE STATISTICS:")
    print(f"  Total Trades:        {results['total_trades']}")
    print(f"  Winning Trades:      {results['winning_trades']}")
    print(f"  Losing Trades:       {results['losing_trades']}")
    print(f"  Win Rate:            {results['win_rate']:.2f}%")
    print(f"  Average Win:         ${results['avg_win']:.2f}")
    print(f"  Average Loss:        ${results['avg_loss']:.2f}")
    print()

    print("RISK METRICS:")
    print(f"  Max Drawdown:        {results['max_drawdown']:.2f}%")
    print(f"  Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print()

    print("OPPORTUNITY METRICS:")
    print(f"  Scans Performed:     {results.get('scans_performed', 0)}")
    print(f"  Opportunities Found: {results.get('opportunities_found', 0)}")
    print()

    # Trade type breakdown
    trade_types = results.get('trade_types', {})
    if trade_types:
        print("TRADE TYPES:")
        for ttype, count in sorted(trade_types.items()):
            print(f"  {ttype:25s} {count}")
        print()

    # Scaling & rolling
    print("SCALING & MANAGEMENT:")
    print(f"  Avg contracts (Q1):  {results.get('avg_contracts_q1', 0):.1f}")
    print(f"  Avg contracts (Q4):  {results.get('avg_contracts_q4', 0):.1f}")
    print(f"  Rolled positions:    {results.get('rolled_positions', 0)}")
    print()

    # Count pricing sources
    trades = results.get('trades', [])
    polygon_trades = sum(1 for t in trades if t.get('pricing_source') == 'polygon')
    synthetic_trades = len(trades) - polygon_trades
    print(f"PRICING SOURCES:")
    print(f"  Polygon (real):      {polygon_trades}")
    print(f"  Synthetic (BS):      {synthetic_trades}")
    print()

    print("=" * 80)

    # Save results
    suffix = "synthetic" if use_synthetic else "polygon"
    year_str = start_date.strftime('%Y')
    output_path = Path(f'output/backtest_results_{suffix}_{year_str}.json')
    output_path.parent.mkdir(exist_ok=True, parents=True)

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to: {output_path}")

    # Show sample trades if any
    if results['total_trades'] > 0:
        print("\nSAMPLE TRADES (first 5):")
        for i, trade in enumerate(results['trades'][:5], 1):
            src = trade.get('pricing_source', 'synthetic')
            print(f"\n{i}. {trade['ticker']} {trade['type']} [{src}]")
            print(f"   Entry: {trade['entry_date']}, Score: {trade['score']:.1f}")
            print(f"   Strikes: {trade['short_strike']}/{trade['long_strike']}")
            print(f"   Credit: ${trade['credit']:.2f}, Contracts: {trade['contracts']}")
            print(f"   P&L: ${trade['pnl']:.2f}, Exit: {trade.get('exit_reason', 'N/A')}")


if __name__ == '__main__':
    main()
