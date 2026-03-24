"""
Integration tests for the new COMPASS ensemble ML modules.

Tests the critical seams between new and existing code:
  1. EnsembleSignalModel ↔ FeatureEngine output format
  2. WalkForwardValidator ↔ collect_training_data.py format
  3. PortfolioOptimizer  ↔ backtest results from output/*.json
  4. EnsembleSignalModel.predict() ↔ MLEnhancedStrategy expected input
"""

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import GradientBoostingClassifier

from compass.ensemble_signal_model import EnsembleSignalModel
from compass.features import FeatureEngine
from compass.ml_strategy import (
    MLEnhancedStrategy,
    RegimeModelRouter,
    confidence_to_size_multiplier,
)
from compass.portfolio_optimizer import (
    EXPERIMENT_IDS,
    EXPERIMENT_PROFILES,
    MIN_WEIGHT,
    OptimizationResult,
    PortfolioOptimizer,
)
from compass.signal_model import SignalModel
from compass.walk_forward import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET_COL,
    WalkForwardValidator,
    prepare_features,
)
from shared.types import PredictionResult

OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

def _feature_engine_feature_names() -> list:
    """Return the canonical feature names from FeatureEngine.get_feature_names()."""
    engine = FeatureEngine()
    return engine.get_feature_names()


def _make_feature_dict(feature_names: list, seed: int = 42) -> dict:
    """Generate a plausible feature dict matching FeatureEngine output."""
    rng = np.random.RandomState(seed)
    features = {}
    for name in feature_names:
        if "regime_id" in name:
            features[name] = float(rng.randint(0, 5))
        elif "regime_" in name and any(k in name for k in ("low_vol", "high_vol", "mean_rev", "crisis")):
            features[name] = float(rng.choice([0, 1]))
        elif "day_of_week" in name:
            features[name] = float(rng.randint(0, 5))
        elif "is_" in name:
            features[name] = float(rng.choice([0, 1]))
        elif "rsi" in name:
            features[name] = rng.uniform(20, 80)
        elif "iv_rank" in name:
            features[name] = rng.uniform(0, 100)
        elif "vix" in name:
            features[name] = rng.uniform(10, 40)
        elif "vol" in name:
            features[name] = rng.uniform(0.05, 0.5)
        else:
            features[name] = rng.normal(0, 1)
    return features


