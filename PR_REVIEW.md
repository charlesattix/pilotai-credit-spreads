# PR Review: `origin/maximus/ensemble-ml`

**Reviewer:** Claude Code (automated static analysis)
**Date:** 2026-03-24
**Branch:** `origin/maximus/ensemble-ml` vs `main`
**Scope:** +7,309 / -46,836 lines across 179 files
**Commits:** 2 — `feat: Maximus ML integration` (5016dad) + `test: add tests` (bad697c)

---

## VERDICT: ❌ DO NOT MERGE

**Blockers:** 5 critical issues (3 ML bugs + 2 deployment-breaking deletions)
**High issues:** 6 additional high-severity findings

---

## Summary Table

| # | Severity | Category | File | Issue |
|---|----------|----------|------|-------|
| 1 | CRITICAL | Data Leakage | `ensemble_signal_model.py:276` | Random shuffle train/test split on time-series data |
| 2 | CRITICAL | Deployment | `Procfile` (deleted) | No valid Railway start command after merge |
| 3 | CRITICAL | Live Trading | `scan-cron.sh` | Silently replaces EXP-400/401/503/600 with retired exps |
| 4 | CRITICAL | Security | `SECURITY_AUDIT.md` (deleted) | Hides findings without fixing SQL/command injection |
| 5 | CRITICAL | Runtime Crash | `portfolio_optimizer.py` | Depends on `macro_state.db` which same PR deletes |
| 6 | HIGH | Data Leakage | `walk_forward.py:236` | One-hot encoding fitted on full dataset before fold split |
| 7 | HIGH | ML Bug | `ensemble_signal_model.py:483` | Confidence threshold formula off by ~2x |
| 8 | HIGH | Numerical | `portfolio_optimizer.py:157` | No covariance matrix regularization → explosive weights |
| 9 | HIGH | Dashboard | `web_dashboard/` (deleted) | Entire auth+dashboard system deleted, no replacement |
| 10 | HIGH | Data Pipeline | `sync_dashboard_data.py` (deleted) | Railway data sync pipeline destroyed |
| 11 | HIGH | Visual Bug | `stress_test.py:401` | `equity_path` is index path, not portfolio path |
| 12 | MEDIUM | ML | `ensemble_signal_model.py:305` | `eval_set` passed without `early_stopping_rounds` |
| 13 | MEDIUM | Online Retrain | `online_retrain.py:269` | Performance baseline includes in-sample data |
| 14 | MEDIUM | Metrics | `portfolio_optimizer.py:341` | Sharpe computed on pre-scaling weights, not deployed weights |
| 15 | MEDIUM | Walk-Forward | `walk_forward.py:394` | Sharpe annualization hardcoded `sqrt(52)` |
| 16 | MEDIUM | Experiments | `experiments/registry.json` (deleted) | Audit trail for live paper trades destroyed |

---

## Part 1 — ML Code Review

### 1. `compass/ensemble_signal_model.py` (734 lines, new)

#### CRITICAL — Random Shuffle Split on Time-Series (line 276)

```python
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y,
)
```

`sklearn.train_test_split` with `stratify=y` applies a **random shuffle** to time-series trading data. The 20% test set will contain trades randomly scattered across the full date range, including dates earlier than many training samples. The model is effectively evaluated as if it had future regime knowledge during training. All reported `ensemble_test_auc` figures in `training_stats` are **invalid out-of-sample metrics**.

The same pattern repeats at line 289 (calibration split from `X_train`) and line 305 (XGBoost inner validation split). The entire train/calibrate/test pipeline is temporally incoherent.

**Fix:** Replace with a temporal split:
```python
split_idx = int(len(X) * 0.8)
X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
```

#### HIGH — Confidence Threshold Formula Bug (line 483-487)

```python
confidence_thresholds = [0.6, 0.7, 0.8]
confident_mask = np.abs(probabilities - 0.5) * 2 >= (thresh - 0.5)
```

The RHS should be `thresh`, not `thresh - 0.5`. As written:
- "60% confidence" bucket selects trades with probability ≥ 0.55 (not 0.60)
- "70% confidence" bucket selects trades with probability ≥ 0.60 (not 0.70)
- "80% confidence" bucket selects trades with probability ≥ 0.65 (not 0.80)

