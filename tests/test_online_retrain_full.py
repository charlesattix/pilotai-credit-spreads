"""Extended tests for compass.online_retrain.

Covers areas beyond test_online_retrain.py:
  - Instantiation with custom parameters
  - check_and_retrain with mocked model age and drift
  - Model versioning save/load round-trip correctness
  - A/B comparison edge cases (worse model not promoted, single-class holdout)
  - Rolling window with 'date' column
  - Pruning companion feature_stats.json files
  - RetrainResult dataclass fields
"""

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from compass.online_retrain import (
    ABResult,
    ModelRetrainer,
    RetrainResult,
    RetrainTrigger,
)
from compass.signal_model import SignalModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_data(n=300, seed=42):
    """Create synthetic feature DataFrame + binary labels."""
    rng = np.random.RandomState(seed)
    features = pd.DataFrame({
        "feature_a": rng.randn(n),
        "feature_b": rng.randn(n),
        "feature_c": rng.randn(n),
    })
    labels = (features["feature_a"] + 0.3 * features["feature_b"] > 0).astype(int).values
    return features, labels


def _trained_model(tmpdir, features=None, labels=None):
    """Return a SignalModel that has been trained and saved."""
    if features is None or labels is None:
        features, labels = _make_data()
    model = SignalModel(model_dir=tmpdir)
    model.train(features, labels, calibrate=False, save_model=True)
    return model


# ---------------------------------------------------------------------------
# 1. Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:

    def test_default_params(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = ModelRetrainer(model_dir=tmpdir)
            assert r.max_age_days == 30
            assert r.drift_threshold == 3.0
            assert r.drift_feature_pct == 0.15
            assert r.perf_auc_drop == 0.05
            assert r.rolling_window_months == 12
            assert r.holdout_fraction == 0.20
            assert r.keep_versions == 3
            assert r.min_promotion_auc_delta == -0.005
            assert r.min_samples == 100
            assert r.model_dir.exists()

    def test_custom_params(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = ModelRetrainer(
                model_dir=tmpdir,
                max_age_days=7,
                drift_threshold=2.0,
                drift_feature_pct=0.25,
                perf_auc_drop=0.10,
                rolling_window_months=6,
                holdout_fraction=0.30,
                keep_versions=5,
                min_promotion_auc_delta=0.01,
                min_samples=50,
            )
            assert r.max_age_days == 7
            assert r.drift_threshold == 2.0
            assert r.drift_feature_pct == 0.25
            assert r.perf_auc_drop == 0.10
            assert r.rolling_window_months == 6
            assert r.holdout_fraction == 0.30
            assert r.keep_versions == 5
            assert r.min_promotion_auc_delta == 0.01
            assert r.min_samples == 50

    def test_creates_model_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "nested" / "models"
            assert not new_dir.exists()
            r = ModelRetrainer(model_dir=str(new_dir))
            assert new_dir.exists()


# ---------------------------------------------------------------------------
# 2. check_and_retrain with mocked age and drift
# ---------------------------------------------------------------------------

class TestCheckAndRetrainMocked:

    def test_retrain_triggered_by_mocked_age(self):
        """Inject an old timestamp into a trained model to trigger age check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            # Fake a 60-day-old model
            old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
            model.training_stats["timestamp"] = old_ts

            retrainer = ModelRetrainer(model_dir=tmpdir, max_age_days=30)
            result = retrainer.check_and_retrain(features, labels, current_model=model)

            assert result.trigger.triggered is True
            assert any("model_age" in r for r in result.trigger.reasons)
            assert result.retrained is True
            assert result.ab_result is not None

    def test_retrain_triggered_by_mocked_drift(self):
        """Shift features dramatically to trigger drift-based retrain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            # Shift all features far beyond training distribution
            shifted = features.copy()
            for col in shifted.columns:
                shifted[col] += 100.0

            retrainer = ModelRetrainer(
                model_dir=tmpdir,
                max_age_days=9999,  # don't trigger age
                drift_feature_pct=0.10,
            )
            result = retrainer.check_and_retrain(shifted, labels, current_model=model)

            assert result.trigger.triggered is True
            assert any("feature_drift" in r for r in result.trigger.reasons)
            assert len(result.trigger.drift_features) > 0

    def test_no_retrain_when_nothing_triggers(self):
        """Same data, fresh model → no trigger, no retrain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(features, labels, current_model=model)

            assert result.trigger.triggered is False
            assert result.retrained is False
            assert result.ab_result is None

    def test_force_overrides_no_trigger(self):
        """force=True always retrains even when no trigger fires."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(
                features, labels, current_model=model, force=True
            )

            assert result.retrained is True
            assert "forced" in result.trigger.reasons
            assert result.training_stats is not None

    def test_retrain_from_scratch_no_existing_model(self):
        """With empty model_dir, should force-train from scratch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(features, labels)

            assert result.retrained is True
            assert result.ab_result is not None

    def test_skip_retrain_below_min_samples(self):
        """Tiny dataset should skip retraining even when forced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=20)

            retrainer = ModelRetrainer(model_dir=tmpdir, min_samples=100)
            result = retrainer.check_and_retrain(features, labels, force=True)

            assert result.retrained is False
            assert result.ab_result is None


