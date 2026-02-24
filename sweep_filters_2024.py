#!/usr/bin/env python3
"""
P0 #2: Find Filter Settings with Consistent Weekly Profits

Systematically tests filter combos on SPY 2024 using:
  - Real Polygon intraday option prices (HistoricalOptionsData + SQLite cache)
  - FIXED position sizing: starting_capital × risk_pct (no Kelly compounding)
  - 14 intraday scan times per day (same as live trading)

Parameters swept:
  - otm_pct:        how far OTM the short strike is (3%, 5%, 7%)
  - min_credit_pct: minimum credit as % of spread width (5%, 10%, 15%)
  - stop_loss_mult: exit when loss exceeds credit × mult (2.0x, 2.5x, 3.0x)
  - spread_width:   $5 or $10

Usage:
  python3 sweep_filters_2024.py              # full sweep
  python3 sweep_filters_2024.py --resume     # skip already-completed combos
"""

import os
import sys
import gc
import copy
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from typing import Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from utils import load_config, setup_logging
from backtest.backtester import Backtester
from backtest.historical_data import HistoricalOptionsData

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_PATH = Path('output/sweep_2024_fixed_sizing.json')


def suppress_noisy_loggers():
    for mod in ['backtest.backtester', 'backtest.historical_data',
                'yfinance', 'urllib3', 'peewee']:
        logging.getLogger(mod).setLevel(logging.ERROR)


def combo_key(otm_pct, min_credit_pct, stop_loss_mult, spread_width):
    return f"OTM{int(otm_pct*100)}_CR{min_credit_pct}_SL{stop_loss_mult}_W{spread_width}"


def load_checkpoint():
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH) as f:
                data = json.load(f)
            return data.get('results', []), set(data.get('completed_keys', []))
        except (json.JSONDecodeError, KeyError):
            pass
    return [], set()


def save_checkpoint(all_results, completed_keys):
    OUTPUT_PATH.parent.mkdir(exist_ok=True, parents=True)
    payload = {
        'timestamp': datetime.now().isoformat(),
        'total_completed': len(completed_keys),
        'completed_keys': list(completed_keys),
        'results': all_results,
    }
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(payload, f, indent=2, default=str)


def weekly_stats(trades: list) -> dict:
    """Compute per-week P&L stats from a list of trade dicts."""
    if not trades:
        return {'positive_weeks': 0, 'total_weeks': 0, 'weekly_consistency': 0.0,
                'weekly_pnl': {}}

    df = pd.DataFrame(trades)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    # Use ISO year-week to handle year boundaries
    df['iso_week'] = df['entry_date'].dt.strftime('%G-W%V')
    weekly = df.groupby('iso_week')['pnl'].sum()

    positive = int((weekly > 0).sum())
    total = len(weekly)
    return {
        'positive_weeks': positive,
        'total_weeks': total,
        'weekly_consistency': round(positive / total * 100, 1) if total else 0.0,
        'weekly_pnl': weekly.to_dict(),
    }


def run_combo(base_config: dict, historical_data, otm_pct: float,
              min_credit_pct: int, stop_loss_mult: float,
              spread_width: int) -> Optional[dict]:
    """Run one backtest combo. Returns result dict or None if 0 trades."""
    cfg = copy.deepcopy(base_config)
    cfg['strategy']['spread_width'] = spread_width
    cfg['strategy']['min_credit_pct'] = min_credit_pct
    cfg['risk']['stop_loss_multiplier'] = stop_loss_mult
    # Realistic position sizing: 2% risk per trade → ~4-5 contracts on $5 wide spread.
    # The default 8% leads to 17 contracts and -100%+ drawdowns.
    cfg['risk']['max_risk_per_trade'] = 2.0
    cfg['risk']['max_contracts'] = 5   # hard cap per trade

    bt = Backtester(cfg, historical_data=historical_data, otm_pct=otm_pct)

    start = datetime(2024, 1, 1)
    end = datetime(2024, 12, 31)

    try:
        results = bt.run_backtest('SPY', start, end)
    except Exception as e:
        logging.error("Backtest failed: %s", e)
        return None

    if not results or results['total_trades'] == 0:
        return None

    ws = weekly_stats(results.get('trades', []))

    return {
        'settings': {
            'otm_pct': otm_pct,
            'min_credit_pct': min_credit_pct,
            'stop_loss_mult': stop_loss_mult,
            'spread_width': spread_width,
        },
        'total_trades': results['total_trades'],
        'winning_trades': results['winning_trades'],
        'losing_trades': results['losing_trades'],
        'win_rate': results['win_rate'],
        'total_pnl': round(results['total_pnl'], 2),
        'return_pct': results['return_pct'],
        'max_drawdown': results['max_drawdown'],
        'sharpe_ratio': results['sharpe_ratio'],
        'avg_win': results['avg_win'],
        'avg_loss': results['avg_loss'],
        'bull_put_trades': results['bull_put_trades'],
        'bear_call_trades': results['bear_call_trades'],
        'positive_weeks': ws['positive_weeks'],
        'total_weeks': ws['total_weeks'],
        'weekly_consistency': ws['weekly_consistency'],
        'weekly_pnl': ws['weekly_pnl'],
        'api_calls': historical_data.api_calls_made,
    }


