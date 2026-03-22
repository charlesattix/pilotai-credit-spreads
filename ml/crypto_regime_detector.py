"""
CryptoRegimeDetector — MA-based regime classifier for crypto ETFs.

Produces a {pd.Timestamp: str} map (BULL/NEUTRAL/BEAR) from price history,
compatible with the self._regime_by_date format consumed by the Backtester.

Design notes:
  - Uses a configurable MA period (default 50) — IBIT data only starts Jul 2024
    so a 200-day MA would eliminate almost all usable history.
  - ±0.5% neutral band around the MA to avoid hairline-cross whipsaws
    (same band width used by ComboRegimeDetector and compass/crypto/regime.py).
  - Warmup period (first ma_period dates) → NEUTRAL (no signal).
  - All signals shifted by 1 day (T-1 close) to prevent lookahead bias.
  - No VIX/RSI dependency — crypto ETF has no reliable VIX analogue in cache.
"""

from __future__ import annotations

import logging
from typing import Dict

import pandas as pd

logger = logging.getLogger(__name__)

# Fraction of MA that defines the neutral band (price within ±BAND of MA → NEUTRAL).
_BAND_PCT = 0.005  # 0.5%


class CryptoRegimeDetector:
    """Compute a BULL/NEUTRAL/BEAR regime series from crypto ETF price data.

    Args:
        config: Regime configuration dict.  Recognised keys:
            ma_period (int, default 50): Rolling MA look-back in trading days.
            neutral_band_pct (float, default 0.5): Band width as a percentage
                (e.g. 0.5 means price must deviate > 0.5% from MA to signal).
    """

    def __init__(self, config: dict) -> None:
        self._ma_period = int(config.get("ma_period", 50))
        band_pct_cfg = config.get("neutral_band_pct", 0.5)
        self._band = float(band_pct_cfg) / 100.0  # convert % to fraction

    def compute_regime_series(
        self, price_data: pd.DataFrame
    ) -> Dict[pd.Timestamp, str]:
        """Build the regime map from a price DataFrame.

        Args:
            price_data: DataFrame with DatetimeIndex and a 'Close' column.
                        Typically spans [data_fetch_start, end_date] including
                        the MA warmup prefix.

        Returns:
            Dict mapping pd.Timestamp → 'BULL' | 'NEUTRAL' | 'BEAR'.
            Keys cover every row in price_data.
        """
        if price_data.empty or "Close" not in price_data.columns:
            logger.warning("CryptoRegimeDetector: empty or missing Close column")
            return {}

        closes = price_data["Close"].copy()

        # Rolling MA, then shift by 1 so today's regime uses yesterday's MA value.
        # This prevents any lookahead — entry decision at 9:30 AM uses T-1 close.
        ma = closes.rolling(window=self._ma_period, min_periods=self._ma_period).mean()
        ma_prev = ma.shift(1)
        closes_prev = closes.shift(1)

        regime_map: Dict[pd.Timestamp, str] = {}

        for ts in price_data.index:
            ma_val = ma_prev.get(ts)
            price_val = closes_prev.get(ts)

            # Warmup: MA not yet computed, or price/MA is NaN
            if pd.isna(ma_val) or pd.isna(price_val) or ma_val == 0:
                regime_map[ts] = "NEUTRAL"
                continue

            deviation = (price_val - ma_val) / ma_val

            if deviation > self._band:
                regime_map[ts] = "BULL"
            elif deviation < -self._band:
                regime_map[ts] = "BEAR"
            else:
                regime_map[ts] = "NEUTRAL"

        bull_count = sum(1 for v in regime_map.values() if v == "BULL")
        bear_count = sum(1 for v in regime_map.values() if v == "BEAR")
        neutral_count = sum(1 for v in regime_map.values() if v == "NEUTRAL")

        logger.info(
            "Crypto regime series built: %d dates, BULL=%d BEAR=%d NEUTRAL=%d "
            "(MA%d, band=±%.1f%%)",
            len(regime_map),
            bull_count,
            bear_count,
            neutral_count,
            self._ma_period,
            self._band * 100,
        )

        return regime_map
