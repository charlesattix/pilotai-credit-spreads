#!/usr/bin/env python3
"""
Measure Polygon 5-min intraday option bar availability for 2024 backtest positions.

Samples 20 trades from the winning-config 2024 backtest and checks every
position-day in each trade's hold period to determine what fraction would
have intraday data available for exit simulation.

Must be run BEFORE implementing intraday exit simulation (Problem 1 of
PROPOSAL_BACKTEST_V3) so we know the actual fallback rate.

Key insight: get_intraday_bar() fetches the ENTIRE day's bars in one API call
and caches them. So one check per (symbol, date) pair is sufficient to
determine coverage for all scan times that day.
"""

import os
import sys
import copy
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, date

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from utils import load_config, setup_logging
from backtest.backtester import Backtester, _nearest_friday_expiration
from backtest.historical_data import HistoricalOptionsData

for mod in ['backtest.backtester', 'backtest.historical_data',
            'yfinance', 'urllib3', 'peewee']:
    logging.getLogger(mod).setLevel(logging.ERROR)

SAMPLE_SIZE = 20
# Check at 10:00 ET — well within market hours, representative of mid-morning.
# One check per position-day is sufficient: _fetch_and_cache_intraday fetches
# ALL 5-min bars for that symbol+date in a single API call. If 10:00 has data,
# 9:45/10:30/12:00/14:30 do too (they come from the same cache entry).
CHECK_HOUR, CHECK_MIN = 10, 0


