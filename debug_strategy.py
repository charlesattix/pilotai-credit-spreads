#!/usr/bin/env python3
"""Debug strategy to see why no opportunities are found"""
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

from datetime import datetime, timedelta
import pandas as pd
from scipy.stats import norm
import math
import yfinance as yf

from utils import load_config
from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from shared.data_cache import DataCache

config = load_config()
config['strategy']['min_iv_rank'] = 0
config['strategy']['min_iv_percentile'] = 0

strategy = CreditSpreadStrategy(config)
tech_analyzer = TechnicalAnalyzer(config)
opts_analyzer = OptionsAnalyzer(config, data_cache=DataCache())

# Get real price data
price_data = yf.Ticker('SPY').history(period='1y')
current_price = float(price_data['Close'].iloc[-1])
print(f'\nCurrent price: ${current_price:.2f}')

# Create synthetic options chain with realistic deltas
exp_date = datetime.now() + timedelta(days=35)
dte = 35
iv = 0.25
t = dte / 365.0
sqrt_t = math.sqrt(t)

chain_data = []
for strike in range(int(current_price * 0.90), int(current_price * 1.10), 1):
    moneyness = math.log(current_price / strike)
    d1 = (moneyness + 0.5 * iv**2 * t) / (iv * sqrt_t)
    put_delta = norm.cdf(d1) - 1
    put_delta = max(-0.99, min(-0.01, put_delta))
    
    intrinsic_put = max(0, strike - current_price)
    time_value = current_price * iv * sqrt_t * 0.4 * abs(put_delta)
    put_price = intrinsic_put + time_value
    
    chain_data.append({
        'type': 'put',
        'strike': float(strike),
        'expiration': exp_date,
        'bid': max(0.01, put_price * 0.97),
        'ask': put_price * 1.03,
        'delta': put_delta,
        'iv': iv,
    })

options_chain = pd.DataFrame(chain_data)
print(f'\nChain has {len(options_chain)} rows')
print('\nSample puts (delta range):')
sample = options_chain.sort_values('delta').iloc[::10]
for _, row in sample.iterrows():
    print(f'  Strike={row["strike"]:.0f}, Delta={row["delta"]:.3f}, Bid=${row["bid"]:.2f}')

# Technical analysis
tech_signals = tech_analyzer.analyze('SPY', price_data)
print(f'\nTechnical trend: {tech_signals.get("trend")}')
print(f'RSI: {tech_signals.get("rsi"):.1f}')

# IV data (manual)
iv_data = {'current_iv': 25, 'iv_rank': 50, 'iv_percentile': 50}
print(f'\nIV data: {iv_data}')

# Check conditions
bullish_check = strategy._check_bullish_conditions(tech_signals, iv_data)
print(f'\nBullish conditions met: {bullish_check}')

# Find spreads directly
print('\nFinding bull put spreads...')
bull_puts = strategy._find_bull_put_spreads('SPY', options_chain, current_price, exp_date)
print(f'Found {len(bull_puts)} bull put spreads')
if bull_puts:
    for opp in bull_puts[:5]:
        print(f'  Short={opp["short_strike"]:.0f}, Long={opp["long_strike"]:.0f}, Delta={opp["short_delta"]:.3f}, Credit=${opp["credit"]:.2f}')

# Full opportunity evaluation
print('\nFull opportunity evaluation...')
opps = strategy.evaluate_spread_opportunity('SPY', options_chain, tech_signals, iv_data, current_price)
print(f'Found {len(opps)} total opportunities')
if opps:
    for opp in opps[:5]:
        print(f'  {opp["type"]}: Short={opp["short_strike"]:.0f}, Delta={opp["short_delta"]:.3f}, Credit=${opp["credit"]:.2f}, Score={opp.get("score", 0):.1f}')
else:
    print('  No opportunities found')
    print('\nDebugging info:')
    print(f'  Delta range in chain: {options_chain["delta"].min():.3f} to {options_chain["delta"].max():.3f}')
    print(f'  Target delta range: {config["strategy"]["min_delta"]} to {config["strategy"]["max_delta"]}')
    print(f'  Spread width: ${config["strategy"]["spread_width"]}')
    print(f'  Min credit: {config["risk"]["min_credit_pct"]}% of spread width')
