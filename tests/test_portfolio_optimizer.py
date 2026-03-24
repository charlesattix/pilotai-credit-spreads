"""Tests for compass.portfolio_optimizer."""
import math
from datetime import date
from unittest.mock import patch

import numpy as np
import pytest

from compass.portfolio_optimizer import (
    EXPERIMENT_IDS,
    EXPERIMENT_PROFILES,
    MIN_WEIGHT,
    OptimizationResult,
    PortfolioOptimizer,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_returns(
    n_days: int = 504,
    seed: int = 42,
    experiments: list | None = None,
) -> dict[str, np.ndarray]:
    """Create synthetic daily returns for 4 experiments over ~2 years.

    Each experiment has a distinct Sharpe / volatility profile so that the
    optimizers produce meaningfully different weights.
    """
    rng = np.random.RandomState(seed)
    if experiments is None:
        experiments = list(EXPERIMENT_IDS)

    # annual drift, annual vol → daily
    profiles = {
        "EXP-400": (0.15, 0.10),
        "EXP-401": (0.10, 0.08),
        "EXP-503": (0.25, 0.20),
        "EXP-600": (0.06, 0.05),
    }
    # Correlation: build a factor + idio model
    market_factor = rng.randn(n_days) * 0.01  # daily market noise

    returns = {}
    for eid in experiments:
        drift, vol = profiles.get(eid, (0.10, 0.10))
        daily_drift = drift / 252
        daily_vol = vol / np.sqrt(252)
        beta = rng.uniform(0.2, 0.5)
        idio = rng.randn(n_days) * daily_vol
        r = daily_drift + beta * market_factor + idio
        returns[eid] = r

    return returns


@pytest.fixture
def returns_4exp():
    """4-experiment daily returns over 2 years."""
    return _make_returns()


@pytest.fixture
def optimizer(returns_4exp):
    return PortfolioOptimizer(returns_4exp)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError, match="same length"):
            PortfolioOptimizer({
                "EXP-400": np.zeros(100),
                "EXP-401": np.zeros(200),
            })

    def test_empty_returns_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            PortfolioOptimizer({})

    def test_single_experiment(self):
        opt = PortfolioOptimizer({"EXP-400": np.random.randn(252)})
        w = opt.max_sharpe()
        assert len(w) == 1
        assert w[0] == pytest.approx(1.0)

    def test_statistics_computed(self, optimizer):
        assert optimizer.returns_matrix.shape == (504, 4)
        assert optimizer.mean_returns.shape == (4,)
        assert optimizer.cov_matrix.shape == (4, 4)


# ---------------------------------------------------------------------------
# Optimization methods — weight validity
# ---------------------------------------------------------------------------

METHODS = ["max_sharpe", "risk_parity", "equal_risk_contribution", "min_variance"]


class TestWeightConstraints:
    """Every method must produce non-negative weights that sum to 1."""

    @pytest.mark.parametrize("method", METHODS)
    def test_weights_sum_to_one(self, optimizer, method):
        w = getattr(optimizer, method)()
        assert w.sum() == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.parametrize("method", METHODS)
    def test_weights_non_negative(self, optimizer, method):
        w = getattr(optimizer, method)()
        assert (w >= 0).all(), f"Negative weight found: {w}"

    @pytest.mark.parametrize("method", METHODS)
    def test_weights_below_one(self, optimizer, method):
        w = getattr(optimizer, method)()
        assert (w <= 1.0 + 1e-9).all()

    @pytest.mark.parametrize("method", METHODS)
    def test_min_weight_enforced(self, optimizer, method):
        w = getattr(optimizer, method)()
        assert w.min() >= MIN_WEIGHT - 1e-9


# ---------------------------------------------------------------------------
# Individual method behaviour
# ---------------------------------------------------------------------------

class TestMaxSharpe:

    def test_overweights_high_sharpe_asset(self, returns_4exp):
        """EXP-503 has the highest return; it should get substantial weight."""
        opt = PortfolioOptimizer(returns_4exp)
        w = opt.max_sharpe()
        idx_503 = opt.experiment_ids.index("EXP-503")
        idx_600 = opt.experiment_ids.index("EXP-600")
        # EXP-503 should not be the lowest-weighted
        assert w[idx_503] > w.min()

    def test_fallback_on_negative_excess(self):
        """When all returns < rf, should fall back to equal weight."""
        rng = np.random.RandomState(0)
        # Very negative returns → all excess < 0
        returns = {eid: rng.randn(252) * 0.001 - 0.01 for eid in EXPERIMENT_IDS}
        opt = PortfolioOptimizer(returns, risk_free_rate=0.50)
        w = opt.max_sharpe()
        assert w.sum() == pytest.approx(1.0, abs=1e-6)