def _is_already_cached(db_path: str, symbol: str, date_str: str) -> str:
    """
    Check SQLite without making API calls.
    Returns: 'has_data' | 'sentinel' | 'not_cached'
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT bar_time FROM option_intraday "
        "WHERE contract_symbol=? AND date=? LIMIT 1",
        (symbol, date_str),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return 'not_cached'
    return 'sentinel' if row[0] == 'FETCHED' else 'has_data'


def main():
    print("=" * 72)
    print("INTRADAY DATA AVAILABILITY MEASUREMENT — 2024 BACKTEST POSITIONS")
    print(f"Check time: {CHECK_HOUR:02d}:{CHECK_MIN:02d} ET per position-day")
    print("=" * 72)

    base_config = load_config()
    setup_logging(base_config)

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
    db_path = os.path.join('data', 'options_cache.db')

    # ── Step 1: Run 2024 backtest (all daily data should be cached) ───────
    print("\n[1/3] Running 2024 backtest to get trade list...")
    cfg = copy.deepcopy(base_config)
    cfg['strategy']['spread_width'] = 5
    cfg['strategy']['min_credit_pct'] = 10
    cfg['risk']['stop_loss_multiplier'] = 2.5
    cfg['risk']['max_risk_per_trade'] = 2.0
    cfg['risk']['max_contracts'] = 5
    cfg.setdefault('strategy', {}).setdefault('iron_condor', {})['enabled'] = False

    bt = Backtester(cfg, historical_data=historical_data, otm_pct=0.03)
    results = bt.run_backtest('SPY', datetime(2024, 1, 1), datetime(2024, 12, 31))

    if not results or results['total_trades'] == 0:
        print("  ERROR: 0 trades generated.")
        sys.exit(1)

    api_after_backtest = historical_data.api_calls_made
    print(f"  {results['total_trades']} trades | API calls for daily data: {api_after_backtest}")

    trades = results.get('trades', [])

    # Extract trading days from equity curve (no extra yfinance call needed)
    trading_dates: set = set()
    for entry in results.get('equity_curve', []):
        d = entry.get('date')
        if d is not None:
            if isinstance(d, str):
                trading_dates.add(datetime.fromisoformat(d).date())
            elif hasattr(d, 'date'):
                trading_dates.add(d.date() if callable(d.date) else d.date)
            elif isinstance(d, date):
                trading_dates.add(d)

    # ── Step 2: Sample trades evenly across the year ──────────────────────
    if len(trades) <= SAMPLE_SIZE:
        sampled = trades
    else:
        step = len(trades) // SAMPLE_SIZE
        sampled = [trades[i * step] for i in range(SAMPLE_SIZE)]

    print(f"\n[2/3] Checking {len(sampled)} sampled trades "
          f"({len(sampled)} of {len(trades)} total)...")
    print(f"      Checking SHORT + LONG leg — position-day counted as covered")
    print(f"      only if BOTH legs have intraday bars available.\n")

    # Per-day-type counters
    by_day_type = defaultdict(lambda: {
        'has_data': 0, 'no_data': 0, 'pre_cached': 0, 'new_api': 0
    })
    total_pos_days = 0
    total_has = 0
    total_no  = 0
    api_calls_start = historical_data.api_calls_made

    print(f"  {'#':>2}  {'Entry':>10}  {'Exit':>10}  {'Hold':>4}  "
          f"{'Type':>4}  {'Strike':>6}  {'Has/Total':>9}  {'Coverage':>8}")
    print(f"  {'─'*70}")

    for t_idx, trade in enumerate(sampled):
        entry_dt = pd.to_datetime(trade['entry_date']).to_pydatetime().replace(tzinfo=None)
        exit_dt  = pd.to_datetime(trade['exit_date']).to_pydatetime().replace(tzinfo=None)

        # Infer option type and expiration (not stored in trade record)
        ot = 'P' if trade.get('type', '') == 'bull_put_spread' else 'C'
        expiration = _nearest_friday_expiration(entry_dt)

        short_sym = HistoricalOptionsData.build_occ_symbol(
            'SPY', expiration, trade['short_strike'], ot)
        long_sym  = HistoricalOptionsData.build_occ_symbol(
            'SPY', expiration, trade['long_strike'],  ot)

        # All trading days in hold period
        hold_days = []
        cur_day = entry_dt.date()
        end_day = exit_dt.date()
        while cur_day <= end_day:
            if cur_day in trading_dates:
                hold_days.append(cur_day)
            cur_day += timedelta(days=1)

        trade_has = 0
        trade_no  = 0

        for d_idx, day in enumerate(hold_days):
            date_str = day.strftime('%Y-%m-%d')

            if d_idx == 0:
                day_type = 'entry'
            elif d_idx == len(hold_days) - 1:
                day_type = 'exit'
            else:
                day_type = 'holding'

            # Cache status BEFORE the call (to classify pre-cached vs new API)
            short_pre = _is_already_cached(db_path, short_sym, date_str)
            long_pre  = _is_already_cached(db_path, long_sym,  date_str)

            api_before = historical_data.api_calls_made
            short_bar  = historical_data.get_intraday_bar(
                short_sym, date_str, CHECK_HOUR, CHECK_MIN)
            long_bar   = historical_data.get_intraday_bar(
                long_sym,  date_str, CHECK_HOUR, CHECK_MIN)
            new_calls  = historical_data.api_calls_made - api_before

            both_have_data = (short_bar is not None and long_bar is not None)

            total_pos_days += 1
            if both_have_data:
                total_has += 1
                trade_has += 1
                by_day_type[day_type]['has_data'] += 1
            else:
                total_no  += 1
                trade_no  += 1
                by_day_type[day_type]['no_data'] += 1

            was_pre_cached = (short_pre != 'not_cached' and long_pre != 'not_cached')
            if was_pre_cached:
                by_day_type[day_type]['pre_cached'] += 1
            else:
                by_day_type[day_type]['new_api'] += new_calls

        n_hold = len(hold_days)
        pct    = f"{100 * trade_has // n_hold}%" if n_hold else "N/A"
        print(f"  {t_idx+1:2d}  {str(entry_dt.date()):>10}  {str(exit_dt.date()):>10}"
              f"  {n_hold:>4}  {ot:>4}  {trade['short_strike']:>6.0f}"
              f"  {trade_has:>4}/{n_hold:<4}  {pct:>8}")

    total_api_measurement = historical_data.api_calls_made - api_calls_start

    # ── Step 3: Report ─────────────────────────────────────────────────────
    print(f"\n[3/3] RESULTS")
    print("=" * 72)
    pct_has  = 100 * total_has // total_pos_days if total_pos_days else 0
    pct_no   = 100 * total_no  // total_pos_days if total_pos_days else 0

    print(f"\n  OVERALL COVERAGE ({len(sampled)} trades, {total_pos_days} position-days):")
    print(f"  {'Position-days WITH intraday data:':<42} {total_has:>4}  ({pct_has}%)")
    print(f"  {'Position-days WITHOUT intraday data:':<42} {total_no:>4}  ({pct_no}%)")
    print(f"  {'Expected fallback rate (→ daily close):':<42} {pct_no}%")
    print(f"  {'API calls for this measurement:':<42} {total_api_measurement}")

    print(f"\n  BREAKDOWN BY POSITION-DAY TYPE:")
    print(f"  {'Day Type':<10} {'Has Data':>10} {'No Data':>10} {'Coverage%':>10}  Notes")
    print(f"  {'─'*60}")
    for day_type in ['entry', 'holding', 'exit']:
        v   = by_day_type[day_type]
        tot = v['has_data'] + v['no_data']
        pct_t = f"{100 * v['has_data'] // tot}%" if tot else "N/A"
        note = ""
        if day_type == 'entry':
            note = "← entry intraday already fetched at scan"
        print(f"  {day_type:<10} {v['has_data']:>10} {v['no_data']:>10} {pct_t:>10}  {note}")

    print(f"\n  INTERPRETATION:")
    if pct_no < 10:
        verdict = "EXCELLENT — intraday simulation will cover >90% of days"
        color   = "✅"
    elif pct_no < 25:
        verdict = "GOOD — >75% coverage; fallback to daily close is a minor edge case"
        color   = "✅"
    elif pct_no < 50:
        verdict = "MODERATE — some coverage gaps; fallback will be needed regularly"
        color   = "⚠️ "
    else:
        verdict = "POOR — majority lack intraday data; fix may be mostly a no-op"
        color   = "🚨"

    print(f"  {color} Fallback rate: {pct_no}%  →  {verdict}")

    if pct_no >= 25:
        print()
        print("  RECOMMENDATION: Before implementing intraday exits, consider whether")
        print("  the expected coverage justifies the added complexity and runtime.")
        print("  A high fallback rate means most position-days still use daily close,")
        print("  limiting the impact of the fix on win rate / P&L.")

    print(f"\n  Total API calls this session: {historical_data.api_calls_made}")
    print("=" * 72)


if __name__ == '__main__':
    main()
