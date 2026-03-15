"""
combo_regime_detector.py — Multi-signal regime detector v2 for credit spread direction filter.

v2 Architecture (Phase 6 revised):
  Three genuinely uncorrelated signals replace the correlated v1 trio (MA50+MA200+VIX spot):
    1. price_vs_ma200  — trend anchor (price vs 200-day MA, prior day, with confidence band)
    2. rsi_momentum    — RSI(14) momentum (prior day, no new data needed)
    3. vix_structure   — VIX/VIX3M term structure ratio (backwardation = stress)

Asymmetric voting rule:
  bull_votes >= 2 → BULL   (2/3 consensus, biased toward safe default)
  bear_votes == 3 → BEAR   (unanimous, only enter bear when all signals agree)
  else            → NEUTRAL (bull puts allowed; conservative in uncertain environments)

Additional safeguards:
  - Hysteresis: cooldown_days before any regime change is accepted
  - VIX circuit breaker: VIX > vix_extreme → force BEAR (bypasses hysteresis)
  - MA200 confidence band: price within ±0.5% of MA200 → MA200 abstains

Regime → strategy mapping (applied to ALL experiments regardless of direction config):
  BULL    → allow bull puts; bear calls blocked
  BEAR    → allow bear calls; bull puts blocked
  NEUTRAL → allow bull puts; conservative default for uncertain environments
"""

import logging
from typing import Dict

import pandas as pd

logger = logging.getLogger(__name__)