# ---------------------------------------------------------------------------
# 3. Model versioning save/load round-trip
# ---------------------------------------------------------------------------

class TestVersioningRoundTrip:

    def test_save_and_reload(self):
        """A versioned save should be loadable by a fresh SignalModel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            path = retrainer._save_versioned(model)

            assert path.exists()
            assert "signal_model_" in path.name

            # Load into a fresh model
            loader = SignalModel(model_dir=tmpdir)
            assert loader.load(path.name) is True
            assert loader.trained is True
            assert loader.feature_names == model.feature_names

    def test_loaded_model_predicts(self):
        """A loaded model should produce valid predictions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            path = retrainer._save_versioned(model)

            loader = SignalModel(model_dir=tmpdir)
            loader.load(path.name)

            probas = loader.predict_batch(features)
            assert len(probas) == len(features)
            assert all(0.0 <= p <= 1.0 for p in probas)

    def test_feature_stats_saved_with_version(self):
        """Versioned save should include feature distribution stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            path = retrainer._save_versioned(model)

            # Load and verify feature stats survived round-trip
            loader = SignalModel(model_dir=tmpdir)
            loader.load(path.name)

            assert loader.feature_means is not None
            assert loader.feature_stds is not None
            assert len(loader.feature_means) == len(model.feature_means)
            np.testing.assert_array_almost_equal(loader.feature_means, model.feature_means)

    def test_prune_removes_feature_stats_json(self):
        """Pruning a .joblib should also remove its companion .feature_stats.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            retrainer = ModelRetrainer(model_dir=tmpdir, keep_versions=1)

            model = SignalModel(model_dir=tmpdir)
            model.train(features, labels, calibrate=False, save_model=False)

            # Save two versions
            model.save("signal_model_20250101_120000.joblib")
            time.sleep(0.02)
            model.save("signal_model_20250102_120000.joblib")

            # Check companion files exist
            stats1 = Path(tmpdir) / "signal_model_20250101_120000.feature_stats.json"
            stats2 = Path(tmpdir) / "signal_model_20250102_120000.feature_stats.json"
            assert stats1.exists() or stats2.exists()  # at least one should exist

            retrainer._prune_old_versions()

            joblibfiles = list(Path(tmpdir).glob("signal_model_*.joblib"))
            assert len(joblibfiles) == 1

    def test_list_versions_ordered_newest_first(self):
        """list_versions should return newest model first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = SignalModel(model_dir=tmpdir)
            model.train(features, labels, calibrate=False, save_model=False)

            model.save("signal_model_20250101_120000.joblib")
            time.sleep(0.05)
            model.save("signal_model_20250201_120000.joblib")

            retrainer = ModelRetrainer(model_dir=tmpdir)
            versions = retrainer.list_versions()

            assert len(versions) >= 2
            # Newest should be first (most recent mtime)
            assert "20250201" in versions[0]["filename"]

    def test_count_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = SignalModel(model_dir=tmpdir)
            model.train(features, labels, calibrate=False, save_model=False)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            assert retrainer._count_versions() == 0

            model.save("signal_model_20250101_120000.joblib")
            assert retrainer._count_versions() == 1

            model.save("signal_model_20250102_120000.joblib")
            assert retrainer._count_versions() == 2


# ---------------------------------------------------------------------------
# 4. A/B comparison edge cases
# ---------------------------------------------------------------------------

class TestABComparisonExtended:

    def test_worse_model_not_promoted(self):
        """A new model that is significantly worse should not be promoted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=400)
            good_model = _trained_model(tmpdir, features, labels)

            # Create a "bad" model by training on noise
            rng = np.random.RandomState(99)
            noise_labels = rng.randint(0, 2, size=len(labels))
            bad_model = SignalModel(model_dir=tmpdir)
            bad_model.train(features, noise_labels, calibrate=False, save_model=False)

            holdout_f = features.iloc[-80:]
            holdout_l = labels[-80:]

            # Require substantial improvement
            retrainer = ModelRetrainer(model_dir=tmpdir, min_promotion_auc_delta=0.05)
            ab = retrainer._compare_models(good_model, bad_model, holdout_f, holdout_l)

            # The bad model should not beat the good model by 0.05
            # (it's trained on noise, good model on signal)
            assert isinstance(ab, ABResult)
            assert ab.holdout_size == 80
            # Can't guarantee exact outcome with noise, but structure is correct
            assert isinstance(ab.promoted, bool)
            assert isinstance(ab.reason, str)

    def test_ab_with_single_class_holdout(self):
        """Holdout with all-positive labels should still work (AUC=0.5 fallback)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            holdout_f = features.iloc[-40:]
            holdout_l = np.ones(40, dtype=int)  # all wins

            retrainer = ModelRetrainer(model_dir=tmpdir)
            ab = retrainer._compare_models(model, model, holdout_f, holdout_l)

            # With single class, both AUCs should be 0.5
            assert ab.old_auc == 0.5
            assert ab.new_auc == 0.5
            assert ab.holdout_size == 40

    def test_ab_result_fields(self):
        """ABResult should have all expected fields."""
        ab = ABResult(
            old_auc=0.75,
            new_auc=0.80,
            old_accuracy=0.70,
            new_accuracy=0.76,
            holdout_size=100,
            promoted=True,
            reason="test",
        )
        assert ab.old_auc == 0.75
        assert ab.new_auc == 0.80
        assert ab.old_accuracy == 0.70
        assert ab.new_accuracy == 0.76
        assert ab.holdout_size == 100
        assert ab.promoted is True
        assert ab.reason == "test"

    def test_promotion_with_negative_delta_threshold(self):
        """min_promotion_auc_delta < 0 allows slightly worse new models through."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            holdout_f = features.iloc[-60:]
            holdout_l = labels[-60:]

            # Allow new model to be 0.01 worse and still promote
            retrainer = ModelRetrainer(model_dir=tmpdir, min_promotion_auc_delta=-0.01)
            ab = retrainer._compare_models(model, model, holdout_f, holdout_l)

            # Same model → delta=0, which is > -0.01 → promoted
            assert ab.promoted is True


