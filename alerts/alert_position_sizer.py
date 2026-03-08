"""
AlertPositionSizer — calculates contract count for approved alert opportunities.

Implements flat-risk sizing that matches backtester.py sizing logic (exp_154):
  - Directional spreads (bull_put / bear_call): max_risk_per_trade% of starting_capital
  - Iron condors: ic_risk_per_trade% of starting_capital (separate budget, default 12%)
  - Sizing mode: 'flat' uses starting_capital as base; 'compound' uses current equity
  - VIX dynamic scaling (optional): reduces size at elevated VIX

Backward compatibility: if config is not injected at construction, falls back to the
legacy IV-rank dynamic sizer (original behaviour for exp_036/exp_059).
"""

import logging
from typing import Optional

from alerts.alert_schema import Alert, SizeResult

logger = logging.getLogger(__name__)

# Legacy fallback (used when no config injected)
_LEGACY_MAX_CONTRACTS = 5
_LEGACY_BASE_RISK_PCT = 0.02


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
    ) -> SizeResult:
        """Calculate position size for an alert.

        If config is available, uses flat 5%/12% risk from config.
        Otherwise falls back to legacy IV-rank dynamic sizing for backward compat.

        Args:
            alert: The candidate alert.
            account_value: Current account balance in dollars.
            iv_rank: Current IV Rank 0–100 (used by legacy sizer only).
            current_portfolio_risk: Dollar value of open max-loss exposure.
            weekly_loss_breach: If True, cut size by 50%.

        Returns:
            SizeResult with risk_pct, contracts, dollar_risk, max_loss.
        """
        if self.config:
            return self._flat_risk_size(alert, account_value, weekly_loss_breach)
        else:
            return self._legacy_size(alert, account_value, iv_rank, current_portfolio_risk, weekly_loss_breach)

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
            # IC max loss = 2 × spread_width − combined_credit (both wings ITM simultaneously)
            max_loss_per_spread = max((spread_width * 2 - credit) * 100, 1.0)
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
