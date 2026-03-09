"""Tests for shared/vix_regime.py — VIX regime filter and sizing."""

import pandas as pd
import pytest

from shared.vix_regime import VixSizingResult, compute_vrp, vix_sizing_factor


# -----------------------------------------------------------------------
# TestComputeVRP
# -----------------------------------------------------------------------

class TestComputeVRP:
    def test_basic_calculation(self):
        # VIX=20, realized_vol=0.15 → VRP = 20 - 15 = 5
        assert compute_vrp(20.0, 0.15) == pytest.approx(5.0)

    def test_zero_realized_vol(self):
        assert compute_vrp(25.0, 0.0) == pytest.approx(25.0)

    def test_high_vix_high_rvol(self):
        # VIX=40, realized_vol=0.35 → VRP = 40 - 35 = 5
        assert compute_vrp(40.0, 0.35) == pytest.approx(5.0)

    def test_negative_vrp(self):
        # VIX=15, realized_vol=0.25 → VRP = 15 - 25 = -10
        assert compute_vrp(15.0, 0.25) == pytest.approx(-10.0)


# -----------------------------------------------------------------------
# TestVixSizingRegimes
# -----------------------------------------------------------------------

class TestVixSizingRegimes:
    """Each regime tier returns the expected label and base factor."""

    def test_crisis_regime(self):
        result = vix_sizing_factor(45.0, 0.35)
        assert result.regime == "crisis"
        assert result.factor == pytest.approx(0.25)

    def test_high_vol_regime(self):
        result = vix_sizing_factor(37.0, 0.30)
        assert result.regime == "high_vol"
        assert result.factor == pytest.approx(0.50)

    def test_elevated_favorable_vrp(self):
        # VIX=30, realized_vol=0.20 → VRP=10 (>4) → factor=1.0
        result = vix_sizing_factor(30.0, 0.20)
        assert result.regime == "elevated"
        assert result.vrp == pytest.approx(10.0)
        assert result.factor == pytest.approx(1.0)

    def test_elevated_unfavorable_vrp(self):
        # VIX=28, realized_vol=0.25 → VRP=3 (≤4) → factor=0.65
        result = vix_sizing_factor(28.0, 0.25)
        assert result.regime == "elevated"
        assert result.vrp == pytest.approx(3.0)
        assert result.factor == pytest.approx(0.65)

    def test_normal_favorable_vrp(self):
        # VIX=20, realized_vol=0.12 → VRP=8 (>4) → factor=1.25
        result = vix_sizing_factor(20.0, 0.12)
        assert result.regime == "normal"
        assert result.factor == pytest.approx(1.25)

    def test_normal_neutral_vrp(self):
        # VIX=18, realized_vol=0.15 → VRP=3 (≤4) → factor=1.0
        result = vix_sizing_factor(18.0, 0.15)
        assert result.regime == "normal"
        assert result.factor == pytest.approx(1.0)

    def test_low_vol_regime(self):
        result = vix_sizing_factor(12.0, 0.10)
        assert result.regime == "low_vol"
        assert result.factor == pytest.approx(0.80)

    def test_vrp_boundary_exactly_4(self):
        # VRP exactly 4 → ≤4 branch (not >4)
        # VIX=20, realized_vol=0.16 → VRP=4.0
        result = vix_sizing_factor(20.0, 0.16)
        assert result.regime == "normal"
        assert result.vrp == pytest.approx(4.0)
        assert result.factor == pytest.approx(1.0)  # neutral, not 1.25


# -----------------------------------------------------------------------
# TestTermStructure
# -----------------------------------------------------------------------

class TestTermStructure:
    """Term structure adjustment via vix_history."""

    @staticmethod
    def _make_history(values):
        return pd.Series(values)

    def test_backwardation_penalty(self):
        # 20-day MA = 25, current VIX = 30 → slope = -5 (< -3) → ×0.85
        history = self._make_history([25.0] * 20)
        result = vix_sizing_factor(30.0, 0.20, vix_history=history)
        # elevated + favorable VRP(10) → base 1.0, then ×0.85 = 0.85
        assert result.factor == pytest.approx(0.85)
        assert result.term_slope == pytest.approx(-5.0)

    def test_contango_boost(self):
        # 20-day MA = 28, current VIX = 20 → slope = 8 (> 5) → ×1.10
        history = self._make_history([28.0] * 20)
        result = vix_sizing_factor(20.0, 0.12, vix_history=history)
        # normal + favorable VRP(8) → base 1.25, then ×1.10 = 1.375
        assert result.factor == pytest.approx(1.375)
        assert result.term_slope == pytest.approx(8.0)

    def test_no_history_no_adjustment(self):
        result = vix_sizing_factor(20.0, 0.12, vix_history=None)
        assert result.factor == pytest.approx(1.25)
        assert result.term_slope == pytest.approx(0.0)

    def test_short_history_no_adjustment(self):
        # < 20 data points → no term structure adjustment
        history = self._make_history([20.0] * 10)
        result = vix_sizing_factor(20.0, 0.12, vix_history=history)
        assert result.factor == pytest.approx(1.25)
        assert result.term_slope == pytest.approx(0.0)

    def test_neutral_slope_no_adjustment(self):
        # slope between -3 and 5 → no multiplier
        history = self._make_history([21.0] * 20)
        result = vix_sizing_factor(20.0, 0.12, vix_history=history)
        # normal + favorable VRP → base 1.25, slope=1.0 (neutral range)
        assert result.factor == pytest.approx(1.25)
        assert result.term_slope == pytest.approx(1.0)


