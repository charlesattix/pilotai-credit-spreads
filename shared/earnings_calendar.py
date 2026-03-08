"""
Earnings calendar, expected move calculator, and historical stay-in-range analysis.

Provides earnings date fetching via yfinance, ATM straddle expected move
calculation, and historical earnings move analysis for the earnings volatility
play scanner (Phase 5).
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ETFs and indices that don't have earnings
_NO_EARNINGS_TICKERS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV",
    "SMH", "ARKK", "TLT", "GLD", "SLV", "VIX", "^VIX",
})


class EarningsCalendar:
    """Earnings date fetcher with caching and historical analysis."""

    def __init__(self, data_cache=None):
        self._data_cache = data_cache
        # Simple earnings cache: ticker -> (datetime, fetched_at)
        self._earnings_cache: Dict[str, tuple] = {}
        self._cache_ttl_hours = 24

    def get_next_earnings(self, ticker: str) -> Optional[datetime]:
        """Get the next earnings date for a ticker.

        Uses yfinance Ticker.calendar with 24h caching.
        Returns None for ETFs/indices or if date is unavailable.
        """
        if ticker in _NO_EARNINGS_TICKERS:
            return None

        # Check cache
        if ticker in self._earnings_cache:
            cached_date, fetched_at = self._earnings_cache[ticker]
            age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
            if age_hours < self._cache_ttl_hours:
                return cached_date

        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is None:
                self._earnings_cache[ticker] = (None, datetime.now(timezone.utc))
                return None

            # calendar may be a dict or DataFrame depending on yfinance version
            earnings_date = None
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date", [])
                if dates:
                    earnings_date = dates[0]
            else:
                # DataFrame format
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    if hasattr(val, "iloc"):
                        earnings_date = val.iloc[0]
                    else:
                        earnings_date = val

            if earnings_date is not None:
                if isinstance(earnings_date, str):
                    earnings_date = datetime.fromisoformat(earnings_date)
                elif hasattr(earnings_date, "to_pydatetime"):
                    earnings_date = earnings_date.to_pydatetime()
                # Ensure timezone-aware
                if earnings_date.tzinfo is None:
                    earnings_date = earnings_date.replace(tzinfo=timezone.utc)

            self._earnings_cache[ticker] = (earnings_date, datetime.now(timezone.utc))
            return earnings_date

        except Exception as e:
            logger.warning(f"Failed to fetch earnings for {ticker}: {e}")
            self._earnings_cache[ticker] = (None, datetime.now(timezone.utc))
            return None

    def get_lookahead_calendar(
        self, tickers: List[str], days_ahead: int = 14
    ) -> List[Dict]:
        """Get upcoming earnings within a lookahead window.

        Returns a list of dicts sorted by days_until ascending:
        [{"ticker": str, "earnings_date": datetime, "days_until": int}, ...]
        """
        now = datetime.now(timezone.utc)
        results = []

        for ticker in tickers:
            earnings_date = self.get_next_earnings(ticker)
            if earnings_date is None:
                continue

            days_until = (earnings_date - now).days
            if 0 <= days_until <= days_ahead:
                results.append({
                    "ticker": ticker,
                    "earnings_date": earnings_date,
                    "days_until": days_until,
                })

        results.sort(key=lambda x: x["days_until"])
        return results

    def get_historical_earnings_dates(
        self, ticker: str, num_quarters: int = 8
    ) -> List[datetime]:
        """Get historical earnings dates for a ticker.

        Uses yfinance earnings_dates (DatetimeIndex).
        Returns up to num_quarters past dates, most recent first.
        """
        if ticker in _NO_EARNINGS_TICKERS:
            return []

        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            dates = t.earnings_dates
            if dates is None or (hasattr(dates, "empty") and dates.empty):
                return []

            # earnings_dates is a DataFrame with DatetimeIndex
            idx = dates.index
            now = datetime.now(timezone.utc)
            past_dates = []
            for dt in idx:
                dt_py = dt.to_pydatetime() if hasattr(dt, "to_pydatetime") else dt
                if dt_py.tzinfo is None:
                    dt_py = dt_py.replace(tzinfo=timezone.utc)
                if dt_py < now:
                    past_dates.append(dt_py)

            # Sort most recent first, limit to num_quarters
            past_dates.sort(reverse=True)
            return past_dates[:num_quarters]

        except Exception as e:
            logger.warning(f"Failed to fetch historical earnings for {ticker}: {e}")
            return []

    def calculate_expected_move(
        self, options_chain, current_price: float
    ) -> Optional[float]:
        """Calculate expected move from ATM straddle mid-prices.

        Finds the ATM call and ATM put (closest strikes to current_price),
        computes their mid-prices, and returns the sum as the implied
        expected move in dollars.

        Args:
            options_chain: DataFrame with columns: strike, type, bid, ask
            current_price: Current underlying price

        Returns:
            Expected move in dollars, or None if calculation fails.
        """
        try:
            if options_chain is None or (hasattr(options_chain, "empty") and options_chain.empty):
                return None

            calls = options_chain[options_chain["type"] == "call"] if "type" in options_chain.columns else None
            puts = options_chain[options_chain["type"] == "put"] if "type" in options_chain.columns else None

            if calls is None or puts is None:
                return None
            if hasattr(calls, "empty") and calls.empty:
                return None
            if hasattr(puts, "empty") and puts.empty:
                return None

            # Find ATM call
            calls = calls.copy()
            calls["_dist"] = (calls["strike"] - current_price).abs()
            atm_call = calls.loc[calls["_dist"].idxmin()]
            call_mid = (float(atm_call.get("bid", 0)) + float(atm_call.get("ask", 0))) / 2

            # Find ATM put
            puts = puts.copy()
            puts["_dist"] = (puts["strike"] - current_price).abs()
            atm_put = puts.loc[puts["_dist"].idxmin()]
            put_mid = (float(atm_put.get("bid", 0)) + float(atm_put.get("ask", 0))) / 2

            if call_mid <= 0 or put_mid <= 0:
                return None

            return round(call_mid + put_mid, 2)

        except Exception as e:
            logger.warning(f"Expected move calculation failed: {e}")
            return None

    def calculate_historical_stay_in_range(
        self, ticker: str, num_quarters: int = 8
    ) -> Dict:
        """Analyze historical earnings moves vs expected move approximation.

        For each historical earnings date:
        - Gets pre-earnings close and post-earnings close
        - Computes actual move percentage
        - Approximates expected move from 30-day historical volatility

        Returns:
            {
                "stay_in_range_pct": float (0-100),
                "avg_move_pct": float,
                "total_quarters": int,
                "quarters_in_range": int,
            }
        """
        default = {
            "stay_in_range_pct": 0.0,
            "avg_move_pct": 0.0,
            "total_quarters": 0,
            "quarters_in_range": 0,
        }

        try:
            import yfinance as yf
            hist_dates = self.get_historical_earnings_dates(ticker, num_quarters)
            if not hist_dates:
                return default

            # Get price history
            t = yf.Ticker(ticker)
            price_data = t.history(period="5y")
            if price_data is None or (hasattr(price_data, "empty") and price_data.empty):
                return default

            closes = price_data["Close"]
            total = 0
            in_range = 0
            move_pcts = []

            for earnings_dt in hist_dates:
                try:
                    # Find the trading day closest to earnings
                    earnings_date = earnings_dt.date() if hasattr(earnings_dt, "date") else earnings_dt

                    # Get pre-earnings close (day before or closest prior)
                    prior_closes = closes[closes.index.date < earnings_date]
                    if len(prior_closes) < 30:
                        continue
                    pre_close = float(prior_closes.iloc[-1])

                    # Get post-earnings close (day after or closest after)
                    post_closes = closes[closes.index.date > earnings_date]
                    if post_closes.empty:
                        continue
                    post_close = float(post_closes.iloc[0])

                    # Actual move
                    actual_move_pct = abs(post_close - pre_close) / pre_close * 100

                    # Approximate expected move from 30-day HV
                    recent = prior_closes.iloc[-30:]
                    returns = recent.pct_change().dropna()
                    if len(returns) < 5:
                        continue
                    daily_vol = float(returns.std())
                    # Annualize and convert to 1-day expected move
                    expected_move_pct = daily_vol * (252 ** 0.5) / (252 ** 0.5) * 100
                    # Use 1-day expected move (daily vol * 100)
                    expected_move_pct = daily_vol * 100

                    total += 1
                    move_pcts.append(actual_move_pct)
                    if actual_move_pct <= expected_move_pct * 1.2:
                        in_range += 1

                except Exception:
                    continue

            if total == 0:
                return default

            return {
                "stay_in_range_pct": round(in_range / total * 100, 1),
                "avg_move_pct": round(sum(move_pcts) / len(move_pcts), 2),
                "total_quarters": total,
                "quarters_in_range": in_range,
            }

        except Exception as e:
            logger.warning(f"Historical stay-in-range calculation failed for {ticker}: {e}")
            return default