The backtest metrics under `threshold_results` are mislabeled by roughly 2x. Any confidence gate tuned from these numbers will use the wrong threshold in production.

**Fix:** `confident_mask = np.abs(probabilities - 0.5) * 2 >= thresh`

#### MEDIUM — `eval_set` Without `early_stopping_rounds` (line 305-311)

```python
est.fit(X_inner, y_inner, eval_set=[(X_val, y_val)], verbose=False)
```

`early_stopping_rounds` is absent from `_XGB_PARAMS` and the `fit()` call. XGBoost trains all 200 estimators regardless of validation performance. The `eval_set` is dead code — it logs but does not stop. Add `early_stopping_rounds=20` to avoid overfitting.

#### LOW — Walk-Forward Weight Computation (lines 127-192)

The `_walk_forward_weights()` expanding-window implementation is **correct**. Fold `k` trains on `X[:k*fold_size]`, validates on `X[k*fold_size:(k+1)*fold_size]`. No fence-post error. AUC-minus-0.5 weighting is reasonable. No issues.

---

### 2. `compass/walk_forward.py` (501 lines, new)

#### HIGH — One-Hot Encoding Leakage via Full-Dataset `prepare_features` (lines 236-247)

```python
# Build feature matrix once on full data to get consistent one-hot columns
features_full = prepare_features(df, ...)
feature_cols = list(features_full.columns)
```

`pd.get_dummies()` is called on the **entire dataset** before fold splitting. Any new category value first appearing in year N causes a column to be added to all prior years (zero-filled). Earlier folds "know" that a future category exists — structural leakage from future data. The comment even acknowledges the purpose is "consistency," which is achieved at the cost of lookahead.

**Fix:** Call `prepare_features()` only on the training slice per fold; align test columns to match, filling unseen categories with zero.

#### MEDIUM — Sharpe Annualization Hardcoded `sqrt(52)` (line 394)

```python
signal_sharpe = (mean_r / std_r) * np.sqrt(52)
```

Assumes 52 trades per year, hardcoded. If trade frequency differs, reported `signal_sharpe` in `FoldResult` will be systematically wrong. Should derive annualization factor from actual trades-per-year in each fold.

#### LOW — Walk-Forward Logic is Correct

Expanding-window by year (`train_years = years[:fold_idx+1]`, `test_year = years[fold_idx+1]`) is correctly implemented. No train/test overlap. Fresh `clone(model)` per fold. No issues.

---

### 3. `compass/online_retrain.py` (522 lines, new)

#### MEDIUM — Performance Baseline Includes In-Sample Data (lines 269-282)

`_check_performance()` evaluates the current model on the full `features_df` passed in, including data the model was trained on. The resulting AUC "baseline" is optimistically inflated. The retrain-on-degradation trigger (`perf_auc_drop=0.05`) needs a larger real degradation to fire, making the system under-sensitive to genuine model decay.

**Fix:** Evaluate only on the holdout slice (`features_df.iloc[-n_holdout:]`) for the baseline.

#### LOW — Holdout Split is Temporal (Correct)

Lines 192-195 correctly reserve the most recent 20% as holdout. No leakage here.

#### LOW — `min_promotion_auc_delta=-0.005` Allows Worse Models to Promote

Intentional per docstring, but means the ensemble can silently degrade by 0.5 AUC points per cycle. Warrants monitoring.

---

### 4. `compass/portfolio_optimizer.py` (439 lines, new)

#### CRITICAL (runtime) — Depends on `macro_state.db` Which This Same PR Deletes

`_fetch_macro_regime()` reads from `deploy/macro-api/data/macro_state.db`. That database (933,888 bytes) is **deleted by this same PR**. Any call to `optimize()` that uses macro tilt will throw `sqlite3.OperationalError: unable to open database file` at runtime.

#### HIGH — No Covariance Matrix Regularization (lines 157-158, 225-226)

```python
inv_cov = np.linalg.inv(self.cov_matrix)
```

Both `max_sharpe()` and `min_variance()` use exact matrix inversion without regularization. Near-singular covariance matrices (common with only 4 highly-correlated SPY experiments in short windows) will produce numerically explosive inverse values, leading to extreme weights that are then clipped to floor values — silently degenerating to equal-weight allocation with no warning.

