"""
Model Monitor — live performance tracking, drift detection, and alerting.

Sits between the prediction path and trade outcome logging to build a
continuous picture of model health.  Designed to run alongside the live
scanner without adding latency to the prediction hot path — all heavy
computation (rolling AUC, KL divergence) is deferred to periodic
``evaluate()`` calls.

Integration points:
  - ``log_prediction()`` is called after every ``SignalModel.predict()``
    or ``EnsembleSignalModel.predict()`` in the scan loop.
  - ``log_outcome()`` is called when a trade closes and the actual
    win/loss is known.
  - ``evaluate()`` is called on a schedule (e.g. daily after market
    close) to compute rolling metrics and fire alerts.
  - Drift detection reuses the same ``feature_means`` / ``feature_stds``
    from ``SignalModel`` but adds KL-divergence for distributional shift
    (not just z-score outliers).
"""

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_ROLLING_WINDOW = 50      # trades for rolling AUC
MIN_ROLLING_SAMPLES = 20         # need at least this many matched outcomes
DEFAULT_AUC_FLOOR = 0.55         # alert if rolling AUC drops below
DEFAULT_KL_THRESHOLD = 0.10      # alert if any feature KL > this
DEFAULT_DRIFT_PCT = 0.20         # alert if >= 20% of features are drifted
DEFAULT_N_BINS = 20              # histogram bins for KL divergence
DEFAULT_ALERT_COOLDOWN_S = 3600  # 1 hour between repeat alerts


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class MonitorAlert:
    """A single alert emitted by the monitor."""
    alert_type: str        # "performance", "drift", "staleness"
    severity: str          # "warning", "critical"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class MonitorReport:
    """Output of a periodic evaluate() call."""
    n_predictions: int
    n_outcomes: int
    n_matched: int
    rolling_auc: Optional[float]
    rolling_accuracy: Optional[float]
    drifted_features: List[str]
    kl_scores: Dict[str, float]
    alerts: List[MonitorAlert]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ── SQLite audit log ────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    ticker      TEXT,
    probability REAL    NOT NULL,
    confidence  REAL    NOT NULL,
    prediction  INTEGER NOT NULL,
    signal      TEXT,
    model_type  TEXT,
    features    TEXT
);

CREATE TABLE IF NOT EXISTS outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    ticker          TEXT,
    prediction_id   INTEGER,
    actual_outcome  INTEGER NOT NULL,
    pnl             REAL,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    alert_type  TEXT NOT NULL,
    severity    TEXT NOT NULL,
    message     TEXT NOT NULL,
    details     TEXT
);

