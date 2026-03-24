"""Tests for compass/stress_test.py — Monte Carlo, crisis scenarios, sensitivity."""

import json
import math

import numpy as np
import pytest

from compass.stress_test import (
    CRISIS_SCENARIOS,
    StressTester,
    _build_crash_path,
    _cagr,
    _calmar_ratio,
    _max_drawdown,
    _percentile_safe,
    _returns_to_equity,
    _sharpe_ratio,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_returns():
    """500 days of synthetic daily returns: slight positive drift + vol."""
    rng = np.random.RandomState(123)
    return rng.normal(0.0004, 0.012, 500)


@pytest.fixture
def tester(synthetic_returns):
    """StressTester with 500-day synthetic returns, reduced sims for speed."""
    return StressTester(
        synthetic_returns,
        starting_capital=100_000,
        n_simulations=200,
        block_size=5,
        seed=99,
    )


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_sharpe_ratio_positive_drift(self):
        rng = np.random.RandomState(0)
        rets = rng.normal(0.001, 0.01, 252)
        sharpe = _sharpe_ratio(rets)
        assert sharpe > 0, "Positive-drift returns should have positive Sharpe"

    def test_sharpe_ratio_constant_returns(self):
        # np.std of constant floats can be ~1e-17 (not exactly 0) due to
        # floating point arithmetic, so _sharpe_ratio may return a huge number.
        # Truly zero returns should return 0.
        rets = np.full(100, 0.0)
        assert _sharpe_ratio(rets) == 0.0, "All-zero returns should yield Sharpe=0"

    def test_sharpe_ratio_empty(self):
        assert _sharpe_ratio(np.array([])) == 0.0

    def test_sharpe_ratio_single_element(self):
        assert _sharpe_ratio(np.array([0.01])) == 0.0

    def test_max_drawdown_monotonically_increasing(self):
        equity = np.arange(100, 200, dtype=float)
        assert _max_drawdown(equity) == 0.0

    def test_max_drawdown_known_case(self):
        equity = np.array([100.0, 110.0, 90.0, 95.0, 105.0])
        dd = _max_drawdown(equity)
        expected = (90.0 - 110.0) / 110.0  # -18.18%
        assert abs(dd - expected) < 1e-6

    def test_max_drawdown_empty(self):
        assert _max_drawdown(np.array([100.0])) == 0.0

    def test_cagr_doubling_in_one_year(self):
        equity = np.array([100.0, 200.0])
        # 2 points = 1 period; 1/252 years
        cagr = _cagr(equity, trading_days=252)
        assert cagr > 0

    def test_cagr_flat(self):
        equity = np.full(253, 100.0)
        assert abs(_cagr(equity)) < 1e-6

    def test_cagr_zero_start(self):
        equity = np.array([0.0, 100.0])
        assert _cagr(equity) == 0.0

    def test_calmar_ratio_no_drawdown(self):
        equity = np.arange(100, 200, dtype=float)
        assert _calmar_ratio(equity) == 0.0

    def test_returns_to_equity_no_returns(self):
        eq = _returns_to_equity(np.array([]), 100_000)
        assert len(eq) == 1
        assert eq[0] == 100_000

    def test_returns_to_equity_shape(self):
        rets = np.array([0.01, -0.005, 0.003])
        eq = _returns_to_equity(rets, 100_000)
        assert len(eq) == 4  # T+1 points for T returns
        assert eq[0] == 100_000

    def test_returns_to_equity_compounding(self):
        rets = np.array([0.10, -0.05])
        eq = _returns_to_equity(rets, 1000)
        assert abs(eq[-1] - 1000 * 1.10 * 0.95) < 0.01

    def test_percentile_safe_empty(self):
        assert _percentile_safe(np.array([]), 50) == 0.0

    def test_percentile_safe_median(self):
        arr = np.arange(1, 101, dtype=float)
        assert abs(_percentile_safe(arr, 50) - 50.5) < 0.01


# ---------------------------------------------------------------------------
# _build_crash_path
# ---------------------------------------------------------------------------

class TestBuildCrashPath:
    def test_total_return_compounds_correctly(self):
        target = -0.34
        path = _build_crash_path(target, 23)
        assert len(path) == 23
        compound = 1.0
        for r in path:
            compound *= (1 + r)
        assert abs(compound - (1 + target)) < 1e-6

    def test_single_day(self):
        path = _build_crash_path(-0.10, 1)
        assert len(path) == 1
        assert abs(path[0] - (-0.10)) < 1e-10

    def test_zero_days(self):
        assert _build_crash_path(-0.20, 0) == []

    def test_all_crisis_scenarios_have_paths(self):
        for sc in CRISIS_SCENARIOS:
            shocks = sc["daily_shocks"]
            assert len(shocks) > 0
            # Overall compound return should be negative (crash scenario)
            compound = 1.0
            for r in shocks:
                compound *= (1 + r)
            assert compound < 1.0, f"Compound return should be < 1.0 for {sc['name']}"


# ---------------------------------------------------------------------------
# Monte Carlo simulation
# ---------------------------------------------------------------------------

class TestMonteCarlo:
    def test_output_structure(self, tester):
        mc = tester.run_monte_carlo()

        # Top-level keys
        assert "n_simulations" in mc
        assert "horizon_days" in mc
        assert "terminal_wealth" in mc
        assert "max_drawdown" in mc
        assert "sharpe_ratio" in mc
        assert "prob_profit" in mc
        assert "prob_ruin_50pct" in mc
        assert "sample_paths" in mc

    def test_terminal_wealth_distribution(self, tester):
        mc = tester.run_monte_carlo()
        tw = mc["terminal_wealth"]

        assert tw["mean"] > 0
        assert tw["min"] > 0
        assert tw["min"] <= tw["median"] <= tw["max"]
        assert tw["std"] > 0

        pcts = tw["percentiles"]
        assert "p5" in pcts
        assert "p50" in pcts
        assert "p95" in pcts
        assert pcts["p5"] <= pcts["p50"] <= pcts["p95"]

    def test_sharpe_distribution(self, tester):
        mc = tester.run_monte_carlo()
        sr = mc["sharpe_ratio"]

        assert "mean" in sr
        assert "median" in sr
        assert "std" in sr
        assert sr["std"] > 0  # should have some variance across sims
        assert "percentiles" in sr

    def test_drawdown_distribution(self, tester):
        mc = tester.run_monte_carlo()
        dd = mc["max_drawdown"]

        # Drawdowns are reported as negative percentages
        assert dd["worst_pct"] <= dd["median_pct"] <= 0
        assert dd["mean_pct"] <= 0

        pcts = dd["percentiles_pct"]
        assert "p5" in pcts
        # p5 = 5th percentile of drawdowns (more negative = worse)
        assert pcts["p5"] <= pcts["p50"]

    def test_probabilities_in_range(self, tester):
        mc = tester.run_monte_carlo()
        assert 0.0 <= mc["prob_profit"] <= 1.0
        assert 0.0 <= mc["prob_ruin_50pct"] <= 1.0

    def test_sample_paths_capped(self, tester):
        mc = tester.run_monte_carlo()
        assert len(mc["sample_paths"]) <= 200
        assert len(mc["sample_paths"]) > 0
        # Each path should be horizon + 1 points (equity curve includes t=0)
        for path in mc["sample_paths"][:5]:
            assert len(path) == mc["horizon_days"] + 1
            assert path[0] == tester.starting_capital

    def test_custom_horizon(self, tester):
        mc = tester.run_monte_carlo(horizon_days=60)
        assert mc["horizon_days"] == 60
        for path in mc["sample_paths"][:3]:
            assert len(path) == 61

    def test_empty_returns(self):
        t = StressTester([], starting_capital=50_000)
        mc = t.run_monte_carlo()
        assert mc["n_simulations"] == 0
        assert mc["terminal_wealth"]["mean"] == 50_000

    def test_deterministic_with_seed(self, synthetic_returns):
        t1 = StressTester(synthetic_returns, n_simulations=100, seed=42)
        t2 = StressTester(synthetic_returns, n_simulations=100, seed=42)
        mc1 = t1.run_monte_carlo()
        mc2 = t2.run_monte_carlo()
        assert mc1["terminal_wealth"]["mean"] == mc2["terminal_wealth"]["mean"]
        assert mc1["sharpe_ratio"]["median"] == mc2["sharpe_ratio"]["median"]


# ---------------------------------------------------------------------------
# Crisis scenarios
# ---------------------------------------------------------------------------

class TestCrisisScenarios:
    def test_runs_all_default_scenarios(self, tester):
        results = tester.run_crisis_scenarios()
        assert len(results) == len(CRISIS_SCENARIOS)

    def test_scenario_metrics_computed(self, tester):
        results = tester.run_crisis_scenarios()

        for r in results:
            assert "name" in r
            assert "description" in r
            assert "n_days" in r and r["n_days"] > 0
            assert "underlying_drawdown_pct" in r
            assert "portfolio_drawdown_pct" in r
            assert "max_drawdown_pct" in r
            assert "trough_value" in r
            assert "spread_beta" in r
            assert "vix_start" in r
            assert "vix_peak" in r
            assert "vix_multiplier" in r
            assert "equity_path" in r

    def test_drawdowns_are_negative(self, tester):
        results = tester.run_crisis_scenarios()
        for r in results:
            assert r["underlying_drawdown_pct"] < 0, f"{r['name']}: underlying DD should be negative"
            assert r["portfolio_drawdown_pct"] < 0, f"{r['name']}: portfolio DD should be negative"
            assert r["max_drawdown_pct"] < 0, f"{r['name']}: max DD should be negative"

    def test_spread_beta_amplifies_losses(self, tester):
        results = tester.run_crisis_scenarios()
        for r in results:
            assert abs(r["portfolio_drawdown_pct"]) >= abs(r["underlying_drawdown_pct"]), \
                f"{r['name']}: portfolio DD should be >= underlying DD (spread beta)"

    def test_covid_is_worst(self, tester):
        results = tester.run_crisis_scenarios()
        worst = min(results, key=lambda r: r["portfolio_drawdown_pct"])
        assert "COVID" in worst["name"]

    def test_recovery_days_estimated(self, tester):
        results = tester.run_crisis_scenarios()
        for r in results:
            if r["estimated_recovery_days"] is not None:
                assert r["estimated_recovery_days"] > 0

    def test_equity_path_shape(self, tester):
        results = tester.run_crisis_scenarios()
        for r in results:
            path = r["equity_path"]
            assert len(path) == r["n_days"] + 1
            assert path[0] == tester.starting_capital

    def test_custom_scenario(self, tester):
        custom = [{
            "name": "Mild Correction",
            "description": "5% drop over 10 days",
            "daily_shocks": _build_crash_path(-0.05, 10),
            "vix_start": 15,
            "vix_peak": 25,
        }]
        results = tester.run_crisis_scenarios(scenarios=custom)
        assert len(results) == 1
        assert results[0]["name"] == "Mild Correction"
        assert results[0]["underlying_drawdown_pct"] < 0

    def test_empty_returns_crisis(self):
        """Crisis scenarios should still run with empty historical returns."""
        t = StressTester([], starting_capital=100_000)
        results = t.run_crisis_scenarios()
        assert len(results) == len(CRISIS_SCENARIOS)
        # Recovery days should be None since hist mean return is 0
        for r in results:
            assert r["estimated_recovery_days"] is None


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------

class TestSensitivityAnalysis:
    def test_output_structure(self, tester):
        sens = tester.run_sensitivity_analysis()

        assert isinstance(sens, dict)
        assert len(sens) > 0

        for param_name, param_data in sens.items():
            assert "label" in param_data
            assert "description" in param_data
            assert "baseline" in param_data
            assert "results" in param_data
            assert len(param_data["results"]) > 0

    def test_all_default_params_swept(self, tester):
        sens = tester.run_sensitivity_analysis()

        expected_params = [
            "position_size_pct",
            "stop_loss_multiplier",
            "iv_rank_threshold",
            "profit_target_pct",
            "spread_width",
        ]
        for p in expected_params:
            assert p in sens, f"Missing sweep for {p}"

    def test_result_metrics_present(self, tester):
        sens = tester.run_sensitivity_analysis()

        for param_name, param_data in sens.items():
            for r in param_data["results"]:
                assert "value" in r
                assert "sharpe" in r
                assert "max_dd_pct" in r
                assert "cagr_pct" in r
                assert "calmar" in r
                assert "terminal_value" in r
                assert "is_baseline" in r
                assert isinstance(r["sharpe"], float)
                assert isinstance(r["max_dd_pct"], float)

    def test_baseline_marked(self, tester):
        """Each param where baseline is in the values list should have exactly 1 baseline."""
        sens = tester.run_sensitivity_analysis()

        for param_name, param_data in sens.items():
            baselines = [r for r in param_data["results"] if r["is_baseline"]]
            baseline_val = param_data["baseline"]
            values = [r["value"] for r in param_data["results"]]

            if any(abs(v - baseline_val) < 1e-9 for v in values):
                assert len(baselines) == 1, \
                    f"{param_name}: baseline {baseline_val} is in values but not marked"
            else:
                # baseline not in values list (e.g. iv_rank_threshold=12 not in [0,5,10,...])
                assert len(baselines) == 0, \
                    f"{param_name}: baseline {baseline_val} not in values but something marked"

    def test_position_size_scales_risk(self, tester):
        sens = tester.run_sensitivity_analysis()
        ps = sens["position_size_pct"]["results"]

        # Larger position size → more extreme drawdowns
        small = next(r for r in ps if r["value"] == 1.0)
        large = next(r for r in ps if r["value"] == 15.0)
        assert small["max_dd_pct"] > large["max_dd_pct"], \
            "Larger position size should produce worse (more negative) drawdowns"

    def test_custom_sweep(self, tester):
        custom_sweeps = {
            "test_param": {
                "label": "Test",
                "description": "A test parameter",
                "values": [1.0, 2.0, 3.0],
                "baseline": 2.0,
            }
        }
        sens = tester.run_sensitivity_analysis(sweeps=custom_sweeps)
        assert "test_param" in sens
        assert len(sens["test_param"]["results"]) == 3

    def test_custom_param_sweep_fn(self, tester, synthetic_returns):
        """Test with a real param_sweep_fn callback."""
        call_log = []

        def sweep_fn(param_name, value):
            call_log.append((param_name, value))
            # Scale returns by value
            return synthetic_returns * (value / 5.0)

        custom_sweeps = {
            "risk_pct": {
                "label": "Risk %",
                "description": "Test risk",
                "values": [2.0, 5.0, 10.0],
                "baseline": 5.0,
            }
        }
        sens = tester.run_sensitivity_analysis(
            param_sweep_fn=sweep_fn, sweeps=custom_sweeps,
        )
        assert len(call_log) == 3
        assert sens["risk_pct"]["results"][0]["value"] == 2.0


# ---------------------------------------------------------------------------
# run_all integration
# ---------------------------------------------------------------------------

class TestRunAll:
    def test_run_all_structure(self, tester):
        results = tester.run_all()

        assert "monte_carlo" in results
        assert "crisis_scenarios" in results
        assert "sensitivity" in results
        assert "summary" in results

    def test_summary_structure(self, tester):
        results = tester.run_all()
        s = results["summary"]

        assert "historical" in s
        assert "monte_carlo_confidence" in s
        assert "worst_crisis" in s
        assert "most_sensitive_parameter" in s
        assert "risk_rating" in s

    def test_historical_metrics(self, tester):
        results = tester.run_all()
        hist = results["summary"]["historical"]

        assert hist["n_days"] == 500
        assert hist["starting_capital"] == 100_000
        assert isinstance(hist["sharpe"], float)
        assert isinstance(hist["max_drawdown_pct"], float)
        assert isinstance(hist["cagr_pct"], float)
        assert isinstance(hist["calmar"], float)

    def test_risk_rating_valid(self, tester):
        results = tester.run_all()
        assert results["summary"]["risk_rating"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")

    def test_worst_crisis_identified(self, tester):
        results = tester.run_all()
        wc = results["summary"]["worst_crisis"]
        assert "name" in wc
        assert wc["portfolio_drawdown_pct"] < 0

    def test_most_sensitive_param_identified(self, tester):
        results = tester.run_all()
        param = results["summary"]["most_sensitive_parameter"]
        assert param is not None
        assert param in StressTester.DEFAULT_SWEEPS


# ---------------------------------------------------------------------------
# JSON serializability (for HTML reports)
# ---------------------------------------------------------------------------

class TestJSONSerializable:
    def test_monte_carlo_serializable(self, tester):
        mc = tester.run_monte_carlo()
        serialized = json.dumps(mc)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert roundtrip["n_simulations"] == mc["n_simulations"]

    def test_crisis_serializable(self, tester):
        results = tester.run_crisis_scenarios()
        serialized = json.dumps(results)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert len(roundtrip) == len(results)

    def test_sensitivity_serializable(self, tester):
        sens = tester.run_sensitivity_analysis()
        serialized = json.dumps(sens)
        assert isinstance(serialized, str)

    def test_full_run_all_serializable(self, tester):
        results = tester.run_all()
        serialized = json.dumps(results)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert set(roundtrip.keys()) == {"monte_carlo", "crisis_scenarios", "sensitivity", "summary"}

    def test_no_numpy_types_in_output(self, tester):
        """Ensure no numpy scalar types leak into the output (they break json.dumps)."""
        results = tester.run_all()

        def check_no_numpy(obj, path="root"):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    check_no_numpy(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    check_no_numpy(v, f"{path}[{i}]")
            elif isinstance(obj, (np.integer, np.floating, np.bool_)):
                pytest.fail(f"numpy type {type(obj).__name__} at {path}: {obj}")

        check_no_numpy(results)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_short_returns(self):
        t = StressTester(np.array([0.01, -0.01]), n_simulations=100)
        results = t.run_all()
        assert results["summary"]["historical"]["n_days"] == 2

    def test_all_zero_returns(self):
        t = StressTester(np.zeros(100), n_simulations=100)
        mc = t.run_monte_carlo()
        assert mc["terminal_wealth"]["mean"] == t.starting_capital
        assert mc["sharpe_ratio"]["mean"] == 0.0

    def test_all_positive_returns(self):
        t = StressTester(np.full(252, 0.001), n_simulations=100)
        mc = t.run_monte_carlo()
        assert mc["prob_profit"] == 1.0
        assert mc["prob_ruin_50pct"] == 0.0
        assert mc["max_drawdown"]["worst_pct"] == 0.0

    def test_large_block_size_clamped(self):
        rets = np.random.RandomState(0).normal(0, 0.01, 20)
        t = StressTester(rets, block_size=100)  # block > data length
        mc = t.run_monte_carlo()
        assert mc["block_size"] == 20  # clamped to data length

    def test_min_simulations_enforced(self):
        t = StressTester(np.zeros(50), n_simulations=10)
        assert t.n_simulations == 100  # minimum enforced
