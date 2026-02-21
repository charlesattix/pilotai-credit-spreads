#!/usr/bin/env python3
"""
CRITICAL P0: Find Alert Settings That Yield Positive Weekly P&L

Carlos Directive (Feb 21, 11:32 AM):
"Top of the MASTERPLAN is to identify alert settings that yield positive trades 
and P&L every week of the year. Without this, the project is a massive failure."

This script:
1. Runs backtests with REAL Polygon historical options data
2. Tests systematic combinations of filters
3. Finds settings that deliver consistent weekly profits
4. Shows winning configuration
"""

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import Dict, List
import pandas as pd

from utils import load_config, setup_logging
from backtest.backtester import Backtester
from backtest.historical_data import HistoricalOptionsData

logger = logging.getLogger(__name__)


def run_backtest_variant(config: Dict, historical_data: HistoricalOptionsData, 
                        iv_rank_min: int, score_threshold: int, 
                        min_dte: int, max_dte: int) -> Dict:
    """Run a single backtest variant with specific settings."""
    
    # Modify config for this variant
    test_config = config.copy()
    test_config['strategy']['min_iv_rank'] = iv_rank_min
    test_config['strategy']['min_iv_percentile'] = iv_rank_min
    test_config['strategy']['min_dte'] = min_dte
    test_config['strategy']['max_dte'] = max_dte
    test_config['backtest']['score_threshold'] = score_threshold
    
    # Create backtester
    backtester = Backtester(test_config, historical_data=historical_data)
    
    # Run 1-year backtest
    ticker = 'SPY'
    end_date = datetime(2024, 12, 31)
    start_date = datetime(2024, 1, 1)
    
    logger.info(f"Testing: IV={iv_rank_min}%, Score={score_threshold}, DTE={min_dte}-{max_dte}")
    
    try:
        results = backtester.run_backtest(ticker, start_date, end_date)
        
        # Calculate weekly P&L consistency
        if results['total_trades'] > 0:
            trades_df = pd.DataFrame(results['trades'])
            trades_df['entry_date'] = pd.to_datetime(trades_df['entry_date'])
            trades_df['week'] = trades_df['entry_date'].dt.isocalendar().week
            
            weekly_pnl = trades_df.groupby('week')['pnl'].sum()
            positive_weeks = (weekly_pnl > 0).sum()
            total_weeks = len(weekly_pnl)
            weekly_consistency = positive_weeks / total_weeks if total_weeks > 0 else 0
            
            results['weekly_consistency'] = weekly_consistency
            results['positive_weeks'] = positive_weeks
            results['total_weeks_traded'] = total_weeks
        else:
            results['weekly_consistency'] = 0
            results['positive_weeks'] = 0
            results['total_weeks_traded'] = 0
        
        results['settings'] = {
            'iv_rank_min': iv_rank_min,
            'score_threshold': score_threshold,
            'min_dte': min_dte,
            'max_dte': max_dte,
        }
        
        return results
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        return {
            'total_trades': 0,
            'total_pnl': 0,
            'weekly_consistency': 0,
            'error': str(e),
            'settings': {
                'iv_rank_min': iv_rank_min,
                'score_threshold': score_threshold,
                'min_dte': min_dte,
                'max_dte': max_dte,
            }
        }


