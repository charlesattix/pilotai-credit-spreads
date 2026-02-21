#!/usr/bin/env python3
"""
Run Fixed Backtest with REAL Strategy Logic

This is the P0 CRITICAL test - uses the properly integrated backtester
that calls strategy.evaluate_spread_opportunity() just like live scanning.

Author: Charles
Date: 2026-02-21
"""

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

from utils import load_config, setup_logging
from backtest.backtester_fixed import BacktesterFixed
from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from shared.data_cache import DataCache

logger = logging.getLogger(__name__)


def main():
    """Run fixed backtest."""
    print("=" * 80)
    print("P0 CRITICAL: FIXED BACKTEST WITH REAL STRATEGY LOGIC")
    print("=" * 80)
    print()
    
    # Load config
    config = load_config()
    setup_logging(config)
    
    # Initialize strategy components (THE REAL ONES)
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
        logger.info("✓ ML pipeline loaded")
    except Exception as e:
        logger.warning(f"ML pipeline not available: {e}")
    
    # Create FIXED backtester
    backtester = BacktesterFixed(
        config=config,
        strategy=strategy,
        technical_analyzer=technical_analyzer,
        options_analyzer=options_analyzer,
        ml_pipeline=ml_pipeline,
        historical_data=None,  # Using synthetic options for now
    )
    
    # Run 1-year backtest
    ticker = 'SPY'
    end_date = datetime(2024, 12, 31)
    start_date = datetime(2024, 1, 1)
    
    logger.info(f"Ticker: {ticker}")
    logger.info(f"Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Score threshold: {backtester.score_threshold}")
    logger.info("")
    
    # Run backtest
    results = backtester.run_backtest(ticker, start_date, end_date)
    
    # Display results
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    print(f"Ticker: {ticker}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Score Threshold: {backtester.score_threshold}")
    print("")
    
    print("PERFORMANCE METRICS:")
    print(f"  Starting Capital:    ${results['starting_capital']:,.2f}")
    print(f"  Ending Capital:      ${results['ending_capital']:,.2f}")
    print(f"  Total P&L:           ${results['total_pnl']:,.2f}")
    print(f"  Return:              {results['return_pct']:.2f}%")
    print("")
    
    print("TRADE STATISTICS:")
    print(f"  Total Trades:        {results['total_trades']}")
    print(f"  Winning Trades:      {results['winning_trades']}")
    print(f"  Losing Trades:       {results['losing_trades']}")
    print(f"  Win Rate:            {results['win_rate']:.2f}%")
    print(f"  Average Win:         ${results['avg_win']:.2f}")
    print(f"  Average Loss:        ${results['avg_loss']:.2f}")
    print("")
    
    print("RISK METRICS:")
    print(f"  Max Drawdown:        {results['max_drawdown']:.2f}%")
    print(f"  Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print("")
    
    print("OPPORTUNITY METRICS:")
    print(f"  Scans Performed:     {results.get('scans_performed', 0)}")
    print(f"  Opportunities Found: {results.get('opportunities_found', 0)}")
    print("")
    
    print("=" * 80)
    
    # Save results
    import json
    output_path = Path('output/fixed_backtest_results.json')
    output_path.parent.mkdir(exist_ok=True, parents=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n✓ Results saved to: {output_path}")
    
    # Show sample trades if any
    if results['total_trades'] > 0:
        print("\nSAMPLE TRADES (first 5):")
        for i, trade in enumerate(results['trades'][:5], 1):
            print(f"\n{i}. {trade['ticker']} {trade['type']}")
            print(f"   Entry: {trade['entry_date']}, Score: {trade['score']:.1f}")
            print(f"   Strikes: {trade['short_strike']}/{trade['long_strike']}")
            print(f"   Credit: ${trade['credit']:.2f}, Contracts: {trade['contracts']}")
            print(f"   P&L: ${trade['pnl']:.2f}, Exit: {trade.get('exit_reason', 'N/A')}")


if __name__ == '__main__':
    main()
