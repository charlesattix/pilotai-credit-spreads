#!/usr/bin/env python3
"""
Iron condor validation — compare with/without condors across 2024, 2025, 2026 YTD.

Winning config: OTM=3%, Width=$5, MinCredit=10%, SL=2.5x, 2% risk, max 5 contracts
Condor config:  same + iron_condor.enabled=True, min_combined_credit_pct=20%

Goal: fill the inactive weeks in low-IV periods (Jan–Jun 2024, VIX 12–15).
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
        return {
            'positive_weeks': 0, 'total_weeks': 0,
            'weekly_consistency': 0.0, 'weekly_pnl': {},
        }
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


def weekly_condor_trades(trades: list) -> dict:
    """Return number of iron condor trades per ISO week."""
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    df['iso_week'] = df['entry_date'].dt.strftime('%G-W%V')
    condors = df[df['type'] == 'iron_condor']
    if condors.empty:
        return {}
    return condors.groupby('iso_week').size().to_dict()


def run_period(base_config: dict, historical_data, label: str,
               start: datetime, end: datetime,
               condors_enabled: bool):
    cfg = copy.deepcopy(base_config)
    # Winning config
    cfg['strategy']['spread_width'] = 5
    cfg['strategy']['min_credit_pct'] = 10
    cfg['risk']['stop_loss_multiplier'] = 2.5
    cfg['risk']['max_risk_per_trade'] = 2.0
    cfg['risk']['max_contracts'] = 5
    # Iron condor toggle
    if 'iron_condor' not in cfg['strategy']:
        cfg['strategy']['iron_condor'] = {}
    cfg['strategy']['iron_condor']['enabled'] = condors_enabled
    cfg['strategy']['iron_condor']['min_combined_credit_pct'] = 20

    bt = Backtester(cfg, historical_data=historical_data, otm_pct=0.03)

    try:
        results = bt.run_backtest('SPY', start, end)
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

    if not results or results['total_trades'] == 0:
        return {
            'label': label,
            'period': f"{start.date()} to {end.date()}",
            'condors_enabled': condors_enabled,
            'total_trades': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'return_pct': 0,
            'max_drawdown': 0,
            'sharpe_ratio': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'bull_put_trades': 0,
            'bear_call_trades': 0,
            'iron_condor_trades': 0,
            'iron_condor_win_rate': 0,
            'positive_weeks': 0,
            'total_weeks': 0,
            'weekly_consistency': 0.0,
            'weekly_pnl': {},
            'condor_trades_by_week': {},
        }

    ws = weekly_stats(results.get('trades', []))
    condor_by_week = weekly_condor_trades(results.get('trades', []))

    return {
        'label': label,
        'period': f"{start.date()} to {end.date()}",
        'condors_enabled': condors_enabled,
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
        'iron_condor_trades': results['iron_condor_trades'],
        'iron_condor_win_rate': results['iron_condor_win_rate'],
        'positive_weeks': ws['positive_weeks'],
        'total_weeks': ws['total_weeks'],
        'weekly_consistency': ws['weekly_consistency'],
        'weekly_pnl': ws['weekly_pnl'],
        'condor_trades_by_week': condor_by_week,
    }


def print_result(r: dict):
    flag = "[+condors]" if r['condors_enabled'] else "[baseline]"
    print(f"\n  {flag} {r['label']}  ({r['period']})")
    print(f"  {'─'*60}")
    print(f"  Trades:     {r['total_trades']:>5}   "
          f"(puts={r['bull_put_trades']}, calls={r['bear_call_trades']}, "
          f"condors={r['iron_condor_trades']})")
    if r['iron_condor_trades'] > 0:
        print(f"  Condor WR:  {r['iron_condor_win_rate']:>5.1f}%")
    print(f"  Win Rate:   {r['win_rate']:>5.1f}%")
    print(f"  Total P&L:  ${r['total_pnl']:>10,.2f}")
    print(f"  Return:     {r['return_pct']:>5.1f}%")
    print(f"  Max DD:     {r['max_drawdown']:>5.1f}%")
    print(f"  Sharpe:     {r['sharpe_ratio']:>5.2f}")
    print(f"  Weekly:     {r['positive_weeks']}/{r['total_weeks']} "
          f"({r['weekly_consistency']}%)")


def print_weekly_comparison(baseline: dict, with_condors: dict, label: str):
    """Show week-by-week comparison, highlighting weeks filled by condors."""
    all_weeks = sorted(set(
        list(baseline['weekly_pnl'].keys()) + list(with_condors['weekly_pnl'].keys())
    ))

    print(f"\n{'='*78}")
    print(f"  {label} — Week-by-Week Comparison")
    print(f"{'─'*78}")
    print(f"  {'Week':<12} {'Baseline':>10} {'+Condors':>10} {'Δ P&L':>10} {'IC trades':>10}")
    print(f"{'─'*78}")

    for week in all_weeks:
        base_pnl = baseline['weekly_pnl'].get(week, 0)
        cond_pnl = with_condors['weekly_pnl'].get(week, 0)
        delta = cond_pnl - base_pnl
        ic_count = with_condors.get('condor_trades_by_week', {}).get(week, 0)

        # Mark weeks newly filled by condors (baseline=0, condors>0)
        marker = " ← IC" if base_pnl == 0 and cond_pnl != 0 else ""
        print(
            f"  {week:<12} ${base_pnl:>9,.0f} ${cond_pnl:>9,.0f} "
            f"${delta:>+9,.0f} {ic_count:>10}{marker}"
        )

    print(f"{'─'*78}")
    b_pos = baseline['positive_weeks']
    b_tot = baseline['total_weeks']
    c_pos = with_condors['positive_weeks']
    c_tot = with_condors['total_weeks']
    print(
        f"  TOTAL: baseline {b_pos}/{b_tot} ({baseline['weekly_consistency']}%)  "
        f"→  +condors {c_pos}/{c_tot} ({with_condors['weekly_consistency']}%)"
    )
    print(f"{'='*78}")


def main():
    print("=" * 78)
    print("IRON CONDOR VALIDATION — WITH vs WITHOUT CONDORS")
    print("OTM=3% | Width=$5 | MinCredit=10% | SL=2.5x | 2% risk | max 5 contracts")
    print("Condor trigger: fallback only (bull put → bear call → condor)")
    print("Condor min credit: 20% of width = $1.00 on $5 spread")
    print("=" * 78)

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
    print(f"SQLite cache: data/options_cache.db\n")

    periods = [
        ("2024 Full Year", datetime(2024, 1, 1), datetime(2024, 12, 31)),
        ("2025 Full Year", datetime(2025, 1, 1), datetime(2025, 12, 31)),
        ("2026 YTD",       datetime(2026, 1, 1), datetime(2026, 2, 24)),
    ]

    all_results = []
    for label, start, end in periods:
        print(f"\n{'='*78}")
        print(f"  Period: {label}  ({start.date()} → {end.date()})")
        print(f"{'='*78}")

        baseline = run_period(base_config, historical_data, label, start, end,
                              condors_enabled=False)
        with_condors = run_period(base_config, historical_data, label, start, end,
                                  condors_enabled=True)

        if baseline:
            print_result(baseline)
        if with_condors:
            print_result(with_condors)

        if baseline and with_condors:
            print_weekly_comparison(baseline, with_condors, label)

        all_results.append({
            'period': label,
            'baseline': baseline,
            'with_condors': with_condors,
        })

    # ── Comparison summary table ──────────────────────────────────────────────
    print()
    print("=" * 78)
    print("COMPARISON SUMMARY")
    print("=" * 78)
    print(
        f"\n{'Period':<14} {'Mode':<11} {'Trades':>7} {'IC':>4} {'WR%':>6} "
        f"{'Ret%':>6} {'DD%':>6} {'Sharpe':>7} {'Weekly%':>9}"
    )
    print("─" * 78)
    for entry in all_results:
        for mode_key, mode_label in [('baseline', 'baseline'), ('with_condors', '+condors')]:
            r = entry[mode_key]
            if r is None:
                continue
            print(
                f"{r['label']:<14} {mode_label:<11} {r['total_trades']:>7} "
                f"{r['iron_condor_trades']:>4} {r['win_rate']:>6.1f} "
                f"{r['return_pct']:>6.1f} {r['max_drawdown']:>6.1f} "
                f"{r['sharpe_ratio']:>7.2f} {r['weekly_consistency']:>9.1f}"
            )
        print("─" * 78)

    # Save results
    out_path = Path('output/condor_validation.json')
    out_path.parent.mkdir(exist_ok=True, parents=True)
    with open(out_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'config': {
                'otm_pct': 0.03, 'spread_width': 5,
                'min_credit_pct': 10, 'stop_loss_mult': 2.5,
                'max_risk_per_trade': 2.0, 'max_contracts': 5,
                'condor_min_combined_credit_pct': 20,
            },
            'results': all_results,
        }, f, indent=2, default=str)
    print(f"\nResults saved to: {out_path}")
    print("=" * 78)


if __name__ == '__main__':
    main()
