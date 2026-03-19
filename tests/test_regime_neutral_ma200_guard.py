"""
Tests for the NEUTRAL + MA200-bearish guard in the regime-to-strategy mapping.

Verifies that:
  - NEUTRAL + ma200_vote='bear'    → bull puts BLOCKED
  - NEUTRAL + ma200_vote='neutral' → bull puts ALLOWED
  - NEUTRAL + ma200_vote='bull'    → bull puts ALLOWED
  - NEUTRAL + ma200_vote absent    → bull puts ALLOWED (safe default)
  - BULL                           → bull puts ALLOWED (unchanged)
  - BEAR                           → bear calls ALLOWED, bull puts BLOCKED

The guard lives in strategy/spread_strategy.py evaluate_spread_opportunity(),
where it reads technical_signals['combo_regime'] and technical_signals['ma200_vote'].
We test it by calling evaluate_spread_opportunity() with a minimal option chain
and checking which spread types are returned.
"""

import pandas as pd
import pytest
from datetime import datetime, timedelta, timezone

from strategy.spread_strategy import CreditSpreadStrategy


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

def _make_config(direction: str = "both") -> dict:
    return {
        "strategy": {
            "regime_mode": "combo",
            "direction": direction,
            "min_dte": 10,
            "max_dte": 45,
            "target_dte": 30,
            "manage_dte": 0,
            "otm_pct": 0.02,
            "use_delta_selection": False,
            "min_delta": 0.05,
            "max_delta": 0.30,
            "spread_width": 5,
            "spread_width_high_iv": 5,
            "spread_width_low_iv": 5,
            "min_iv_rank": 0,
            "min_iv_percentile": 0,
            "technical": {
                "use_trend_filter": False,
                "use_rsi_filter": False,
                "use_support_resistance": False,
                "fast_ma": 50,
                "slow_ma": 200,
                "rsi_period": 14,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
            },
            "iron_condor": {"enabled": False},
        },
        "risk": {
            "profit_target": 50,
            "stop_loss_multiplier": 2.0,
            "min_credit_pct": 20,
            "max_risk_per_trade": 5,
        },
        "backtest": {"slippage": 0.0},
    }


def _make_option_chain(current_price: float, as_of_date: datetime) -> pd.DataFrame:
    """Build a minimal option chain with realistic premiums.

    Puts: lower strike = cheaper (so short_bid > long_ask → positive credit).
    Calls: higher strike = cheaper (same logic for bear call spreads).
    Spread width = 5 pts; strikes in multiples of 5 for clean long-leg matching.
    """
    expiration = as_of_date + timedelta(days=30)
    rows = []
    # Put legs: 5 strikes spaced 5 pts below current price
    # Premium decreases as strike drops further OTM
    put_premiums = [4.50, 3.00, 2.00, 1.20, 0.70]
    for i, mult in enumerate([0.99, 0.98, 0.97, 0.96, 0.95]):
        strike = round(current_price * mult / 5) * 5  # round to nearest $5
        bid = put_premiums[i]
        rows.append({
            "expiration": expiration,
            "type": "put",
            "strike": float(strike),
            "bid": bid,
            "ask": bid + 0.10,
            "delta": -0.15,
            "iv": 0.25,
        })
    # Call legs: 5 strikes spaced 5 pts above current price
    call_premiums = [4.50, 3.00, 2.00, 1.20, 0.70]
    for i, mult in enumerate([1.01, 1.02, 1.03, 1.04, 1.05]):
        strike = round(current_price * mult / 5) * 5
        bid = call_premiums[i]
        rows.append({
            "expiration": expiration,
            "type": "call",
            "strike": float(strike),
            "bid": bid,
            "ask": bid + 0.10,
            "delta": 0.15,
            "iv": 0.25,
        })
    return pd.DataFrame(rows)


def _get_spread_types(opportunities: list) -> set:
    return {o["type"] for o in opportunities}


AS_OF = datetime(2024, 6, 1, tzinfo=timezone.utc)
PRICE = 500.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_neutral_ma200_bear_blocks_bull_puts():
    """NEUTRAL regime + ma200_vote='bear' → no bull puts."""
    strategy = CreditSpreadStrategy(_make_config())
    chain = _make_option_chain(PRICE, AS_OF)
    technical = {"combo_regime": "NEUTRAL", "ma200_vote": "bear"}
    opps = strategy.evaluate_spread_opportunity(
        "SPY", chain, technical, {"iv_rank": 30}, PRICE, as_of_date=AS_OF
    )
    types = _get_spread_types(opps)
    assert "bull_put_spread" not in types, (
        f"NEUTRAL+ma200_bear should block bull puts, got: {types}"
    )


