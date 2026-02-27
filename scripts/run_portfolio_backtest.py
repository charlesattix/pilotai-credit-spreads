#!/usr/bin/env python3
"""
CLI entry point for the multi-strategy portfolio backtester.

Usage:
    python scripts/run_portfolio_backtest.py
    python scripts/run_portfolio_backtest.py --tickers SPY --start 2024-01-01 --end 2024-12-31
    python scripts/run_portfolio_backtest.py --strategies credit_spread iron_condor
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.constants import OUTPUT_DIR
from strategies import STRATEGY_REGISTRY
from engine.portfolio_backtester import PortfolioBacktester


def main():
    parser = argparse.ArgumentParser(description="Run multi-strategy portfolio backtest")
    parser.add_argument(
        "--strategies", nargs="+", default=list(STRATEGY_REGISTRY.keys()),
        help="Strategy names to include (default: all)",
    )
    parser.add_argument(
        "--tickers", nargs="+", default=["SPY", "QQQ", "IWM"],
        help="Tickers to trade (default: SPY QQQ IWM)",
    )
    parser.add_argument(
        "--start", type=str, default="2020-01-01",
        help="Start date YYYY-MM-DD (default: 2020-01-01)",
    )
    parser.add_argument(
        "--end", type=str, default="2025-12-31",
        help="End date YYYY-MM-DD (default: 2025-12-31)",
    )
    parser.add_argument(
        "--capital", type=float, default=100_000,
        help="Starting capital (default: 100000)",
    )
    parser.add_argument(
        "--max-positions", type=int, default=10,
        help="Max concurrent positions (default: 10)",
    )
    parser.add_argument(
        "--max-per-strategy", type=int, default=5,
        help="Max positions per strategy (default: 5)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON path (default: output/portfolio_backtest_YYYY-MM-DD.json)",
    )
    args = parser.parse_args()

    # Validate strategy names
    for name in args.strategies:
        if name not in STRATEGY_REGISTRY:
            print(f"ERROR: Unknown strategy '{name}'. Available: {list(STRATEGY_REGISTRY.keys())}")
            sys.exit(1)

    # Instantiate strategies with default params
    strategies = [
        (name, STRATEGY_REGISTRY[name](STRATEGY_REGISTRY[name].get_default_params()))
        for name in args.strategies
    ]

    start_date = datetime.strptime(args.start, "%Y-%m-%d")
    end_date = datetime.strptime(args.end, "%Y-%m-%d")

    print(f"Portfolio Backtest Configuration:")
    print(f"  Strategies:  {', '.join(args.strategies)}")
    print(f"  Tickers:     {', '.join(args.tickers)}")
    print(f"  Period:      {args.start} to {args.end}")
    print(f"  Capital:     ${args.capital:,.0f}")
    print(f"  Max Pos:     {args.max_positions} total, {args.max_per_strategy} per strategy")
    print()

    bt = PortfolioBacktester(
        strategies=strategies,
        tickers=args.tickers,
        start_date=start_date,
        end_date=end_date,
        starting_capital=args.capital,
        max_positions=args.max_positions,
        max_positions_per_strategy=args.max_per_strategy,
    )

    results = bt.run()

    # Write JSON output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = args.output or os.path.join(
        OUTPUT_DIR, f"portfolio_backtest_{datetime.now().strftime('%Y-%m-%d')}.json"
    )
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults written to {out_path}")

    # Print summary table
    _print_summary(results)


def _print_summary(results: dict) -> None:
    """Print a formatted summary table to stdout."""
    c = results["combined"]
    print("\n" + "=" * 65)
    print("PORTFOLIO BACKTEST RESULTS")
    print("=" * 65)
    print(f"  Total Trades:     {c['total_trades']}")
    print(f"  Win Rate:         {c['win_rate']:.1f}%")
    print(f"  Total P&L:        ${c['total_pnl']:>+,.2f}")
    print(f"  Return:           {c['return_pct']:>+.2f}%")
    print(f"  Sharpe Ratio:     {c['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown:     {c['max_drawdown']:.2f}%")
    print(f"  Profit Factor:    {c.get('profit_factor', 0):.2f}")
    print(f"  Avg Win:          ${c['avg_win']:>+,.2f}")
    print(f"  Avg Loss:         ${c['avg_loss']:>,.2f}")
    print(f"  Starting Capital: ${c['starting_capital']:>,.2f}")
    print(f"  Ending Capital:   ${c['ending_capital']:>,.2f}")

    # Per-strategy breakdown
    ps = results.get("per_strategy", {})
    if ps:
        print("\n" + "-" * 65)
        print(f"{'Strategy':<30} {'Trades':>6} {'Win%':>6} {'P&L':>12} {'PF':>6}")
        print("-" * 65)
        for name, metrics in sorted(ps.items()):
            print(
                f"  {name:<28} {metrics['total_trades']:>6} "
                f"{metrics['win_rate']:>5.1f}% "
                f"${metrics['total_pnl']:>+10,.2f} "
                f"{metrics['profit_factor']:>5.2f}"
            )

    # Yearly breakdown
    yearly = results.get("yearly", {})
    if yearly:
        print("\n" + "-" * 65)
        print(f"{'Year':<8} {'Trades':>6} {'Return%':>9} {'MaxDD%':>9} {'P&L':>12}")
        print("-" * 65)
        for year in sorted(yearly.keys()):
            y = yearly[year]
            print(
                f"  {year:<6} {y['trades']:>6} "
                f"{y['return_pct']:>+8.2f}% "
                f"{y['max_drawdown']:>8.2f}% "
                f"${y['total_pnl']:>+10,.2f}"
            )

    print("=" * 65)


if __name__ == "__main__":
    main()