def main():
    """Run systematic backtest matrix to find profitable settings."""
    
    print("=" * 80)
    print("CRITICAL P0: FIND PROFITABLE ALERT SETTINGS")
    print("=" * 80)
    print()
    print("Mission: Find settings that yield positive weekly P&L over full year")
    print()
    
    # Load config
    config = load_config()
    setup_logging(config)
    
    # Initialize historical data
    logger.info("Initializing Polygon historical options data...")
    import os
    polygon_key = os.environ.get('POLYGON_API_KEY', '')
    if not polygon_key:
        polygon_cfg = config.get('data', {}).get('polygon', {})
        polygon_key = polygon_cfg.get('api_key', '')
        if polygon_key.startswith('${') and polygon_key.endswith('}'):
            polygon_key = os.environ.get(polygon_key[2:-1], '')
    
    if not polygon_key:
        print("❌ ERROR: No POLYGON_API_KEY found. Cannot run backtests with real data.")
        return
    
    historical_data = HistoricalOptionsData(
        api_key=polygon_key,
        cache_dir='data'
    )
    
    # Test matrix
    iv_rank_options = [10, 15, 20, 25]
    score_threshold_options = [25, 28, 30, 35, 40]
    dte_ranges = [(21, 45), (30, 45), (14, 45)]
    
    total_tests = len(iv_rank_options) * len(score_threshold_options) * len(dte_ranges)
    logger.info(f"Running {total_tests} backtest variants...")
    print(f"\nRunning {total_tests} backtest combinations...\n")
    
    results_list = []
    test_num = 0
    
    for iv_rank in iv_rank_options:
        for score_thresh in score_threshold_options:
            for min_dte, max_dte in dte_ranges:
                test_num += 1
                print(f"[{test_num}/{total_tests}] IV={iv_rank}%, Score={score_thresh}, DTE={min_dte}-{max_dte}")
                
                results = run_backtest_variant(
                    config, historical_data,
                    iv_rank, score_thresh, min_dte, max_dte
                )
                
                results_list.append(results)
                
                # Show quick summary
                if results['total_trades'] > 0:
                    print(f"  → {results['total_trades']} trades, P&L: ${results['total_pnl']:.2f}, "
                          f"Win Rate: {results['win_rate']:.1f}%, "
                          f"Weekly Consistency: {results['weekly_consistency']*100:.1f}%")
                else:
                    print(f"  → No trades found")
                print()
    
    # Analyze results
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS ANALYSIS")
    print("=" * 80)
    print()
    
    # Sort by weekly consistency + total P&L
    results_df = pd.DataFrame(results_list)
    results_df = results_df[results_df['total_trades'] > 0]  # Only configs with trades
    
    if len(results_df) == 0:
        print("❌ NO PROFITABLE CONFIGURATIONS FOUND")
        print("All filter combinations produced 0 trades.")
        print("\nRECOMMENDATION: The backtest logic needs fundamental fixes.")
        return
    
    results_df['score'] = (results_df['weekly_consistency'] * 100) + (results_df['return_pct'] / 10)
    results_df = results_df.sort_values('score', ascending=False)
    
    # Show top 5
    print("TOP 5 CONFIGURATIONS:\n")
    for idx, row in results_df.head(5).iterrows():
        settings = row['settings']
        print(f"#{idx+1}:")
        print(f"  Settings: IV={settings['iv_rank_min']}%, Score={settings['score_threshold']}, "
              f"DTE={settings['min_dte']}-{settings['max_dte']}")
        print(f"  Performance:")
        print(f"    - Trades: {row['total_trades']}")
        print(f"    - Total P&L: ${row['total_pnl']:.2f}")
        print(f"    - Return: {row['return_pct']:.2f}%")
        print(f"    - Win Rate: {row['win_rate']:.2f}%")
        print(f"    - Weekly Consistency: {row['weekly_consistency']*100:.1f}% ({row['positive_weeks']}/{row['total_weeks_traded']} weeks)")
        print(f"    - Sharpe Ratio: {row['sharpe_ratio']:.2f}")
        print()
    
    # Save results
    output_path = Path('output/profitable_settings_analysis.json')
    output_path.parent.mkdir(exist_ok=True, parents=True)
    
    results_df.to_json(output_path, orient='records', indent=2)
    print(f"✓ Full results saved to: {output_path}")
    
    # Show winner
    winner = results_df.iloc[0]
    print("\n" + "=" * 80)
    print("🏆 WINNING CONFIGURATION")
    print("=" * 80)
    print()
    print(f"IV Rank Minimum: {winner['settings']['iv_rank_min']}%")
    print(f"Score Threshold: {winner['settings']['score_threshold']}")
    print(f"DTE Range: {winner['settings']['min_dte']}-{winner['settings']['max_dte']} days")
    print()
    print(f"Expected Performance:")
    print(f"  - Annual Return: {winner['return_pct']:.2f}%")
    print(f"  - Win Rate: {winner['win_rate']:.2f}%")
    print(f"  - Weekly Profit Consistency: {winner['weekly_consistency']*100:.1f}%")
    print(f"  - Max Drawdown: {winner['max_drawdown']:.2f}%")
    print(f"  - Sharpe Ratio: {winner['sharpe_ratio']:.2f}")
    print()
    print("=" * 80)


if __name__ == '__main__':
    main()