**Fix:** Add ridge regularization: `inv_cov = np.linalg.inv(cov + epsilon * np.eye(n))`

#### MEDIUM — Metrics Computed on Pre-Scaling Weights (lines 341-343)

```python
w = tilted_weights  # NOT scaled_weights
ann_return = float(w @ self.mean_returns * self.periods_per_year)
```

`OptimizationResult.metrics` (Sharpe, annual return, vol) reflect full-capital allocation. But `scaled_weights` (what gets deployed) may be reduced to 0.5× during event windows. Reported Sharpe will not match realized performance when event scaling is active.

---

### 5. `compass/stress_test.py` (749 lines, new)

#### HIGH — `equity_path` Shows Index Drawdown, Not Portfolio Drawdown (lines 401-440)

```python
equity = _returns_to_equity(shocks, self.starting_capital)   # INDEX path
adjusted_trough = self.starting_capital * (1 + adjusted_trough_pct)  # portfolio trough
results.append({
    "equity_path": equity.tolist(),   # BUG: index path, not portfolio path
    "trough_value": round(adjusted_trough, 2),  # correctly adjusted
```

`equity_path` is built from raw index shocks. `trough_value` and `portfolio_drawdown_pct` correctly apply `spread_beta=1.5`. Any visualization of `equity_path` will show -34% for COVID while the summary says -51% — contradictory numbers from the same scenario.

**Fix:** Build `equity_path` from `adjusted_shocks = shocks * spread_beta`.

#### MEDIUM — `spread_beta=1.5` Hardcoded Without Empirical Basis (line 408)

Applied identically to all four crisis scenarios regardless of DTE, position sizing, or delta. A deep OTM spread at DTE=35 has meaningfully different crash sensitivity than a near-ATM position near expiration. This constant is not documented as a model limitation and is not configurable.

---

## Part 2 — Deletion Audit

### CRITICAL — `Procfile` Deleted With No Valid Replacement

`web: uvicorn web_dashboard.app:app --host 0.0.0.0 --port $PORT` is deleted. The `railway.toml` specifies start command `./docker-entrypoint.sh all` — but `docker-entrypoint.sh` is **not added** by this PR. Railway will fail to start after merge.

### CRITICAL — `web_dashboard/` Deleted Entirely (~1,530 lines across 4 files)

The entire auth + dashboard system built on `main` today is deleted:
- `web_dashboard/app.py` — FastAPI app with session auth, 8 endpoints, rate limiting
- `web_dashboard/auth.py` — HMAC-SHA256 session tokens, 24h TTL
- `web_dashboard/data.py` — experiment data aggregation layer
- `web_dashboard/html.py` — HTML renderer with XSS protections

No replacement dashboard is added. Railway will have no web service to deploy.

### CRITICAL — `SECURITY_AUDIT.md` Deleted (399 lines)

Deletes documentation of 15 security findings — including 5 CRITICAL (SQL injection in `database.py`, command injection in `pilotctl.py`, secrets in VCS). The underlying vulnerabilities **remain in the codebase**. This deletion hides the audit trail without fixing any issues.

### CRITICAL — `scan-cron.sh` Replaces Live Experiments With Retired Ones

```bash
# BEFORE (main) — currently running:
_run_scan "exp400"  "configs/paper_champion.yaml"  ".env.exp400"  "data/pilotai_exp400.db"
_run_scan "exp401"  "configs/paper_exp401.yaml"    ".env.exp401"  "data/pilotai_exp401.db"
_run_scan "exp503"  "configs/paper_exp503.yaml"    ".env.exp503"  "data/pilotai_exp503.db"
_run_scan "exp600"  "configs/paper_exp600.yaml"    ".env.exp600"  "data/pilotai_exp600.db"

# AFTER (this branch) — retired experiments:
_run_scan "exp036"  "configs/paper_exp036.yaml"    ".env.exp036"  "data/pilotai_exp036.db"
_run_scan "exp059"  "configs/paper_exp059.yaml"    ".env.exp059"  "data/pilotai_exp059.db"
_run_scan "exp154"  "configs/paper_exp154.yaml"    ".env.exp154"  "data/pilotai_exp154.db"
_run_scan "exp305"  "configs/paper_exp305.yaml"    ".env.exp305"  "data/pilotai_exp305.db"
```