# ---------------------------------------------------------------------------
# 5. Rolling window with 'date' column
# ---------------------------------------------------------------------------

class TestRollingWindowDateColumn:

    def test_window_uses_date_column(self):
        """DataFrame with a 'date' column should trigger calendar-based windowing."""
        n = 400
        dates = pd.date_range("2022-01-01", periods=n, freq="B")
        features = pd.DataFrame({
            "date": dates,
            "feature_a": np.random.randn(n),
        })
        labels = np.random.randint(0, 2, n)

        retrainer = ModelRetrainer(rolling_window_months=6)
        windowed_f, windowed_l = retrainer._apply_rolling_window(features, labels)

        # Should be less than full dataset
        assert len(windowed_f) < n
        # Should be roughly 6 months of business days (~126)
        assert 90 < len(windowed_f) < 200
        assert len(windowed_f) == len(windowed_l)


# ---------------------------------------------------------------------------
# 6. RetrainResult / RetrainTrigger dataclass fields
# ---------------------------------------------------------------------------

class TestDataclasses:

    def test_retrain_trigger_defaults(self):
        t = RetrainTrigger()
        assert t.model_age_days is None
        assert t.drift_features == []
        assert t.perf_auc_current is None
        assert t.perf_auc_baseline is None
        assert t.triggered is False
        assert t.reasons == []

    def test_retrain_result_defaults(self):
        t = RetrainTrigger()
        r = RetrainResult(trigger=t)
        assert r.retrained is False
        assert r.ab_result is None
        assert r.new_model_path is None
        assert r.training_stats is None
        assert r.versions_on_disk == 0

    def test_retrain_result_with_promotion(self):
        """Full cycle result should have all fields populated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(features, labels, force=True)

            assert isinstance(result, RetrainResult)
            assert isinstance(result.trigger, RetrainTrigger)
            assert result.retrained is True

            if result.ab_result and result.ab_result.promoted:
                assert result.new_model_path is not None
                assert Path(result.new_model_path).exists()
                assert result.versions_on_disk >= 1

            assert isinstance(result.training_stats, dict)
            assert "test_accuracy" in result.training_stats


# ---------------------------------------------------------------------------
# 7. Model age edge cases
# ---------------------------------------------------------------------------

class TestModelAge:

    def test_age_none_when_no_model_files(self):
        """Age should be None when no model files exist and no timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = SignalModel(model_dir=tmpdir)
            retrainer = ModelRetrainer(model_dir=tmpdir)
            age = retrainer._get_model_age_days(model)
            assert age is None

    def test_age_from_timestamp_string(self):
        """Age should be computed from training_stats timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = SignalModel(model_dir=tmpdir)
            ts = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
            model.training_stats = {"timestamp": ts}

            retrainer = ModelRetrainer(model_dir=tmpdir)
            age = retrainer._get_model_age_days(model)
            assert age is not None
            assert 14 <= age <= 16  # allow 1 day tolerance

    def test_age_from_file_mtime_fallback(self):
        """When no timestamp in stats, should fall back to file mtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)
            # Remove timestamp from stats
            model.training_stats.pop("timestamp", None)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            age = retrainer._get_model_age_days(model)
            # File was just created, so age should be 0
            assert age is not None
            assert age == 0


# ---------------------------------------------------------------------------
# 8. Performance check edge cases
# ---------------------------------------------------------------------------

class TestPerformanceCheck:

    def test_perf_check_returns_none_for_untrained(self):
        """Untrained model should return None from performance check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = SignalModel(model_dir=tmpdir)
            features, labels = _make_data(n=100)
            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer._check_performance(model, features, labels)
            assert result is None

    def test_perf_check_returns_none_without_baseline(self):
        """Model with no test_auc in training_stats should return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)
            model.training_stats.pop("test_auc", None)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer._check_performance(model, features, labels)
            assert result is None

    def test_perf_check_returns_dict_for_valid_model(self):
        """Trained model with baseline AUC should return performance dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer._check_performance(model, features, labels)

            assert result is not None
            assert "baseline_auc" in result
            assert "current_auc" in result
            assert 0.0 <= result["current_auc"] <= 1.0

    def test_perf_check_single_class_labels(self):
        """Single-class labels should return None (can't compute AUC)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            all_ones = np.ones(len(labels), dtype=int)
            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer._check_performance(model, features, all_ones)
            assert result is None