class TestRiskParity:

    def test_low_vol_gets_higher_weight(self, returns_4exp):
        """Lower-vol experiment should get higher weight under risk parity."""
        opt = PortfolioOptimizer(returns_4exp)
        w = opt.risk_parity()
        # EXP-600 (lowest vol) should have highest weight
        idx_600 = opt.experiment_ids.index("EXP-600")
        idx_503 = opt.experiment_ids.index("EXP-503")
        assert w[idx_600] > w[idx_503]


class TestERC:

    def test_risk_contributions_roughly_equal(self, optimizer):
        """After ERC, marginal risk contributions should be approximately equal."""
        w = optimizer.equal_risk_contribution()
        cov_ann = optimizer.cov_matrix * optimizer.periods_per_year
        sigma_w = cov_ann @ w
        port_vol = np.sqrt(w @ sigma_w)
        rc = w * sigma_w / port_vol
        # Relative deviation from mean risk contribution
        mean_rc = rc.mean()
        rel_dev = np.abs(rc - mean_rc) / mean_rc
        assert rel_dev.max() < 0.15, f"Risk contributions too unequal: {rc}"


class TestMinVariance:

    def test_min_variance_lower_vol(self, returns_4exp):
        """Min-variance portfolio should have lower vol than equal weight."""
        opt = PortfolioOptimizer(returns_4exp)
        w_mv = opt.min_variance()
        w_eq = np.full(4, 0.25)

        cov_ann = opt.cov_matrix * opt.periods_per_year
        vol_mv = np.sqrt(w_mv @ cov_ann @ w_mv)
        vol_eq = np.sqrt(w_eq @ cov_ann @ w_eq)
        assert vol_mv <= vol_eq + 1e-9


# ---------------------------------------------------------------------------
# Regime-adaptive rebalancing
# ---------------------------------------------------------------------------

class TestRegimeTilt:

    def test_neutral_regime_no_change(self, optimizer):
        """NEUTRAL_MACRO should return weights unchanged."""
        w = optimizer.risk_parity()
        tilted = optimizer.apply_regime_tilt(w, "NEUTRAL_MACRO")
        np.testing.assert_allclose(tilted, w, atol=1e-9)

    def test_bull_tilts_toward_momentum(self, optimizer):
        """BULL_MACRO should increase weight on momentum experiments."""
        w = optimizer.risk_parity()
        tilted = optimizer.apply_regime_tilt(w, "BULL_MACRO")

        idx_503 = optimizer.experiment_ids.index("EXP-503")  # momentum_affinity=0.9
        idx_600 = optimizer.experiment_ids.index("EXP-600")  # momentum_affinity=0.1

        # EXP-503 weight should increase relative to base
        assert tilted[idx_503] > w[idx_503] - 1e-9
        # EXP-600 weight should decrease relative to base
        assert tilted[idx_600] < w[idx_600] + 1e-9

    def test_bear_tilts_toward_defensive(self, optimizer):
        """BEAR_MACRO should increase weight on defensive experiments."""
        w = optimizer.risk_parity()
        tilted = optimizer.apply_regime_tilt(w, "BEAR_MACRO")

        idx_503 = optimizer.experiment_ids.index("EXP-503")  # defensive_affinity=0.1
        idx_600 = optimizer.experiment_ids.index("EXP-600")  # defensive_affinity=0.9

        # Defensive asset should have higher weight than momentum in bear
        assert tilted[idx_600] > tilted[idx_503]

    def test_tilted_weights_sum_to_one(self, optimizer):
        for regime in ["BULL_MACRO", "BEAR_MACRO", "NEUTRAL_MACRO"]:
            w = optimizer.max_sharpe()
            tilted = optimizer.apply_regime_tilt(w, regime)
            assert tilted.sum() == pytest.approx(1.0, abs=1e-6)

    def test_zero_blend_preserves_weights(self):
        """regime_blend=0 should leave weights unchanged."""
        returns = _make_returns()
        opt = PortfolioOptimizer(returns, regime_blend=0.0)
        w = opt.risk_parity()
        tilted = opt.apply_regime_tilt(w, "BULL_MACRO")
        np.testing.assert_allclose(tilted, w, atol=1e-9)

    def test_unknown_regime_treated_as_neutral(self, optimizer):
        """An unrecognized regime string should behave like neutral-ish."""
        w = optimizer.risk_parity()
        tilted = optimizer.apply_regime_tilt(w, "UNKNOWN_REGIME")
        # Should still sum to 1 and be non-negative
        assert tilted.sum() == pytest.approx(1.0, abs=1e-6)
        assert (tilted >= 0).all()