All four live paper trading experiments (EXP-400 The Champion, EXP-401 The Blend, EXP-503 ML V2 Aggressive, EXP-600 IBIT Adaptive) would **stop scanning on merge**. The branch silently reinstates EXP-036/059/154/305 which are retired experiments.

### HIGH — `experiments/registry.json` Deleted

Complete audit trail for all paper trading experiments lost. Live Alpaca account IDs, configs, phases, and notes for EXP-400 through EXP-601 are deleted with no documented handoff.

### HIGH — `scripts/sync_dashboard_data.py` Deleted (654 lines)

The Alpaca data sync pipeline to Railway is destroyed. Even if a replacement dashboard were present, it would have no data.

### MEDIUM — All Crypto Infrastructure Deleted

`compass/crypto/` (8 files), `backtest/ibit_backtester.py`, `ml/regime_model_router.py`, all IBIT configs and tests. EXP-600 (IBIT Adaptive, Charles's experiment) loses all supporting code.

---

## Part 3 — Breaking Changes After Merge

| Component | State After Merge |
|-----------|------------------|
| Railway web process | **BROKEN** — no `Procfile`, `docker-entrypoint.sh` missing |
| Live paper trading scans (EXP-400/401/503/600) | **STOPPED** — cron points to retired experiments |
| Alpaca data sync to Railway | **BROKEN** — `sync_dashboard_data.py` deleted |
| Experiment audit trail | **GONE** — `registry.json` deleted |
| `portfolio_optimizer._fetch_macro_regime()` | **RUNTIME CRASH** — `macro_state.db` deleted in same PR |
| Security audit findings | **HIDDEN** — `SECURITY_AUDIT.md` deleted, vulns unfixed |
| IBIT/crypto strategy (EXP-600) | **GONE** — all infrastructure deleted |

---

## Part 4 — What Is Actually Good Here

The five new ML modules are **architecturally sound** and well-documented. The concepts are strong:
- Ensemble of XGBoost + Logistic Regression + Random Forest with walk-forward weighting is a reasonable approach for regime classification
- Online retraining pipeline with performance monitoring and holdout validation is production-grade thinking
- Portfolio optimizer supporting mean-variance, risk-parity, and ERC is well-structured
- Block-bootstrap Monte Carlo stress testing is appropriate for autocorrelated returns
- Walk-forward validation framework with fold-level metrics is the right methodology

The implementation bugs identified above are fixable. The ML code is worth keeping — just not at the cost of the existing live infrastructure.

---

## Recommended Path Forward

Instead of merging this branch, **cherry-pick only the new ML files** onto `main`:

```bash
git checkout origin/maximus/ensemble-ml -- \
  compass/ensemble_signal_model.py \
  compass/online_retrain.py \
  compass/portfolio_optimizer.py \
  compass/stress_test.py \
  compass/walk_forward.py \
  tests/test_online_retrain.py
```

Then open a separate PR to fix the 3 critical ML bugs before any production use:
1. `ensemble_signal_model.py:276` — temporal train/test split
2. `walk_forward.py:236` — per-fold one-hot encoding
3. `ensemble_signal_model.py:487` — confidence threshold formula

Do NOT merge the deletions of `web_dashboard/`, `Procfile`, `registry.json`, `SECURITY_AUDIT.md`, or `scan-cron.sh`.

---

## Required Blockers Before Any ML Production Use

1. **[CRITICAL]** Fix temporal train/test split in `ensemble_signal_model.py:276`
2. **[CRITICAL]** Fix per-fold one-hot encoding in `walk_forward.py:236`
3. **[CRITICAL]** Fix confidence threshold formula in `ensemble_signal_model.py:487`
4. **[HIGH]** Add covariance matrix regularization in `portfolio_optimizer.py:157,225`
5. **[HIGH]** Fix `equity_path` in stress_test results to use adjusted (portfolio) returns
6. **[HIGH]** Restore `macro_state.db` dependency or refactor `_fetch_macro_regime()` before using `portfolio_optimizer`

---

*Review performed via static analysis of git diff and full file reads. No runtime execution of ML models. Additional bugs may exist in untested code paths.*
