#!/usr/bin/env python3
"""
Run Enhanced Backtest with Real Alert Logic
Integrates ML scoring, IV filtering, regime detection, and full technical analysis.
"""

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

from utils import load_config, setup_logging
from backtest.backtester_enhanced import BacktesterEnhanced
from shared.data_cache import DataCache

logger = logging.getLogger(__name__)


def main():
    """Run enhanced backtest."""
    # Load config
    config = load_config()
    
    # Setup logging
    setup_logging(config)
    
    logger.info("=" * 80)
    logger.info("ENHANCED BACKTEST WITH REAL ALERT LOGIC")
    logger.info("=" * 80)
    
    # Initialize ML pipeline (optional but recommended)
    ml_pipeline = None
    try:
        from ml.ml_pipeline import MLPipeline
        data_cache = DataCache()
        ml_pipeline = MLPipeline(config, data_cache=data_cache)
        ml_pipeline.initialize()
        logger.info("✓ ML pipeline loaded successfully")
    except Exception as e:
        logger.warning(f"ML pipeline not available, using rules-based scoring only: {e}")
    
    # Create enhanced backtester
    backtester = BacktesterEnhanced(
        config=config,
        historical_data=None,  # Using synthetic options chains for now
        ml_pipeline=ml_pipeline,
    )
    
    # Run 1-year SPY backtest with threshold=40
    ticker = 'SPY'
    end_date = datetime(2024, 12, 31)  # Use historical date
    start_date = end_date - timedelta(days=365)
    
    logger.info(f"Ticker: {ticker}")
    logger.info(f"Start: {start_date.date()}")
    logger.info(f"End: {end_date.date()}")
    logger.info(f"Score threshold: {backtester.score_threshold}")
    logger.info("")
    
    # Run backtest
    results = backtester.run_backtest(ticker, start_date, end_date)
    
    # Display detailed results
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
    print(f"  Average Win:         ${results['avg_win']:,.2f}")
    print(f"  Average Loss:        ${results['avg_loss']:,.2f}")
    print(f"  Profit Factor:       {results['profit_factor']:.2f}")
    print("")
    
    print("RISK METRICS:")
    print(f"  Max Drawdown:        {results['max_drawdown']:.2f}%")
    print(f"  Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print("")
    
    print("OPPORTUNITY METRICS:")
    print(f"  Scans Performed:     {results.get('scan_count', 0)}")
    print(f"  Opportunities Found: {results.get('opportunity_count', 0)}")
    print(f"  Opps per Scan:       {results.get('opportunities_per_scan', 0):.1f}")
    print(f"  Entry Rate:          {results.get('entry_rate', 0):.1%}")
    print("")
    
    # Trade breakdown
    if results['total_trades'] > 0:
        print("TRADE BREAKDOWN:")
        for i, trade in enumerate(results['trades'][:10], 1):  # Show first 10
            entry = trade['entry_date'].strftime('%Y-%m-%d')
            exit = trade['exit_date'].strftime('%Y-%m-%d')
            pnl_str = f"${trade['pnl']:,.2f}"
            score_str = f"Score={trade.get('score', 0):.1f}" if trade.get('score') else ""
            regime_str = f"Regime={trade.get('regime', 'N/A')}" if trade.get('regime') else ""
            
            print(f"  #{i}: {trade['type']:20s} "
                  f"{entry} → {exit} | "
                  f"{pnl_str:>12s} | "
                  f"{score_str:12s} | "
                  f"{regime_str}")
        
        if results['total_trades'] > 10:
            print(f"  ... and {results['total_trades'] - 10} more trades")
    
    print("=" * 80)
    
    # Save detailed results
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)
    
    import json
    results_file = output_dir / 'enhanced_backtest_results.json'
    
    # Convert datetime objects to strings for JSON serialization
    def serialize_datetime(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=serialize_datetime)
    
    logger.info(f"\n✓ Detailed results saved to {results_file}")
    
    # Save opportunity log as CSV for analysis
    if results.get('opportunity_log'):
        import pandas as pd
        opp_df = pd.DataFrame(results['opportunity_log'])
        opp_file = output_dir / 'opportunity_log.csv'
        opp_df.to_csv(opp_file, index=False)
        logger.info(f"✓ Opportunity log saved to {opp_file}")
        
        # Quick analysis
        total_opps = len(opp_df)
        entered_opps = opp_df['entered'].sum()
        avg_score = opp_df['score'].mean()
        avg_entered_score = opp_df[opp_df['entered']]['score'].mean() if entered_opps > 0 else 0
        
        print(f"\nOPPORTUNITY ANALYSIS:")
        print(f"  Total Opportunities:     {total_opps}")
        print(f"  Opportunities Entered:   {entered_opps}")
        print(f"  Entry Rate:              {entered_opps/total_opps*100:.1f}%")
        print(f"  Avg Opportunity Score:   {avg_score:.1f}")
        print(f"  Avg Entered Score:       {avg_entered_score:.1f}")
        
        # Score distribution
        print(f"\n  Score Distribution:")
        for threshold in [30, 40, 50, 60, 70]:
            count = (opp_df['score'] >= threshold).sum()
            pct = count / total_opps * 100
            print(f"    Score >= {threshold}: {count:3d} ({pct:5.1f}%)")


if __name__ == '__main__':
    main()