def test_neutral_ma200_neutral_allows_bull_puts():
    """NEUTRAL regime + ma200_vote='neutral' → bull puts allowed."""
    strategy = CreditSpreadStrategy(_make_config())
    chain = _make_option_chain(PRICE, AS_OF)
    technical = {"combo_regime": "NEUTRAL", "ma200_vote": "neutral"}
    opps = strategy.evaluate_spread_opportunity(
        "SPY", chain, technical, {"iv_rank": 30}, PRICE, as_of_date=AS_OF
    )
    types = _get_spread_types(opps)
    assert "bull_put_spread" in types, (
        f"NEUTRAL+ma200_neutral should allow bull puts, got: {types}"
    )


def test_neutral_ma200_bull_allows_bull_puts():
    """NEUTRAL regime + ma200_vote='bull' → bull puts allowed."""
    strategy = CreditSpreadStrategy(_make_config())
    chain = _make_option_chain(PRICE, AS_OF)
    technical = {"combo_regime": "NEUTRAL", "ma200_vote": "bull"}
    opps = strategy.evaluate_spread_opportunity(
        "SPY", chain, technical, {"iv_rank": 30}, PRICE, as_of_date=AS_OF
    )
    types = _get_spread_types(opps)
    assert "bull_put_spread" in types, (
        f"NEUTRAL+ma200_bull should allow bull puts, got: {types}"
    )


def test_neutral_ma200_absent_allows_bull_puts():
    """NEUTRAL regime + no ma200_vote key → bull puts allowed (safe default)."""
    strategy = CreditSpreadStrategy(_make_config())
    chain = _make_option_chain(PRICE, AS_OF)
    technical = {"combo_regime": "NEUTRAL"}  # ma200_vote absent
    opps = strategy.evaluate_spread_opportunity(
        "SPY", chain, technical, {"iv_rank": 30}, PRICE, as_of_date=AS_OF
    )
    types = _get_spread_types(opps)
    assert "bull_put_spread" in types, (
        f"NEUTRAL+absent ma200_vote should default to allowing bull puts, got: {types}"
    )


def test_bull_regime_allows_bull_puts():
    """BULL regime always allows bull puts regardless of ma200_vote."""
    strategy = CreditSpreadStrategy(_make_config())
    chain = _make_option_chain(PRICE, AS_OF)
    technical = {"combo_regime": "BULL", "ma200_vote": "bear"}
    opps = strategy.evaluate_spread_opportunity(
        "SPY", chain, technical, {"iv_rank": 30}, PRICE, as_of_date=AS_OF
    )
    types = _get_spread_types(opps)
    assert "bull_put_spread" in types, (
        f"BULL regime should always allow bull puts, got: {types}"
    )


def test_bear_regime_blocks_bull_puts():
    """BEAR regime blocks bull puts and allows bear calls."""
    strategy = CreditSpreadStrategy(_make_config())
    chain = _make_option_chain(PRICE, AS_OF)
    technical = {"combo_regime": "BEAR", "ma200_vote": "bear"}
    opps = strategy.evaluate_spread_opportunity(
        "SPY", chain, technical, {"iv_rank": 30}, PRICE, as_of_date=AS_OF
    )
    types = _get_spread_types(opps)
    assert "bull_put_spread" not in types, f"BEAR regime should block bull puts, got: {types}"
    assert "bear_call_spread" in types, f"BEAR regime should allow bear calls, got: {types}"


def test_neutral_ma200_bear_does_not_block_bear_calls():
    """NEUTRAL + ma200_vote='bear' blocks bull puts but also should NOT open bear calls
    (BEAR regime is still required for bear calls — NEUTRAL does not enable them)."""
    strategy = CreditSpreadStrategy(_make_config())
    chain = _make_option_chain(PRICE, AS_OF)
    technical = {"combo_regime": "NEUTRAL", "ma200_vote": "bear"}
    opps = strategy.evaluate_spread_opportunity(
        "SPY", chain, technical, {"iv_rank": 30}, PRICE, as_of_date=AS_OF
    )
    types = _get_spread_types(opps)
    assert "bear_call_spread" not in types, (
        f"NEUTRAL+ma200_bear should NOT open bear calls (BEAR regime required), got: {types}"
    )
    assert "bull_put_spread" not in types, (
        f"NEUTRAL+ma200_bear should block bull puts, got: {types}"
    )
