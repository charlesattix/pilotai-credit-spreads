#!/usr/bin/env python3
"""
Run the winning 2024 config on 2025 and 2026 YTD for out-of-sample validation.

Winning config: OTM=3%, Width=$5, MinCredit=10%, SL=2.5x, 2% risk, max 5 contracts
"""

import os
import sys
import copy
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from utils import load_config, setup_logging
from backtest.backtester import Backtester
from backtest.historical_data import HistoricalOptionsData


def suppress_noisy_loggers():
    for mod in ['backtest.backtester', 'backtest.historical_data',
                'yfinance', 'urllib3', 'peewee']:
        logging.getLogger(mod).setLevel(logging.ERROR)


def weekly_stats(trades: list) -> dict:
    if not trades:
        return {'positive_weeks': 0, 'total_weeks': 0, 'weekly_consistency': 0.0, 'weekly_pnl': {}}
    df = pd.DataFrame(trades)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
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


def print_weekly_breakdown(ws: dict, label: str):
    print(f"\n{'='*70}")
    print(f"  {label} — Weekly P&L")
    print(f"{'─'*70}")
    print(f"  {'Week':<12} {'P&L':>10} {'✓/✗':>5}")
    print(f"{'─'*70}")
    for week, pnl in sorted(ws['weekly_pnl'].items()):
        flag = '✓' if pnl > 0 else ('✗' if pnl < 0 else '—')
        print(f"  {week:<12} ${pnl:>9,.0f} {flag:>5}")
    print(f"{'─'*70}")
    print(f"  TOTAL: {ws['positive_weeks']}/{ws['total_weeks']} weeks positive "
          f"({ws['weekly_consistency']}%)")
    print(f"{'='*70}")


def run_period(base_config: dict, historical_data, label: str,
               start: datetime, end: datetime):
    cfg = copy.deepcopy(base_config)
    # Winning config
    cfg['strategy']['spread_width'] = 5
    cfg['strategy']['min_credit_pct'] = 10
    cfg['risk']['stop_loss_multiplier'] = 2.5
    cfg['risk']['max_risk_per_trade'] = 2.0
    cfg['risk']['max_contracts'] = 5

    bt = Backtester(cfg, historical_data=historical_data, otm_pct=0.03)

    print(f"\n{'='*70}")
    print(f"  Running: {label} ({start.date()} → {end.date()})")
    print(f"{'='*70}")

    try:
        results = bt.run_backtest('SPY', start, end)
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

    if not results or results['total_trades'] == 0:
        print("  0 trades generated.")
        return None

    ws = weekly_stats(results.get('trades', []))

    print(f"  Trades:           {results['total_trades']}")
    print(f"  Win Rate:         {results['win_rate']}%")
    print(f"  Total P&L:        ${results['total_pnl']:,.2f}")
    print(f"  Return:           {results['return_pct']}%")
    print(f"  Max Drawdown:     {results['max_drawdown']:.1f}%")
    print(f"  Sharpe:           {results['sharpe_ratio']:.2f}")
    print(f"  Avg Win:          ${results['avg_win']:,.2f}")
    print(f"  Avg Loss:         ${results['avg_loss']:,.2f}")
    print(f"  Bull Puts:        {results['bull_put_trades']}")
    print(f"  Bear Calls:       {results['bear_call_trades']}")
    print(f"  Iron Condors:     {results.get('iron_condor_trades', 0)}")
    if results.get('iron_condor_trades', 0) > 0:
        print(f"  Condor WR:        {results.get('iron_condor_win_rate', 0)}%")
    print(f"  Weekly Consist.:  {ws['positive_weeks']}/{ws['total_weeks']} "
          f"({ws['weekly_consistency']}%)")

    print_weekly_breakdown(ws, label)

    return {
        'label': label,
        'period': f"{start.date()} to {end.date()}",
        'total_trades': results['total_trades'],
        'win_rate': results['win_rate'],
        'total_pnl': round(results['total_pnl'], 2),
        'return_pct': results['return_pct'],
        'max_drawdown': results['max_drawdown'],
        'sharpe_ratio': results['sharpe_ratio'],
        'avg_win': results['avg_win'],
        'avg_loss': results['avg_loss'],
        'bull_put_trades': results['bull_put_trades'],
        'bear_call_trades': results['bear_call_trades'],
        'iron_condor_trades': results.get('iron_condor_trades', 0),
        'iron_condor_win_rate': results.get('iron_condor_win_rate', 0),
        'positive_weeks': ws['positive_weeks'],
        'total_weeks': ws['total_weeks'],
        'weekly_consistency': ws['weekly_consistency'],
        'weekly_pnl': ws['weekly_pnl'],
    }


