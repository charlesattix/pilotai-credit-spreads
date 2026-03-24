"""
Online / Rolling Retraining for the Signal Model

Monitors model staleness, feature drift, and out-of-sample performance to
decide when to retrain.  After retraining, compares the new model against
the current model on a held-out set before promoting it to production.

Keeps the last N model versions on disk for rollback.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from compass.signal_model import SignalModel
from shared.indicators import sanitize_features

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RetrainTrigger:
    """Why a retrain was triggered."""
    model_age_days: Optional[int] = None
    drift_features: List[str] = field(default_factory=list)
    perf_auc_current: Optional[float] = None
    perf_auc_baseline: Optional[float] = None
    triggered: bool = False
    reasons: List[str] = field(default_factory=list)


@dataclass
class ABResult:
    """Side-by-side evaluation of old vs new model on a holdout set."""
    old_auc: float
    new_auc: float
    old_accuracy: float
    new_accuracy: float
    holdout_size: int
    promoted: bool
    reason: str


@dataclass
class RetrainResult:
    """Full result of a check_and_retrain cycle."""
    trigger: RetrainTrigger
    retrained: bool = False
    ab_result: Optional[ABResult] = None
    new_model_path: Optional[str] = None
    training_stats: Optional[Dict] = None
    versions_on_disk: int = 0


# ---------------------------------------------------------------------------
# ModelRetrainer
# ---------------------------------------------------------------------------

class ModelRetrainer:
    """Online / rolling retraining manager for :class:`SignalModel`.

    Parameters
    ----------
    model_dir : str
        Directory where versioned model files are stored.
    max_age_days : int
        Retrain if the current model is older than this.
    drift_threshold : float
        Number of standard deviations used to flag a feature as drifted.
    drift_feature_pct : float
        Fraction of features that must be drifted to trigger a retrain.
    perf_auc_drop : float
        Absolute AUC drop from baseline that triggers a retrain.
    rolling_window_months : int
        Training window size in months (most recent trades).
    holdout_fraction : float
        Fraction of training data reserved for A/B holdout comparison.
    keep_versions : int
        Number of old model versions to keep on disk.
    min_promotion_auc_delta : float
        New model must beat old model by at least this much AUC to be
        promoted.  Set to a small negative number (e.g. -0.005) to allow
        promotions that are slightly worse on the holdout but still fresh.
    min_samples : int
        Minimum number of training samples required to attempt retraining.
    """

    def __init__(
        self,
        model_dir: str = "ml/models",
        max_age_days: int = 30,
        drift_threshold: float = 3.0,
        drift_feature_pct: float = 0.15,
        perf_auc_drop: float = 0.05,
        rolling_window_months: int = 12,
        holdout_fraction: float = 0.20,
        keep_versions: int = 3,
        min_promotion_auc_delta: float = -0.005,
        min_samples: int = 100,
    ):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_days = max_age_days
        self.drift_threshold = drift_threshold
        self.drift_feature_pct = drift_feature_pct
        self.perf_auc_drop = perf_auc_drop
        self.rolling_window_months = rolling_window_months
        self.holdout_fraction = holdout_fraction
        self.keep_versions = keep_versions
        self.min_promotion_auc_delta = min_promotion_auc_delta
        self.min_samples = min_samples

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_retrain(
        self,
        trades_df: pd.DataFrame,
        labels: np.ndarray,
        current_model: Optional[SignalModel] = None,
        force: bool = False,
    ) -> RetrainResult:
        """Evaluate whether the model needs retraining and, if so, retrain.

        Parameters
        ----------
        trades_df : pd.DataFrame
            Feature DataFrame (rows = trades, columns = feature names).
            Should be sorted chronologically (oldest first).
        labels : np.ndarray
            Binary labels aligned with *trades_df* rows.
        current_model : SignalModel, optional
            The currently-deployed model.  If ``None``, a fresh one is loaded
            from ``model_dir``.
        force : bool
            Skip trigger checks and retrain unconditionally.

        Returns
        -------
        RetrainResult
        """
        # --- load current model if needed ---
        if current_model is None:
            current_model = SignalModel(model_dir=str(self.model_dir))
            if not current_model.load():
                logger.info("No existing model found — will train from scratch")
                force = True

        # --- check triggers ---
        trigger = self._evaluate_triggers(current_model, trades_df, labels)

        if not force and not trigger.triggered:
            logger.info("No retrain trigger fired — model is current")
            return RetrainResult(
                trigger=trigger,
                versions_on_disk=self._count_versions(),
            )

        if force:
            trigger.triggered = True
            trigger.reasons.append("forced")

        logger.info("Retrain triggered: %s", ", ".join(trigger.reasons))

        # --- window the data ---
        trades_windowed, labels_windowed = self._apply_rolling_window(
            trades_df, labels
        )

        if len(trades_windowed) < self.min_samples:
            logger.warning(
                "Only %d samples in rolling window (need %d) — skipping retrain",
                len(trades_windowed),
                self.min_samples,
            )
            return RetrainResult(trigger=trigger)

        # --- split holdout ---
        n_holdout = max(1, int(len(trades_windowed) * self.holdout_fraction))
        train_features = trades_windowed.iloc[:-n_holdout]
        train_labels = labels_windowed[:-n_holdout]
        holdout_features = trades_windowed.iloc[-n_holdout:]
        holdout_labels = labels_windowed[-n_holdout:]

        # --- train new model ---
        new_model = SignalModel(model_dir=str(self.model_dir))
        stats = new_model.train(
            train_features,
            train_labels,
            calibrate=True,
            save_model=False,
        )

        if not stats or not new_model.trained:
            logger.error("New model training failed — keeping current model")
            return RetrainResult(trigger=trigger)

        # --- A/B comparison on holdout ---
        ab_result = self._compare_models(
            current_model, new_model, holdout_features, holdout_labels
        )

        result = RetrainResult(
            trigger=trigger,
            retrained=True,
            ab_result=ab_result,
            training_stats=stats,
        )

        if ab_result.promoted:
            version_path = self._save_versioned(new_model)
            result.new_model_path = str(version_path)
            self._prune_old_versions()
            logger.info("New model promoted → %s", version_path)
        else:
            logger.info(
                "New model NOT promoted (old AUC=%.4f, new AUC=%.4f): %s",
                ab_result.old_auc,
                ab_result.new_auc,
                ab_result.reason,
            )

        result.versions_on_disk = self._count_versions()
        return result

    # ------------------------------------------------------------------
    # Trigger evaluation
    # ------------------------------------------------------------------

    def _evaluate_triggers(
        self,
        model: SignalModel,
        features_df: pd.DataFrame,
        labels: np.ndarray,
    ) -> RetrainTrigger:
        trigger = RetrainTrigger()

        # 1. Model age
        age = self._get_model_age_days(model)
        trigger.model_age_days = age
        if age is not None and age > self.max_age_days:
            trigger.triggered = True
            trigger.reasons.append(f"model_age={age}d > {self.max_age_days}d")

        # 2. Feature drift
        drifted = self._check_feature_drift(model, features_df)
        trigger.drift_features = drifted
        if model.feature_names and len(drifted) / max(len(model.feature_names), 1) >= self.drift_feature_pct:
            trigger.triggered = True
            trigger.reasons.append(
                f"feature_drift={len(drifted)}/{len(model.feature_names)} "
                f"(>= {self.drift_feature_pct:.0%})"
            )

        # 3. Performance degradation
        perf = self._check_performance(model, features_df, labels)
        if perf is not None:
            trigger.perf_auc_current = perf["current_auc"]
            trigger.perf_auc_baseline = perf["baseline_auc"]
            drop = perf["baseline_auc"] - perf["current_auc"]
            if drop >= self.perf_auc_drop:
                trigger.triggered = True
                trigger.reasons.append(
                    f"auc_drop={drop:.4f} (baseline={perf['baseline_auc']:.4f}, "
                    f"current={perf['current_auc']:.4f})"
                )

        return trigger

    def _get_model_age_days(self, model: SignalModel) -> Optional[int]:
        """Return model age in days, or None if unknown."""
        ts = model.training_stats.get("timestamp") if model.training_stats else None
        if ts is None:
            # Fall back: check the most recent model file's saved timestamp
            model_files = sorted(
                self.model_dir.glob("signal_model_*.joblib"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not model_files:
                return None
            # Use file mtime as approximation
            mtime = datetime.fromtimestamp(
                model_files[0].stat().st_mtime, tz=timezone.utc
            )
            return (datetime.now(timezone.utc) - mtime).days

        try:
            trained_at = datetime.fromisoformat(ts)
            if trained_at.tzinfo is None:
                trained_at = trained_at.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - trained_at).days
        except (ValueError, TypeError):
            return None

    def _check_feature_drift(
        self, model: SignalModel, features_df: pd.DataFrame
    ) -> List[str]:
        """Return names of features whose recent mean drifted beyond threshold.

        Integrates with SignalModel's existing ``feature_means`` / ``feature_stds``
        that are computed during training.
        """
        if model.feature_means is None or model.feature_stds is None:
            return []
        if model.feature_names is None:
            return []

        drifted: List[str] = []
        # Align columns to model's expected order
        available = [c for c in model.feature_names if c in features_df.columns]
        if not available:
            return []

        X = features_df[available].values
        X = sanitize_features(X)
        recent_means = np.nanmean(X, axis=0)

        # Map available columns back to index in model.feature_names
        for j, col in enumerate(available):
            idx = model.feature_names.index(col)
            std = model.feature_stds[idx]
            if std == 0 or np.isnan(std):
                continue
            z = abs(recent_means[j] - model.feature_means[idx]) / std
            if z > self.drift_threshold:
                drifted.append(col)

        return drifted

    def _check_performance(
        self,
        model: SignalModel,
        features_df: pd.DataFrame,
        labels: np.ndarray,
    ) -> Optional[Dict]:
        """Evaluate model on recent data and compare to training baseline."""
        if not model.trained:
            return None

        baseline_auc = model.training_stats.get("test_auc")
        if baseline_auc is None:
            return None

        try:
            probas = model.predict_batch(features_df)
            if len(np.unique(labels)) < 2:
                return None
            current_auc = float(roc_auc_score(labels, probas))
            return {"baseline_auc": baseline_auc, "current_auc": current_auc}
        except Exception as e:
            logger.warning("Performance check failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Rolling window
    # ------------------------------------------------------------------

    def _apply_rolling_window(
        self, features_df: pd.DataFrame, labels: np.ndarray
    ) -> tuple:
        """Trim to the most recent ``rolling_window_months`` of data.

        If the DataFrame has a DatetimeIndex or a 'date'/'timestamp' column,
        the window is calendar-based.  Otherwise, the last
        ``rolling_window_months * 21`` rows are used (approx trading days).
        """
        n_rows = len(features_df)

        # Try calendar-based window
        dt_index = None
        if isinstance(features_df.index, pd.DatetimeIndex):
            dt_index = features_df.index
        elif "date" in features_df.columns:
            dt_index = pd.to_datetime(features_df["date"], errors="coerce")
        elif "timestamp" in features_df.columns:
            dt_index = pd.to_datetime(features_df["timestamp"], errors="coerce")

        if dt_index is not None and not dt_index.isna().all():
            cutoff = dt_index.max() - pd.DateOffset(months=self.rolling_window_months)
            mask = dt_index >= cutoff
            mask_arr = mask.values if hasattr(mask, 'values') else np.asarray(mask)
            return features_df.loc[mask], labels[mask_arr]

        # Fallback: row-count approximation
        approx_rows = self.rolling_window_months * 21
        if n_rows > approx_rows:
            return features_df.iloc[-approx_rows:], labels[-approx_rows:]
        return features_df, labels

    # ------------------------------------------------------------------
    # A/B comparison
    # ------------------------------------------------------------------

    def _compare_models(
        self,
        old_model: SignalModel,
        new_model: SignalModel,
        holdout_features: pd.DataFrame,
        holdout_labels: np.ndarray,
    ) -> ABResult:
        """Compare old and new model on a holdout set."""
        from sklearn.metrics import accuracy_score

        has_two_classes = len(np.unique(holdout_labels)) >= 2

        # --- old model ---
        if old_model.trained:
            old_probas = old_model.predict_batch(holdout_features)
            old_preds = (old_probas > 0.5).astype(int)
            old_auc = float(roc_auc_score(holdout_labels, old_probas)) if has_two_classes else 0.5
            old_acc = float(accuracy_score(holdout_labels, old_preds))
        else:
            old_auc = 0.5
            old_acc = 0.0

        # --- new model ---
        new_probas = new_model.predict_batch(holdout_features)
        new_preds = (new_probas > 0.5).astype(int)
        new_auc = float(roc_auc_score(holdout_labels, new_probas)) if has_two_classes else 0.5
        new_acc = float(accuracy_score(holdout_labels, new_preds))

        # --- promotion decision ---
        delta = new_auc - old_auc
        if delta >= self.min_promotion_auc_delta:
            promoted = True
            reason = f"new_auc={new_auc:.4f} >= old_auc={old_auc:.4f} + {self.min_promotion_auc_delta}"
        else:
            promoted = False
            reason = (
                f"new_auc={new_auc:.4f} < old_auc={old_auc:.4f} + "
                f"{self.min_promotion_auc_delta} (delta={delta:.4f})"
            )

        return ABResult(
            old_auc=old_auc,
            new_auc=new_auc,
            old_accuracy=old_acc,
            new_accuracy=new_acc,
            holdout_size=len(holdout_labels),
            promoted=promoted,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Versioned save / prune
    # ------------------------------------------------------------------

    def _save_versioned(self, model: SignalModel) -> Path:
        """Save model with a timestamped filename and return the path."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"signal_model_{ts}.joblib"
        model.save(filename)
        return self.model_dir / filename

    def _prune_old_versions(self) -> List[Path]:
        """Delete model versions beyond ``keep_versions``, oldest first.

        Returns list of deleted paths.
        """
        model_files = sorted(
            self.model_dir.glob("signal_model_*.joblib"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        to_delete = model_files[self.keep_versions:]
        deleted: List[Path] = []
        for fp in to_delete:
            try:
                fp.unlink()
                # Also remove companion feature_stats json if present
                stats_path = fp.with_suffix(".feature_stats.json")
                if stats_path.exists():
                    stats_path.unlink()
                deleted.append(fp)
                logger.info("Pruned old model version: %s", fp.name)
            except OSError as e:
                logger.warning("Failed to prune %s: %s", fp, e)

        return deleted

    def _count_versions(self) -> int:
        return len(list(self.model_dir.glob("signal_model_*.joblib")))

    # ------------------------------------------------------------------
    # Convenience: list versions
    # ------------------------------------------------------------------

    def list_versions(self) -> List[Dict]:
        """Return metadata for each model version on disk, newest first."""
        model_files = sorted(
            self.model_dir.glob("signal_model_*.joblib"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        versions = []
        for fp in model_files:
            entry = {
                "filename": fp.name,
                "size_bytes": fp.stat().st_size,
                "modified": datetime.fromtimestamp(
                    fp.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            stats_path = fp.with_suffix(".feature_stats.json")
            if stats_path.exists():
                entry["has_feature_stats"] = True
            versions.append(entry)
        return versions
