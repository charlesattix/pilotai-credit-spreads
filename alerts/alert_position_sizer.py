"""
Alert-aware position sizer.

Wraps the standalone functions in ``ml/position_sizer.py``
(``calculate_dynamic_risk`` and ``get_contract_size``) with account-level
caps from the MASTERPLAN.
"""

import logging

from shared.constants import MAX_RISK_PER_TRADE
from ml.position_sizer import calculate_dynamic_risk, get_contract_size
from alerts.alert_schema import Alert, SizeResult

logger = logging.getLogger(__name__)


class AlertPositionSizer:
    """Account-aware position sizer for the alert pipeline."""

    def size(
        self,
        alert: Alert,
        account_value: float,
        iv_rank: float,
        current_portfolio_risk: float,
        weekly_loss_breach: bool = False,
    ) -> SizeResult:
        """Calculate position size for an alert.

        Args:
            alert: The candidate alert.
            account_value: Current account balance in dollars.
            iv_rank: Current IV Rank 0–100.
            current_portfolio_risk: Dollar value of open max-loss exposure.
            weekly_loss_breach: If True, cut size by 50% (MASTERPLAN weekly loss rule).

        Returns:
            A ``SizeResult`` with risk_pct, contracts, dollar_risk, max_loss.
        """
        # 1. Get dollar risk budget from IV-scaled sizing
        dollar_risk = calculate_dynamic_risk(
            account_value, iv_rank, current_portfolio_risk
        )

        # 2. Hard cap at MASTERPLAN per-trade limit
        hard_cap = MAX_RISK_PER_TRADE * account_value
        dollar_risk = min(dollar_risk, hard_cap)

        # 3. Weekly loss breach → 50% reduction
        if weekly_loss_breach:
            dollar_risk *= 0.5
            logger.info("AlertPositionSizer: 50%% size reduction (weekly loss breach)")

        # 4. Derive risk_pct
        risk_pct = dollar_risk / account_value if account_value > 0 else 0.0

        # 5. Derive spread_width and credit from alert legs
        spread_width, credit = self._extract_spread_params(alert)

        # 6. Calculate contracts
        contracts = get_contract_size(dollar_risk, spread_width, credit)

        # 7. Compute max_loss
        max_loss_per_contract = (spread_width - credit) * 100
        max_loss = max_loss_per_contract * contracts

        return SizeResult(
            risk_pct=risk_pct,
            contracts=contracts,
            dollar_risk=dollar_risk,
            max_loss=max_loss,
        )

    @staticmethod
    def _extract_spread_params(alert: Alert) -> tuple:
        """Derive spread_width and credit from the alert.

        For multi-leg strategies the spread width is the distance between the
        short and long strikes on the widest wing.

        Returns:
            ``(spread_width, credit)`` — both in dollar terms per share.
        """
        credit = alert.entry_price

        if len(alert.legs) >= 2:
            # Find strikes to compute width (use first two legs as the primary wing)
            strikes = sorted(leg.strike for leg in alert.legs)
            # For a credit spread, spread width = max(strike) - min(strike)
            # For iron condors with 4 legs, compute per-wing width
            if len(alert.legs) == 4:
                # Two wings: put side (legs 0,1) and call side (legs 2,3)
                # Width is the wider of the two wings
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
            spread_width = 5.0  # safety fallback

        return spread_width, credit
