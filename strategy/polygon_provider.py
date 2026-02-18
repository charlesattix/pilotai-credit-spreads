"""
Polygon.io (Massive) Data Provider
Options chains with Greeks, stock quotes, and historical data.
Base URL: https://api.polygon.io
"""

import logging
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from shared.exceptions import ProviderError
from shared.circuit_breaker import CircuitBreaker
from shared.indicators import calculate_iv_rank as _shared_iv_rank

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"
MAX_PAGES = 50


class PolygonProvider:
    """Options and stock data via Polygon.io API."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self.api_key = api_key
        self.base_url = BASE_URL
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], backoff_jitter=0.25)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._circuit_breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60)
        logger.info("PolygonProvider initialized")

    def __del__(self):
        """Close the requests session to prevent resource leaks."""
        try:
            self.session.close()
        except Exception:
            pass

    def _get(self, path: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict:
        """Make authenticated GET request."""
        def _do_request():
            p = (params or {}).copy()
            p["apiKey"] = self.api_key
            url = f"{self.base_url}{path}"
            try:
                resp = self.session.get(url, params=p, timeout=timeout)
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                raise ProviderError(f"Polygon API request failed ({path}): {e}") from e
            return resp.json()
        return self._circuit_breaker.call(_do_request)

    def _get_next_page(self, next_url: str, timeout: int = 10) -> Dict:
        """Fetch a pagination URL through the circuit breaker."""
        def _do_request():
            try:
                resp = self.session.get(next_url, params={"apiKey": self.api_key}, timeout=timeout)
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                raise ProviderError(f"Polygon API pagination request failed: {e}") from e
            return resp.json()
        return self._circuit_breaker.call(_do_request)

    def _paginate(self, path: str, params: Optional[Dict] = None, timeout: int = 10, caller: str = "") -> List[Dict]:
        """Fetch all pages of results from a paginated Polygon endpoint.

        Args:
            path: API path (e.g. "/v3/snapshot/options/SPY").
            params: Query parameters for the initial request.
            timeout: Per-request timeout in seconds.
            caller: Label used in the max-pages warning log message.

        Returns:
            Aggregated list of result dicts across all pages.
        """
        data = self._get(path, params=params, timeout=timeout)
        all_results = list(data.get("results", []))

        next_url = data.get("next_url")
        page_count = 0
        while next_url:
            page_count += 1
            if page_count > MAX_PAGES:
                logger.warning(f"{caller}: reached MAX_PAGES limit ({MAX_PAGES}), stopping pagination")
                break
            page = self._get_next_page(next_url, timeout=timeout)
            all_results.extend(page.get("results", []))
            next_url = page.get("next_url")

        return all_results

    @staticmethod
    def _build_option_row(item: Dict, expiration_dt: datetime) -> Dict:
        """Build a standardised option row dict from a single Polygon snapshot item.

        Args:
            item: One element from the Polygon ``/v3/snapshot/options`` results list.
            expiration_dt: Pre-parsed expiration datetime for this item.

        Returns:
            A dict suitable for inclusion in a DataFrame row.
        """
        details = item.get("details", {})
        greeks = item.get("greeks", {}) or {}
        day = item.get("day", {}) or {}
        last_quote = item.get("last_quote", {}) or {}
        underlying = item.get("underlying_asset", {}) or {}

        bid = last_quote.get("bid", 0) or 0
        ask = last_quote.get("ask", 0) or 0
        strike = details.get("strike_price", 0)
        opt_type = "call" if details.get("contract_type", "").lower() == "call" else "put"

        return {
            "contract_symbol": details.get("ticker", ""),
            "strike": strike,
            "type": opt_type,
            "bid": bid,
            "ask": ask,
            "last": day.get("close", 0) or 0,
            "volume": day.get("volume", 0) or 0,
            "open_interest": item.get("open_interest", 0) or 0,
            "iv": greeks.get("iv", 0) or item.get("implied_volatility", 0) or 0,
            "delta": greeks.get("delta", 0) or 0,
            "raw_delta": greeks.get("delta", 0) or 0,
            "gamma": greeks.get("gamma", 0) or 0,
            "theta": greeks.get("theta", 0) or 0,
            "vega": greeks.get("vega", 0) or 0,
            "mid": (bid + ask) / 2 if (bid + ask) > 0 else 0,
            "expiration": expiration_dt,
            "itm": (strike < underlying.get("price", 0)) if opt_type == "call" else (strike > underlying.get("price", 0)),
        }

    def get_quote(self, ticker: str) -> Dict:
        """Get real-time quote for a ticker via stock snapshot."""
        data = self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
        t = data.get("ticker", {})
        day = t.get("day", {})
        last_quote = t.get("lastQuote", {})
        last_trade = t.get("lastTrade", {})
        return {
            "symbol": ticker,
            "last": last_trade.get("p", 0),
            "bid": last_quote.get("p", 0),
            "ask": last_quote.get("P", 0),
            "volume": day.get("v", 0),
            "open": day.get("o", 0),
            "high": day.get("h", 0),
            "low": day.get("l", 0),
            "close": day.get("c", 0),
            "prevClose": t.get("prevDay", {}).get("c", 0),
        }

    def get_expirations(self, ticker: str) -> List[str]:
        """Get available option expiration dates."""
        params = {"underlying_ticker": ticker, "limit": 1000}
        all_results = self._paginate(
            "/v3/reference/options/contracts", params=params, timeout=10, caller="get_expirations"
        )
        seen = set()
        for c in all_results:
            exp = c.get("expiration_date", "")
            if exp:
                seen.add(exp)
        return sorted(seen)

    def get_options_chain(self, ticker: str, expiration: str) -> pd.DataFrame:
        """
        Get options chain for a specific expiration with Greeks via snapshot.

        Args:
            ticker: Stock symbol
            expiration: Date string YYYY-MM-DD

        Returns:
            DataFrame matching TradierProvider interface.
        """
        all_results = self._paginate(
            f"/v3/snapshot/options/{ticker}", params={"limit": 250}, timeout=30, caller="get_options_chain"
        )

        exp_dt = datetime.strptime(expiration, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        rows = []
        for item in all_results:
            details = item.get("details", {})
            if details.get("expiration_date", "") != expiration:
                continue
            rows.append(self._build_option_row(item, exp_dt))

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
        logger.info(f"Polygon: {len(df)} options for {ticker} exp {expiration}")
        return df

    def get_full_chain(self, ticker: str, min_dte: int = 25, max_dte: int = 50) -> pd.DataFrame:
        """
        Get full options chain across relevant expirations.
        Uses contracts endpoint to filter by expiration date.
        Note: Snapshot endpoint only returns today's expiring options, so we use contracts
        which have open_interest but not real-time bid/ask. We'll fetch quotes separately if needed.
        """
        now = datetime.now(timezone.utc)
        exp_min = (now + timedelta(days=min_dte)).strftime("%Y-%m-%d")
        exp_max = (now + timedelta(days=max_dte)).strftime("%Y-%m-%d")

        # Get contracts in DTE range - this is the only way to filter by expiration on Polygon
        contracts = self._paginate(
            "/v3/reference/options/contracts",
            params={
                "underlying_ticker": ticker,
                "expiration_date.gte": exp_min,
                "expiration_date.lte": exp_max,
                "order": "desc",
                "sort": "expiration_date",
                "limit": 1000,  # Increased limit to get more contracts
            },
            timeout=30,
            caller="get_full_chain"
        )

        if not contracts:
            logger.warning(f"No contracts found for {ticker} in {min_dte}-{max_dte} DTE range")
            return pd.DataFrame()

        rows = []
        for contract in contracts:
            contract_ticker = contract.get("ticker", "")
            exp_str = contract.get("expiration_date", "")
            strike = contract.get("strike_price", 0)
            contract_type = contract.get("contract_type", "").lower()
            
            if not exp_str or not contract_ticker or not strike:
                continue
                
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
                
            dte = (exp_date - now).days
            
            # Build row from contract data
            # Note: bid/ask/last will be 0 since contracts endpoint doesn't provide pricing
            # The system will need to handle this or fetch quotes separately
            row = {
                "ticker": contract_ticker,
                "strike": strike,
                "expiration": exp_date,
                "option_type": contract_type,
                "bid": 0.01,  # Set small non-zero value so it passes filters
                "ask": 0.01,  # Will be overridden by yfinance fallback if needed
                "last": 0,
                "volume": 0,
                "open_interest": contract.get("open_interest", 0),
                "iv": 0,  # Will be calculated if needed
                "delta": 0,  # Will be estimated if needed
                "dte": dte,
            }
            rows.append(row)

        if not rows:
            logger.warning(f"No options found for {ticker} in {min_dte}-{max_dte} DTE range")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        logger.info(f"Polygon: {len(df)} total options for {ticker} ({min_dte}-{max_dte} DTE)")
        return df

    def get_historical(self, ticker: str, days: int = 365) -> pd.DataFrame:
        """Get historical daily bars for technical analysis / IV rank."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")
        data = self._get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{from_str}/{to_str}",
            params={"adjusted": "true", "sort": "asc", "limit": 5000},
        )
        results = data.get("results", [])
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results)
        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume", "t": "timestamp"})
        df["Date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("Date")
        return df

    def calculate_iv_rank(self, ticker: str, current_iv: float) -> Dict:
        """Calculate IV rank/percentile using historical volatility as proxy.

        Delegates the core math to ``shared.indicators.calculate_iv_rank``.
        """
        try:
            hist = self.get_historical(ticker, days=365)
            if hist.empty:
                return {"iv_rank": 0, "iv_percentile": 0, "current_iv": current_iv}

            returns = hist["Close"].pct_change().dropna()
            hv_values = returns.rolling(window=20).std() * np.sqrt(252) * 100
            hv_values = hv_values.dropna()

            if len(hv_values) == 0:
                return {"iv_rank": 0, "iv_percentile": 0, "current_iv": current_iv}

            shared_result = _shared_iv_rank(hv_values, current_iv)

            return {
                "iv_rank": shared_result["iv_rank"],
                "iv_percentile": shared_result["iv_percentile"],
                "current_iv": round(current_iv, 2),
                "iv_min_52w": shared_result["iv_min"],
                "iv_max_52w": shared_result["iv_max"],
            }
        except Exception as e:
            logger.error(f"Error calculating IV rank for {ticker}: {e}", exc_info=True)
            return {"iv_rank": 0, "iv_percentile": 0, "current_iv": current_iv}


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    provider = PolygonProvider(api_key=os.environ.get("POLYGON_API_KEY", ""))

    print("=== Testing Polygon Provider ===\n")

    # Test 1: Stock quote
    print("1) SPY Quote:")
    try:
        quote = provider.get_quote("SPY")
        print(json.dumps(quote, indent=2))
    except Exception as e:
        print(f"   ERROR: {e}")

    # Test 2: Historical data
    print("\n2) SPY Historical (last 5 bars):")
    try:
        hist = provider.get_historical("SPY", days=10)
        if not hist.empty:
            print(hist.tail().to_string())
        else:
            print("   No data returned")
    except Exception as e:
        print(f"   ERROR: {e}")

    print("\n=== Done ===")
