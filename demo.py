#!/usr/bin/env python3
"""
Demo Script - Generate Sample Alerts
This script creates sample alerts to demonstrate the system's output.
"""

from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent))

from alerts import AlertGenerator
from utils import load_config


def create_sample_opportunities():
    """
    Create sample credit spread opportunities for demonstration.
    """
    opportunities = [
        {
            'ticker': 'SPY',
            'type': 'bull_put_spread',
            'expiration': datetime.now() + timedelta(days=35),
            'dte': 35,
            'short_strike': 485.0,
            'long_strike': 480.0,
            'short_delta': 0.12,
            'credit': 1.75,
            'max_loss': 3.25,
            'max_profit': 1.75,
            'profit_target': 0.88,
            'stop_loss': 4.38,
            'spread_width': 5,
            'current_price': 505.25,
            'distance_to_short': 20.25,
            'pop': 88.0,
            'risk_reward': 0.54,
            'score': 78.5,
        },
        {
            'ticker': 'QQQ',
            'type': 'bull_put_spread',
            'expiration': datetime.now() + timedelta(days=42),
            'dte': 42,
            'short_strike': 420.0,
            'long_strike': 415.0,
            'short_delta': 0.14,
            'credit': 1.90,
            'max_loss': 3.10,
            'max_profit': 1.90,
            'profit_target': 0.95,
            'stop_loss': 4.75,
            'spread_width': 5,
            'current_price': 442.50,
            'distance_to_short': 22.50,
            'pop': 86.0,
            'risk_reward': 0.61,
            'score': 75.2,
        },
        {
            'ticker': 'IWM',
            'type': 'bear_call_spread',
            'expiration': datetime.now() + timedelta(days=38),
            'dte': 38,
            'short_strike': 210.0,
            'long_strike': 215.0,
            'short_delta': 0.13,
            'credit': 1.65,
            'max_loss': 3.35,
            'max_profit': 1.65,
            'profit_target': 0.83,
            'stop_loss': 4.13,
            'spread_width': 5,
            'current_price': 198.75,
            'distance_to_short': 11.25,
            'pop': 87.0,
            'risk_reward': 0.49,
            'score': 72.8,
        },
    ]
    
    return opportunities


def main():
    """
    Generate sample alerts.
    """
    print("=" * 80)
    print("CREDIT SPREAD TRADING SYSTEM - DEMO")
    print("=" * 80)
    print()
    print("Generating sample alerts to demonstrate system output...")
    print()
    
    # Load config
    config = load_config('config.yaml')
    
    # Create alert generator
    alert_gen = AlertGenerator(config)
    
    # Generate sample opportunities
    opportunities = create_sample_opportunities()
    
    # Generate alerts
    outputs = alert_gen.generate_alerts(opportunities)
    
    print("Sample alerts generated!")
    print()
    print("Output files:")
    for output_type, path in outputs.items():
        print(f"  {output_type.upper()}: {path}")
    
    print()
    print("=" * 80)
    print("SAMPLE ALERT PREVIEW")
    print("=" * 80)
    print()
    
    # Display first alert as text
    opp = opportunities[0]
    print(f"Ticker: {opp['ticker']}")
    print(f"Type: {opp['type'].replace('_', ' ').upper()}")
    print(f"Score: {opp['score']}/100")
    print()
    print("Trade Setup:")
    print(f"  Sell ${opp['short_strike']:.2f} Put")
    print(f"  Buy  ${opp['long_strike']:.2f} Put")
    print(f"  Expiration: {opp['expiration'].strftime('%Y-%m-%d')} ({opp['dte']} DTE)")
    print(f"  Credit: ${opp['credit']:.2f}")
    print()
    print("Risk/Reward:")
    print(f"  Max Profit: ${opp['max_profit']:.2f}")
    print(f"  Target (50%): ${opp['profit_target']:.2f}")
    print(f"  Max Loss: ${opp['max_loss']:.2f}")
    print(f"  Stop Loss: ${opp['stop_loss']:.2f}")
    print()
    print("Probability:")
    print(f"  POP: {opp['pop']:.1f}%")
    print(f"  Delta: {opp['short_delta']:.3f}")
    print()
    print("Market Context:")
    print(f"  Current Price: ${opp['current_price']:.2f}")
    print(f"  Distance to Short Strike: ${opp['distance_to_short']:.2f}")
    print()
    print("=" * 80)
    print()
    print("Check the 'output/' directory for complete alerts in multiple formats!")
    print()


if __name__ == '__main__':
    main()