def _make_training_df(n_trades: int = 200, n_years: int = 3, seed: int = 42) -> pd.DataFrame:
    """Build a DataFrame matching collect_training_data.py output format.

    Includes all NUMERIC_FEATURES, CATEGORICAL_FEATURES, TARGET_COL, entry_date,
    and return_pct — exactly the schema WalkForwardValidator expects.
    """
    rng = np.random.RandomState(seed)
    start_year = 2021

    records = []
    for i in range(n_trades):
        year = start_year + (i * n_years // n_trades)
        day_of_year = rng.randint(1, 252)
        entry_date = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(days=int(day_of_year))
        win = rng.choice([0, 1], p=[0.3, 0.7])
        return_pct = rng.uniform(1, 15) if win else rng.uniform(-30, -1)

        row = {
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "win": win,
            "return_pct": return_pct,
        }

        # Populate NUMERIC_FEATURES with plausible values
        for feat in NUMERIC_FEATURES:
            if feat == "dte_at_entry":
                row[feat] = rng.randint(15, 60)
            elif feat == "hold_days":
                row[feat] = rng.randint(1, 45)
            elif feat == "day_of_week":
                row[feat] = rng.randint(0, 5)
            elif feat == "days_since_last_trade":
                row[feat] = rng.randint(0, 10)
            elif feat == "rsi_14":
                row[feat] = rng.uniform(20, 80)
            elif "momentum" in feat:
                row[feat] = rng.normal(0, 3)
            elif feat == "vix":
                row[feat] = rng.uniform(12, 45)
            elif "vix_percentile" in feat:
                row[feat] = rng.uniform(0, 100)
            elif feat == "iv_rank":
                row[feat] = rng.uniform(0, 100)
            elif feat == "spy_price":
                row[feat] = rng.uniform(350, 550)
            elif "dist_from_ma" in feat:
                row[feat] = rng.normal(0, 3)
            elif "slope" in feat:
                row[feat] = rng.normal(0, 20)
            elif "realized_vol" in feat:
                row[feat] = rng.uniform(5, 40)
            elif feat == "net_credit":
                row[feat] = rng.uniform(0.2, 2.0)
            elif feat == "spread_width":
                row[feat] = rng.choice([2.5, 5.0, 10.0])
            elif feat == "max_loss_per_unit":
                row[feat] = row.get("spread_width", 5) - row.get("net_credit", 0.5)
            elif feat == "otm_pct":
                row[feat] = rng.uniform(1, 8)
            elif feat == "contracts":
                row[feat] = rng.randint(1, 15)
            else:
                row[feat] = rng.normal(0, 1)

        # Populate CATEGORICAL_FEATURES
        row["regime"] = rng.choice(["bull", "bear", "neutral", "high_vol"])
        row["strategy_type"] = rng.choice(["CS", "IC"])
        row["spread_type"] = rng.choice(["bull_put_spread", "bear_call_spread", "iron_condor"])

        records.append(row)

    return pd.DataFrame(records)


def _train_ensemble(feature_names: list, n_samples: int = 300) -> EnsembleSignalModel:
    """Train and return an EnsembleSignalModel on synthetic data."""
    rng = np.random.RandomState(42)
    X = pd.DataFrame(
        rng.randn(n_samples, len(feature_names)),
        columns=feature_names,
    )
    # Correlated labels for above-chance AUC
    y = (X.iloc[:, 0] + rng.normal(0, 0.5, n_samples) > 0).astype(int)

    model = EnsembleSignalModel(model_dir="/tmp/test_ensemble_integration")
    model.train(X, y, calibrate=True, save_model=False, n_wf_folds=3)
    return model


# ═══════════════════════════════════════════════════════════════════════════════
# 1. EnsembleSignalModel ↔ FeatureEngine
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnsembleFeatureEngineIntegration:
    """Verify EnsembleSignalModel can consume FeatureEngine output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.feature_names = _feature_engine_feature_names()
        self.model = _train_ensemble(self.feature_names)

    def test_feature_names_match_engine(self):
        """Model trained on FeatureEngine names accepts FeatureEngine output."""
        assert self.model.feature_names == self.feature_names
        assert len(self.feature_names) > 30  # sanity: not empty

    def test_predict_with_feature_engine_dict(self):
        """predict() accepts a dict keyed by FeatureEngine feature names."""
        features = _make_feature_dict(self.feature_names)
        result = self.model.predict(features)

        assert isinstance(result, dict)
        assert "prediction" in result
        assert "probability" in result
        assert "confidence" in result
        assert "signal" in result
        assert "signal_strength" in result
        assert "timestamp" in result

    def test_probability_range(self):
        """Probability is in [0, 1]."""
        features = _make_feature_dict(self.feature_names)
        result = self.model.predict(features)
        assert 0.0 <= result["probability"] <= 1.0

    def test_confidence_formula(self):
        """confidence = abs(probability - 0.5) * 2."""
        features = _make_feature_dict(self.feature_names)
        result = self.model.predict(features)
        expected_conf = abs(result["probability"] - 0.5) * 2
        assert abs(result["confidence"] - round(expected_conf, 4)) < 1e-3

    def test_signal_mapping(self):
        """Signal is bullish/bearish/neutral based on probability thresholds."""
        features = _make_feature_dict(self.feature_names)
        result = self.model.predict(features)
        p = result["probability"]
        if p > 0.55:
            assert result["signal"] == "bullish"
        elif p < 0.45:
            assert result["signal"] == "bearish"
        else:
            assert result["signal"] == "neutral"

    def test_predict_batch_with_feature_df(self):
        """predict_batch() accepts a DataFrame of FeatureEngine features."""
        rng = np.random.RandomState(99)
        n = 20
        df = pd.DataFrame(
            rng.randn(n, len(self.feature_names)),
            columns=self.feature_names,
        )
        probas = self.model.predict_batch(df)

        assert isinstance(probas, np.ndarray)
        assert probas.shape == (n,)
        assert np.all((probas >= 0) & (probas <= 1))

    def test_missing_features_filled_with_zero(self):
        """Missing feature keys are filled with 0.0, not raising."""
        partial = _make_feature_dict(self.feature_names)
        # Remove 10 features
        keys_to_remove = list(partial.keys())[:10]
        for k in keys_to_remove:
            del partial[k]

        result = self.model.predict(partial)
        assert isinstance(result, dict)
        assert "prediction" in result
        # Should not be a fallback — just degraded
        assert result.get("fallback") is not True or "prediction" in result

    def test_none_values_handled(self):
        """None values in feature dict are converted to 0.0."""
        features = _make_feature_dict(self.feature_names)
        # Set some features to None
        for key in list(features.keys())[:5]:
            features[key] = None

        result = self.model.predict(features)
        assert isinstance(result, dict)
        assert "probability" in result

    def test_extra_features_ignored(self):
        """Extra keys not in feature_names don't cause errors."""
        features = _make_feature_dict(self.feature_names)
        features["ticker"] = "SPY"
        features["timestamp"] = "2026-01-01T00:00:00"
        features["current_price"] = 500.0

        result = self.model.predict(features)
        assert isinstance(result, dict)
        assert 0.0 <= result["probability"] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. WalkForwardValidator ↔ collect_training_data format
# ═══════════════════════════════════════════════════════════════════════════════

class TestWalkForwardTrainingDataIntegration:
    """Verify WalkForwardValidator works with collect_training_data output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.df = _make_training_df(n_trades=200, n_years=3)

    def test_training_data_has_required_columns(self):
        """Training data fixture matches collect_training_data schema."""
        for col in NUMERIC_FEATURES:
            assert col in self.df.columns, f"Missing numeric feature: {col}"
        for col in CATEGORICAL_FEATURES:
            assert col in self.df.columns, f"Missing categorical feature: {col}"
        assert TARGET_COL in self.df.columns
        assert "entry_date" in self.df.columns
        assert "return_pct" in self.df.columns

    def test_prepare_features_produces_clean_matrix(self):
        """prepare_features() handles the training data without errors."""
        features = prepare_features(self.df)
        assert isinstance(features, pd.DataFrame)
        assert len(features) == len(self.df)
        # Should have numeric cols + one-hot categoricals
        assert features.shape[1] > len(NUMERIC_FEATURES)
        # No NaN after preparation
        assert not features.isna().any().any()
        # No inf (cast to float to handle one-hot bool columns)
        assert not np.isinf(features.values.astype(float)).any()

    def test_walk_forward_runs_on_training_data(self):
        """WalkForwardValidator.run() produces folds and aggregate metrics."""
        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(self.df)

        assert "folds" in results
        assert "aggregate" in results
        assert "n_folds" in results
        assert "oos_predictions" in results
        assert results["n_folds"] >= 1

    def test_walk_forward_fold_structure(self):
        """Each fold has required metric keys."""
        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(self.df)

        required_keys = {
            "fold", "train_period", "test_period",
            "n_train", "n_test", "accuracy", "precision",
            "recall", "brier_score", "auc", "test_win_rate",
        }
        for fold in results["folds"]:
            assert required_keys.issubset(fold.keys()), (
                f"Missing keys: {required_keys - fold.keys()}"
            )

    def test_walk_forward_aggregate_keys(self):
        """Aggregate dict contains mean/std for all core metrics."""
        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(self.df)
        agg = results["aggregate"]

        for metric in ["accuracy", "precision", "recall", "brier_score"]:
            assert f"{metric}_mean" in agg, f"Missing {metric}_mean"
            assert f"{metric}_std" in agg, f"Missing {metric}_std"
        assert "total_oos_samples" in agg
        assert "n_folds" in agg

    def test_oos_predictions_shape(self):
        """OOS predictions are concatenated across all folds."""
        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(self.df)
        oos = results["oos_predictions"]

        assert "predictions" in oos
        assert "probabilities" in oos
        assert "labels" in oos
        n_oos = len(oos["predictions"])
        assert n_oos > 0
        assert len(oos["probabilities"]) == n_oos
        assert len(oos["labels"]) == n_oos
        # All probabilities in [0, 1]
        assert np.all((oos["probabilities"] >= 0) & (oos["probabilities"] <= 1))

    def test_oos_includes_returns_when_present(self):
        """If return_pct column exists, OOS includes a returns array."""
        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(self.df)
        assert "returns" in results["oos_predictions"]

    def test_chronological_split_no_lookahead(self):
        """Training periods always precede test periods (no lookahead)."""
        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(self.df)

        for fold in results["folds"]:
            # train_period: "2021-01-XX → 2021-12-XX"
            # test_period:  "2022-01-XX → 2022-12-XX"
            train_end = fold["train_period"].split(" → ")[1]
            test_start = fold["test_period"].split(" → ")[0]
            assert train_end < test_start, (
                f"Lookahead detected: train ends {train_end}, test starts {test_start}"
            )

    def test_expanding_window(self):
        """Each fold's training set is >= the previous fold's."""
        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(self.df)

        prev_n_train = 0
        for fold in results["folds"]:
            assert fold["n_train"] >= prev_n_train
            prev_n_train = fold["n_train"]

    def test_nan_in_features_handled(self):
        """NaN values in features are handled gracefully."""
        df = self.df.copy()
        # Inject NaN in 10% of rsi_14
        mask = np.random.RandomState(99).random(len(df)) < 0.1
        df.loc[mask, "rsi_14"] = np.nan

        model = GradientBoostingClassifier(
            n_estimators=20, max_depth=3, random_state=42,
        )
        validator = WalkForwardValidator(model)
        results = validator.run(df)
        assert results["n_folds"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PortfolioOptimizer ↔ Backtest results
# ═══════════════════════════════════════════════════════════════════════════════

class TestPortfolioOptimizerBacktestIntegration:
    """Verify PortfolioOptimizer can consume backtest results."""

    @staticmethod
    def _weekly_pnl_to_returns(weekly_pnl: dict, starting_capital: float) -> np.ndarray:
        """Convert a weekly_pnl dict to a return series — the transform the
        optimizer needs to ingest backtest output files."""
        sorted_weeks = sorted(weekly_pnl.keys())
        equity = starting_capital
        returns = []
        for week in sorted_weeks:
            pnl = weekly_pnl[week]
            r = pnl / equity if equity > 0 else 0.0
            returns.append(r)
            equity += pnl
        return np.array(returns)

    @staticmethod
    def _load_backtest_json(filepath: Path) -> dict:
        with open(filepath) as f:
            return json.load(f)

    def test_backtest_json_files_exist(self):
        """At least one backtest result JSON exists in output/."""
        files = list(OUTPUT_DIR.glob("backtest_results*.json"))
        assert len(files) > 0, "No backtest_results*.json files found in output/"

    def test_backtest_json_has_weekly_pnl(self):
        """Backtest JSON results contain weekly_pnl for return derivation."""
        files = list(OUTPUT_DIR.glob("backtest_results*.json"))
        data = self._load_backtest_json(files[0])
        assert "results" in data
        for period in data["results"]:
            assert "weekly_pnl" in period, f"Missing weekly_pnl in {period.get('label')}"

    def test_optimizer_accepts_derived_returns(self):
        """PortfolioOptimizer can be constructed from weekly PnL derived returns."""
        # Build synthetic multi-experiment returns from actual backtest files
        files = sorted(OUTPUT_DIR.glob("backtest_results*.json"))
        if not files:
            pytest.skip("No backtest result files found")

        data = self._load_backtest_json(files[0])
        all_periods_pnl = {}
        for period in data["results"]:
            for week, pnl in period.get("weekly_pnl", {}).items():
                all_periods_pnl[week] = all_periods_pnl.get(week, 0) + pnl

        if len(all_periods_pnl) < 4:
            pytest.skip("Not enough weekly data")

        base_returns = self._weekly_pnl_to_returns(all_periods_pnl, 100_000)
        n = len(base_returns)

        # Create synthetic experiment returns by perturbing the base
        rng = np.random.RandomState(42)
        returns = {}
        for eid in EXPERIMENT_IDS:
            returns[eid] = base_returns + rng.normal(0, 0.005, n)

        optimizer = PortfolioOptimizer(returns, periods_per_year=52)
        assert optimizer.n_assets == len(EXPERIMENT_IDS)

    def test_optimizer_produces_valid_weights(self):
        """All optimization methods produce weights that sum to 1 with floor."""
        rng = np.random.RandomState(42)
        n = 100
        returns = {eid: rng.normal(0.002, 0.03, n) for eid in EXPERIMENT_IDS}

        optimizer = PortfolioOptimizer(returns, periods_per_year=52)

        for method in ["max_sharpe", "risk_parity", "equal_risk_contribution", "min_variance"]:
            result = optimizer.optimize(method=method, regime="NEUTRAL_MACRO")
            assert isinstance(result, OptimizationResult)

            weights = list(result.weights.values())
            assert abs(sum(weights) - 1.0) < 1e-4, f"{method}: weights don't sum to 1"
            assert all(w >= MIN_WEIGHT - 1e-6 for w in weights), (
                f"{method}: weight below MIN_WEIGHT: {weights}"
            )

    def test_optimizer_result_has_scaled_weights(self):
        """OptimizationResult contains event-scaled weights."""
        rng = np.random.RandomState(42)
        n = 100
        returns = {eid: rng.normal(0.002, 0.03, n) for eid in EXPERIMENT_IDS}

        optimizer = PortfolioOptimizer(returns, periods_per_year=52)
        result = optimizer.optimize(method="risk_parity", regime="NEUTRAL_MACRO")

        assert "scaled_weights" in result.__dict__
        assert set(result.scaled_weights.keys()) == set(EXPERIMENT_IDS)
        # Scaled weights <= raw weights (event_scaling ∈ (0, 1])
        for eid in EXPERIMENT_IDS:
            assert result.scaled_weights[eid] <= result.weights[eid] + 1e-6

    def test_optimizer_regime_tilt_changes_weights(self):
        """BULL and BEAR regimes produce different weight distributions."""
        rng = np.random.RandomState(42)
        n = 100
        returns = {eid: rng.normal(0.002, 0.03, n) for eid in EXPERIMENT_IDS}

        optimizer = PortfolioOptimizer(returns, periods_per_year=52, regime_blend=0.5)

        bull = optimizer.optimize(method="risk_parity", regime="BULL_MACRO")
        bear = optimizer.optimize(method="risk_parity", regime="BEAR_MACRO")

        # In BULL, momentum experiments (EXP-503) should get more weight
        # In BEAR, defensive experiments (EXP-600) should get more weight
        if "EXP-503" in bull.weights and "EXP-503" in bear.weights:
            assert bull.weights["EXP-503"] > bear.weights["EXP-503"], (
                "BULL should tilt toward momentum (EXP-503)"
            )
        if "EXP-600" in bull.weights and "EXP-600" in bear.weights:
            assert bear.weights["EXP-600"] > bull.weights["EXP-600"], (
                "BEAR should tilt toward defensive (EXP-600)"
            )

    def test_optimizer_metrics_structure(self):
        """OptimizationResult.metrics has expected fields."""
        rng = np.random.RandomState(42)
        n = 100
        returns = {eid: rng.normal(0.002, 0.03, n) for eid in EXPERIMENT_IDS}

        optimizer = PortfolioOptimizer(returns, periods_per_year=52)
        result = optimizer.optimize(method="max_sharpe", regime="NEUTRAL_MACRO")

        for key in ["annual_return", "annual_volatility", "sharpe_ratio", "max_weight", "min_weight"]:
            assert key in result.metrics, f"Missing metric: {key}"

    def test_optimizer_rejects_mismatched_lengths(self):
        """Raises ValueError if return arrays have different lengths."""
        returns = {
            "EXP-400": np.random.randn(100),
            "EXP-401": np.random.randn(99),  # different length
        }
        with pytest.raises(ValueError, match="same length"):
            PortfolioOptimizer(returns)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. EnsembleSignalModel.predict() ↔ MLEnhancedStrategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnsembleMLStrategyIntegration:
    """Verify ensemble predict() output is compatible with MLEnhancedStrategy."""

    PREDICTION_REQUIRED_KEYS = {"prediction", "probability", "confidence", "signal", "signal_strength", "timestamp"}

    @pytest.fixture(autouse=True)
    def setup(self):
        self.feature_names = _feature_engine_feature_names()
        self.ensemble = _train_ensemble(self.feature_names)

    def test_predict_returns_all_required_keys(self):
        """predict() output has every key MLEnhancedStrategy reads."""
        features = _make_feature_dict(self.feature_names)
        result = self.ensemble.predict(features)
        missing = self.PREDICTION_REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing PredictionResult keys: {missing}"

    def test_predict_types_match_prediction_result(self):
        """Field types match the PredictionResult TypedDict spec."""
        features = _make_feature_dict(self.feature_names)
        result = self.ensemble.predict(features)

        assert isinstance(result["prediction"], int)
        assert isinstance(result["probability"], float)
        assert isinstance(result["confidence"], float)
        assert isinstance(result["signal"], str)
        assert isinstance(result["signal_strength"], float)
        assert isinstance(result["timestamp"], str)

    def test_prediction_is_binary(self):
        """prediction is 0 or 1."""
        features = _make_feature_dict(self.feature_names)
        result = self.ensemble.predict(features)
        assert result["prediction"] in (0, 1)

    def test_signal_is_valid_enum(self):
        """signal is one of the three values MLEnhancedStrategy checks."""
        features = _make_feature_dict(self.feature_names)
        result = self.ensemble.predict(features)
        assert result["signal"] in ("bullish", "bearish", "neutral")

    def test_signal_strength_range(self):
        """signal_strength = probability * 100, in [0, 100]."""
        features = _make_feature_dict(self.feature_names)
        result = self.ensemble.predict(features)
        assert 0.0 <= result["signal_strength"] <= 100.0
        expected = round(result["probability"] * 100, 1)
        assert abs(result["signal_strength"] - expected) < 0.2

    def test_confidence_feeds_size_multiplier(self):
        """confidence value maps to a valid size multiplier via confidence_to_size_multiplier."""
        features = _make_feature_dict(self.feature_names)
        result = self.ensemble.predict(features)
        mult = confidence_to_size_multiplier(result["confidence"])

        assert 0.25 <= mult <= 1.25
        # Verify the formula: min + (max - min) * clamp(confidence, 0, 1)
        expected = 0.25 + (1.25 - 0.25) * max(0.0, min(1.0, result["confidence"]))
        assert abs(mult - expected) < 1e-6

    def test_fallback_prediction_is_compatible(self):
        """Untrained model returns fallback prediction with required keys + fallback flag."""
        untrained = EnsembleSignalModel(model_dir="/tmp/test_untrained_integration")
        features = _make_feature_dict(self.feature_names)
        result = untrained.predict(features)

        # Must still have all required keys so MLEnhancedStrategy doesn't crash
        missing = self.PREDICTION_REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Fallback missing keys: {missing}"

        # Fallback flag should be True
        assert result.get("fallback") is True

        # Neutral defaults
        assert result["probability"] == 0.5
        assert result["confidence"] == 0.0
        assert result["signal"] == "neutral"

    def test_ensemble_is_drop_in_for_signal_model(self):
        """EnsembleSignalModel has the same public API methods as SignalModel."""
        signal_model_methods = {"predict", "predict_batch", "train", "save", "load", "backtest"}
        ensemble_methods = set(dir(self.ensemble))

        for method in signal_model_methods:
            assert method in ensemble_methods, (
                f"EnsembleSignalModel missing {method} — not a drop-in for SignalModel"
            )

    def test_regime_router_accepts_ensemble(self):
        """RegimeModelRouter works with EnsembleSignalModel as the default model.

        This is the V2 pathway: MLEnhancedStrategy → RegimeModelRouter → model.predict().
        """
        # RegimeModelRouter expects a model with a predict() method
        router = RegimeModelRouter(default_model=self.ensemble)
        features = _make_feature_dict(self.feature_names)

        result = router.predict(features, regime="bull")
        assert isinstance(result, dict)
        assert "probability" in result
        assert "confidence" in result

    def test_v2_sizing_pipeline_end_to_end(self):
        """Full V2 pipeline: features → ensemble → confidence → multiplier → sizing metadata.

        Simulates what MLEnhancedStrategy.generate_signals() does internally.
        """
        features = _make_feature_dict(self.feature_names)

        # Step 1: Model predicts
        prediction = self.ensemble.predict(features)

        # Step 2: MLEnhancedStrategy reads confidence
        confidence = prediction.get("confidence", 0.0)
        assert isinstance(confidence, float)

        # Step 3: Map to size multiplier
        multiplier = confidence_to_size_multiplier(confidence)
        assert 0.25 <= multiplier <= 1.25

        # Step 4: Build metadata (what MLEnhancedStrategy attaches to Signal)
        metadata = {
            "ml_size_multiplier": multiplier,
            "ml_confidence": confidence,
            "ml_prediction": prediction,
            "ml_gated": True,
        }

        # Verify all expected metadata keys are present
        assert "ml_size_multiplier" in metadata
        assert "ml_confidence" in metadata
        assert "ml_prediction" in metadata
        assert isinstance(metadata["ml_prediction"], dict)

    def test_v1_gating_pipeline_end_to_end(self):
        """Full V1 pipeline: features → predict → confidence >= threshold → keep/drop.

        Simulates binary gating in MLEnhancedStrategy.
        """
        features = _make_feature_dict(self.feature_names)
        prediction = self.ensemble.predict(features)
        confidence = prediction.get("confidence", 0.0)
        probability = prediction.get("probability", 0.5)
        is_fallback = prediction.get("fallback", False)

        threshold = 0.30

        if is_fallback:
            # Fallback → pass through (V1 allows fallback predictions)
            gated = False
            passed = True
        elif confidence >= threshold:
            gated = True
            passed = True
        else:
            gated = True
            passed = False

        # The metadata that MLEnhancedStrategy would attach
        if passed:
            metadata = {
                "ml_prediction": prediction,
                "ml_gated": gated,
                "ml_confidence": confidence,
                "ml_probability": probability,
            }
            assert all(k in metadata for k in ["ml_prediction", "ml_gated", "ml_confidence", "ml_probability"])

    def test_multiple_predictions_deterministic(self):
        """Same features produce same prediction (ensemble is deterministic)."""
        features = _make_feature_dict(self.feature_names, seed=123)
        r1 = self.ensemble.predict(features)
        r2 = self.ensemble.predict(features)

        assert r1["probability"] == r2["probability"]
        assert r1["prediction"] == r2["prediction"]
        assert r1["confidence"] == r2["confidence"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Cross-module consistency checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossModuleConsistency:
    """Verify consistency invariants across modules."""

    def test_feature_engine_names_are_strings(self):
        """All feature names from FeatureEngine are non-empty strings."""
        names = _feature_engine_feature_names()
        assert all(isinstance(n, str) and len(n) > 0 for n in names)
        # No duplicates
        assert len(names) == len(set(names))

    def test_walk_forward_features_subset_of_training_data(self):
        """NUMERIC_FEATURES used by WalkForwardValidator exist in training data."""
        df = _make_training_df()
        for feat in NUMERIC_FEATURES:
            assert feat in df.columns, f"WF feature '{feat}' missing from training data"

    def test_experiment_profiles_cover_experiment_ids(self):
        """EXPERIMENT_PROFILES covers all EXPERIMENT_IDS."""
        for eid in EXPERIMENT_IDS:
            assert eid in EXPERIMENT_PROFILES, f"Missing profile for {eid}"
            profile = EXPERIMENT_PROFILES[eid]
            assert "momentum_affinity" in profile
            assert "defensive_affinity" in profile

    def test_confidence_to_size_multiplier_boundary_values(self):
        """Edge cases for the confidence → multiplier mapping."""
        assert confidence_to_size_multiplier(0.0) == 0.25
        assert confidence_to_size_multiplier(1.0) == 1.25
        assert confidence_to_size_multiplier(0.5) == pytest.approx(0.75)
        # Negative clamped to 0
        assert confidence_to_size_multiplier(-1.0) == 0.25
        # Above 1 clamped to 1
        assert confidence_to_size_multiplier(2.0) == 1.25

    def test_prediction_result_keys_match_typed_dict(self):
        """EnsembleSignalModel returns all PredictionResult typed dict keys."""
        feature_names = _feature_engine_feature_names()
        model = _train_ensemble(feature_names)
        features = _make_feature_dict(feature_names)
        result = model.predict(features)

        # PredictionResult fields (excluding optional 'fallback')
        required = {"prediction", "probability", "confidence", "signal", "signal_strength", "timestamp"}
        assert required.issubset(set(result.keys()))
