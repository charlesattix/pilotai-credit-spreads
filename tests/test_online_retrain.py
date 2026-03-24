"""Tests for compass.online_retrain."""
import tempfile
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from compass.online_retrain import ModelRetrainer, RetrainTrigger, ABResult
from compass.signal_model import SignalModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data(n=300, seed=42):
    """Create synthetic training data with enough samples for train+holdout."""
    rng = np.random.RandomState(seed)
    features = pd.DataFrame({
        'feature_a': rng.randn(n),
        'feature_b': rng.randn(n),
        'feature_c': rng.randn(n),
    })
    labels = (features['feature_a'] + 0.3 * features['feature_b'] > 0).astype(int).values
    return features, labels


def _trained_model(tmpdir, features, labels):
    """Return a SignalModel that has been trained and saved."""
    model = SignalModel(model_dir=tmpdir)
    model.train(features, labels, calibrate=False, save_model=True)
    return model


# ---------------------------------------------------------------------------
# RetrainTrigger checks
# ---------------------------------------------------------------------------

class TestTriggerEvaluation:

    def test_no_trigger_when_model_is_fresh(self):
        """A freshly-trained model should not trigger retraining."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            trigger = retrainer._evaluate_triggers(model, features, labels)

            assert trigger.triggered is False
            assert trigger.reasons == []

    def test_trigger_on_model_age(self):
        """Model older than max_age_days should trigger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            # Fake old timestamp
            old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
            model.training_stats['timestamp'] = old_ts

            retrainer = ModelRetrainer(model_dir=tmpdir, max_age_days=30)
            trigger = retrainer._evaluate_triggers(model, features, labels)

            assert trigger.triggered is True
            assert any("model_age" in r for r in trigger.reasons)

    def test_trigger_on_feature_drift(self):
        """Shifted features should trigger drift detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            # Shift all features by 10 std devs
            shifted = features.copy()
            shifted['feature_a'] += 50
            shifted['feature_b'] += 50
            shifted['feature_c'] += 50

            retrainer = ModelRetrainer(model_dir=tmpdir, drift_feature_pct=0.10)
            trigger = retrainer._evaluate_triggers(model, shifted, labels)

            assert trigger.triggered is True
            assert any("feature_drift" in r for r in trigger.reasons)
            assert len(trigger.drift_features) > 0

    def test_trigger_on_performance_drop(self):
        """AUC drop below threshold should trigger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            # Use random labels to simulate performance drop
            rng = np.random.RandomState(99)
            bad_labels = rng.randint(0, 2, size=len(labels))

            # Force a high baseline so the drop is detectable
            model.training_stats['test_auc'] = 0.95

            retrainer = ModelRetrainer(model_dir=tmpdir, perf_auc_drop=0.05)
            trigger = retrainer._evaluate_triggers(model, features, bad_labels)

            # We can't guarantee the exact AUC on random labels, but the drop
            # from 0.95 should be large enough
            if trigger.perf_auc_current is not None:
                assert trigger.triggered is True
                assert any("auc_drop" in r for r in trigger.reasons)


# ---------------------------------------------------------------------------
# Feature drift
# ---------------------------------------------------------------------------

