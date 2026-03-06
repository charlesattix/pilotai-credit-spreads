"""Comprehensive tests for CreditSpreadStrategy core logic.

Covers:
  1. POP calculation from delta
  2. _find_bull_put_spreads  — credit math, strike selection, rejection filters
  3. _find_bear_call_spreads — credit math, strike selection, rejection filters
  4. Scoring formula weights — each component individually + total sum
  5. evaluate_spread_opportunity end-to-end
  6. Spread width selection by IV environment
"""

import pytest
import pandas as pd
from datetime import datetime, timezone

from strategy.spread_strategy import CreditSpreadStrategy, SCORING_WEIGHTS

# ---------------------------------------------------------------------------
# Deterministic dates — DTE = 35, within default 30-45 range
# ---------------------------------------------------------------------------
AS_OF = datetime(2026, 3, 6, 0, 0, 0, tzinfo=timezone.utc)
EXP_35D = datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)  # 35 DTE from AS_OF


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**strategy_overrides):
    """Build a config dict with optional strategy-level overrides."""
    config = {
        "strategy": {
            "min_dte": 30,
            "max_dte": 45,
            "min_delta": 0.10,
            "max_delta": 0.15,
            "spread_width": 5,
            "spread_width_high_iv": 15,
            "spread_width_low_iv": 10,
            "min_iv_rank": 25,
            "min_iv_percentile": 25,
            "iron_condor": {"enabled": False},
            "technical": {
                "use_trend_filter": True,
                "use_rsi_filter": True,
                "use_support_resistance": True,
                "fast_ma": 20,
                "slow_ma": 50,
                "rsi_period": 14,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
            },
        },
        "risk": {
            "account_size": 100_000,
            "max_risk_per_trade": 2.0,
            "max_positions": 7,
            "profit_target": 50,
            "stop_loss_multiplier": 2.5,
            "delta_threshold": 0.30,
            "min_credit_pct": 20,
        },
    }
    config["strategy"].update(strategy_overrides)
    return config


def _put(strike, bid, ask, delta, exp=EXP_35D):
    """Single put row for an options chain."""
    return {
        "strike": float(strike), "bid": bid, "ask": ask,
        "type": "put", "delta": delta, "expiration": exp, "iv": 0.25,
    }


def _call(strike, bid, ask, delta, exp=EXP_35D):
    """Single call row for an options chain."""
    return {
        "strike": float(strike), "bid": bid, "ask": ask,
        "type": "call", "delta": delta, "expiration": exp, "iv": 0.25,
    }


def _chain(rows):
    """DataFrame from a list of option rows."""
    return pd.DataFrame(rows)


def _opp(credit=1.50, spread_width=5, risk_reward=0.43, pop=88.0,
         opp_type="bull_put_spread"):
    """Minimal opportunity dict for scoring-only tests."""
    return {
        "ticker": "SPY", "type": opp_type,
        "credit": credit, "spread_width": spread_width,
        "risk_reward": risk_reward, "pop": pop,
        "max_loss": spread_width - credit,
    }


# ===================================================================
# 1. POP calculation
# ===================================================================

class TestPOPCalculation:
    """POP ≈ (1 - |delta|) * 100."""

    def test_negative_delta(self):
        s = CreditSpreadStrategy(_cfg())
        assert s._calculate_pop(-0.12) == pytest.approx(88.0)

    def test_positive_delta(self):
        s = CreditSpreadStrategy(_cfg())
        assert s._calculate_pop(0.30) == pytest.approx(70.0)

    def test_zero_delta_gives_100(self):
        s = CreditSpreadStrategy(_cfg())
        assert s._calculate_pop(0.0) == pytest.approx(100.0)

    def test_unity_delta_gives_0(self):
        s = CreditSpreadStrategy(_cfg())
        assert s._calculate_pop(-1.0) == pytest.approx(0.0)


# ===================================================================
# 2. _find_bull_put_spreads
# ===================================================================

