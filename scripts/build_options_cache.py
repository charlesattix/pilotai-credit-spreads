#!/usr/bin/env python3
"""
build_options_cache.py — Bulk-download historical option data into SQLite cache.

Pre-fetches option contracts and daily OHLCV bars from Polygon.io for
backtesting. Supports resumption (skips already-completed months).

Usage:
    # Smoke test: SPY 2024 only (~30 min)
    python3 scripts/build_options_cache.py --tickers SPY --start-year 2024 --end-year 2024

    # Full build: all tickers, all years (~6-12 hours)
    python3 scripts/build_options_cache.py --tickers SPY,QQQ,IWM --start-year 2020 --end-year 2025

    # Check cache stats
    python3 scripts/build_options_cache.py --stats

    # Clear and rebuild
    python3 scripts/build_options_cache.py --clear-cache
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backtest.historical_data import HistoricalOptionsData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cache_builder")


def get_underlying_price_range(cache: HistoricalOptionsData, ticker: str,
                                year: int, month: int) -> tuple:
    """Fetch underlying OHLCV for a month and return (min_price, max_price).

    Uses Polygon /v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}.
    """
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{last_day:02d}"

    data = cache._api_get(
        f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
        params={"adjusted": "true", "sort": "asc", "limit": 50},
    )
    results = data.get("results", [])
    if not results:
        return None, None

    lows = [bar.get("l", 0) for bar in results if bar.get("l")]
    highs = [bar.get("h", 0) for bar in results if bar.get("h")]

    if not lows or not highs:
        return None, None

    return min(lows), max(highs)


def build_month(cache: HistoricalOptionsData, ticker: str, year: int, month: int,
                strike_pct: float = 0.20, dry_run: bool = False) -> dict:
    """Download all option contracts + bars for one (ticker, year, month).

    Returns dict with counts for logging.
    """
    # Check if already done
    status = cache.get_download_progress(ticker, year, month)
    if status == "complete":
        logger.info("  %s %d-%02d: already complete, skipping", ticker, year, month)
        return {"skipped": True}

    # Get underlying price range for strike filtering
    min_price, max_price = get_underlying_price_range(cache, ticker, year, month)
    if min_price is None:
        logger.warning("  %s %d-%02d: no underlying data, skipping", ticker, year, month)
        cache.update_download_progress(ticker, year, month, "no_data")
        return {"skipped": True, "reason": "no_underlying_data"}

    # Enumerate contracts for this month
    cache.update_download_progress(ticker, year, month, "enumerating")
    contracts = cache.enumerate_month_contracts(ticker, year, month)

    if not contracts:
        logger.info("  %s %d-%02d: no contracts found", ticker, year, month)
        cache.update_download_progress(ticker, year, month, "complete", 0, 0)
        return {"contracts_found": 0, "downloaded": 0}

    # Filter to strikes within ±strike_pct of price range
    strike_low = min_price * (1 - strike_pct)
    strike_high = max_price * (1 + strike_pct)

    filtered = [
        c for c in contracts
        if strike_low <= c.get("strike_price", 0) <= strike_high
    ]

    logger.info(
        "  %s %d-%02d: %d contracts total, %d within ±%.0f%% of $%.0f-$%.0f",
        ticker, year, month, len(contracts), len(filtered),
        strike_pct * 100, min_price, max_price,
    )

    if dry_run:
        return {"contracts_found": len(filtered), "downloaded": 0, "dry_run": True}

    cache.update_download_progress(
        ticker, year, month, "downloading",
        contracts_found=len(filtered),
    )

    # Download bars for each contract
    downloaded = 0
    errors = 0
    for i, contract in enumerate(filtered):
        symbol = contract.get("ticker", "")
        if not symbol:
            continue

        try:
            # Check if already cached
            cur = cache._conn.cursor()
            cur.execute(
                "SELECT 1 FROM option_daily WHERE contract_symbol = ? LIMIT 1",
                (symbol,),
            )
            if cur.fetchone() is not None:
                downloaded += 1
                continue

            # Fetch and cache
            cache._fetch_and_cache(symbol)
            downloaded += 1

            # Also cache the contract reference
            strike = contract.get("strike_price", 0)
            exp = contract.get("expiration_date", "")
            ct = contract.get("contract_type", "")
            ot = "P" if ct == "put" else "C"
            cur.execute(
                "INSERT OR IGNORE INTO option_contracts "
                "(ticker, expiration, strike, option_type, contract_symbol, as_of_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, exp, strike, ot, symbol, f"{year}-{month:02d}-01"),
            )
            cache._conn.commit()

        except Exception as e:
            errors += 1
            logger.debug("  Error fetching %s: %s", symbol, e)

        # Progress log every 100 contracts
        if (i + 1) % 100 == 0:
            logger.info(
                "    %s %d-%02d: %d/%d contracts downloaded",
                ticker, year, month, downloaded, len(filtered),
            )

    cache.update_download_progress(
        ticker, year, month, "complete",
        contracts_found=len(filtered),
        contracts_downloaded=downloaded,
    )

    return {
        "contracts_found": len(filtered),
        "downloaded": downloaded,
        "errors": errors,
    }


def build_cache(
    tickers: list,
    start_year: int,
    end_year: int,
    strike_pct: float = 0.20,
    dry_run: bool = False,
):
    """Main entry point: build cache for all tickers across year range."""
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        print("ERROR: No POLYGON_API_KEY found in environment.")
        print("Set it in .env or export POLYGON_API_KEY=...")
        sys.exit(1)

    cache = HistoricalOptionsData(api_key)
    t0 = time.time()

    total_contracts = 0
    total_downloaded = 0
    total_errors = 0

    for ticker in tickers:
        print(f"\n{'='*60}")
        print(f"  Building cache: {ticker} ({start_year}-{end_year})")
        print(f"{'='*60}")

        for year in range(start_year, end_year + 1):
            # Use months 1-12, but cap end_year at current month
            end_month = 12
            if year == datetime.now().year:
                end_month = min(12, datetime.now().month)

            for month in range(1, end_month + 1):
                result = build_month(cache, ticker, year, month, strike_pct, dry_run)

                if not result.get("skipped"):
                    total_contracts += result.get("contracts_found", 0)
                    total_downloaded += result.get("downloaded", 0)
                    total_errors += result.get("errors", 0)

    elapsed = time.time() - t0

    # Final report
    stats = cache.stats()
    print(f"\n{'='*60}")
    print("  CACHE BUILD COMPLETE")
    print(f"{'='*60}")
    print(f"  Tickers:    {', '.join(tickers)}")
    print(f"  Years:      {start_year}-{end_year}")
    print(f"  Contracts found:      {total_contracts:,}")
    print(f"  Contracts downloaded: {total_downloaded:,}")
    print(f"  Errors:               {total_errors:,}")
    print(f"  Duration:             {elapsed/60:.1f} minutes")
    print(f"  Cache size:           {stats['cache_size_mb']:.1f} MB")
    print(f"  Total bars in cache:  {stats['total_bars']:,}")
    print(f"{'='*60}\n")

    cache.close()


def print_stats():
    """Print cache statistics without downloading anything."""
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        print("ERROR: No POLYGON_API_KEY found.")
        sys.exit(1)

    cache = HistoricalOptionsData(api_key)
    stats = cache.stats()

    print(f"\n{'='*60}")
    print("  OPTIONS CACHE STATS")
    print(f"{'='*60}")
    print(f"  Total unique contracts: {stats['total_contracts']:,}")
    print(f"  Total daily bars:       {stats['total_bars']:,}")
    print(f"  Cache size:             {stats['cache_size_mb']:.1f} MB")

    if stats["per_underlying"]:
        print(f"\n  Per underlying:")
        for ticker, info in stats["per_underlying"].items():
            print(f"    {ticker}: {info['contracts']:,} contracts "
                  f"({info['earliest_exp']} to {info['latest_exp']})")

    if stats["download_progress"]:
        print(f"\n  Download progress:")
        for ticker, statuses in stats["download_progress"].items():
            parts = [f"{status}={count}" for status, count in statuses.items()]
            print(f"    {ticker}: {', '.join(parts)}")

    print(f"{'='*60}\n")
    cache.close()


def main():
    parser = argparse.ArgumentParser(description="Build historical options cache from Polygon")
    parser.add_argument("--tickers", default="SPY", help="Comma-separated tickers (default: SPY)")
    parser.add_argument("--start-year", type=int, default=2020, help="Start year (default: 2020)")
    parser.add_argument("--end-year", type=int, default=2025, help="End year (default: 2025)")
    parser.add_argument("--strike-pct", type=float, default=0.20,
                        help="Strike filter: keep strikes within ±X%% of underlying (default: 0.20)")
    parser.add_argument("--stats", action="store_true", help="Print cache stats and exit")
    parser.add_argument("--clear-cache", action="store_true", help="Clear all cached data")
    parser.add_argument("--dry-run", action="store_true", help="Enumerate contracts without downloading bars")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    if args.clear_cache:
        api_key = os.environ.get("POLYGON_API_KEY", "")
        if not api_key:
            print("ERROR: No POLYGON_API_KEY found.")
            sys.exit(1)
        cache = HistoricalOptionsData(api_key)
        cache.clear_cache()
        print("Cache cleared.")
        cache.close()
        return

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    build_cache(tickers, args.start_year, args.end_year, args.strike_pct, args.dry_run)


if __name__ == "__main__":
    main()
