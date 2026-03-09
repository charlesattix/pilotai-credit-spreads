"""
AlertPositionSizer — calculates contract count for approved alert opportunities.

Implements flat-risk sizing that matches backtester.py sizing logic (exp_154):
  - Directional spreads (bull_put / bear_call): max_risk_per_trade% of starting_capital
  - Iron condors: ic_risk_per_trade% of starting_capital (separate budget, default 12%)
  - Sizing mode: 'flat' uses starting_capital as base; 'compound' uses current equity
  - VIX dynamic scaling (optional): reduces size at elevated VIX

Portfolio mode (compass_portfolio_mode: true):
  - Capital is split per-ticker based on compass.portfolio_weights config
  - SPY gets compass.portfolio_weights.spy_pct of total capital
  - Sector ETFs split compass.portfolio_weights.sector_pct evenly among active sectors
  - Macro score scaling: score < 45 → 1.2× size; score > 75 → 0.85× size
  - Per-ticker max_contracts is derived from the ticker's capital allocation

Backward compatibility: if config is not injected at construction, falls back to the
legacy IV-rank dynamic sizer (original behaviour for exp_036/exp_059).
"""

import logging
from typing import Optional

from alerts.alert_schema import Alert, SizeResult

# Module-level import for testability (allows unittest.mock.patch to replace it)
try:
    from shared.macro_state_db import get_current_macro_score
except ImportError:  # pragma: no cover
    def get_current_macro_score():  # type: ignore[misc]
        return 50.0

logger = logging.getLogger(__name__)

# Legacy fallback (used when no config injected)
_LEGACY_MAX_CONTRACTS = 5
_LEGACY_BASE_RISK_PCT = 0.02

# Macro score thresholds for position size scaling (COMPASS portfolio mode)
_MACRO_FEAR_THRESHOLD = 45    # score < this → boost size 1.2×
_MACRO_GREED_THRESHOLD = 75   # score > this → reduce size 0.85×
_MACRO_FEAR_SCALE = 1.20
_MACRO_GREED_SCALE = 0.85