class TestFindBullPutSpreads:

    def test_credit_and_strike_math(self):
        """credit = short.bid - long.ask; long = short - width."""
        chain = _chain([
            _put(440, bid=3.00, ask=3.50, delta=-0.12),
            _put(435, bid=1.50, ask=2.00, delta=-0.08),
        ])
        s = CreditSpreadStrategy(_cfg())
        spreads = s._find_bull_put_spreads(
            "SPY", chain, 450.0, EXP_35D, as_of_date=AS_OF,
        )
        assert len(spreads) == 1
        sp = spreads[0]
        assert sp["short_strike"] == 440.0
        assert sp["long_strike"] == 435.0
        assert sp["credit"] == pytest.approx(1.00)       # 3.00 - 2.00
        assert sp["max_loss"] == pytest.approx(4.00)      # 5 - 1.00
        assert sp["pop"] == pytest.approx(88.0)           # 1 - 0.12
        assert sp["risk_reward"] == pytest.approx(0.25)   # 1.00 / 4.00
        assert sp["type"] == "bull_put_spread"
        assert sp["spread_width"] == 5
        assert sp["dte"] == 35

    def test_negative_credit_rejected(self):
        """Crossed market → credit <= 0 → no spread returned."""
        chain = _chain([
            _put(440, bid=1.00, ask=1.50, delta=-0.12),
            _put(435, bid=2.00, ask=3.00, delta=-0.08),   # long.ask > short.bid
        ])
        s = CreditSpreadStrategy(_cfg())
        assert s._find_bull_put_spreads(
            "SPY", chain, 450.0, EXP_35D, as_of_date=AS_OF,
        ) == []

    def test_below_min_credit_pct_rejected(self):
        """Credit < min_credit_pct of width → filtered out."""
        # min_credit = 5 * 0.20 = 1.00; credit here = 0.40
        chain = _chain([
            _put(440, bid=2.00, ask=2.50, delta=-0.12),
            _put(435, bid=1.50, ask=1.60, delta=-0.08),
        ])
        s = CreditSpreadStrategy(_cfg())
        assert s._find_bull_put_spreads(
            "SPY", chain, 450.0, EXP_35D, as_of_date=AS_OF,
        ) == []

    def test_missing_long_leg_skipped(self):
        """No matching long-leg strike → no spread."""
        chain = _chain([
            _put(440, bid=3.00, ask=3.50, delta=-0.12),
            # 435 strike absent
        ])
        s = CreditSpreadStrategy(_cfg())
        assert s._find_bull_put_spreads(
            "SPY", chain, 450.0, EXP_35D, as_of_date=AS_OF,
        ) == []

    def test_delta_outside_range_ignored(self):
        """Short candidate delta outside [min_delta, max_delta] → skipped."""
        chain = _chain([
            _put(440, bid=5.00, ask=5.50, delta=-0.40),   # too deep
            _put(435, bid=3.00, ask=3.50, delta=-0.30),
        ])
        s = CreditSpreadStrategy(_cfg())
        assert s._find_bull_put_spreads(
            "SPY", chain, 450.0, EXP_35D, as_of_date=AS_OF,
        ) == []


# ===================================================================
# 3. _find_bear_call_spreads
# ===================================================================

class TestFindBearCallSpreads:

    def test_credit_and_strike_math(self):
        """credit = short.bid - long.ask; long = short + width."""
        chain = _chain([
            _call(460, bid=2.50, ask=3.00, delta=0.12),
            _call(465, bid=1.00, ask=1.50, delta=0.08),
        ])
        s = CreditSpreadStrategy(_cfg())
        spreads = s._find_bear_call_spreads(
            "SPY", chain, 450.0, EXP_35D, as_of_date=AS_OF,
        )
        assert len(spreads) == 1
        sp = spreads[0]
        assert sp["short_strike"] == 460.0
        assert sp["long_strike"] == 465.0
        assert sp["credit"] == pytest.approx(1.00)
        assert sp["max_loss"] == pytest.approx(4.00)
        assert sp["type"] == "bear_call_spread"

    def test_negative_credit_rejected(self):
        """Bear call with bid < long.ask → no spread."""
        chain = _chain([
            _call(460, bid=0.50, ask=1.00, delta=0.12),
            _call(465, bid=0.80, ask=1.20, delta=0.08),
        ])
        s = CreditSpreadStrategy(_cfg())
        assert s._find_bear_call_spreads(
            "SPY", chain, 450.0, EXP_35D, as_of_date=AS_OF,
        ) == []


# ===================================================================
# 4. Scoring formula weights — isolate each component
# ===================================================================

