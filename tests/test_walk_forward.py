"""Tests for WalkForwardValidator and related utilities."""
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier

from compass.walk_forward import (
    FoldResult,
    WalkForwardValidator,
    prepare_features,
    validate_model,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    TARGET_COL,
    DATE_COL,
    RETURN_COL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_walk_forward_data(
    n_per_year=60,
    years=(2020, 2021, 2022, 2023),
    n_numeric=5,
    seed=42,
):
    """Build a synthetic DataFrame that mimics collect_training_data.py output.

    Columns: entry_date, win, return_pct, regime, strategy_type, spread_type,
    plus n_numeric numeric feature columns named f0..fN.
    """
    rng = np.random.RandomState(seed)
    rows = []
    for yr in years:
        for i in range(n_per_year):
            day = 1 + (i * 5) % 28  # spread across months
            month = 1 + (i * 5 // 28) % 12
            rows.append({
                DATE_COL: f"{yr}-{month:02d}-{day:02d}",
                TARGET_COL: int(rng.rand() > 0.45),  # ~55% win rate
                RETURN_COL: float(rng.randn() * 5),
                "regime": rng.choice(["bull", "bear", "high_vol"]),
                "strategy_type": rng.choice(["CS", "IC"]),
                "spread_type": rng.choice(["bull_put_spread", "bear_call_spread"]),
            })
    df = pd.DataFrame(rows)

    # Add numeric feature columns
    numeric_cols = [f"f{i}" for i in range(n_numeric)]
    for col in numeric_cols:
        df[col] = rng.randn(len(df))

    # Add a learnable signal: f0 correlates with win
    df["f0"] = df[TARGET_COL].values * 2.0 + rng.randn(len(df)) * 0.5

    return df, numeric_cols


# ---------------------------------------------------------------------------
# prepare_features
# ---------------------------------------------------------------------------

class TestPrepareFeatures:

    def test_returns_dataframe(self):
        df, num_cols = _make_walk_forward_data()
        result = prepare_features(
            df, numeric_features=num_cols, categorical_features=["regime"],
        )
        assert isinstance(result, pd.DataFrame)

    def test_one_hot_encoding(self):
        df, num_cols = _make_walk_forward_data()
        result = prepare_features(
            df, numeric_features=num_cols, categorical_features=["regime"],
        )
        # Should have regime_bull, regime_bear, regime_high_vol columns
        regime_cols = [c for c in result.columns if c.startswith("regime_")]
        assert len(regime_cols) >= 2

    def test_numeric_features_preserved(self):
        df, num_cols = _make_walk_forward_data(n_numeric=3)
        result = prepare_features(
            df, numeric_features=num_cols, categorical_features=[],
        )
        assert list(result.columns) == num_cols

    def test_nan_filled_with_zero(self):
        df, num_cols = _make_walk_forward_data(n_numeric=2)
        df.loc[0, "f0"] = np.nan
        result = prepare_features(
            df, numeric_features=num_cols, categorical_features=[],
        )
        assert result.iloc[0, 0] == 0.0

    def test_missing_columns_silently_skipped(self):
        df, num_cols = _make_walk_forward_data(n_numeric=2)
        result = prepare_features(
            df, numeric_features=num_cols + ["nonexistent_col"],
            categorical_features=["nonexistent_cat"],
        )
        # Should still produce columns for the two numeric features only
        assert len(result.columns) == 2

    def test_inf_values_sanitized(self):
        df, num_cols = _make_walk_forward_data(n_numeric=2)
        df.loc[0, "f0"] = float('inf')
        df.loc[1, "f1"] = float('-inf')
        result = prepare_features(
            df, numeric_features=num_cols, categorical_features=[],
        )
        assert np.isfinite(result.values).all()


# ---------------------------------------------------------------------------
# FoldResult
# ---------------------------------------------------------------------------

class TestFoldResult:

    def test_to_dict_has_expected_keys(self):
        fr = FoldResult(
            fold=0,
            train_start="2020-01-01",
            train_end="2020-12-31",
            test_start="2021-01-01",
            test_end="2021-12-31",
            n_train=100,
            n_test=50,
            accuracy=0.72,
            precision=0.68,
            recall=0.75,
            brier_score=0.22,
            auc=0.78,
            signal_sharpe=1.5,
            test_win_rate=0.55,
            predictions=np.array([1, 0]),
            probabilities=np.array([0.8, 0.3]),
            test_labels=np.array([1, 0]),
        )
        d = fr.to_dict()
        assert d["fold"] == 0
        assert d["n_train"] == 100
        assert d["accuracy"] == 0.72
        assert d["auc"] == 0.78
        assert "train_period" in d
        assert "test_period" in d

    def test_to_dict_none_auc(self):
        fr = FoldResult(
            fold=0,
            train_start="2020-01-01", train_end="2020-12-31",
            test_start="2021-01-01", test_end="2021-12-31",
            n_train=100, n_test=50,
            accuracy=0.72, precision=0.68, recall=0.75,
            brier_score=0.22, auc=None, signal_sharpe=None,
            test_win_rate=0.55,
            predictions=np.array([1]), probabilities=np.array([0.8]),
            test_labels=np.array([1]),
        )
        d = fr.to_dict()
        assert d["auc"] is None
        assert d["signal_sharpe"] is None


# ---------------------------------------------------------------------------
# WalkForwardValidator — chronological splitting
# ---------------------------------------------------------------------------

class TestWalkForwardValidator:

    def test_splits_by_year_chronologically(self):
        """Each fold should train on earlier years and test on the next year."""
        df, num_cols = _make_walk_forward_data(years=(2020, 2021, 2022))
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)

        folds = result["folds"]
        # 3 years → 2 folds: train[2020]→test[2021], train[2020,2021]→test[2022]
        assert len(folds) == 2
        assert "2020" in folds[0]["train_period"]
        assert "2021" in folds[0]["test_period"]
        assert "2022" in folds[1]["test_period"]

    def test_expanding_window(self):
        """Training set should grow with each fold."""
        df, num_cols = _make_walk_forward_data(years=(2020, 2021, 2022, 2023))
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)
        folds = result["folds"]

        assert len(folds) >= 2
        # Each fold's n_train should be >= previous fold's n_train
        for i in range(1, len(folds)):
            assert folds[i]["n_train"] >= folds[i - 1]["n_train"]

    def test_returns_aggregate_metrics(self):
        df, num_cols = _make_walk_forward_data()
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)

        agg = result["aggregate"]
        assert "accuracy_mean" in agg
        assert "brier_score_mean" in agg
        assert "n_folds" in agg
        assert "total_oos_samples" in agg
        assert agg["n_folds"] >= 2

    def test_aggregate_accuracy_in_range(self):
        df, num_cols = _make_walk_forward_data()
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)
        acc = result["aggregate"]["accuracy_mean"]
        assert 0.0 <= acc <= 1.0

    def test_oos_predictions_concatenated(self):
        df, num_cols = _make_walk_forward_data()
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)

        oos = result["oos_predictions"]
        assert "predictions" in oos
        assert "probabilities" in oos
        assert "labels" in oos
        assert len(oos["predictions"]) == oos["labels"].shape[0]
        assert len(oos["predictions"]) == result["aggregate"]["total_oos_samples"]

    def test_oos_returns_included_when_available(self):
        df, num_cols = _make_walk_forward_data()
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)
        assert "returns" in result["oos_predictions"]

    def test_raises_with_single_year(self):
        df, num_cols = _make_walk_forward_data(years=(2020,))
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        with pytest.raises(ValueError, match="at least 2 distinct years"):
            validator.run(df)

    def test_min_train_samples_respected(self):
        """If min_train_samples is very large, folds should be skipped."""
        df, num_cols = _make_walk_forward_data(n_per_year=10, years=(2020, 2021, 2022))
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
            min_train_samples=1000,  # way more than available
        )
        with pytest.raises(ValueError, match="No valid folds"):
            validator.run(df)

    def test_categorical_features_work(self):
        df, num_cols = _make_walk_forward_data(years=(2020, 2021, 2022))
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=["regime", "strategy_type"],
        )
        result = validator.run(df)
        assert result["n_folds"] >= 1