class AlertPositionSizer:
    """Account-aware position sizer for the alert pipeline.

    Args:
        config: Full application config dict. If None, uses legacy IV-rank sizer.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config

    def size(
        self,
        alert: Alert,
        account_value: float,
        iv_rank: float,
        current_portfolio_risk: float,
        weekly_loss_breach: bool = False,
        macro_score: Optional[float] = None,
        rrg_quadrant: Optional[str] = None,
    ) -> SizeResult:
        """Calculate position size for an alert.

        When compass_portfolio_mode is enabled, routes to portfolio-aware sizing.
        If config is available but portfolio mode is off, uses flat 5%/12% risk.
        Otherwise falls back to legacy IV-rank dynamic sizing.

        Args:
            alert: The candidate alert.
            account_value: Current account balance in dollars.
            iv_rank: Current IV Rank 0–100 (used by legacy sizer only).
            current_portfolio_risk: Dollar value of open max-loss exposure.
            weekly_loss_breach: If True, cut size by 50%.
            macro_score: COMPASS macro score 0–100. When provided and portfolio
                         mode is enabled, used for fear/greed position scaling.
                         If None, the sizer will attempt to read from macro_state.db.
            rrg_quadrant: RRG quadrant for the underlying (unused currently,
                          reserved for future directional bias scaling).

        Returns:
            SizeResult with risk_pct, contracts, dollar_risk, max_loss.
        """
        if not self.config:
            return self._legacy_size(alert, account_value, iv_rank, current_portfolio_risk, weekly_loss_breach)

        compass_cfg = self.config.get("compass", {})
        if compass_cfg.get("portfolio_mode", False):
            return self._portfolio_risk_size(
                alert, account_value, weekly_loss_breach, macro_score
            )

        return self._flat_risk_size(alert, account_value, weekly_loss_breach)

    # ------------------------------------------------------------------
    # Portfolio-mode sizing (COMPASS multi-underlying)
    # ------------------------------------------------------------------

    def _portfolio_risk_size(
        self,
        alert: Alert,
        account_value: float,
        weekly_loss_breach: bool,
        macro_score: Optional[float],
    ) -> SizeResult:
        """Portfolio-aware sizing: per-ticker capital allocation + macro scaling.

        Allocation logic:
          - SPY: `compass.portfolio_weights.spy_pct` × account_value
          - Sector ETF: `compass.portfolio_weights.sector_pct` / n_active_sectors
            × account_value
          - Unlisted ticker: falls back to flat_risk_size
        """
        compass_cfg = self.config.get("compass", {})
        weights_cfg = compass_cfg.get("portfolio_weights", {})
        risk_cfg = self.config.get("risk", {})
        strategy_cfg = self.config.get("strategy", {})
        backtest_cfg = self.config.get("backtest", {})

        ticker = alert.ticker.upper()

        # Resolve ticker's allocation weight
        spy_pct = float(weights_cfg.get("spy_pct", 0.60))
        sector_pct = float(weights_cfg.get("sector_pct", 0.40))

        # Active sectors list (from config; CC1 populates this at scan time)
        active_sectors = [s.upper() for s in compass_cfg.get("active_sectors", [])]

        # Per-ticker weight
        if ticker == "SPY":
            allocation_weight = spy_pct
        elif ticker in active_sectors and len(active_sectors) > 0:
            allocation_weight = sector_pct / len(active_sectors)
        else:
            # Unknown ticker — fall back to flat sizing
            logger.warning(
                "AlertPositionSizer (portfolio): %s not in active_sectors %s, "
                "falling back to flat sizing",
                ticker, active_sectors,
            )
            return self._flat_risk_size(alert, account_value, weekly_loss_breach)

        # Account base for this ticker's allocation
        account_base = account_value * allocation_weight

        # Sizing mode (flat vs compound)
        sizing_mode = risk_cfg.get("sizing_mode", "flat")
        if sizing_mode == "flat":
            starting_capital = float(
                backtest_cfg.get("starting_capital", risk_cfg.get("account_size", 100_000))
            )
            account_base = starting_capital * allocation_weight

        # Detect iron condor
        is_ic = alert.type.value == "iron_condor" or "condor" in str(alert.type).lower()

        # Risk % per trade (same as flat mode — applied to the allocated slice)
        if is_ic:
            ic_cfg = strategy_cfg.get("iron_condor", {})
            raw_risk_pct = float(ic_cfg.get("ic_risk_per_trade", 12.0)) / 100.0
        else:
            raw_risk_pct = float(risk_cfg.get("max_risk_per_trade", 5.0)) / 100.0

        # Macro score scaling
        effective_risk_pct = raw_risk_pct * self._macro_scale(macro_score)

        # Weekly loss breach → 50% reduction
        if weekly_loss_breach:
            effective_risk_pct *= 0.5
            logger.info(
                "AlertPositionSizer (portfolio): 50%% size reduction (weekly loss breach)"
            )

        dollar_risk = account_base * effective_risk_pct

        # Spread geometry
        spread_width, credit = self._extract_spread_params(alert)
        if is_ic:
            # IC max loss = one wing's width minus combined credit.
            # Both wings cannot lose simultaneously; only one can be ITM at expiry.
            max_loss_per_spread = max((spread_width - credit) * 100, 1.0)
        else:
            max_loss_per_spread = max((spread_width - credit) * 100, 1.0)

        contracts = int(dollar_risk / max_loss_per_spread) if max_loss_per_spread > 0 else 1

        # Contract caps: global config cap and per-ticker allocation cap
        min_contracts = int(risk_cfg.get("min_contracts", 1))
        global_max = int(risk_cfg.get("max_contracts", 25))

        # Per-ticker max_contracts derived from full account allocation budget
        # (allocation_budget / max_loss_per_spread, rounded down)
        full_allocation_budget = account_value * allocation_weight
        ticker_max_contracts = int(full_allocation_budget / max_loss_per_spread) if max_loss_per_spread > 0 else global_max
        effective_max = min(global_max, ticker_max_contracts)

        contracts = max(min_contracts, min(contracts, effective_max))

        actual_dollar_risk = contracts * max_loss_per_spread
        actual_risk_pct = actual_dollar_risk / account_base if account_base > 0 else 0.0
        max_loss = actual_dollar_risk

        logger.info(
            "AlertPositionSizer (portfolio): %s %s | alloc=%.1f%% base=$%.0f "
            "risk=%.1f%% macro_scale=%.2f → %d contracts ($%.0f max loss)",
            ticker, alert.type.value,
            allocation_weight * 100, account_base,
            raw_risk_pct * 100,
            self._macro_scale(macro_score),
            contracts, max_loss,
        )

        return SizeResult(
            risk_pct=actual_risk_pct,
            contracts=contracts,
            dollar_risk=actual_dollar_risk,
            max_loss=max_loss,
        )

    def _macro_scale(self, macro_score: Optional[float]) -> float:
        """Return position size scalar based on macro score.

        If macro_score is None, attempts to read from macro_state.db.
        Falls back to 1.0 (no scaling) on any error.

        Returns:
            1.2 (fear boost) if score < 45
            0.85 (greed reduction) if score > 75
            1.0 (neutral) otherwise
        """
        score = macro_score
        if score is None:
            try:
                score = get_current_macro_score()
            except Exception as e:
                logger.debug("AlertPositionSizer: macro score fetch failed: %s", e)
                return 1.0

        if score < _MACRO_FEAR_THRESHOLD:
            logger.info(
                "AlertPositionSizer: macro_score=%.1f < %d → fear boost ×%.2f",
                score, _MACRO_FEAR_THRESHOLD, _MACRO_FEAR_SCALE,
            )
            return _MACRO_FEAR_SCALE
        if score > _MACRO_GREED_THRESHOLD:
            logger.info(
                "AlertPositionSizer: macro_score=%.1f > %d → greed reduction ×%.2f",
                score, _MACRO_GREED_THRESHOLD, _MACRO_GREED_SCALE,
            )
            return _MACRO_GREED_SCALE
        return 1.0

    # ------------------------------------------------------------------
    # Flat-risk sizing (exp_154 / backtest-parity mode)
    # ------------------------------------------------------------------

    def _flat_risk_size(self, alert: Alert, account_value: float, weekly_loss_breach: bool) -> SizeResult:
        """Flat-risk sizing matching backtester.py logic."""
        risk_cfg = self.config.get("risk", {})
        strategy_cfg = self.config.get("strategy", {})
        backtest_cfg = self.config.get("backtest", {})

        # Sizing base: flat uses starting_capital, compound uses current equity
        sizing_mode = risk_cfg.get("sizing_mode", "flat")
        starting_capital = float(backtest_cfg.get("starting_capital", risk_cfg.get("account_size", 100_000)))
        account_base = starting_capital if sizing_mode == "flat" else account_value

        # Detect iron condor
        is_ic = alert.type.value == "iron_condor" or "condor" in str(alert.type).lower()

        # Risk % per trade
        if is_ic:
            ic_cfg = strategy_cfg.get("iron_condor", {})
            raw_risk_pct = float(ic_cfg.get("ic_risk_per_trade", 12.0)) / 100.0
        else:
            raw_risk_pct = float(risk_cfg.get("max_risk_per_trade", 5.0)) / 100.0

        # VIX dynamic scaling (optional — only if vix_dynamic_sizing configured)
        vix_scale = 1.0
        vix_sizing_cfg = strategy_cfg.get("vix_dynamic_sizing", {})
        if vix_sizing_cfg:
            current_vix = self._get_current_vix()
            vix_scale = self._compute_vix_scale(current_vix, vix_sizing_cfg)
            if vix_scale == 0.0:
                logger.info("AlertPositionSizer: VIX scaling blocked entry (scale=0)")
                return SizeResult(risk_pct=0.0, contracts=0, dollar_risk=0.0, max_loss=0.0)

        effective_risk_pct = raw_risk_pct * vix_scale

        # Weekly loss breach → 50% reduction
        if weekly_loss_breach:
            effective_risk_pct *= 0.5
            logger.info("AlertPositionSizer: 50%% size reduction (weekly loss breach)")

        dollar_risk = account_base * effective_risk_pct

        # Spread geometry
        spread_width, credit = self._extract_spread_params(alert)
        if is_ic:
            # IC max loss = one wing's width minus combined credit.
            # Both wings cannot lose simultaneously; only one can be ITM at expiry.
            max_loss_per_spread = max((spread_width - credit) * 100, 1.0)
        else:
            max_loss_per_spread = max((spread_width - credit) * 100, 1.0)

        contracts = int(dollar_risk / max_loss_per_spread) if max_loss_per_spread > 0 else 1

        # Config limits — max_contracts from config (not hardcoded)
        min_contracts = int(risk_cfg.get("min_contracts", 1))
        max_contracts = int(risk_cfg.get("max_contracts", 25))
        contracts = max(min_contracts, min(contracts, max_contracts))

        actual_dollar_risk = contracts * max_loss_per_spread
        actual_risk_pct = actual_dollar_risk / account_base if account_base > 0 else 0.0
        max_loss = actual_dollar_risk

        logger.debug(
            "AlertPositionSizer: %s %s | base=$%.0f risk=%.1f%% (×%.2f vix_scale) "
            "width=$%.0f credit=%.4f → %d contracts ($%.0f max loss)",
            alert.ticker, alert.type.value, account_base, raw_risk_pct * 100, vix_scale,
            spread_width, credit, contracts, max_loss,
        )

        return SizeResult(
            risk_pct=actual_risk_pct,
            contracts=contracts,
            dollar_risk=actual_dollar_risk,
            max_loss=max_loss,
        )

    def _get_current_vix(self) -> float:
        """Fetch current VIX from data cache."""
        try:
            from shared.data_cache import DataCache
            cache = DataCache()
            vix_data = cache.get_history("^VIX", period="5d")
            if not vix_data.empty:
                return float(vix_data["Close"].iloc[-1])
        except Exception as e:
            logger.warning("AlertPositionSizer: VIX fetch failed, using default 20: %s", e)
        return 20.0

    @staticmethod
    def _compute_vix_scale(vix: float, vix_cfg: dict) -> float:
        """Return position size scalar based on VIX level.

        Returns 1.0 (full), 0.5 (half), 0.25 (quarter), or 0.0 (block).
        """
        full_below = float(vix_cfg.get("full_below", 18))
        half_below = float(vix_cfg.get("half_below", 22))
        quarter_below = float(vix_cfg.get("quarter_below", 25))

        if vix < full_below:
            return 1.0
        elif vix < half_below:
            return 0.5
        elif vix < quarter_below:
            return 0.25
        else:
            return 0.0  # Block entries at extreme VIX

    # ------------------------------------------------------------------
    # Legacy IV-rank dynamic sizer (backward compat for exp_036/exp_059)
    # ------------------------------------------------------------------

    def _legacy_size(
        self,
        alert: Alert,
        account_value: float,
        iv_rank: float,
        current_portfolio_risk: float,
        weekly_loss_breach: bool,
    ) -> SizeResult:
        """Original IV-rank based dynamic sizing (pre-exp_154)."""
        from shared.constants import MAX_RISK_PER_TRADE
        from ml.position_sizer import calculate_dynamic_risk, get_contract_size

        dollar_risk = calculate_dynamic_risk(account_value, iv_rank, current_portfolio_risk)

        hard_cap = MAX_RISK_PER_TRADE * account_value
        dollar_risk = min(dollar_risk, hard_cap)

        if weekly_loss_breach:
            dollar_risk *= 0.5
            logger.info("AlertPositionSizer [legacy]: 50%% size reduction (weekly loss breach)")

        risk_pct = dollar_risk / account_value if account_value > 0 else 0.0
        spread_width, credit = self._extract_spread_params(alert)
        contracts = get_contract_size(dollar_risk, spread_width, credit)

        max_loss_per_contract = (spread_width - credit) * 100
        max_loss = max_loss_per_contract * contracts

        return SizeResult(
            risk_pct=risk_pct,
            contracts=contracts,
            dollar_risk=dollar_risk,
            max_loss=max_loss,
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_spread_params(alert: Alert) -> tuple:
        """Derive (spread_width, credit) from the alert legs.

        Returns dollar-per-share values.
        """
        credit = alert.entry_price

        if len(alert.legs) >= 2:
            strikes = sorted(leg.strike for leg in alert.legs)
            if len(alert.legs) == 4:
                put_strikes = sorted(
                    leg.strike for leg in alert.legs if leg.option_type == "put"
                )
                call_strikes = sorted(
                    leg.strike for leg in alert.legs if leg.option_type == "call"
                )
                put_width = (put_strikes[-1] - put_strikes[0]) if len(put_strikes) >= 2 else 0
                call_width = (call_strikes[-1] - call_strikes[0]) if len(call_strikes) >= 2 else 0
                spread_width = max(put_width, call_width)
            else:
                spread_width = strikes[-1] - strikes[0]
        else:
            spread_width = 5.0  # fallback

        if spread_width <= 0:
            spread_width = 5.0

        return spread_width, credit