class TestScoringWeights:
    """Each test zeros out other components to verify one in isolation."""

    # -- Credit component: min(credit_pct * 0.5, 25) --------------------

    def test_credit_component(self):
        """credit=2/5 → 40% → 40*0.5 = 20 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=2.00, risk_reward=0, pop=0)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 0})
        assert scored[0]["score"] == pytest.approx(20.0)

    def test_credit_component_capped_at_25(self):
        """credit=4/5 → 80% → min(40, 25) = 25 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=4.00, risk_reward=0, pop=0)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 0})
        assert scored[0]["score"] == pytest.approx(25.0)

    # -- Risk/reward component: min(rr * 8, 25) -------------------------

    def test_rr_component(self):
        """rr=2.0 → 2*8 = 16 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=2.0, pop=0)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 0})
        assert scored[0]["score"] == pytest.approx(16.0)

    def test_rr_component_capped_at_25(self):
        """rr=5.0 → min(40, 25) = 25 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=5.0, pop=0)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 0})
        assert scored[0]["score"] == pytest.approx(25.0)

    # -- POP component: min((pop / 85) * 25, 25) ------------------------

    def test_pop_at_baseline(self):
        """pop=85 → full 25 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=85.0)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 0})
        assert scored[0]["score"] == pytest.approx(25.0)

    def test_pop_half_baseline(self):
        """pop=42.5 → (42.5/85)*25 = 12.5 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=42.5)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 0})
        assert scored[0]["score"] == pytest.approx(12.5)

    # -- IV component: min(iv_rank / 10, 10) -----------------------------

    def test_iv_component(self):
        """iv_rank=60 → 6 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=0)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 60})
        assert scored[0]["score"] == pytest.approx(6.0)

    def test_iv_component_capped_at_10(self):
        """iv_rank=200 → min(20, 10) = 10 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=0)
        scored = s._score_opportunities([opp], {}, {"iv_rank": 200})
        assert scored[0]["score"] == pytest.approx(10.0)

    # -- Technical alignment component (capped at 15) --------------------

    def test_tech_bull_put_bullish_trend(self):
        """Bull put + bullish → 10 pts (strong signal)."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=0, opp_type="bull_put_spread")
        scored = s._score_opportunities(
            [opp], {"trend": "bullish"}, {"iv_rank": 0},
        )
        assert scored[0]["score"] == pytest.approx(10.0)

    def test_tech_bull_put_neutral_trend(self):
        """Bull put + neutral → 5 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=0, opp_type="bull_put_spread")
        scored = s._score_opportunities(
            [opp], {"trend": "neutral"}, {"iv_rank": 0},
        )
        assert scored[0]["score"] == pytest.approx(5.0)

    def test_tech_bear_call_bearish_trend(self):
        """Bear call + bearish → 10 pts (strong signal)."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=0, opp_type="bear_call_spread")
        scored = s._score_opportunities(
            [opp], {"trend": "bearish"}, {"iv_rank": 0},
        )
        assert scored[0]["score"] == pytest.approx(10.0)

    def test_tech_support_bonus_bull_put(self):
        """Bull put near support → +5 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=0, opp_type="bull_put_spread")
        scored = s._score_opportunities(
            [opp], {"near_support": True}, {"iv_rank": 0},
        )
        assert scored[0]["score"] == pytest.approx(5.0)

    def test_tech_resistance_bonus_bear_call(self):
        """Bear call near resistance → +5 pts."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(credit=0, risk_reward=0, pop=0, opp_type="bear_call_spread")
        scored = s._score_opportunities(
            [opp], {"near_resistance": True}, {"iv_rank": 0},
        )
        assert scored[0]["score"] == pytest.approx(5.0)

    # -- Total formula verification --------------------------------------

    def test_all_components_sum(self):
        """Verify credit + rr + pop + tech + iv sum to expected total."""
        s = CreditSpreadStrategy(_cfg())
        opp = _opp(
            credit=1.00, spread_width=5, risk_reward=0.25,
            pop=88.0, opp_type="bull_put_spread",
        )
        scored = s._score_opportunities(
            [opp], {"trend": "bullish"}, {"iv_rank": 40},
        )
        # credit: min(20*0.5, 25) = 10
        # rr:     min(0.25*8, 25) = 2
        # pop:    min((88/85)*25, 25) = 25 (capped)
        # tech:   10 (bullish alignment)
        # iv:     min(40/10, 10) = 4
        assert scored[0]["score"] == pytest.approx(51.0)

    def test_sorted_descending(self):
        """Scoring sorts opportunities highest-first."""
        s = CreditSpreadStrategy(_cfg())
        low = _opp(credit=0.50, pop=50.0, risk_reward=0.10)
        high = _opp(credit=3.00, pop=90.0, risk_reward=0.60)
        scored = s._score_opportunities([low, high], {}, {"iv_rank": 30})
        assert scored[0]["score"] > scored[1]["score"]


# ===================================================================
# 5. evaluate_spread_opportunity end-to-end
# ===================================================================

class TestEvaluateEndToEnd:
    """Full pipeline: conditions → find spreads → score → sort."""

    def _bull_chain(self):
        return _chain([
            _put(440, bid=3.00, ask=3.50, delta=-0.12),
            _put(435, bid=1.50, ask=2.00, delta=-0.08),
        ])

    def _bear_chain(self):
        return _chain([
            _call(460, bid=2.50, ask=3.00, delta=0.12),
            _call(465, bid=1.00, ask=1.50, delta=0.08),
        ])

    def _full_chain(self):
        return _chain([
            _put(440, bid=3.00, ask=3.50, delta=-0.12),
            _put(435, bid=1.50, ask=2.00, delta=-0.08),
            _call(460, bid=2.50, ask=3.00, delta=0.12),
            _call(465, bid=1.00, ask=1.50, delta=0.08),
        ])

    def test_bullish_produces_bull_puts_only(self):
        """Bullish trend + elevated IV → only bull put spreads returned."""
        s = CreditSpreadStrategy(_cfg())
        # iv_rank=10 keeps spread_width at default 5; iv_percentile=30
        # passes the IV condition check (>= min_iv_percentile=25).
        result = s.evaluate_spread_opportunity(
            "SPY", self._full_chain(),
            {"trend": "bullish", "rsi": 50},
            {"iv_rank": 10, "iv_percentile": 30},
            450.0, as_of_date=AS_OF,
        )
        assert len(result) >= 1
        assert all(r["type"] == "bull_put_spread" for r in result)
        assert all("score" in r for r in result)

    def test_bearish_produces_bear_calls_only(self):
        """Bearish trend + elevated IV → only bear call spreads returned."""
        s = CreditSpreadStrategy(_cfg())
        result = s.evaluate_spread_opportunity(
            "SPY", self._full_chain(),
            {"trend": "bearish", "rsi": 50},
            {"iv_rank": 10, "iv_percentile": 30},
            450.0, as_of_date=AS_OF,
        )
        assert len(result) >= 1
        assert all(r["type"] == "bear_call_spread" for r in result)

    def test_neutral_produces_both_directions(self):
        """Neutral trend → both bull puts and bear calls."""
        s = CreditSpreadStrategy(_cfg())
        result = s.evaluate_spread_opportunity(
            "SPY", self._full_chain(),
            {"trend": "neutral", "rsi": 50},
            {"iv_rank": 10, "iv_percentile": 30},
            450.0, as_of_date=AS_OF,
        )
        types = {r["type"] for r in result}
        assert "bull_put_spread" in types
        assert "bear_call_spread" in types

    def test_low_iv_returns_empty(self):
        """IV below both thresholds → no conditions pass → empty."""
        s = CreditSpreadStrategy(_cfg())
        result = s.evaluate_spread_opportunity(
            "SPY", self._full_chain(),
            {"trend": "bullish", "rsi": 50},
            {"iv_rank": 10, "iv_percentile": 10},
            450.0, as_of_date=AS_OF,
        )
        assert result == []

    def test_empty_chain_returns_empty(self):
        """No options → no opportunities."""
        s = CreditSpreadStrategy(_cfg())
        empty = pd.DataFrame(
            columns=["strike", "bid", "ask", "type", "delta", "expiration", "iv"],
        )
        result = s.evaluate_spread_opportunity(
            "SPY", empty,
            {"trend": "bullish", "rsi": 50},
            {"iv_rank": 40, "iv_percentile": 40},
            450.0, as_of_date=AS_OF,
        )
        assert result == []

    def test_overbought_rsi_blocks_bull_put(self):
        """RSI above overbought (70) blocks bull put conditions."""
        s = CreditSpreadStrategy(_cfg())
        result = s.evaluate_spread_opportunity(
            "SPY", self._bull_chain(),
            {"trend": "bullish", "rsi": 75},
            {"iv_rank": 40, "iv_percentile": 40},
            450.0, as_of_date=AS_OF,
        )
        assert result == []

    def test_scored_results_have_all_fields(self):
        """End-to-end results carry all required spread fields."""
        s = CreditSpreadStrategy(_cfg())
        result = s.evaluate_spread_opportunity(
            "SPY", self._bull_chain(),
            {"trend": "bullish", "rsi": 50},
            {"iv_rank": 10, "iv_percentile": 30},
            450.0, as_of_date=AS_OF,
        )
        assert len(result) >= 1
        sp = result[0]
        required = {
            "ticker", "type", "expiration", "dte", "short_strike",
            "long_strike", "credit", "max_loss", "max_profit",
            "profit_target", "stop_loss", "spread_width", "current_price",
            "pop", "risk_reward", "score",
        }
        assert required.issubset(sp.keys())


# ===================================================================
# 6. Spread width selection
# ===================================================================

class TestSpreadWidthSelection:

    def test_high_iv_uses_wide(self):
        """iv_rank >= 50 → spread_width_high_iv (15)."""
        s = CreditSpreadStrategy(_cfg())
        assert s._select_spread_width({"iv_rank": 60}) == 15

    def test_mid_iv_uses_low_iv_width(self):
        """25 <= iv_rank < 50 → spread_width_low_iv (10)."""
        s = CreditSpreadStrategy(_cfg())
        assert s._select_spread_width({"iv_rank": 30}) == 10

    def test_low_iv_uses_default(self):
        """iv_rank < 25 → default spread_width (5)."""
        s = CreditSpreadStrategy(_cfg())
        assert s._select_spread_width({"iv_rank": 10}) == 5
