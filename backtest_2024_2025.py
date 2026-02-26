#!/usr/bin/env python3
"""
Run full-year backtests for 2024 and 2025 using the production winning config.

Production config: OTM=3%, Width=$5, MinCredit=10%, SL=2.5x, 2% risk, max 5 contracts

Note: 2024/2025 data is accessible via Polygon's reference API (recent enough).
Pre-seeding is still used for speed and cache consistency with the 2020-2023 scripts.
"""

import os
import sys
import copy
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ── Patch _DEFAULT_LOOKBACK_YEARS BEFORE importing HistoricalOptionsData ──────
# _fetch_and_cache uses now - N*365 days as start; with N=7 we cover back to 2019
import backtest.historical_data as hd_module
hd_module._DEFAULT_LOOKBACK_YEARS = 7

from utils import load_config, setup_logging
from backtest.backtester import Backtester, _nearest_friday_expiration
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


def preseed_option_contracts(historical_data: HistoricalOptionsData, ticker: str,
                              start: datetime, end: datetime):
    """Pre-seed option_contracts table with computed strikes for all trading days.

    Generates $1-step strikes from price*0.75 to price*1.25 for both P and C,
    covering every unique (expiration, option_type) the backtester will request.
    This bypasses the empty Polygon reference endpoint for pre-2022 expirations.

    Uses yfinance for SPY daily prices (free, no auth required).
    """
    import yfinance as yf

    print(f"\n  Pre-seeding option_contracts for {ticker} {start.year}–{end.year}...")

    # Fetch daily prices with 30 days of warmup (for MA20 in backtester)
    fetch_start = start - timedelta(days=45)
    raw = yf.download(ticker, start=fetch_start.strftime('%Y-%m-%d'),
                      end=(end + timedelta(days=1)).strftime('%Y-%m-%d'),
                      progress=False, auto_adjust=True)
    if raw.empty:
        print("  ERROR: yfinance returned no data.")
        return

    # Flatten MultiIndex if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].dropna()
    print(f"  Got {len(prices)} trading days from yfinance.")

    conn = historical_data._conn
    cur = conn.cursor()

    seeded_keys = set()  # (ticker, expiration_str, strike, option_type)
    rows_to_insert = []

    trading_days = prices.index[prices.index >= pd.Timestamp(start)]

    for ts in trading_days:
        date = ts.to_pydatetime().replace(tzinfo=None)
        price = float(prices[ts])

        expiration = _nearest_friday_expiration(date)
        exp_str = expiration.strftime('%Y-%m-%d')
        as_of_str = date.strftime('%Y-%m-%d')

        # Strike range: price*0.75 to price*1.25, $1 steps
        low_strike = int(price * 0.75)
        high_strike = int(price * 1.25) + 1

        for option_type in ('P', 'C'):
            for strike in range(low_strike, high_strike):
                key = (ticker, exp_str, float(strike), option_type)
                if key in seeded_keys:
                    continue
                seeded_keys.add(key)
                occ = hd_module.HistoricalOptionsData.build_occ_symbol(
                    ticker, expiration, float(strike), option_type
                )
                rows_to_insert.append(
                    (ticker, exp_str, float(strike), option_type, occ, as_of_str)
                )

    # Bulk insert (INSERT OR IGNORE respects existing rows)
    cur.executemany(
        "INSERT OR IGNORE INTO option_contracts "
        "(ticker, expiration, strike, option_type, contract_symbol, as_of_date) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows_to_insert,
    )
    conn.commit()
    print(f"  Inserted {len(rows_to_insert):,} strike rows "
          f"({len(seeded_keys):,} unique keys) into option_contracts.")


def run_period(base_config: dict, historical_data, label: str,
               start: datetime, end: datetime):
    cfg = copy.deepcopy(base_config)
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
        import traceback; traceback.print_exc()
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
    print("HISTORICAL BACKTEST — 2024 & 2025 FULL YEARS")
    print("OTM=3% | Width=$5 | MinCredit=10% | SL=2.5x | 2% risk | max 5 contracts")
    print(f"_DEFAULT_LOOKBACK_YEARS patched to {hd_module._DEFAULT_LOOKBACK_YEARS} "
          f"(covers ~{datetime.now().year - hd_module._DEFAULT_LOOKBACK_YEARS} onward)")
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
    print(f"_DEFAULT_LOOKBACK_YEARS = {hd_module._DEFAULT_LOOKBACK_YEARS}")

    periods = [
        ("2024 Full Year", datetime(2024, 1, 1), datetime(2024, 12, 31)),
        ("2025 Full Year", datetime(2025, 1, 1), datetime(2025, 12, 31)),
    ]

    # Pre-seed option_contracts for both years in one pass
    combined_start = datetime(2024, 1, 1)
    combined_end = datetime(2025, 12, 31)
    preseed_option_contracts(historical_data, 'SPY', combined_start, combined_end)

    all_results = []
    for label, start, end in periods:
        result = run_period(base_config, historical_data, label, start, end)
        if result:
            all_results.append(result)

    # ── Summary table ──────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n{'Year':<12} {'Trades':>7} {'WR%':>6} {'Return%':>8} {'DD%':>7} "
          f"{'Sharpe':>7} {'Weekly%':>9} {'Bulls':>6} {'Calls':>6}")
    print("─" * 70)
    for r in all_results:
        print(f"{r['label']:<12} {r['total_trades']:>7} {r['win_rate']:>6} "
              f"{r['return_pct']:>8} {r['max_drawdown']:>7.1f} "
              f"{r['sharpe_ratio']:>7.2f} {r['weekly_consistency']:>9} "
              f"{r['bull_put_trades']:>6} {r['bear_call_trades']:>6}")

    # ── Save individual JSON files ─────────────────────────────────────────────
    out_dir = Path('output')
    out_dir.mkdir(exist_ok=True)

    config_meta = {
        'otm_pct': 0.03, 'spread_width': 5,
        'min_credit_pct': 10, 'stop_loss_mult': 2.5,
        'max_risk_per_trade': 2.0, 'max_contracts': 5,
    }

    for r in all_results:
        year = r['label'].split()[0]
        out_path = out_dir / f"backtest_results_polygon_REAL_{year}.json"
        payload = {
            'timestamp': datetime.now().isoformat(),
            'config': config_meta,
            'results': [r],
        }
        with open(out_path, 'w') as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"\nSaved: {out_path}")

    # ── Combined file ──────────────────────────────────────────────────────────
    combined_path = out_dir / "backtest_results_2024_2025.json"
    with open(combined_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'config': config_meta,
            'results': all_results,
        }, f, indent=2, default=str)
    print(f"Saved: {combined_path}")
    print("=" * 70)


if __name__ == '__main__':
    main()
