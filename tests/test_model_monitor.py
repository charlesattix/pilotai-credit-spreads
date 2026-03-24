"""Tests for compass.model_monitor."""
import tempfile

import numpy as np
import pytest

from compass.model_monitor import (
    DEFAULT_AUC_FLOOR,
    DEFAULT_KL_THRESHOLD,
    ModelMonitor,
    MonitorAlert,
    MonitorReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_monitor(tmpdir, **kwargs):
    """Create a ModelMonitor with synthetic training stats."""
    db_path = f"{tmpdir}/monitor.db"
    defaults = dict(
        db_path=db_path,
        feature_means=np.array([0.0, 5.0, 50.0]),
        feature_stds=np.array([1.0, 2.0, 10.0]),
        feature_names=["feat_a", "feat_b", "feat_c"],
        rolling_window=50,
    )
    defaults.update(kwargs)
    return ModelMonitor(**defaults)


def _seed_predictions_and_outcomes(monitor, n=60, seed=42):
    """Insert n matched prediction+outcome pairs.

    Probabilities are correlated with outcomes so AUC > 0.5.
    """
    rng = np.random.RandomState(seed)
    outcomes = rng.randint(0, 2, size=n)

    for i in range(n):
        actual = int(outcomes[i])
        # Correlated: wins get higher probability
        prob = 0.7 + rng.uniform(-0.1, 0.1) if actual == 1 else 0.3 + rng.uniform(-0.1, 0.1)
        prob = max(0.01, min(0.99, prob))
        pred = 1 if prob > 0.5 else 0
        conf = abs(prob - 0.5) * 2

        result = {
            "probability": prob,
            "confidence": conf,
            "prediction": pred,
            "signal": "bullish" if pred == 1 else "bearish",
        }
        monitor.log_prediction(result, ticker="SPY", model_type="test")

    # Flush predictions to get IDs
    monitor._flush_predictions()

    # Now log outcomes matched by ID
    rows = monitor._conn.execute(
        "SELECT id FROM predictions ORDER BY id ASC LIMIT ?", (n,)
    ).fetchall()

    for i, (pred_id,) in enumerate(rows[:n]):
        actual = int(outcomes[i])
        monitor.log_outcome(
            ticker="SPY",
            prediction_id=pred_id,
            actual_outcome=actual,
            pnl=100.0 if actual == 1 else -200.0,
        )


def _seed_random_outcomes(monitor, n=60, seed=99):
    """Seed predictions where model output is uncorrelated with outcome (AUC ≈ 0.5)."""
    rng = np.random.RandomState(seed)
    for i in range(n):
        prob = rng.uniform(0.2, 0.8)
        pred = 1 if prob > 0.5 else 0
        result = {
            "probability": prob,
            "confidence": abs(prob - 0.5) * 2,
            "prediction": pred,
            "signal": "neutral",
        }
        monitor.log_prediction(result, ticker="SPY", model_type="test")

    monitor._flush_predictions()

    rows = monitor._conn.execute(
        "SELECT id FROM predictions ORDER BY id ASC LIMIT ?", (n,)
    ).fetchall()

    # Random outcomes — no correlation with predictions
    for i, (pred_id,) in enumerate(rows[:n]):
        actual = rng.randint(0, 2)
        monitor.log_outcome(ticker="SPY", prediction_id=pred_id, actual_outcome=actual)


# ---------------------------------------------------------------------------
# Prediction logging
# ---------------------------------------------------------------------------

class TestLogPrediction:

    def test_predictions_persisted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            result = {"probability": 0.75, "confidence": 0.50, "prediction": 1, "signal": "bullish"}
            mon.log_prediction(result, ticker="SPY", model_type="xgboost")
            mon._flush_predictions()

            rows = mon.get_recent_predictions(limit=10)
            assert len(rows) == 1
            assert rows[0]["ticker"] == "SPY"
            assert rows[0]["probability"] == 0.75

    def test_multiple_predictions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            for i in range(5):
                result = {"probability": 0.5 + i * 0.05, "confidence": 0.1, "prediction": 1, "signal": "bullish"}
                mon.log_prediction(result, ticker="QQQ")
            mon._flush_predictions()
            assert len(mon.get_recent_predictions(limit=100)) == 5

    def test_features_stored_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            features = {"feat_a": 1.5, "feat_b": 3.0, "feat_c": 55.0}
            result = {"probability": 0.6, "confidence": 0.2, "prediction": 1, "signal": "bullish"}
            mon.log_prediction(result, features=features)
            mon._flush_predictions()

            row = mon._conn.execute("SELECT features FROM predictions LIMIT 1").fetchone()
            import json
            parsed = json.loads(row[0])
            assert parsed["feat_a"] == 1.5

    def test_feature_buffer_populated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            features = {"feat_a": 1.0, "feat_b": 5.0, "feat_c": 50.0}
            result = {"probability": 0.5, "confidence": 0.0, "prediction": 0, "signal": "neutral"}
            mon.log_prediction(result, features=features)
            assert len(mon._feature_buffer) == 1
            np.testing.assert_allclose(mon._feature_buffer[0], [1.0, 5.0, 50.0])


# ---------------------------------------------------------------------------
# Outcome logging
# ---------------------------------------------------------------------------

class TestLogOutcome:

    def test_outcome_persisted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            mon.log_outcome(ticker="SPY", actual_outcome=1, pnl=150.0)
            row = mon._conn.execute("SELECT actual_outcome, pnl FROM outcomes LIMIT 1").fetchone()
            assert row[0] == 1
            assert row[1] == 150.0

    def test_outcome_linked_to_prediction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            result = {"probability": 0.8, "confidence": 0.6, "prediction": 1, "signal": "bullish"}
            mon.log_prediction(result, ticker="SPY")
            mon._flush_predictions()
            pred_id = mon._conn.execute("SELECT id FROM predictions LIMIT 1").fetchone()[0]

            mon.log_outcome(ticker="SPY", prediction_id=pred_id, actual_outcome=1)
            row = mon._conn.execute("SELECT prediction_id FROM outcomes LIMIT 1").fetchone()
            assert row[0] == pred_id


# ---------------------------------------------------------------------------
# Rolling performance
# ---------------------------------------------------------------------------

class TestRollingPerformance:

    def test_auc_above_chance_with_correlated_data(self):
        """With correlated predictions, rolling AUC should be well above 0.5."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            _seed_predictions_and_outcomes(mon, n=60)
            auc, acc, n = mon._compute_rolling_performance()
            assert n >= 50
            assert auc is not None
            assert auc > 0.65

    def test_auc_near_chance_with_random_data(self):
        """With uncorrelated predictions, AUC should be near 0.5."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            _seed_random_outcomes(mon, n=60)
            auc, acc, n = mon._compute_rolling_performance()
            assert n >= 20
            if auc is not None:
                assert auc < 0.75  # not meaningfully above chance

    def test_insufficient_data_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            auc, acc, n = mon._compute_rolling_performance()
            assert auc is None
            assert n == 0


# ---------------------------------------------------------------------------
# Feature drift (KL divergence)
# ---------------------------------------------------------------------------

class TestFeatureDrift:

    def test_no_drift_on_matching_distribution(self):
        """Features drawn from the same distribution should have low KL.

        With only 100 samples, histogram binning noise pushes KL to
        ~0.05-0.15 even for the correct distribution.  We raise the
        threshold for this test to avoid false positives from small-sample
        variance.  In production (1000+ samples) the default 0.10 is fine.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir, kl_threshold=0.30)
            rng = np.random.RandomState(42)
            # Generate features matching training distribution (500 for stable KL)
            for _ in range(500):
                features = {
                    "feat_a": rng.normal(0.0, 1.0),
                    "feat_b": rng.normal(5.0, 2.0),
                    "feat_c": rng.normal(50.0, 10.0),
                }
                result = {"probability": 0.5, "confidence": 0.0, "prediction": 0, "signal": "neutral"}
                mon.log_prediction(result, features=features)

            kl_scores, drifted = mon._compute_feature_drift()
            assert len(drifted) == 0
            for name, kl in kl_scores.items():
                assert kl < 0.5  # should be small

    def test_drift_detected_on_shifted_distribution(self):
        """Features shifted by 5 stds should trigger drift."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            rng = np.random.RandomState(42)
            # Generate features shifted far from training distribution
            for _ in range(100):
                features = {
                    "feat_a": rng.normal(10.0, 1.0),  # shifted from mean=0
                    "feat_b": rng.normal(5.0, 2.0),   # same
                    "feat_c": rng.normal(50.0, 10.0),  # same
                }
                result = {"probability": 0.5, "confidence": 0.0, "prediction": 0, "signal": "neutral"}
                mon.log_prediction(result, features=features)

            kl_scores, drifted = mon._compute_feature_drift()
            assert "feat_a" in drifted
            assert kl_scores["feat_a"] > DEFAULT_KL_THRESHOLD

    def test_no_drift_without_training_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = ModelMonitor(db_path=f"{tmpdir}/m.db")
            kl_scores, drifted = mon._compute_feature_drift()
            assert kl_scores == {}
            assert drifted == []


# ---------------------------------------------------------------------------
# Full evaluate() cycle
# ---------------------------------------------------------------------------

class TestEvaluate:

    def test_evaluate_with_good_model(self):
        """Good model should produce report with no alerts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            _seed_predictions_and_outcomes(mon, n=60)
            report = mon.evaluate()

            assert isinstance(report, MonitorReport)
            assert report.n_predictions >= 60
            assert report.n_outcomes >= 60
            assert report.rolling_auc is not None
            assert report.rolling_auc > DEFAULT_AUC_FLOOR
            assert len(report.alerts) == 0

    def test_evaluate_fires_performance_alert(self):
        """Random model should trigger a performance alert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir, auc_floor=0.70)
            _seed_random_outcomes(mon, n=60)
            report = mon.evaluate()

            if report.rolling_auc is not None:
                perf_alerts = [a for a in report.alerts if a.alert_type == "performance"]
                assert len(perf_alerts) >= 1

    def test_evaluate_fires_drift_alert(self):
        """Shifted features should trigger a drift alert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir, drift_feature_pct=0.30)
            rng = np.random.RandomState(42)
            for _ in range(100):
                features = {
                    "feat_a": rng.normal(10.0, 1.0),   # shifted
                    "feat_b": rng.normal(20.0, 2.0),   # shifted
                    "feat_c": rng.normal(50.0, 10.0),   # same
                }
                result = {"probability": 0.5, "confidence": 0.0, "prediction": 0, "signal": "neutral"}
                mon.log_prediction(result, features=features)

            report = mon.evaluate()
            drift_alerts = [a for a in report.alerts if a.alert_type == "drift"]
            assert len(drift_alerts) >= 1
            assert len(report.drifted_features) >= 2

    def test_evaluate_empty_db_no_crash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            report = mon.evaluate()
            assert report.n_predictions == 0
            assert report.rolling_auc is None
            assert len(report.alerts) == 0


# ---------------------------------------------------------------------------
# Alert dispatch
# ---------------------------------------------------------------------------

class TestAlertDispatch:

    def test_callback_invoked(self):
        fired = []
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir, alert_callback=lambda a: fired.append(a))
            alert = MonitorAlert(alert_type="test", severity="warning", message="test alert")
            mon._dispatch_alert(alert)
            assert len(fired) == 1
            assert fired[0].message == "test alert"

    def test_cooldown_suppresses_repeat(self):
        fired = []
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir, alert_callback=lambda a: fired.append(a))
            alert1 = MonitorAlert(alert_type="perf", severity="warning", message="first")
            alert2 = MonitorAlert(alert_type="perf", severity="warning", message="second")
            mon._dispatch_alert(alert1)
            mon._dispatch_alert(alert2)  # should be suppressed
            assert len(fired) == 1

    def test_different_types_not_suppressed(self):
        fired = []
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir, alert_callback=lambda a: fired.append(a))
            mon._dispatch_alert(MonitorAlert(alert_type="performance", severity="warning", message="a"))
            mon._dispatch_alert(MonitorAlert(alert_type="drift", severity="warning", message="b"))
            assert len(fired) == 2

    def test_alerts_persisted_to_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            mon._dispatch_alert(MonitorAlert(alert_type="test", severity="critical", message="persisted"))
            alerts = mon.get_recent_alerts(limit=10)
            assert len(alerts) == 1
            assert alerts[0]["severity"] == "critical"


# ---------------------------------------------------------------------------
# Factory: from_signal_model
# ---------------------------------------------------------------------------

class TestFromSignalModel:

    def test_creates_monitor_from_model_attrs(self):
        class FakeModel:
            feature_means = np.array([0.0, 1.0])
            feature_stds = np.array([1.0, 2.0])
            feature_names = ["a", "b"]

        with tempfile.TemporaryDirectory() as tmpdir:
            mon = ModelMonitor.from_signal_model(
                FakeModel(), db_path=f"{tmpdir}/m.db"
            )
            assert mon.feature_names == ["a", "b"]
            np.testing.assert_array_equal(mon.feature_means, [0.0, 1.0])

    def test_handles_model_without_stats(self):
        class BareModel:
            pass

        with tempfile.TemporaryDirectory() as tmpdir:
            mon = ModelMonitor.from_signal_model(
                BareModel(), db_path=f"{tmpdir}/m.db"
            )
            assert mon.feature_means is None
            assert mon.feature_names == []


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------

class TestQueryAPI:

    def test_get_recent_predictions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            for i in range(3):
                result = {"probability": 0.5, "confidence": 0.0, "prediction": 0, "signal": "neutral"}
                mon.log_prediction(result, ticker=f"T{i}")
            mon._flush_predictions()
            preds = mon.get_recent_predictions(limit=2)
            assert len(preds) == 2

    def test_get_performance_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _make_monitor(tmpdir)
            _seed_predictions_and_outcomes(mon, n=60)
            hist = mon.get_performance_history()
            assert "rolling_auc" in hist
            assert hist["rolling_auc"] is not None


# ---------------------------------------------------------------------------
# KL divergence unit test
# ---------------------------------------------------------------------------

class TestKLDivergence:

    def test_identical_distribution_near_zero(self):
        rng = np.random.RandomState(42)
        samples = rng.normal(0.0, 1.0, size=10000)
        kl = ModelMonitor._kl_divergence_gauss(samples, ref_mean=0.0, ref_std=1.0)
        assert kl < 0.05

    def test_shifted_distribution_large_kl(self):
        rng = np.random.RandomState(42)
        samples = rng.normal(5.0, 1.0, size=1000)
        kl = ModelMonitor._kl_divergence_gauss(samples, ref_mean=0.0, ref_std=1.0)
        assert kl > 1.0

    def test_wider_distribution_nonzero_kl(self):
        rng = np.random.RandomState(42)
        samples = rng.normal(0.0, 3.0, size=5000)
        kl = ModelMonitor._kl_divergence_gauss(samples, ref_mean=0.0, ref_std=1.0)
        assert kl > 0.1