def composite_score(r: dict) -> float:
    """Rank combos: weekly consistency first, then sharpe, then return."""
    return (
        r['weekly_consistency'] * 3.0
        + r['sharpe_ratio'] * 10.0
        + min(r['return_pct'], 100) * 0.5
        - abs(r['max_drawdown']) * 0.5
    )


def print_weekly_breakdown(r: dict, label: str):
    """Print week-by-week P&L for a result."""
    s = r['settings']
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  OTM={s['otm_pct']*100:.0f}% | MinCredit={s['min_credit_pct']}% | "
          f"StopLoss={s['stop_loss_mult']}x | Width=${s['spread_width']}")
    print(f"  {r['total_trades']} trades | WR={r['win_rate']}% | "
          f"P&L=${r['total_pnl']:,.0f} ({r['return_pct']}%) | "
          f"DD={r['max_drawdown']:.1f}% | Sharpe={r['sharpe_ratio']:.2f}")
    print(f"  Weekly: {r['positive_weeks']}/{r['total_weeks']} positive "
          f"({r['weekly_consistency']}%)")
    print(f"{'─'*70}")
    print(f"  {'Week':<12} {'P&L':>10} {'✓/✗':>5}")
    print(f"{'─'*70}")
    for week, pnl in sorted(r['weekly_pnl'].items()):
        flag = '✓' if pnl > 0 else '✗'
        print(f"  {week:<12} ${pnl:>9,.0f} {flag:>5}")
    print(f"{'='*70}")


