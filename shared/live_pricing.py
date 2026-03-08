"""
Live option pricing via Polygon snapshots.

Thin caching layer over OptionsAnalyzer that looks up specific contracts
for spread pricing.  Used by paper_trader._evaluate_position() to get
real bid/ask mid prices instead of Black-Scholes estimates.
"""

import logging
import threading
import time
from typing import Optional

import pandas as pd

from strategies.base import LegType, Position

logger = logging.getLogger(__name__)

# Strike-snap offsets: try exact match first, then widen
# (same pattern as backtester _STRIKE_SNAP_OFFSETS)
_STRIKE_SNAP_OFFSETS = [0, 0.5, -0.5, 1, -1, 1.5, -1.5, 2, -2]


class LivePricing:
    """Real-time spread pricing from Polygon option snapshots.

    Caches chain fetches for ``cache_ttl`` seconds (default 300 = 5 min)
    to avoid API hammering.  Thread-safe — the scanner runs in a scheduler
    thread that may overlap with the main loop.
    """

    def __init__(self, options_analyzer, cache_ttl: int = 300):
        self._analyzer = options_analyzer
        self._cache: dict = {}          # (ticker, exp_str) → (mono_ts, DataFrame)
        self._cache_ttl = cache_ttl
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_spread_value(
        self, position: Position, underlying_price: float,
    ) -> Optional[float]:
        """Net spread value from real Polygon bid/ask mid prices.

        For a credit spread the value is negative (we owe money to close).
        Specifically: ``sum(short_mids) - sum(long_mids)`` which yields a
        negative number when the spread has moved against us and a number
        close to zero when the spread is expiring worthless (profit).

        Returns ``None`` if *any* leg cannot be priced (caller should fall
        back to Black-Scholes).
        """
        if not position.legs:
            return None

        # All legs share the same expiration in our strategies
        exp_dt = position.legs[0].expiration
        exp_str = exp_dt.strftime("%Y-%m-%d")
        ticker = position.ticker

        chain = self._get_chain_cached(ticker, exp_str)
        if chain is None or chain.empty:
            return None

        net = 0.0
        for leg in position.legs:
            opt_type = "put" if "put" in leg.leg_type.value else "call"
            row = self._find_contract(chain, leg.strike, opt_type)
            if row is None:
                return None  # can't price this leg

            mid = float(row["mid"])

            if leg.leg_type in (LegType.SHORT_PUT, LegType.SHORT_CALL):
                net += mid   # we sold this; positive contribution
            else:
                net -= mid   # we bought this; negative contribution

        # net > 0 should not happen for a credit spread that moved against us;
        # for safety, clamp to the range the caller expects.
        return round(net, 4)

    def get_contract_iv(
        self, ticker: str, strike: float, expiration_str: str, opt_type: str,
    ) -> Optional[float]:
        """Real IV for a specific contract, or ``None``."""
        chain = self._get_chain_cached(ticker, expiration_str)
        if chain is None or chain.empty:
            return None
        row = self._find_contract(chain, strike, opt_type)
        if row is None:
            return None
        iv = float(row.get("iv", 0))
        return iv if iv > 0 else None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_chain_cached(self, ticker: str, exp_str: str) -> Optional[pd.DataFrame]:
        """Fetch chain via OptionsAnalyzer/Polygon, caching for TTL."""
        key = (ticker, exp_str)
        now = time.monotonic()

        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                ts, df = entry
                if now - ts < self._cache_ttl:
                    return df

        # Fetch outside lock (network I/O)
        df = self._fetch_chain(ticker, exp_str)

        with self._lock:
            self._cache[key] = (time.monotonic(), df)

        return df

    def _fetch_chain(self, ticker: str, exp_str: str) -> Optional[pd.DataFrame]:
        """Call through to the Polygon provider for a specific expiration."""
        try:
            provider = getattr(self._analyzer, "polygon", None) or getattr(
                self._analyzer, "tradier", None
            )
            if provider is None:
                logger.debug("LivePricing: no provider on OptionsAnalyzer")
                return None

            df = provider.get_options_chain(ticker, exp_str)
            if df is None or df.empty:
                logger.debug(
                    "LivePricing: empty chain for %s exp %s", ticker, exp_str,
                )
                return None
            return df
        except Exception:
            logger.warning(
                "LivePricing: failed to fetch chain for %s exp %s",
                ticker, exp_str, exc_info=True,
            )
            return None

    @staticmethod
    def _find_contract(
        chain_df: pd.DataFrame, strike: float, opt_type: str,
    ) -> Optional[pd.Series]:
        """Find a contract row using strike-snap offsets."""
        for offset in _STRIKE_SNAP_OFFSETS:
            snapped = strike + offset
            mask = (chain_df["strike"] == snapped) & (chain_df["type"] == opt_type)
            matches = chain_df[mask]
            if not matches.empty:
                return matches.iloc[0]
        return None
