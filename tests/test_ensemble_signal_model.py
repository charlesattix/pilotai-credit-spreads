"""Tests for EnsembleSignalModel."""
import tempfile

import numpy as np
import pandas as pd
import pytest

from compass.ensemble_signal_model import (
    EnsembleSignalModel,
    _build_base_models,
    _walk_forward_weights,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_training_data(n=300, n_features=5, seed=42):
    """Create synthetic training data with a learnable signal.

    feature_0 and feature_1 carry signal; the rest are noise.
    Labels are correlated with a linear combination so classifiers
    can achieve AUC well above 0.5.
    """
    rng = np.random.RandomState(seed)
    X = rng.randn(n, n_features)
    noise = rng.randn(n) * 0.3
    y = (X[:, 0] + 0.5 * X[:, 1] + noise > 0).astype(int)
    cols = [f"f{i}" for i in range(n_features)]
    return pd.DataFrame(X, columns=cols), y


def _make_feature_dict(feature_names, seed=7):
    """Create a single-sample feature dict for predict()."""
    rng = np.random.RandomState(seed)
    return {name: float(rng.randn()) for name in feature_names}


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestEnsembleInit:

    def test_can_instantiate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            assert model.trained is False
            assert model.calibrated_models == {}
            assert model.ensemble_weights == {}

    def test_model_dir_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = f"{tmpdir}/nested/models"
            model = EnsembleSignalModel(model_dir=subdir)
            import os
            assert os.path.isdir(subdir)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

class TestEnsembleTrain:

    def test_train_returns_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            stats = model.train(features, labels, calibrate=False, save_model=False)

            assert isinstance(stats, dict)
            assert 'ensemble_test_auc' in stats
            assert stats['ensemble_test_auc'] > 0.5

    def test_train_with_calibration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            stats = model.train(features, labels, calibrate=True, save_model=False)

            assert stats['ensemble_test_auc'] > 0.5
            assert stats['n_calibration'] > 0

    def test_train_sets_trained_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=False, save_model=False)
            assert model.trained is True

    def test_train_populates_feature_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=False, save_model=False)
            assert model.feature_names == list(features.columns)

    def test_train_populates_ensemble_weights(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=False, save_model=False)

            assert len(model.ensemble_weights) >= 2  # at least RF + ET
            total = sum(model.ensemble_weights.values())
            assert abs(total - 1.0) < 1e-6, f"Weights should sum to 1.0, got {total}"

    def test_train_populates_calibrated_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=False, save_model=False)
            assert len(model.calibrated_models) >= 2

    def test_per_model_stats_included(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            stats = model.train(features, labels, calibrate=False, save_model=False)

            assert 'per_model' in stats
            for name, ms in stats['per_model'].items():
                assert 'test_auc' in ms
                assert 'weight' in ms

    def test_train_stores_feature_distribution_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data(n_features=3)
            model.train(features, labels, calibrate=False, save_model=False)

            assert model.feature_means is not None
            assert model.feature_stds is not None
            assert len(model.feature_means) == 3
            assert len(model.feature_stds) == 3


# ---------------------------------------------------------------------------
# Prediction — single sample
# ---------------------------------------------------------------------------

class TestEnsemblePredict:

    @pytest.fixture(autouse=True)
    def _trained_model(self, tmp_path):
        self.model = EnsembleSignalModel(model_dir=str(tmp_path))
        features, labels = _make_training_data()
        self.model.train(features, labels, calibrate=True, save_model=False)
        self.feature_names = list(features.columns)

    def test_predict_returns_required_keys(self):
        fd = _make_feature_dict(self.feature_names)
        result = self.model.predict(fd)

        assert 'probability' in result
        assert 'confidence' in result
        assert 'prediction' in result
        assert 'signal' in result
        assert 'signal_strength' in result
        assert 'timestamp' in result

    def test_predict_probability_in_range(self):
        fd = _make_feature_dict(self.feature_names)
        result = self.model.predict(fd)
        assert 0.0 <= result['probability'] <= 1.0

    def test_predict_confidence_in_range(self):
        fd = _make_feature_dict(self.feature_names)
        result = self.model.predict(fd)
        assert 0.0 <= result['confidence'] <= 1.0

    def test_predict_confidence_matches_probability(self):
        fd = _make_feature_dict(self.feature_names)
        result = self.model.predict(fd)
        expected_conf = abs(result['probability'] - 0.5) * 2
        assert abs(result['confidence'] - round(expected_conf, 4)) < 1e-4

    def test_predict_no_fallback_key_when_trained(self):
        fd = _make_feature_dict(self.feature_names)
        result = self.model.predict(fd)
        assert 'fallback' not in result

    def test_predict_signal_bullish_bearish_neutral(self):
        fd = _make_feature_dict(self.feature_names)
        result = self.model.predict(fd)
        assert result['signal'] in ('bullish', 'bearish', 'neutral')

    def test_predict_handles_missing_features(self):
        """predict() should work with partial feature dict (fills 0.0)."""
        partial = {self.feature_names[0]: 1.5}
        result = self.model.predict(partial)
        assert 'probability' in result
        assert 0.0 <= result['probability'] <= 1.0

    def test_predict_handles_nan_values(self):
        fd = {name: float('nan') for name in self.feature_names}
        result = self.model.predict(fd)
        assert 'probability' in result

    def test_predict_prediction_matches_probability(self):
        fd = _make_feature_dict(self.feature_names)
        result = self.model.predict(fd)
        expected_pred = 1 if result['probability'] > 0.5 else 0
        assert result['prediction'] == expected_pred


# ---------------------------------------------------------------------------
# Prediction — fallback
# ---------------------------------------------------------------------------

class TestEnsembleFallback:

    def test_untrained_predict_returns_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            result = model.predict({'x': 1.0})
            assert result['fallback'] is True
            assert result['probability'] == 0.5
            assert result['confidence'] == 0.0

    def test_untrained_predict_batch_returns_half(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            df = pd.DataFrame({'x': [1.0, 2.0, 3.0]})
            proba = model.predict_batch(df)
            np.testing.assert_array_equal(proba, [0.5, 0.5, 0.5])


# ---------------------------------------------------------------------------
# Prediction — batch
# ---------------------------------------------------------------------------

class TestEnsemblePredictBatch:

    def test_batch_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data(n=200)
            model.train(features, labels, calibrate=False, save_model=False)

            proba = model.predict_batch(features)
            assert proba.shape == (200,)

    def test_batch_values_in_range(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data(n=200)
            model.train(features, labels, calibrate=False, save_model=False)

            proba = model.predict_batch(features)
            assert np.all(proba >= 0.0)
            assert np.all(proba <= 1.0)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

class TestEnsembleBacktest:

    def test_backtest_returns_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data(n=300)
            model.train(features, labels, calibrate=False, save_model=False)

            bt = model.backtest(features, labels)
            assert 'accuracy' in bt
            assert 'auc' in bt
            assert 'precision' in bt
            assert 'recall' in bt
            assert 'n_trades' in bt
            assert bt['auc'] > 0.5

    def test_backtest_untrained_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data(n=100)
            bt = model.backtest(features, labels)
            assert bt == {}


# ---------------------------------------------------------------------------
# Save / Load round-trip
# ---------------------------------------------------------------------------

class TestEnsemblePersistence:

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=True, save_model=False)

            model.save("test_model.joblib")

            model2 = EnsembleSignalModel(model_dir=tmpdir)
            assert model2.load("test_model.joblib") is True
            assert model2.trained is True
            assert model2.feature_names == model.feature_names

    def test_loaded_model_predicts_same(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=True, save_model=False)

            fd = _make_feature_dict(model.feature_names)
            result1 = model.predict(fd)

            model.save("test_model.joblib")
            model2 = EnsembleSignalModel(model_dir=tmpdir)
            model2.load("test_model.joblib")
            result2 = model2.predict(fd)

            assert abs(result1['probability'] - result2['probability']) < 1e-6

    def test_load_nonexistent_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            assert model.load("no_such_file.joblib") is False

    def test_load_auto_finds_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=False, save_model=False)
            model.save("ensemble_model_20260101.joblib")
            model.save("ensemble_model_20260102.joblib")

            model2 = EnsembleSignalModel(model_dir=tmpdir)
            assert model2.load() is True  # should pick most recent
            assert model2.trained is True

    def test_feature_stats_json_saved(self):
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            features, labels = _make_training_data()
            model.train(features, labels, calibrate=False, save_model=False)
            model.save("test_model.joblib")

            json_path = os.path.join(tmpdir, "test_model.feature_stats.json")
            assert os.path.exists(json_path)

    def test_path_traversal_blocked(self):
        """Ensure symlink-based path traversal is refused."""
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            # Create a symlink pointing outside model_dir
            outside = tempfile.mktemp(suffix=".joblib")
            link = os.path.join(tmpdir, "ensemble_model_evil.joblib")
            try:
                # Write a dummy file outside
                with open(outside, 'w') as f:
                    f.write("not a model")
                os.symlink(outside, link)
                assert model.load("ensemble_model_evil.joblib") is False
            finally:
                if os.path.exists(outside):
                    os.unlink(outside)
                if os.path.lexists(link):
                    os.unlink(link)


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------

class TestEnsembleMonitoring:

    def test_fallback_stats_initially_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            assert model.get_fallback_stats() == {}

    def test_fallback_stats_increment_on_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = EnsembleSignalModel(model_dir=tmpdir)
            # Force predict to fail: set trained=True with a model that
            # will choke on feature count mismatch.
            model.trained = True
            model.feature_names = ['x']
            # Put a broken object in calibrated_models that will raise
            # when predict_proba is called.
            model.calibrated_models = {'broken': object()}
            model.ensemble_weights = {'broken': 1.0}
            result = model.predict({'x': 1.0})
            assert result.get('fallback') is True
            stats = model.get_fallback_stats()
            assert stats.get('predict', 0) >= 1


# ---------------------------------------------------------------------------
# Internal: _build_base_models
# ---------------------------------------------------------------------------

class TestBuildBaseModels:

    def test_returns_at_least_two_models(self):
        models = _build_base_models()
        assert len(models) >= 2

    def test_model_names_unique(self):
        models = _build_base_models()
        names = [name for name, _ in models]
        assert len(names) == len(set(names))

    def test_includes_random_forest_and_extra_trees(self):
        models = _build_base_models()
        names = {name for name, _ in models}
        assert 'random_forest' in names
        assert 'extra_trees' in names


# ---------------------------------------------------------------------------
# Internal: _walk_forward_weights
# ---------------------------------------------------------------------------

class TestWalkForwardWeights:

    def test_weights_sum_to_one(self):
        rng = np.random.RandomState(0)
        n = 300
        X = rng.randn(n, 3)
        y = (X[:, 0] > 0).astype(int)
        base_models = _build_base_models()

        weights = _walk_forward_weights(X, y, base_models, n_folds=3)
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-6

    def test_weights_all_non_negative(self):
        rng = np.random.RandomState(0)
        n = 300
        X = rng.randn(n, 3)
        y = (X[:, 0] > 0).astype(int)
        base_models = _build_base_models()

        weights = _walk_forward_weights(X, y, base_models, n_folds=3)
        for w in weights.values():
            assert w >= 0.0

    def test_small_data_falls_back_to_equal_weights(self):
        """With very few samples, should use equal weights."""
        rng = np.random.RandomState(0)
        n = 20  # too small for MIN_FOLD_SAMPLES=30 per fold
        X = rng.randn(n, 3)
        y = (X[:, 0] > 0).astype(int)
        base_models = _build_base_models()

        weights = _walk_forward_weights(X, y, base_models, n_folds=5)
        expected = 1.0 / len(base_models)
        for w in weights.values():
            assert abs(w - expected) < 1e-6
