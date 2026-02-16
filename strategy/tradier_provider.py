"""
Tradier Data Provider
Real-time options chains with actual Greeks from ORATS.
Sandbox: https://sandbox.tradier.com/v1/
Production: https://api.tradier.com/v1/
"""

import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from shared.exceptions import ProviderError

logger = logging.getLogger(__name__)

SANDBOX_URL = "https://sandbox.tradier.com/v1"
PROD_URL = "https://api.tradier.com/v1"


class TradierProvider:
    """Real-time options data via Tradier API."""

    def __init__(self, api_key: str, sandbox: bool = True):
        self.api_key = api_key
        self.base_url = SANDBOX_URL if sandbox else PROD_URL
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], backoff_jitter=0.25)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        logger.info(f"TradierProvider initialized ({'sandbox' if sandbox else 'production'})")

    def get_quote(self, ticker: str) -> Dict:
        """Get real-time quote for a ticker."""
        url = f"{self.base_url}/markets/quotes"
        params = {"symbols": ticker, "greeks": "false"}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ProviderError(f"Tradier quote request failed for {ticker}: {e}") from e
        data = resp.json()
        quote = data.get("quotes", {}).get("quote", {})
        return quote

    def get_expirations(self, ticker: str) -> List[str]:
        """Get available option expiration dates."""
        url = f"{self.base_url}/markets/options/expirations"
        params = {"symbol": ticker, "includeAllRoots": "true", "strikes": "false"}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ProviderError(f"Tradier expirations request failed for {ticker}: {e}") from e
        data = resp.json()
        expirations = data.get("expirations", {})
        if expirations is None:
            return []
        dates = expirations.get("date", [])
        if isinstance(dates, str):
            dates = [dates]
        return dates

    def get_options_chain(self, ticker: str, expiration: str) -> pd.DataFrame:
        """
        Get options chain for a specific expiration with real Greeks.
        
        Args:
            ticker: Stock symbol
            expiration: Date string YYYY-MM-DD
            
        Returns:
            DataFrame with columns: strike, type, bid, ask, last, volume, 
            open_interest, iv, delta, gamma, theta, vega, mid, expiration
        """
        url = f"{self.base_url}/markets/options/chains"
        params = {
            "symbol": ticker,
            "expiration": expiration,
            "greeks": "true",
        }
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ProviderError(f"Tradier options chain request failed for {ticker}: {e}") from e
        data = resp.json()

        options = data.get("options", {})
        if options is None:
            return pd.DataFrame()
        
        option_list = options.get("option", [])
        if isinstance(option_list, dict):
            option_list = [option_list]
        if not option_list:
            return pd.DataFrame()

        rows = []
        for opt in option_list:
            greeks = opt.get("greeks") or {}
            rows.append({
                "contract_symbol": opt.get("symbol", ""),
                "strike": opt.get("strike", 0),
                "type": "call" if opt.get("option_type") == "call" else "put",
                "bid": opt.get("bid", 0) or 0,
                "ask": opt.get("ask", 0) or 0,
                "last": opt.get("last", 0) or 0,
                "volume": opt.get("volume", 0) or 0,
                "open_interest": opt.get("open_interest", 0) or 0,
                "iv": greeks.get("mid_iv", 0) or 0,
                "delta": greeks.get("delta", 0) or 0,
                "raw_delta": greeks.get("delta", 0) or 0,
                "gamma": greeks.get("gamma", 0) or 0,
                "theta": greeks.get("theta", 0) or 0,
                "vega": greeks.get("vega", 0) or 0,
                "mid": ((opt.get("bid", 0) or 0) + (opt.get("ask", 0) or 0)) / 2,
                "expiration": datetime.strptime(expiration, "%Y-%m-%d"),
                "itm": opt.get("strike", 0) < opt.get("last", 0) if opt.get("option_type") == "call" else opt.get("strike", 0) > opt.get("last", 0),
            })

        df = pd.DataFrame(rows)
        # Filter out zero bid/ask
        df = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
        
        logger.info(f"Tradier: {len(df)} options for {ticker} exp {expiration}")
        return df

    def get_full_chain(self, ticker: str, min_dte: int = 25, max_dte: int = 50) -> pd.DataFrame:
        """
        Get full options chain across relevant expirations.
        
        Args:
            ticker: Stock symbol
            min_dte: Minimum days to expiration
            max_dte: Maximum days to expiration
            
        Returns:
            Combined DataFrame of all relevant expirations
        """
        expirations = self.get_expirations(ticker)
        now = datetime.now()
        
        all_chains = []
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            dte = (exp_date - now).days
            
            if min_dte <= dte <= max_dte:
                chain = self.get_options_chain(ticker, exp_str)
                if not chain.empty:
                    chain["dte"] = dte
                    all_chains.append(chain)

        if not all_chains:
            logger.warning(f"No options found for {ticker} in {min_dte}-{max_dte} DTE range")
            return pd.DataFrame()

        result = pd.concat(all_chains, ignore_index=True)
        logger.info(f"Tradier: {len(result)} total options for {ticker} ({min_dte}-{max_dte} DTE)")
        return result