class ComboRegimeDetector:
    """Rule-based multi-signal regime classifier v2.

    Supported signals (VALID_SIGNALS):
      price_vs_ma200 — price above/below 200-day MA with confidence band
      rsi_momentum   — RSI(14) directional momentum
      vix_structure  — VIX/VIX3M term structure ratio (contango=BULL, backwardation=BEAR)
      ma_crossover   — MA50 > MA200 golden/death cross (optional; not in default set)
    """

    VALID_SIGNALS = frozenset(['price_vs_ma200', 'rsi_momentum', 'vix_structure', 'ma_crossover'])

    def __init__(self, config: dict):
        self.signals            = config.get('signals', ['price_vs_ma200', 'rsi_momentum', 'vix_structure'])
        self.ma_slow            = int(config.get('ma_slow_period', 200))
        self.ma200_neutral_pct  = float(config.get('ma200_neutral_band_pct', 0.5)) / 100
        self.rsi_period         = int(config.get('rsi_period', 14))
        self.rsi_bull           = float(config.get('rsi_bull_threshold', 55.0))
        self.rsi_bear           = float(config.get('rsi_bear_threshold', 45.0))
        self.vix_struct_bull    = float(config.get('vix_structure_bull', 0.95))
        self.vix_struct_bear    = float(config.get('vix_structure_bear', 1.05))
        self.bear_unanimous     = bool(config.get('bear_requires_unanimous', True))
        self.cooldown_days      = int(config.get('cooldown_days', 10))
        self.vix_extreme        = float(config.get('vix_extreme', 40.0))

        # ma_crossover needs fast MA period
        self.ma_fast            = int(config.get('ma_fast_period', 50))

        unknown = set(self.signals) - self.VALID_SIGNALS
        if unknown:
            logger.warning("Unknown combo regime signals (ignored): %s", unknown)
        self.signals = [s for s in self.signals if s in self.VALID_SIGNALS]

    def compute_regime_series(
        self,
        price_data: pd.DataFrame,
        vix_by_date: dict,
        vix3m_by_date: dict = None,
    ) -> Dict[pd.Timestamp, str]:
        """Compute regime label for each date in price_data.

        Args:
            price_data:    DataFrame with 'Close' column and DatetimeIndex.
                           Must include MA warmup prefix (MA_SLOW extra days before
                           the backtest start so early dates have valid MAs).
            vix_by_date:   {pd.Timestamp: float} raw VIX closes.
            vix3m_by_date: {pd.Timestamp: float} raw VIX3M closes (optional).
                           If None or empty, vix_structure signal abstains.

        Returns:
            {pd.Timestamp: 'BULL' | 'BEAR' | 'NEUTRAL'} for every date in price_data.

        Lookahead handling:
            All series are shifted by 1 so regime on date T uses data through T-1.
        """
        if vix3m_by_date is None:
            vix3m_by_date = {}

        closes = price_data['Close']

        # --- Pre-compute all signal series (efficient: once, not per date) ---

        # MA200 (and optionally MA50 for ma_crossover)
        ma_slow_series = closes.rolling(
            self.ma_slow, min_periods=max(10, self.ma_slow // 2)
        ).mean()
        ma_slow_prev = ma_slow_series.shift(1)

        ma_fast_prev = None
        if 'ma_crossover' in self.signals:
            ma_fast_series = closes.rolling(
                self.ma_fast, min_periods=max(10, self.ma_fast // 2)
            ).mean()
            ma_fast_prev = ma_fast_series.shift(1)

        # RSI(14) using EMA-smoothed formula (standard Wilder's RSI)
        delta = closes.diff()
        gain = delta.clip(lower=0).ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        rsi_series = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))
        rsi_prev = rsi_series.shift(1)

        # VIX/VIX3M ratio — convert dicts to Series aligned with price_data index
        vix_series = pd.Series(vix_by_date, dtype=float).reindex(price_data.index)
        vix3m_series = pd.Series(vix3m_by_date, dtype=float).reindex(price_data.index) if vix3m_by_date else pd.Series(index=price_data.index, dtype=float)
        # Forward-fill to handle weekends/gaps, then shift for no-lookahead
        vix_prev = vix_series.ffill().shift(1)
        vix3m_prev = vix3m_series.ffill().shift(1)
        vix_ratio_prev = vix_prev / vix3m_prev  # NaN when either is missing → abstain

        # --- Iterate with hysteresis state ---
        current_regime = 'BULL'      # default starting regime (optimistic prior)
        last_change_idx = -1         # index of last regime change (-1 = never changed)
        n_signals = len(self.signals)
        bear_required = n_signals if self.bear_unanimous else 2

        # closes_prev: yesterday's close — used for price_vs_ma200 to keep the comparison
        # look-ahead-free (regime on date T must only use data available through T-1).
        closes_prev = closes.shift(1)

        result: Dict[pd.Timestamp, str] = {}

        for idx, ts in enumerate(price_data.index):
            price = float(closes_prev.loc[ts])  # yesterday's close (no look-ahead)
            ma_s = ma_slow_prev.loc[ts]
            ma_f = ma_fast_prev.loc[ts] if ma_fast_prev is not None else float('nan')
            rsi = rsi_prev.loc[ts]
            vix_val = vix_prev.loc[ts]
            vix_ratio = vix_ratio_prev.loc[ts]

            # --- VIX circuit breaker (overrides hysteresis) ---
            if not pd.isna(vix_val) and vix_val > self.vix_extreme:
                result[ts] = 'BEAR'
                if current_regime != 'BEAR':
                    current_regime = 'BEAR'
                    last_change_idx = idx
                continue

            # --- Vote ---
            bull_votes, bear_votes = self._vote(price, ma_s, ma_f, rsi, vix_ratio)

            # --- Determine raw regime ---
            if bull_votes >= 2:
                raw_regime = 'BULL'
            elif bear_votes >= bear_required:
                raw_regime = 'BEAR'
            else:
                raw_regime = 'NEUTRAL'

            # --- Apply hysteresis ---
            if raw_regime != current_regime:
                days_since_change = idx - last_change_idx
                if last_change_idx >= 0 and days_since_change < self.cooldown_days:
                    # Hysteresis active: keep current regime
                    result[ts] = current_regime
                    continue
                # Accept the change
                current_regime = raw_regime
                last_change_idx = idx

            result[ts] = current_regime

        return result

    def _vote(
        self,
        price: float,
        ma_slow: float,
        ma_fast: float,
        rsi: float,
        vix_ratio: float,
    ):
        """Count bull and bear votes from active signals.

        Returns:
            (bull_votes, bear_votes) — int counts; abstains counted in neither.
        """
        bull = 0
        bear = 0

        for signal in self.signals:
            if signal == 'price_vs_ma200':
                if pd.isna(ma_slow):
                    continue  # insufficient warmup — abstain
                band = ma_slow * self.ma200_neutral_pct
                if price > ma_slow + band:
                    bull += 1
                elif price < ma_slow - band:
                    bear += 1
                # else: within confidence band → abstain

            elif signal == 'rsi_momentum':
                if pd.isna(rsi):
                    continue
                if rsi > self.rsi_bull:
                    bull += 1
                elif rsi < self.rsi_bear:
                    bear += 1
                # else: neutral momentum zone (45–55) → abstain

            elif signal == 'vix_structure':
                if pd.isna(vix_ratio):
                    continue  # missing VIX3M data → abstain gracefully
                if vix_ratio < self.vix_struct_bull:
                    bull += 1   # contango: VIX < VIX3M → market expects calm
                elif vix_ratio > self.vix_struct_bear:
                    bear += 1   # backwardation: VIX > VIX3M → market expects sustained stress

            elif signal == 'ma_crossover':
                if pd.isna(ma_fast) or pd.isna(ma_slow):
                    continue
                if ma_fast > ma_slow:
                    bull += 1   # golden cross
                else:
                    bear += 1   # death cross

        return bull, bear
