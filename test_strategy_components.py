#!/usr/bin/env python3
"""
Test Strategy Components to verify they work correctly
"""

import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from utils import load_config, setup_logging
from strategy import CreditSpreadStrategy, TechnicalAnalyzer
from shared.data_cache import DataCache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_options_chain(current_price: float, date: datetime) -> pd.DataFrame:
    """Create a simple test options chain."""
    chain_data = []
    
    # Create one expiration: 35 DTE
    exp_date = date + timedelta(days=35)
    
    # Create strikes around current price
    for pct in range(-10, 11, 1):
        strike = round(current_price * (1 + pct/100))
        
        # Puts
        distance_pct = (strike - current_price) / current_price
        put_delta = -0.5 * (1 + distance_pct)
        put_delta = max(-0.99, min(-0.01, put_delta))
        
        chain_data.append({
            'type': 'put',
            'strike': strike,
            'expiration': exp_date,
            'bid': max(0.01, abs(put_delta) * 5),
            'ask': max(0.02, abs(put_delta) * 5 * 1.1),
            'delta': put_delta,
            'iv': 0.30,  # 30% IV
        })
        
        # Calls
        call_delta = 0.5 * (1 - distance_pct)
        call_delta = max(0.01, min(0.99, call_delta))
        
        chain_data.append({
            'type': 'call',
            'strike': strike,
            'expiration': exp_date,
            'bid': max(0.01, call_delta * 5),
            'ask': max(0.02, call_delta * 5 * 1.1),
            'delta': call_delta,
            'iv': 0.30,
        })
    
    return pd.DataFrame(chain_data)


def main():
    """Test strategy components."""
    config = load_config()
    
    # Override IV filters for testing
    config['strategy']['min_iv_rank'] = 0
    config['strategy']['min_iv_percentile'] = 0
    
    strategy = CreditSpreadStrategy(config)
    tech_analyzer = TechnicalAnalyzer(config)
    
    # Create test price data
    dates = pd.date_range(end=datetime.now(), periods=252, freq='D')
    prices = 400 + np.cumsum(np.random.randn(252) * 2)  # Random walk around 400
    price_data = pd.DataFrame({
        'Close': prices,
        'High': prices + np.random.rand(252) * 2,
        'Low': prices - np.random.rand(252) * 2,
        'Volume': np.random.randint(100000, 200000, 252)
    }, index=dates)
    
    current_price = float(prices[-1])
    logger.info(f"Test price: ${current_price:.2f}")
    
    # Technical analysis
    tech_signals = tech_analyzer.analyze('SPY', price_data)
    logger.info(f"Technical signals: {tech_signals}")
    
    # Create options chain
    options_chain = create_test_options_chain(current_price, datetime.now())
    logger.info(f"Options chain rows: {len(options_chain)}")
    
    # Synthetic IV data (bypass real IV calculation)
    iv_data = {
        'current_iv': 30,
        'iv_rank': 50,
        'iv_percentile': 50,
    }
    logger.info(f"IV data: {iv_data}")
    
    # Evaluate opportunities
    logger.info("\nEvaluating spread opportunities...")
    opportunities = strategy.evaluate_spread_opportunity(
        ticker='SPY',
        option_chain=options_chain,
        technical_signals=tech_signals,
        iv_data=iv_data,
        current_price=current_price
    )
    
    logger.info(f"\nFound {len(opportunities)} opportunities:")
    for i, opp in enumerate(opportunities[:10], 1):
        logger.info(
            f"  #{i}: {opp['type']:20s} "
            f"Score={opp.get('score', 0):.1f}, "
            f"Credit=${opp['credit']:.2f}, "
            f"POP={opp['pop']:.1f}%"
        )
    
    if opportunities:
        best = opportunities[0]
        logger.info(f"\nBest opportunity details:")
        for key in ['ticker', 'type', 'short_strike', 'long_strike', 'credit', 
                    'max_loss', 'pop', 'score']:
            logger.info(f"  {key}: {best.get(key)}")
    else:
        logger.warning("No opportunities found!")


if __name__ == '__main__':
    main()