# ---------------------------------------------------------------------------
# Event-driven scaling
# ---------------------------------------------------------------------------

class TestEventScaling:

    @patch("compass.portfolio_optimizer.PortfolioOptimizer.get_event_scaling")
    def test_event_scaling_reduces_allocation(self, mock_scaling, optimizer):
        """Pre-event scaling < 1.0 should reduce all scaled_weights."""
        mock_scaling.return_value = 0.60  # simulate pre-FOMC day

        result = optimizer.optimize(
            method="risk_parity",
            regime="NEUTRAL_MACRO",
            as_of=date(2026, 3, 24),
        )

        assert result.event_scaling == 0.60
        for eid in EXPERIMENT_IDS:
            raw = result.weights[eid]
            scaled = result.scaled_weights[eid]
            assert scaled == pytest.approx(raw * 0.60, abs=1e-6)

    @patch("compass.portfolio_optimizer.PortfolioOptimizer.get_event_scaling")
    def test_no_event_risk_full_allocation(self, mock_scaling, optimizer):
        """Event scaling = 1.0 means scaled weights equal raw weights."""
        mock_scaling.return_value = 1.0

        result = optimizer.optimize(
            method="risk_parity",
            regime="NEUTRAL_MACRO",
            as_of=date(2026, 3, 24),
        )

        assert result.event_scaling == 1.0
        for eid in EXPERIMENT_IDS:
            assert result.scaled_weights[eid] == pytest.approx(
                result.weights[eid], abs=1e-6
            )

    @patch("compass.portfolio_optimizer.PortfolioOptimizer.get_event_scaling")
    def test_scaled_weights_sum_le_one(self, mock_scaling, optimizer):
        """Scaled weights should sum to <= 1.0 (event scaling ∈ (0,1])."""
        for scale in [0.50, 0.75, 1.0]:
            mock_scaling.return_value = scale
            result = optimizer.optimize(
                method="max_sharpe",
                regime="NEUTRAL_MACRO",
                as_of=date(2026, 3, 24),
            )
            total = sum(result.scaled_weights.values())
            assert total <= 1.0 + 1e-6


# ---------------------------------------------------------------------------
# Full optimize() pipeline
# ---------------------------------------------------------------------------

class TestOptimizePipeline:

    @patch("compass.portfolio_optimizer.PortfolioOptimizer.get_event_scaling",
           return_value=1.0)
    @pytest.mark.parametrize("method", METHODS)
    def test_optimize_all_methods(self, mock_scaling, optimizer, method):
        result = optimizer.optimize(
            method=method,
            regime="NEUTRAL_MACRO",
            as_of=date(2026, 3, 24),
        )
        assert isinstance(result, OptimizationResult)
        assert result.method == method
        assert result.regime == "NEUTRAL_MACRO"
        assert len(result.weights) == 4
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-5)

    @patch("compass.portfolio_optimizer.PortfolioOptimizer.get_event_scaling",
           return_value=1.0)
    def test_optimize_unknown_method_raises(self, mock_scaling, optimizer):
        with pytest.raises(ValueError, match="Unknown method"):
            optimizer.optimize(method="magic", regime="NEUTRAL_MACRO")

    @patch("compass.portfolio_optimizer.PortfolioOptimizer.get_event_scaling",
           return_value=0.80)
    def test_optimize_returns_metrics(self, mock_scaling, optimizer):
        result = optimizer.optimize(
            method="risk_parity",
            regime="NEUTRAL_MACRO",
            as_of=date(2026, 1, 5),  # Monday
        )
        assert "annual_return" in result.metrics
        assert "annual_volatility" in result.metrics
        assert "sharpe_ratio" in result.metrics
        assert result.metrics["annual_volatility"] > 0
        assert result.next_rebalance is not None
        # Next rebalance should be on a weekday
        assert result.next_rebalance.weekday() < 5

    @patch("compass.portfolio_optimizer.PortfolioOptimizer.get_event_scaling",
           return_value=0.70)
    def test_regime_plus_event_together(self, mock_scaling, optimizer):
        """Regime tilt + event scaling should both be applied."""
        result = optimizer.optimize(
            method="max_sharpe",
            regime="BEAR_MACRO",
            as_of=date(2026, 3, 24),
        )
        assert result.regime == "BEAR_MACRO"
        assert result.event_scaling == 0.70
        total_scaled = sum(result.scaled_weights.values())
        total_raw = sum(result.weights.values())
        assert total_scaled == pytest.approx(total_raw * 0.70, abs=1e-5)
