#!/usr/bin/env python3
import pandas as pd
from datetime import datetime, timedelta
import math
from scipy.stats import norm

current_price = 689
exp_date = datetime.now() + timedelta(days=35)
dte = 35
iv = 0.25
t = dte / 365.0
sqrt_t = math.sqrt(t)

chain_data = []
# Create strikes at $1 increments
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

# Find puts with delta between -0.15 and -0.10
short_candidates = options_chain[(options_chain['delta'] >= -0.15) & (options_chain['delta'] <= -0.10)]
print(f'Short candidates (delta -0.15 to -0.10): {len(short_candidates)} strikes')
for _, row in short_candidates.iterrows():
    short_strike = row['strike']
    long_strike = short_strike - 5  # Spread width = 5
    long_exists = (options_chain['strike'] == long_strike).any()
    print(f'  Short={short_strike:.0f}, Delta={row["delta"]:.3f}, Long={long_strike:.0f} exists: {long_exists}')
    if long_exists:
        long_row = options_chain[options_chain['strike'] == long_strike].iloc[0]
        credit = row['bid'] - long_row['ask']
        min_credit = 5 * 0.20  # 20% of spread width
        print(f'    Credit=${credit:.2f}, Min=${min_credit:.2f}, OK: {credit >= min_credit}')