def main():
    print("=" * 70)
    print("OUT-OF-SAMPLE VALIDATION — WINNING CONFIG")
    print("OTM=3% | Width=$5 | MinCredit=10% | SL=2.5x | 2% risk | max 5 contracts")
    print("=" * 70)

    base_config = load_config()
    setup_logging(base_config)
    suppress_noisy_loggers()

    api_key = os.environ.get('POLYGON_API_KEY', '')
    if not api_key:
        poly_cfg = base_config.get('data', {}).get('polygon', {})
        raw = poly_cfg.get('api_key', '')
        if raw.startswith('${') and raw.endswith('}'):
            api_key = os.environ.get(raw[2:-1], '')
    if not api_key:
        print("ERROR: No POLYGON_API_KEY in environment.")
        sys.exit(1)

    historical_data = HistoricalOptionsData(api_key=api_key, cache_dir='data')
    print(f"SQLite cache: data/options_cache.db")

    periods = [
        ("2024 Full Year", datetime(2024, 1, 1), datetime(2024, 12, 31)),
        ("2025 Full Year", datetime(2025, 1, 1), datetime(2025, 12, 31)),
        ("2026 YTD",       datetime(2026, 1, 1), datetime(2026, 2, 24)),
    ]

    all_results = []
    for label, start, end in periods:
        result = run_period(base_config, historical_data, label, start, end)
        if result:
            all_results.append(result)

    # ── Comparison summary ────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("COMPARISON SUMMARY (vs 2024 benchmark)")
    print("=" * 70)
    print(f"\n{'Year':<12} {'Trades':>7} {'WR%':>6} {'Return%':>8} {'DD%':>7} "
          f"{'Sharpe':>7} {'Weekly%':>9} {'Bulls':>6} {'Calls':>6} {'Condors':>8}")
    print("─" * 78)
    # 2024 benchmark row (daily-close baseline, pre-intraday-exits)
    print(f"{'2024 (bench)':<12} {'109':>7} {'84.4':>6} {'25.5':>8} {'-24.4':>7} "
          f"{'0.60':>7} {'88.5':>9} {'60':>6} {'49':>6} {'0':>8}")
    for r in all_results:
        print(f"{r['label']:<12} {r['total_trades']:>7} {r['win_rate']:>6} "
              f"{r['return_pct']:>8} {r['max_drawdown']:>7.1f} "
              f"{r['sharpe_ratio']:>7.2f} {r['weekly_consistency']:>9} "
              f"{r['bull_put_trades']:>6} {r['bear_call_trades']:>6} "
              f"{r.get('iron_condor_trades', 0):>8}")

    # Save results
    out_path = Path('output/out_of_sample_validation.json')
    out_path.parent.mkdir(exist_ok=True, parents=True)
    with open(out_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'config': {
                'otm_pct': 0.03, 'spread_width': 5,
                'min_credit_pct': 10, 'stop_loss_mult': 2.5,
                'max_risk_per_trade': 2.0, 'max_contracts': 5,
            },
            'results': all_results,
        }, f, indent=2, default=str)
    print(f"\nResults saved to: {out_path}")
    print("=" * 70)


if __name__ == '__main__':
    main()
