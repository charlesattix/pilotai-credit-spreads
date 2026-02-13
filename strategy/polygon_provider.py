"""
Polygon.io (Massive) Data Provider
Options chains with Greeks, stock quotes, and historical data.
Base URL: https://api.polygon.io
"""

import logging
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"


class PolygonProvider:
    """Options and stock data via Polygon.io API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = BASE_URL
        logger.info("PolygonProvider initialized")

    def _get(self, path: str, params: Optional[Dict] = None, timeout: int = 10) -> Dict:
        """Make authenticated GET request."""
        params = params or {}
        params["apiKey"] = self.api_key
        url = f"{self.base_url}{path}"
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

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
        results = []
        params = {"underlying_ticker": ticker, "limit": 1000}
        data = self._get("/v3/reference/options/contracts", params=params)
        seen = set()
        for c in data.get("results", []):
            exp = c.get("expiration_date", "")
            if exp and exp not in seen:
                seen.add(exp)
        # Paginate
        next_url = data.get("next_url")
        while next_url:
            resp = requests.get(next_url, params={"apiKey": self.api_key}, timeout=10)
            resp.raise_for_status()
            page = resp.json()
            for c in page.get("results", []):
                exp = c.get("expiration_date", "")
                if exp and exp not in seen:
                    seen.add(exp)
            next_url = page.get("next_url")
        results = sorted(seen)
        return results

    def get_options_chain(self, ticker: str, expiration: str) -> pd.DataFrame:
        """
        Get options chain for a specific expiration with Greeks via snapshot.

        Args:
            ticker: Stock symbol
            expiration: Date string YYYY-MM-DD

        Returns:
            DataFrame matching TradierProvider interface.
        """
        # Use options snapshot for Greeks
        all_results = []
        params = {"limit": 250}
        data = self._get(f"/v3/snapshot/options/{ticker}", params=params, timeout=30)
        all_results.extend(data.get("results", []))

        next_url = data.get("next_url")
        while next_url:
            resp = requests.get(next_url, params={"apiKey": self.api_key}, timeout=30)
            resp.raise_for_status()
            page = resp.json()
            all_results.extend(page.get("results", []))
            next_url = page.get("next_url")

        rows = []
        for item in all_results:
            details = item.get("details", {})
            exp = details.get("expiration_date", "")
            if exp != expiration:
                continue

            greeks = item.get("greeks", {}) or {}
            day = item.get("day", {}) or {}
            last_quote = item.get("last_quote", {}) or {}
            underlying = item.get("underlying_asset", {}) or {}

            bid = last_quote.get("bid", 0) or 0
            ask = last_quote.get("ask", 0) or 0
            strike = details.get("strike_price", 0)
            opt_type = "call" if details.get("contract_type", "").lower() == "call" else "put"

            rows.append({
                "contract_symbol": details.get("ticker", ""),
                "strike": strike,
                "type": opt_type,
                "bid": bid,
                "ask": ask,
                "last": day.get("close", 0) or 0,
                "volume": day.get("volume", 0) or 0,
                "open_interest": item.get("open_interest", 0) or 0,
                "iv": greeks.get("iv", 0) or item.get("implied_volatility", 0) or 0,
                "delta": abs(greeks.get("delta", 0) or 0),
                "raw_delta": greeks.get("delta", 0) or 0,
                "gamma": greeks.get("gamma", 0) or 0,
                "theta": greeks.get("theta", 0) or 0,
                "vega": greeks.get("vega", 0) or 0,
                "mid": (bid + ask) / 2 if (bid + ask) > 0 else 0,
                "expiration": datetime.strptime(expiration, "%Y-%m-%d"),
                "itm": (strike < underlying.get("price", 0)) if opt_type == "call" else (strike > underlying.get("price", 0)),
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
        logger.info(f"Polygon: {len(df)} options for {ticker} exp {expiration}")
        return df

    def get_full_chain(self, ticker: str, min_dte: int = 25, max_dte: int = 50) -> pd.DataFrame:
        """
        Get full options chain across relevant expirations.
        Fetches snapshot once and filters by DTE.
        """
        now = datetime.now()

        all_results = []
        params = {"limit": 250}
        data = self._get(f"/v3/snapshot/options/{ticker}", params=params, timeout=30)
        all_results.extend(data.get("results", []))

        next_url = data.get("next_url")
        while next_url:
            resp = requests.get(next_url, params={"apiKey": self.api_key}, timeout=30)
            resp.raise_for_status()
            page = resp.json()
            all_results.extend(page.get("results", []))
            next_url = page.get("next_url")

        rows = []
        for item in all_results:
            details = item.get("details", {})
            exp_str = details.get("expiration_date", "")
            if not exp_str:
                continue
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            except ValueError:
                continue
            dte = (exp_date - now).days
            if not (min_dte <= dte <= max_dte):
                continue

            greeks = item.get("greeks", {}) or {}
            day = item.get("day", {}) or {}
            last_quote = item.get("last_quote", {}) or {}
            underlying = item.get("underlying_asset", {}) or {}

            bid = last_quote.get("bid", 0) or 0
            ask = last_quote.get("ask", 0) or 0
            strike = details.get("strike_price", 0)
            opt_type = "call" if details.get("contract_type", "").lower() == "call" else "put"

            rows.append({
                "contract_symbol": details.get("ticker", ""),
                "strike": strike,
                "type": opt_type,
                "bid": bid,
                "ask": ask,
                "last": day.get("close", 0) or 0,
                "volume": day.get("volume", 0) or 0,
                "open_interest": item.get("open_interest", 0) or 0,
                "iv": greeks.get("iv", 0) or item.get("implied_volatility", 0) or 0,
                "delta": abs(greeks.get("delta", 0) or 0),
                "raw_delta": greeks.get("delta", 0) or 0,
                "gamma": greeks.get("gamma", 0) or 0,
                "theta": greeks.get("theta", 0) or 0,
                "vega": greeks.get("vega", 0) or 0,
                "mid": (bid + ask) / 2 if (bid + ask) > 0 else 0,
                "expiration": exp_date,
                "dte": dte,
                "itm": (strike < underlying.get("price", 0)) if opt_type == "call" else (strike > underlying.get("price", 0)),
            })

        if not rows:
            logger.warning(f"No options found for {ticker} in {min_dte}-{max_dte} DTE range")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
        logger.info(f"Polygon: {len(df)} total options for {ticker} ({min_dte}-{max_dte} DTE)")
        return df

    def get_historical(self, ticker: str, days: int = 365) -> pd.DataFrame:
        """Get historical daily bars for technical analysis / IV rank."""
        end = datetime.now()
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
        """Calculate IV rank/percentile using historical volatility as proxy."""
        try:
            hist = self.get_historical(ticker, days=365)
            if hist.empty:
                return {"iv_rank": 0, "iv_percentile": 0, "current_iv": current_iv}

            returns = hist["Close"].pct_change().dropna()
            hv_values = returns.rolling(window=20).std() * np.sqrt(252) * 100
            hv_values = hv_values.dropna()

            if len(hv_values) == 0:
                return {"iv_rank": 0, "iv_percentile": 0, "current_iv": current_iv}

            iv_min = hv_values.min()
            iv_max = hv_values.max()
            iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100 if iv_max > iv_min else 50
            iv_percentile = (hv_values < current_iv).sum() / len(hv_values) * 100

            return {
                "iv_rank": round(float(iv_rank), 2),
                "iv_percentile": round(float(iv_percentile), 2),
                "current_iv": round(current_iv, 2),
                "iv_min_52w": round(float(iv_min), 2),
                "iv_max_52w": round(float(iv_max), 2),
            }
        except Exception as e:
            logger.error(f"Error calculating IV rank for {ticker}: {e}")
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