# ---------------------------------------------------------------------------
# WalkForwardValidator — metrics quality
# ---------------------------------------------------------------------------

class TestWalkForwardMetrics:

    def test_auc_computed_when_both_classes_present(self):
        df, num_cols = _make_walk_forward_data()
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)

        # At least one fold should have AUC
        aucs = [f.get("auc") for f in result["folds"]]
        non_none = [a for a in aucs if a is not None]
        assert len(non_none) > 0

    def test_brier_score_bounded(self):
        df, num_cols = _make_walk_forward_data()
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)
        brier = result["aggregate"]["brier_score_mean"]
        # Brier score is in [0, 1]; random model gives ~0.25
        assert 0.0 <= brier <= 1.0

    def test_signal_sharpe_included(self):
        df, num_cols = _make_walk_forward_data()
        model = DecisionTreeClassifier(random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)
        agg = result["aggregate"]
        # signal_sharpe_mean should exist (may be None if too few signals)
        assert "signal_sharpe_mean" in agg

    def test_fold_result_probabilities_in_range(self):
        df, num_cols = _make_walk_forward_data()
        model = RandomForestClassifier(n_estimators=10, random_state=0)
        validator = WalkForwardValidator(
            model=model,
            numeric_features=num_cols,
            categorical_features=[],
        )
        result = validator.run(df)
        probas = result["oos_predictions"]["probabilities"]
        assert np.all(probas >= 0.0)
        assert np.all(probas <= 1.0)


# ---------------------------------------------------------------------------
# validate_model convenience function
# ---------------------------------------------------------------------------

class TestValidateModel:

    def test_validate_model_with_explicit_model(self):
        df, num_cols = _make_walk_forward_data()
        # Add columns that match the default NUMERIC_FEATURES list
        # (validate_model uses the module defaults)
        model = DecisionTreeClassifier(random_state=0)
        result = validate_model(df, model=model, min_train_samples=5)

        assert "folds" in result
        assert "aggregate" in result
        assert result["n_folds"] >= 1

    def test_validate_model_default_xgboost(self):
        """validate_model() with no model arg should use XGBoost."""
        df, num_cols = _make_walk_forward_data()
        # Need columns matching NUMERIC_FEATURES defaults
        # Add dummy columns for the required features
        for col in NUMERIC_FEATURES:
            if col not in df.columns:
                df[col] = np.random.randn(len(df))

        result = validate_model(df, min_train_samples=5)
        assert result["n_folds"] >= 1
        assert result["aggregate"]["accuracy_mean"] > 0