# -----------------------------------------------------------------------
# TestEdgeCases
# -----------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_vix(self):
        result = vix_sizing_factor(0.0, 0.0)
        assert result.regime == "low_vol"
        assert result.factor == pytest.approx(0.80)

    def test_very_high_vix(self):
        result = vix_sizing_factor(80.0, 0.50)
        assert result.regime == "crisis"
        assert result.factor == pytest.approx(0.25)

    def test_factor_clamped_at_upper_bound(self):
        # Contango boost on already-high factor: 1.25 × 1.10 = 1.375 (within 1.5)
        # Make an extreme case: would need factor > 1.5 before clamp
        # normal + VRP>4 → 1.25, steep contango → 1.375, still under 1.5
        history = pd.Series([30.0] * 20)
        result = vix_sizing_factor(20.0, 0.12, vix_history=history)
        assert result.factor <= 1.5

    def test_factor_clamped_at_lower_bound(self):
        # crisis (0.25) + backwardation (×0.85) = 0.2125 → clamped to 0.25
        history = pd.Series([35.0] * 20)
        result = vix_sizing_factor(45.0, 0.35, vix_history=history)
        assert result.factor == pytest.approx(0.25)

    def test_boundary_vix_40(self):
        # VIX exactly 40 → high_vol boundary (>40 = crisis, 35-40 = high_vol)
        result = vix_sizing_factor(40.0, 0.30)
        assert result.regime == "high_vol"

    def test_boundary_vix_35(self):
        result = vix_sizing_factor(35.0, 0.30)
        assert result.regime == "high_vol"

    def test_boundary_vix_25(self):
        result = vix_sizing_factor(25.0, 0.20)
        assert result.regime == "elevated"

    def test_boundary_vix_15(self):
        result = vix_sizing_factor(15.0, 0.10)
        assert result.regime == "normal"


# -----------------------------------------------------------------------
# TestStrategyIntegration
# -----------------------------------------------------------------------

class TestStrategyIntegration:
    """Verify that VIX factor can be applied to strategy sizing outputs."""

    def test_credit_spread_sizing_with_vix_factor(self):
        """Simulates CreditSpreadStrategy.size_position() with VIX factor."""
        equity = 100_000.0
        max_risk_pct = 0.02
        risk_budget = equity * max_risk_pct  # 2000
        max_loss = 8.50
        risk_per_unit = max_loss * 100  # 850

        contracts_raw = max(1, int(risk_budget / risk_per_unit))  # 2
        assert contracts_raw == 2

        # Crisis regime: factor = 0.25
        result = vix_sizing_factor(45.0, 0.35)
        contracts = max(1, int(contracts_raw * result.factor))
        assert contracts == 1  # 2 × 0.25 = 0.5 → int → 0 → max(1, 0) = 1

    def test_iron_condor_sizing_normal_boost(self):
        """Normal regime with favorable VRP boosts sizing."""
        equity = 100_000.0
        max_risk_pct = 0.02
        risk_budget = equity * max_risk_pct  # 2000
        max_loss = 5.0
        risk_per_unit = max_loss * 100  # 500

        contracts_raw = max(1, int(risk_budget / risk_per_unit))  # 4
        assert contracts_raw == 4

        result = vix_sizing_factor(18.0, 0.10)
        assert result.factor == pytest.approx(1.25)
        contracts = max(1, int(contracts_raw * result.factor))
        assert contracts == 5  # 4 × 1.25 = 5.0

    def test_zero_dte_replaces_inline_logic(self):
        """VIX=32 now gives elevated regime factor instead of flat 0.5."""
        # Old inline logic: vix > 30 → 0.5
        # New: VIX=32, realized_vol=0.25 → VRP=7 (>4) → elevated → 1.0
        result = vix_sizing_factor(32.0, 0.25)
        assert result.regime == "elevated"
        assert result.factor == pytest.approx(1.0)
        # Old code would have returned 0.5 — new filter is VRP-aware