CREATE INDEX IF NOT EXISTS idx_pred_ts ON predictions(timestamp);
CREATE INDEX IF NOT EXISTS idx_pred_ticker ON predictions(ticker);
CREATE INDEX IF NOT EXISTS idx_out_ts ON outcomes(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp);
"""


def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ── ModelMonitor ────────────────────────────────────────────────────────────

class ModelMonitor:
    """Tracks model predictions, outcomes, and health metrics.

    Parameters
    ----------
    db_path : str
        Path to the SQLite audit log.  Created if it doesn't exist.
    feature_means : np.ndarray, optional
        Training-time feature means (from SignalModel.feature_means).
    feature_stds : np.ndarray, optional
        Training-time feature stds (from SignalModel.feature_stds).
    feature_names : list[str], optional
        Feature names aligned with means/stds.
    rolling_window : int
        Number of most-recent matched predictions to use for rolling AUC.
    auc_floor : float
        Alert if rolling AUC drops below this.
    kl_threshold : float
        Per-feature KL divergence threshold for drift alerts.
    drift_feature_pct : float
        Fraction of features that must exceed kl_threshold to fire a drift alert.
    alert_callback : callable, optional
        Called with each ``MonitorAlert`` — wire to Telegram, logging, etc.
    """

    def __init__(
        self,
        db_path: str = "data/model_monitor.db",
        feature_means: Optional[np.ndarray] = None,
        feature_stds: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
        rolling_window: int = DEFAULT_ROLLING_WINDOW,
        auc_floor: float = DEFAULT_AUC_FLOOR,
        kl_threshold: float = DEFAULT_KL_THRESHOLD,
        drift_feature_pct: float = DEFAULT_DRIFT_PCT,
        alert_callback: Optional[Callable[[MonitorAlert], None]] = None,
    ):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.feature_means = feature_means
        self.feature_stds = feature_stds
        self.feature_names = feature_names or []
        self.rolling_window = rolling_window
        self.auc_floor = auc_floor
        self.kl_threshold = kl_threshold
        self.drift_feature_pct = drift_feature_pct
        self.alert_callback = alert_callback

        # In-memory buffers (flushed to DB periodically or on evaluate)
        self._prediction_buffer: List[Dict] = []
        self._feature_buffer: List[np.ndarray] = []
        self._lock = threading.Lock()

        # Cooldown tracking: alert_type → last_fired_utc
        self._last_alert: Dict[str, float] = {}

        self._conn = _init_db(db_path)
        logger.info("ModelMonitor initialized (db=%s, window=%d)", db_path, rolling_window)

    # ------------------------------------------------------------------
    # Prediction logging (hot path — must be fast)
    # ------------------------------------------------------------------

    def log_prediction(
        self,
        prediction_result: Dict,
        ticker: Optional[str] = None,
        model_type: Optional[str] = None,
        features: Optional[Dict[str, float]] = None,
    ) -> Optional[int]:
        """Record a model prediction.  Returns the prediction row id.

        Call this immediately after ``SignalModel.predict()`` or
        ``EnsembleSignalModel.predict()``.  The method is thread-safe
        and avoids blocking the scan loop.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            row = {
                "timestamp": now,
                "ticker": ticker,
                "probability": prediction_result.get("probability", 0.5),
                "confidence": prediction_result.get("confidence", 0.0),
                "prediction": prediction_result.get("prediction", 0),
                "signal": prediction_result.get("signal", "neutral"),
                "model_type": model_type,
                "features": json.dumps(features) if features else None,
            }

            with self._lock:
                self._prediction_buffer.append(row)
                if features:
                    vec = self._features_dict_to_vec(features)
                    if vec is not None:
                        self._feature_buffer.append(vec)

            # Flush to DB every 50 predictions to avoid memory buildup
            if len(self._prediction_buffer) >= 50:
                self._flush_predictions()

            return None  # id assigned on flush

        except Exception as exc:
            logger.debug("log_prediction error (non-fatal): %s", exc)
            return None

    def log_outcome(
        self,
        ticker: Optional[str] = None,
        prediction_id: Optional[int] = None,
        actual_outcome: int = 0,
        pnl: Optional[float] = None,
    ) -> None:
        """Record the actual outcome for a trade.

        Called when a trade closes.  ``actual_outcome`` should be 1 for
        profitable, 0 for unprofitable (matching the model's label scheme).
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT INTO outcomes (timestamp, ticker, prediction_id, actual_outcome, pnl) "
                "VALUES (?, ?, ?, ?, ?)",
                (now, ticker, prediction_id, actual_outcome, pnl),
            )
            self._conn.commit()
        except Exception as exc:
            logger.debug("log_outcome error (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Periodic evaluation (off hot path)
    # ------------------------------------------------------------------

    def evaluate(self) -> MonitorReport:
        """Run all health checks and return a report.

        Call this on a schedule (e.g. daily after close).  It:
          1. Flushes pending predictions to the DB.
          2. Computes rolling AUC on matched prediction/outcome pairs.
          3. Computes KL divergence on recent feature distributions.
          4. Fires alerts for any threshold violations.
        """
        self._flush_predictions()

        alerts: List[MonitorAlert] = []

        # Counts
        n_predictions = self._count_table("predictions")
        n_outcomes = self._count_table("outcomes")

        # Rolling performance
        rolling_auc, rolling_acc, n_matched = self._compute_rolling_performance()

        if rolling_auc is not None and rolling_auc < self.auc_floor:
            alert = MonitorAlert(
                alert_type="performance",
                severity="critical" if rolling_auc < self.auc_floor - 0.10 else "warning",
                message=(
                    f"Rolling AUC {rolling_auc:.4f} is below floor {self.auc_floor:.2f} "
                    f"(last {n_matched} trades)"
                ),
                details={"rolling_auc": rolling_auc, "n_matched": n_matched, "floor": self.auc_floor},
            )
            alerts.append(alert)

        # Feature drift
        kl_scores, drifted = self._compute_feature_drift()

        if self.feature_names and len(drifted) / max(len(self.feature_names), 1) >= self.drift_feature_pct:
            alert = MonitorAlert(
                alert_type="drift",
                severity="warning",
                message=(
                    f"Concept drift: {len(drifted)}/{len(self.feature_names)} features "
                    f"exceed KL threshold {self.kl_threshold:.3f}"
                ),
                details={"drifted_features": drifted, "kl_scores": kl_scores},
            )
            alerts.append(alert)

        # Dispatch alerts
        for alert in alerts:
            self._dispatch_alert(alert)

        report = MonitorReport(
            n_predictions=n_predictions,
            n_outcomes=n_outcomes,
            n_matched=n_matched,
            rolling_auc=rolling_auc,
            rolling_accuracy=rolling_acc,
            drifted_features=drifted,
            kl_scores=kl_scores,
            alerts=alerts,
        )

        logger.info(
            "Monitor evaluate: predictions=%d outcomes=%d matched=%d auc=%s drifted=%d alerts=%d",
            n_predictions, n_outcomes, n_matched,
            f"{rolling_auc:.4f}" if rolling_auc is not None else "n/a",
            len(drifted), len(alerts),
        )

        return report

    # ------------------------------------------------------------------
    # Rolling performance
    # ------------------------------------------------------------------

    def _compute_rolling_performance(self) -> tuple:
        """Compute rolling AUC and accuracy on the most recent matched pairs.

        Returns (auc_or_None, accuracy_or_None, n_matched).
        """
        try:
            rows = self._conn.execute(
                """
                SELECT p.probability, p.prediction, o.actual_outcome
                FROM outcomes o
                JOIN predictions p ON o.prediction_id = p.id
                ORDER BY o.id DESC
                LIMIT ?
                """,
                (self.rolling_window,),
            ).fetchall()

            if len(rows) < MIN_ROLLING_SAMPLES:
                return None, None, len(rows)

            probas = np.array([r[0] for r in rows])
            preds = np.array([r[1] for r in rows])
            actuals = np.array([r[2] for r in rows])

            n_matched = len(rows)

            if len(np.unique(actuals)) < 2:
                return None, None, n_matched

            from sklearn.metrics import roc_auc_score, accuracy_score
            auc = float(roc_auc_score(actuals, probas))
            acc = float(accuracy_score(actuals, preds))
            return auc, acc, n_matched

        except Exception as exc:
            logger.debug("Rolling performance error: %s", exc)
            return None, None, 0

    # ------------------------------------------------------------------
    # Feature drift (KL divergence)
    # ------------------------------------------------------------------

    def _compute_feature_drift(self) -> tuple:
        """Compute KL divergence between training and recent feature distributions.

        Uses the in-memory feature buffer (recent predictions) vs the
        training-time means/stds (approximated as Gaussian).  For each
        feature, we bin both the training distribution (Gaussian from
        mean/std) and the empirical recent distribution, then compute
        KL(recent || training).

        Returns ({feature_name: kl_score}, [drifted_feature_names]).
        """
        kl_scores: Dict[str, float] = {}
        drifted: List[str] = []

        if self.feature_means is None or self.feature_stds is None:
            return kl_scores, drifted
        if not self.feature_names:
            return kl_scores, drifted

        with self._lock:
            if len(self._feature_buffer) < MIN_ROLLING_SAMPLES:
                return kl_scores, drifted
            recent = np.array(self._feature_buffer[-self.rolling_window:])

        n_features = min(recent.shape[1], len(self.feature_means), len(self.feature_names))

        for i in range(n_features):
            name = self.feature_names[i]
            mean_train = self.feature_means[i]
            std_train = self.feature_stds[i]

            if std_train == 0 or np.isnan(std_train) or np.isnan(mean_train):
                continue

            col = recent[:, i]
            col = col[~np.isnan(col)]
            if len(col) < 5:
                continue

            kl = self._kl_divergence_gauss(col, mean_train, std_train)
            kl_scores[name] = round(kl, 6)

            if kl > self.kl_threshold:
                drifted.append(name)

        return kl_scores, drifted

    @staticmethod
    def _kl_divergence_gauss(
        samples: np.ndarray,
        ref_mean: float,
        ref_std: float,
        n_bins: int = DEFAULT_N_BINS,
    ) -> float:
        """KL(empirical || reference_gaussian) via binned histograms.

        Both distributions are discretised into the same bin edges
        (spanning ±4σ of the reference).  A small epsilon is added to
        avoid log(0).
        """
        lo = ref_mean - 4 * ref_std
        hi = ref_mean + 4 * ref_std
        edges = np.linspace(lo, hi, n_bins + 1)

        # Empirical histogram (recent predictions)
        p_counts, _ = np.histogram(samples, bins=edges)
        p = p_counts.astype(float)
        p = p / p.sum() if p.sum() > 0 else np.ones(n_bins) / n_bins

        # Reference histogram (Gaussian from training stats)
        from scipy.stats import norm
        cdf_vals = norm.cdf(edges, loc=ref_mean, scale=ref_std)
        q = np.diff(cdf_vals)
        q = q / q.sum() if q.sum() > 0 else np.ones(n_bins) / n_bins

        # KL with epsilon smoothing
        eps = 1e-10
        p = np.clip(p, eps, None)
        q = np.clip(q, eps, None)

        return float(np.sum(p * np.log(p / q)))

    # ------------------------------------------------------------------
    # Alerting
    # ------------------------------------------------------------------

    def _dispatch_alert(self, alert: MonitorAlert) -> None:
        """Persist alert and invoke callback (with cooldown)."""
        # Cooldown: don't repeat the same alert type within cooldown window
        now = datetime.now(timezone.utc).timestamp()
        last = self._last_alert.get(alert.alert_type, 0)
        if now - last < DEFAULT_ALERT_COOLDOWN_S:
            logger.debug("Alert %s suppressed (cooldown)", alert.alert_type)
            return

        self._last_alert[alert.alert_type] = now

        # Persist to DB
        try:
            self._conn.execute(
                "INSERT INTO alerts (timestamp, alert_type, severity, message, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    alert.timestamp,
                    alert.alert_type,
                    alert.severity,
                    alert.message,
                    json.dumps(alert.details, default=str),
                ),
            )
            self._conn.commit()
        except Exception as exc:
            logger.debug("Alert persist error: %s", exc)

        # Invoke callback
        if self.alert_callback is not None:
            try:
                self.alert_callback(alert)
            except Exception as exc:
                logger.warning("Alert callback error: %s", exc)

        logger.warning("MODEL ALERT [%s/%s]: %s", alert.alert_type, alert.severity, alert.message)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _flush_predictions(self) -> None:
        """Write buffered predictions to SQLite."""
        with self._lock:
            if not self._prediction_buffer:
                return
            batch = list(self._prediction_buffer)
            self._prediction_buffer.clear()

        try:
            self._conn.executemany(
                "INSERT INTO predictions "
                "(timestamp, ticker, probability, confidence, prediction, signal, model_type, features) "
                "VALUES (:timestamp, :ticker, :probability, :confidence, :prediction, :signal, :model_type, :features)",
                batch,
            )
            self._conn.commit()
        except Exception as exc:
            logger.warning("Flush predictions error: %s", exc)

    def _count_table(self, table: str) -> int:
        try:
            row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _features_dict_to_vec(self, features: Dict[str, float]) -> Optional[np.ndarray]:
        """Convert feature dict to array aligned with self.feature_names."""
        if not self.feature_names:
            return None
        vec = np.zeros(len(self.feature_names))
        for i, name in enumerate(self.feature_names):
            val = features.get(name)
            if val is not None and not np.isnan(val):
                vec[i] = val
        return vec

    # ------------------------------------------------------------------
    # Query API (for dashboards / scripts)
    # ------------------------------------------------------------------

    def get_recent_predictions(self, limit: int = 100) -> List[Dict]:
        """Return most recent predictions as dicts."""
        self._flush_predictions()
        rows = self._conn.execute(
            "SELECT id, timestamp, ticker, probability, confidence, prediction, signal, model_type "
            "FROM predictions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        cols = ["id", "timestamp", "ticker", "probability", "confidence", "prediction", "signal", "model_type"]
        return [dict(zip(cols, r)) for r in rows]

    def get_recent_alerts(self, limit: int = 50) -> List[Dict]:
        """Return most recent alerts as dicts."""
        rows = self._conn.execute(
            "SELECT id, timestamp, alert_type, severity, message, details "
            "FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        cols = ["id", "timestamp", "alert_type", "severity", "message", "details"]
        return [dict(zip(cols, r)) for r in rows]

    def get_performance_history(self, window: int = 50) -> Dict:
        """Return rolling performance metrics for the last N matched trades."""
        auc, acc, n = self._compute_rolling_performance()
        return {
            "rolling_auc": auc,
            "rolling_accuracy": acc,
            "n_matched": n,
            "window": window,
        }

    # ------------------------------------------------------------------
    # Factory: build from a signal model
    # ------------------------------------------------------------------

    @classmethod
    def from_signal_model(
        cls,
        model,
        db_path: str = "data/model_monitor.db",
        alert_callback: Optional[Callable[[MonitorAlert], None]] = None,
        **kwargs,
    ) -> "ModelMonitor":
        """Create a ModelMonitor pre-loaded with a model's training stats.

        Works with both ``SignalModel`` and ``EnsembleSignalModel`` — any
        object that has ``feature_means``, ``feature_stds``, and
        ``feature_names`` attributes.
        """
        return cls(
            db_path=db_path,
            feature_means=getattr(model, "feature_means", None),
            feature_stds=getattr(model, "feature_stds", None),
            feature_names=getattr(model, "feature_names", None),
            alert_callback=alert_callback,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Flush pending data and close the DB connection."""
        self._flush_predictions()
        try:
            self._conn.close()
        except Exception:
            pass