def main():
    print("=" * 70)
    print("P0 #2: FILTER SWEEP — SPY 2024 FULL YEAR (FIXED SIZING)")
    print("=" * 70)
    print()

    base_config = load_config()
    setup_logging(base_config)
    suppress_noisy_loggers()

    # Get Polygon API key
    api_key = os.environ.get('POLYGON_API_KEY', '')
    if not api_key:
        poly_cfg = base_config.get('data', {}).get('polygon', {})
        raw = poly_cfg.get('api_key', '')
        if raw.startswith('${') and raw.endswith('}'):
            api_key = os.environ.get(raw[2:-1], '')
    if not api_key:
        print("ERROR: No POLYGON_API_KEY in environment. Cannot run.")
        sys.exit(1)

    historical_data = HistoricalOptionsData(api_key=api_key, cache_dir='data')
    print(f"SQLite cache loaded from data/options_cache.db")

    # ── Parameter matrix ────────────────────────────────────────────────────
    otm_pcts        = [0.03, 0.05, 0.07]     # 3%, 5%, 7% OTM
    min_credit_pcts = [5, 10, 15]            # min credit as % of spread width
    stop_loss_mults = [2.0, 2.5, 3.0]        # exit when loss > credit × mult
    spread_widths   = [5, 10]                # spread width in dollars

    combos = [
        (otm, cr, sl, w)
        for otm in otm_pcts
        for cr in min_credit_pcts
        for sl in stop_loss_mults
        for w in spread_widths
    ]

    resume = '--resume' in sys.argv
    all_results, completed_keys = (load_checkpoint() if resume else ([], set()))

    if resume and completed_keys:
        print(f"Resuming: {len(completed_keys)} combos already done")

    remaining = [(c, k) for c in combos
                 if (k := combo_key(*c)) not in completed_keys]

    total = len(combos)
    print(f"Combos: {len(remaining)} remaining of {total} total")
    print(f"Period: 2024-01-01 to 2024-12-31 | Ticker: SPY")
    print(f"Sizing: FIXED (2% risk × ${base_config['backtest']['starting_capital']:,} "
          f"starting capital = $2,000 max risk, ≤5 contracts, no Kelly compounding)")
    print()

    api_calls_start = historical_data.api_calls_made

    for seq, (combo, key) in enumerate(remaining, 1):
        otm, cr, sl, w = combo
        label = (f"OTM={otm*100:.0f}% MinCredit={cr}% StopLoss={sl}x Width=${w}")
        n_done = len(completed_keys) + 1
        print(f"[{n_done}/{total}] {label}", end=" ... ", flush=True)

        result = run_combo(base_config, historical_data, otm, cr, sl, w)

        completed_keys.add(key)

        if result:
            print(f"{result['total_trades']} trades | "
                  f"WR={result['win_rate']}% | "
                  f"P&L=${result['total_pnl']:,.0f} | "
                  f"Weekly={result['weekly_consistency']}% "
                  f"({result['positive_weeks']}/{result['total_weeks']})")
            all_results.append(result)
        else:
            print("0 trades")

        save_checkpoint(all_results, completed_keys)
        gc.collect()

    total_api_calls = historical_data.api_calls_made - api_calls_start
    print(f"\nAPI calls made this session: {total_api_calls}")

    # ── Analysis ─────────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("RESULTS ANALYSIS")
    print("=" * 70)

    if not all_results:
        print("\nNO CONFIGURATIONS GENERATED TRADES")
        print("Try: lower min_credit_pct, wider spread, or closer OTM strikes")
        return

    # Score and sort
    for r in all_results:
        r['composite'] = composite_score(r)
    all_results.sort(key=lambda x: x['composite'], reverse=True)

    print(f"\n{len(all_results)} of {total} combos generated trades\n")
    print("TOP 10 CONFIGURATIONS (weekly consistency → sharpe → return):\n")

    for i, r in enumerate(all_results[:10], 1):
        s = r['settings']
        print(f"#{i}  OTM={s['otm_pct']*100:.0f}% | MinCredit={s['min_credit_pct']}% | "
              f"StopLoss={s['stop_loss_mult']}x | Width=${s['spread_width']}")
        print(f"     Trades={r['total_trades']} "
              f"WR={r['win_rate']}% "
              f"P&L=${r['total_pnl']:,.0f} ({r['return_pct']}%) "
              f"DD={r['max_drawdown']:.1f}% "
              f"Sharpe={r['sharpe_ratio']:.2f}")
        print(f"     Weekly: {r['positive_weeks']}/{r['total_weeks']} "
              f"({r['weekly_consistency']}%) "
              f"[Bulls={r['bull_put_trades']} Calls={r['bear_call_trades']}]")
        print()

    # ── Weekly breakdown for top 3 ───────────────────────────────────────────
    print("\nWEEKLY P&L BREAKDOWN — TOP 3 CONFIGURATIONS")
    for i, r in enumerate(all_results[:3], 1):
        print_weekly_breakdown(r, f"#{i} CONFIGURATION")

    # ── Winner ───────────────────────────────────────────────────────────────
    winner = all_results[0]
    ws = winner['settings']
    print()
    print("=" * 70)
    print("WINNING CONFIGURATION")
    print("=" * 70)
    print(f"\n  OTM %:           {ws['otm_pct']*100:.0f}% ({ws['otm_pct']*100:.0f}% below/above current price)")
    print(f"  Min Credit:      {ws['min_credit_pct']}% of spread width")
    print(f"  Stop Loss:       {ws['stop_loss_mult']}x credit received")
    print(f"  Spread Width:    ${ws['spread_width']}")
    print()
    print(f"  Annual Return:   {winner['return_pct']}%")
    print(f"  Win Rate:        {winner['win_rate']}%")
    print(f"  Total Trades:    {winner['total_trades']}")
    print(f"  Avg Win:         ${winner['avg_win']:,.2f}")
    print(f"  Avg Loss:        ${winner['avg_loss']:,.2f}")
    print(f"  Max Drawdown:    {winner['max_drawdown']:.1f}%")
    print(f"  Sharpe Ratio:    {winner['sharpe_ratio']:.2f}")
    print(f"  Weekly: {winner['positive_weeks']}/{winner['total_weeks']} "
          f"weeks positive ({winner['weekly_consistency']}%)")
    print()

    # Final save with composite scores
    save_checkpoint(all_results, completed_keys)
    print(f"Full results saved to: {OUTPUT_PATH}")
    print("=" * 70)


if __name__ == '__main__':
    main()