class TestFeatureDrift:

    def test_no_drift_on_same_data(self):
        """Drift check on the training data itself should return empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            drifted = retrainer._check_feature_drift(model, features)
            assert drifted == []

    def test_drift_detected_on_shifted_data(self):
        """Shifting one feature by many stds should flag it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            shifted = features.copy()
            shifted['feature_a'] += 100  # way beyond 3 stds
            retrainer = ModelRetrainer(model_dir=tmpdir)
            drifted = retrainer._check_feature_drift(model, shifted)
            assert 'feature_a' in drifted

    def test_drift_handles_missing_stats(self):
        """If model has no feature_means, drift check returns empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = SignalModel(model_dir=tmpdir)
            features, _ = _make_data(n=50)
            retrainer = ModelRetrainer(model_dir=tmpdir)
            assert retrainer._check_feature_drift(model, features) == []


# ---------------------------------------------------------------------------
# Rolling window
# ---------------------------------------------------------------------------

class TestRollingWindow:

    def test_window_by_row_count(self):
        """Without date info, should trim by approximate row count."""
        features, labels = _make_data(n=500)
        retrainer = ModelRetrainer(rolling_window_months=6)
        windowed_f, windowed_l = retrainer._apply_rolling_window(features, labels)
        expected_rows = 6 * 21
        assert len(windowed_f) == expected_rows
        assert len(windowed_l) == expected_rows

    def test_window_by_datetime_index(self):
        """With DatetimeIndex, should use calendar-based window."""
        dates = pd.date_range('2024-01-01', periods=400, freq='B')
        features = pd.DataFrame(
            {'feature_a': np.random.randn(400)},
            index=dates,
        )
        labels = np.random.randint(0, 2, 400)

        retrainer = ModelRetrainer(rolling_window_months=6)
        windowed_f, windowed_l = retrainer._apply_rolling_window(features, labels)

        # Should have roughly 6 months of business days
        assert len(windowed_f) < 400
        assert len(windowed_f) > 100

    def test_small_dataset_returned_as_is(self):
        """If dataset smaller than window, return it all."""
        features, labels = _make_data(n=50)
        retrainer = ModelRetrainer(rolling_window_months=12)
        windowed_f, windowed_l = retrainer._apply_rolling_window(features, labels)
        assert len(windowed_f) == 50


# ---------------------------------------------------------------------------
# A/B comparison
# ---------------------------------------------------------------------------

class TestABComparison:

    def test_new_model_promoted_when_better(self):
        """New model trained on same data should be promoted (AUC >= old - delta)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=400)
            old_model = _trained_model(tmpdir, features, labels)
            new_model = _trained_model(tmpdir, features, labels)

            holdout_f = features.iloc[-80:]
            holdout_l = labels[-80:]

            retrainer = ModelRetrainer(model_dir=tmpdir)
            ab = retrainer._compare_models(old_model, new_model, holdout_f, holdout_l)

            assert isinstance(ab, ABResult)
            assert ab.holdout_size == 80
            # Same data → same model → should be promoted
            assert ab.promoted is True

    def test_untrained_old_model_gets_baseline_auc(self):
        """If old model is untrained, it should get AUC=0.5."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            old_model = SignalModel(model_dir=tmpdir)  # untrained
            new_model = _trained_model(tmpdir, features, labels)

            holdout_f = features.iloc[-60:]
            holdout_l = labels[-60:]

            retrainer = ModelRetrainer(model_dir=tmpdir)
            ab = retrainer._compare_models(old_model, new_model, holdout_f, holdout_l)

            assert ab.old_auc == 0.5
            assert ab.promoted is True


# ---------------------------------------------------------------------------
# Model versioning
# ---------------------------------------------------------------------------

class TestVersioning:

    def test_save_versioned_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            path = retrainer._save_versioned(model)
            assert path.exists()
            assert path.suffix == '.joblib'

    def test_prune_keeps_n_versions(self):
        """After pruning, only keep_versions files should remain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            retrainer = ModelRetrainer(model_dir=tmpdir, keep_versions=2)

            # Train once then save with distinct filenames
            model = SignalModel(model_dir=tmpdir)
            model.train(features, labels, calibrate=False, save_model=False)

            for i in range(5):
                model.save(f'signal_model_2025010{i}_120000.joblib')
                time.sleep(0.02)  # ensure distinct mtime

            before = list(retrainer.model_dir.glob('signal_model_*.joblib'))
            assert len(before) == 5

            deleted = retrainer._prune_old_versions()
            remaining = list(retrainer.model_dir.glob('signal_model_*.joblib'))

            assert len(deleted) == 3  # 5 - keep_versions(2)
            assert len(remaining) == 2

    def test_list_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data()
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            retrainer._save_versioned(model)
            versions = retrainer.list_versions()
            assert len(versions) >= 1
            assert 'filename' in versions[0]
            assert 'modified' in versions[0]


# ---------------------------------------------------------------------------
# Full check_and_retrain integration
# ---------------------------------------------------------------------------

class TestCheckAndRetrain:

    def test_no_retrain_when_fresh(self):
        """Fresh model + same data → no retrain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(features, labels, current_model=model)

            assert result.retrained is False
            assert result.trigger.triggered is False

    def test_force_retrain(self):
        """force=True should always retrain and produce an A/B result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)
            model = _trained_model(tmpdir, features, labels)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(
                features, labels, current_model=model, force=True
            )

            assert result.retrained is True
            assert result.ab_result is not None
            assert result.training_stats is not None
            assert 'forced' in result.trigger.reasons

    def test_retrain_from_scratch(self):
        """With no existing model, should train from scratch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(features, labels)

            assert result.retrained is True
            assert result.ab_result is not None

    def test_retrain_skipped_when_too_few_samples(self):
        """Should skip retraining when data is below min_samples."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=20)

            retrainer = ModelRetrainer(model_dir=tmpdir, min_samples=100)
            result = retrainer.check_and_retrain(features, labels, force=True)

            assert result.retrained is False

    def test_promoted_model_is_loadable(self):
        """After promotion, the new model should be loadable by SignalModel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            features, labels = _make_data(n=300)

            retrainer = ModelRetrainer(model_dir=tmpdir)
            result = retrainer.check_and_retrain(features, labels, force=True)

            assert result.retrained is True
            if result.ab_result and result.ab_result.promoted:
                loader = SignalModel(model_dir=tmpdir)
                assert loader.load() is True
                assert loader.trained is True
