# ML Pipeline Reconnaissance — CC-3 Prep Report

**Date:** 2026-03-20
**Author:** CC-3 (ML & Data)
**Branch:** compass-v2
**Purpose:** Audit current ML pipeline, document gaps, plan COMPASS integration

---

## 1. Training Data Inventory

### 1.1 Current Dataset: `ml/training_data.csv`

| Metric | Value |
|--------|-------|
| Rows | 249 |
| Columns | 39 |
| Date range | 2020-02-24 to 2025-12-26 |
| Overall win rate | 82.7% |
| Avg return/trade | -1.86% (skewed by IC losses) |

**Year distribution:**

| Year | Trades | Notes |
|------|--------|-------|
| 2020 | 30 | Includes COVID crash period |
| 2021 | 71 | Bull market, most trades |
| 2022 | 28 | Bear market, fewest trades |
| 2023 | 42 | Recovery year |
| 2024 | 41 | — |
| 2025 | 37 | — |

**Strategy split:** CS=236 (94.8%), IC=13 (5.2%)
**Spread type:** bull_put=218, bear_call=18, unknown=13
**Regime distribution:** bull=216 (86.7%), bear=22, low_vol=6, high_vol=5

### 1.2 EXP-401 Trade Universe (target dataset)

From `output/exp401_robust_score.json` — the champion config (CS 12% + SS 3%):

| Year | Trades | Win Rate | Return |
|------|--------|----------|--------|
| 2020 | 51 | 78.4% | +24.1% |
| 2021 | 86 | 89.5% | +107.4% |
| 2022 | 39 | 74.4% | +8.1% |
| 2023 | 60 | 86.7% | +43.2% |
| 2024 | 62 | 79.0% | +26.4% |
| 2025 | 55 | 90.9% | +35.0% |
| **Total** | **353** | **83.6%** | **+40.7% avg** |

**Gap:** Current training data has 249 trades (CS+IC from EXP-400 config). EXP-401 has 353 trades (CS+SS with regime scaling). Need to re-harvest with EXP-401 config to get the full 353-trade dataset including StraddleStrangle trades.

### 1.3 Features in Current Training Data (39 columns)

**Identity (5):** entry_date, exit_date, year, strategy_type, spread_type
**Timing (4):** dte_at_entry, hold_days, day_of_week, days_since_last_trade
**Regime (1):** regime
**Technical (4):** rsi_14, momentum_5d_pct, momentum_10d_pct, (no MACD/Bollinger)
**VIX/IV (5):** vix, vix_percentile_20d, vix_percentile_50d, vix_percentile_100d, iv_rank
**Price/MAs (6):** spy_price, dist_from_ma20_pct, dist_from_ma50_pct, dist_from_ma80_pct, dist_from_ma200_pct, ma20_slope_ann_pct, ma50_slope_ann_pct
**Volatility (4):** realized_vol_atr20, realized_vol_5d, realized_vol_10d, realized_vol_20d
**Trade structure (5):** net_credit, spread_width, max_loss_per_unit, short_strike, otm_pct, contracts
**Outcome (3):** exit_reason, pnl, return_pct, win

### 1.4 Existing Saved Model

| Artifact | Path | Notes |
|----------|------|-------|
| Model | `ml/models/signal_model_20260305.joblib` | **TRAINED ON SYNTHETIC DATA** |
| Feature stats | `ml/models/signal_model_20260305.feature_stats.json` | 49 features, synthetic distributions |

**CRITICAL:** This model was trained via `generate_synthetic_training_data()` with random normal/gamma distributions. It has zero predictive value on real trades. Must be deleted per blueprint.

The synthetic model uses 49 features (from `feature_engine.py`), while real training data has 39 columns (from `collect_training_data.py`). Feature sets are misaligned.

---

## 2. Data Quality Issues

### 2.1 Current Training Data Problems

1. **`spread_width` is constant** — all 249 rows = 12.0. Zero variance = zero information. **DROP.**

2. **Class imbalance** — 82.7% wins (206/249). Not severe but needs stratified splitting.

3. **IC trades are toxic noise** — 13 IC trades with 46.2% WR and -229.53% avg return massively skew `return_pct`. The full dataset avg return is -1.86% despite 82.7% WR because a few IC max-loss exits dominate.

4. **Missing values** — only `days_since_last_trade` has 6 NULLs (first trade per year). Trivially fillable.

5. **Outliers (>5 std from mean):**
   - `realized_vol_5d`: 2 outliers (COVID spike)
   - `realized_vol_10d`: 3 outliers
   - `pnl`: 3 outliers (IC max-loss exits)
   - `return_pct`: 2 outliers (same IC exits)

6. **Regime imbalance** — 86.7% trades are in `bull` regime. Only 5 `high_vol` and 6 `low_vol` trades. Model will struggle to learn non-bull patterns.

7. **No StraddleStrangle trades** — current data only has CS+IC. EXP-401 includes SS trades.

### 2.2 Feature Correlation with Win/Loss (top signals)

| Feature | Correlation | Interpretation |
|---------|------------|----------------|
| hold_days | -0.336 | Longer holds = worse outcomes (time decay working against) |
| realized_vol_5d | -0.335 | High recent vol = worse outcomes |
| realized_vol_10d | -0.315 | Same pattern, 10d window |
| iv_rank | -0.299 | Higher IV rank = worse (counterintuitive, likely regime confound) |
| vix | -0.294 | Higher VIX = worse |
| realized_vol_20d | -0.267 | Same vol pattern |
| dte_at_entry | -0.244 | Longer DTE = worse |
| dist_from_ma200_pct | +0.223 | Above MA200 = better (trend filter) |
| vix_percentile_100d | -0.208 | High VIX percentile = worse |
| dist_from_ma80_pct | +0.181 | Above MA80 = better |
| rsi_14 | +0.152 | Higher RSI = better (momentum) |

**Key insight:** Volatility cluster (vix, iv_rank, realized_vol) is the dominant signal. Trend distance (ma200, ma80) is secondary. These are real signals that XGBoost can exploit.

---

## 3. IronVault Integration Points

### 3.1 Files That Import yfinance (ML-relevant subset)

| File | Lines | Usage | Replacement |
|------|-------|-------|-------------|
| `ml/feature_engine.py` | 19, 56, 321 | `yf.download()` for price data, `yf.Ticker()` for earnings | IronVault daily bars |
| `ml/iv_analyzer.py` | 18, 313 | `yf.download()` for HV proxy | IronVault daily bars |
| `ml/collect_training_data.py` | 603, 606, 612 | `yf.download("SPY"/"^VIX")` for full history | IronVault + external VIX |
| `ml/regime_detector.py` | 18, 69 | `yf.download()` for HMM training | IronVault daily bars |
| `ml/sentiment_scanner.py` | 20, 173 | `yf.Ticker()` for options chain | IronVault strikes/pricing |
| `engine/portfolio_backtester.py` | 17, 182-188, 219-225 | Core OHLCV + VIX downloads | IronVault + external VIX |
| `shared/data_cache.py` | 8, 58, 101 | TTL cache wrapping yfinance | IronVault |
| `strategy/options_analyzer.py` | 12, 118, 250 | Fallback options chain | IronVault |

### 3.2 IronVault API Summary

**Source:** `shared/iron_vault.py` — singleton wrapping `HistoricalOptionsData`

Key methods for ML pipeline:
- `get_contract_price(symbol, date)` → `Optional[float]`
- `get_available_strikes(ticker, expiration, as_of_date, option_type)` → `List[float]`
- `get_spread_prices(ticker, exp, short, long, type, date)` → `Optional[Dict]`
- `get_intraday_bar(symbol, date_str, hour, minute)` → `Optional[Dict]`
- `coverage_report()` → `Dict`

**Critical constraint:** IronVault returns `None` on cache miss. No synthetic fallback. VIX data is NOT in IronVault — needs external source.

### 3.3 Synthetic Fallback Violations in `feature_engine.py`

The current `FeatureEngine` returns hardcoded defaults when data is missing:
- `rsi_14=50.0`, `macd=0.0`, `bollinger_pct_b=0.5`
- `realized_vol_*=20.0`, `iv_rank=50.0`, `current_iv=20.0`
- `put_call_ratio=1.0`, `spy_realized_vol=15.0`

**Per blueprint:** All these must become `None` returns. Caller skips trade on any `None`.

---

## 4. Feature Engineering Plan

### 4.1 Features to ADD (per blueprint + correlation analysis)

| Feature | Source | Rationale |
|---------|--------|-----------|
| `credit_to_width_ratio` | `net_credit / spread_width` | Spread mechanics — how much premium vs risk |
| `regime_duration_days` | Regime series | How long current regime has persisted (mean-reversion signal) |
| `vix_change_5d` | VIX history | VIX momentum (more informative than spot level) |
| `macro_score` | `macro_state.db` | COMPASS macro intelligence (0-100) |
| `risk_appetite` | `macro_state.db` | Fed policy + market sentiment dimension |
| `score_velocity` | `macro_state.db` | Macro momentum |
| `event_scaling` | COMPASS events | Position scaling from FOMC/CPI/NFP proximity |

### 4.2 Features to DROP

| Feature | Reason |
|---------|--------|
| `spread_width` | Constant (12.0 for all 249 trades). Zero variance. |
| `vix_percentile_20d` | Redundant with vix + vix_percentile_50d + iv_rank (r>0.8) |
| `ma20_slope_ann_pct`, `ma50_slope_ann_pct` | Lagged momentum signal, low correlation with outcome |
| `days_to_earnings`, `days_to_fomc`, `days_to_cpi` (raw) | Replace with composite `event_scaling` from COMPASS |

### 4.3 Feature Set Alignment Issue

Current `feature_engine.py` (live prediction) has 49 features. Current `collect_training_data.py` (training) has 39 columns. These must be aligned to a single canonical set of ~35 features. Blueprint targets `compass/features.py` with unified feature set.

---

## 5. XGBoost Walk-Forward Plan

### 5.1 Data Requirements

- **Source:** Re-harvest from EXP-401 config (353 trades, CS+SS)
- **Enrichment:** Full market context at entry time (all features from Section 4)
- **Output:** `training_data_combined.csv`, chronologically ordered, NO shuffling
- **Target rows:** ~350-400 after enrichment

### 5.2 Walk-Forward Fold Definitions (3-fold anchored)

| Fold | Train Period | Test Period | Est. Train Size | Est. Test Size |
|------|-------------|-------------|-----------------|----------------|
| 1 | 2020-2022 | 2023 | ~176 trades | ~60 trades |
| 2 | 2020-2023 | 2024 | ~236 trades | ~62 trades |
| 3 | 2020-2024 | 2025 | ~298 trades | ~55 trades |

**Key:** Training window is anchored (always starts 2020). Expanding window, not sliding. Temporal order strictly preserved.

### 5.3 XGBoost Hyperparameters (current → planned)

| Parameter | Current | Planned | Notes |
|-----------|---------|---------|-------|
| max_depth | 6 | 4-5 | Reduce overfitting risk with 350 samples |
| learning_rate | 0.05 | 0.03-0.05 | Lower to compensate for fewer boosting rounds |
| n_estimators | 200 | 100-300 (early stop) | Early stopping on validation fold |
| min_child_weight | 5 | 10-20 | More conservative with small dataset |
| subsample | 0.8 | 0.7-0.8 | — |
| colsample_bytree | 0.8 | 0.6-0.8 | Reduce to avoid overfitting on few features |
| gamma | 1 | 1-2 | Increase regularization |

### 5.4 Evaluation Metrics per Fold

| Metric | What | Pass Threshold |
|--------|------|----------------|
| AUC-ROC | Discrimination | ≥ 0.70 |
| Calibration MAE | Prob accuracy | ≤ 0.05 |
| Feature importance overlap | Stability | Top 10 ≥ 80% overlap across folds |
| Confidence trade rate | Utility | 5-20% of trades above threshold (0.50) |

### 5.5 G1-G4 Gate Criteria (Day 11 decision point)

| Gate | Metric | Threshold | Impact if FAIL |
|------|--------|-----------|----------------|
| **G1** | 3-fold AUC ≥ 0.70 all folds | Required | ML integration blocked |
| **G2** | Calibration error ≤ 0.05 all folds | Required | Can't trust probabilities for sizing |
| **G3** | Top-10 feature overlap ≥ 80% across folds | Required | Model overfitting to year-specific noise |
| **G4** | 5-20% trades above confidence threshold | Required | Model too aggressive or too passive |

**If G1-G4 PASS:** Proceed to Phase 4 (M-001 through M-005 backtests)
**If G1-G4 FAIL:** Document negative result, keep EXP-401 champion as-is

---

## 6. Macro State Database Inventory

### 6.1 `data/macro_state.db` Tables

| Table | Rows | Date Range | Key Columns |
|-------|------|------------|-------------|
| `snapshots` | 324 | 2020-01-03 to 2026-03-13 | spy_close, top_sector_3m, macro_overall |
| `sector_rs` | 4,860 | 2020-01-03 to 2026-03-13 | ticker, rs_3m, rs_12m, rrg_quadrant |
| `macro_score` | 324 | 2020-01-03 to 2026-03-13 | overall, growth, inflation, fed_policy, risk_appetite, regime |
| `macro_events` | 195 | 2020-01-29 to 2026-03-20 | event_type, scaling_factor |
| `macro_state` | 5 | — | Key-value config store |

**Coverage:** Weekly snapshots (324 points over 6.2 years). Good alignment with training data date range (2020-2025). Macro features can be joined to trades by nearest prior snapshot date.

### 6.2 Macro Score Dimensions (available for feature enrichment)

- `overall` (0-100): Composite macro health
- `growth`: Economic growth dimension
- `inflation`: Inflation dimension
- `fed_policy`: Fed policy dimension
- `risk_appetite`: Market risk appetite
- `score_velocity`: Rate of change in macro score
- `risk_app_velocity`: Rate of change in risk appetite
- `regime`: Macro regime label (BULL_MACRO, BEAR_MACRO, etc.)

### 6.3 Sector RS Data (potential features)

4,860 rows across 15 ETFs. Each has `rs_3m`, `rs_12m`, `rs_ratio`, `rs_momentum`, `rrg_quadrant`. Could derive:
- Number of sectors in "Leading" quadrant (breadth signal)
- Top sector concentration (diversity signal)
- SPY-specific RRG position

---

## 7. Combo Regime Detector → regime.py Absorption

### 7.1 What Gets Absorbed

`ml/combo_regime_detector.py` (231 lines) provides:
- **3-signal voting system:** price_vs_ma200, rsi_momentum, vix_structure (VIX/VIX3M)
- **Asymmetric voting:** bull needs 2/3, bear needs 3/3 (unanimous)
- **10-day hysteresis** (cooldown before regime change accepted)
- **VIX circuit breaker** (VIX > 40 → force BEAR)
- **MA200 confidence band** (±0.5% → abstain)

### 7.2 What `compass/regime.py` Becomes

Per blueprint: unified `RegimeClassifier` merging `engine/regime.py` (5-regime system: bull/bear/high_vol/low_vol/crash) with combo detector's voting + hysteresis. Output stays 5-regime (not 3-regime), but gains:
- Configurable thresholds via config dict
- RSI momentum signal
- VIX/VIX3M term structure signal
- Shift-by-1 lookahead protection
- Hysteresis

### 7.3 Impact on ML Features

Regime features in training data currently just have `regime` as a string label. After absorption, regime features should include:
- regime label (one-hot: bull/bear/high_vol/low_vol/crash)
- regime confidence score
- regime duration (days since last change)
- individual signal votes (bull_votes, bear_votes)

---

## 8. Action Items for Phase 2-3

### Phase 2 (CC-3 tasks)
- [ ] Move `ml/signal_model.py` → `compass/signal_model.py`
- [ ] Move `ml/feature_engine.py` → `compass/features.py` (with IronVault refactor)
- [ ] Move `ml/iv_analyzer.py` → `compass/iv_surface.py` (with IronVault refactor)
- [ ] Move `ml/collect_training_data.py` → `compass/collect_training_data.py`
- [ ] Absorb `ml/combo_regime_detector.py` into `compass/regime.py`
- [ ] Delete `generate_synthetic_training_data()` from signal_model.py
- [ ] Delete `ml/models/signal_model_20260305.joblib` (synthetic model artifact)

### Phase 3 (CC-3 tasks)
- [ ] Replace all yfinance calls in features.py/iv_surface.py with IronVault
- [ ] Remove all synthetic fallback defaults (return None on cache miss)
- [ ] Re-harvest training data from EXP-401 config (353 trades)
- [ ] Add macro features from macro_state.db
- [ ] Add new features: credit_to_width_ratio, regime_duration, vix_change_5d
- [ ] Drop dead features: spread_width, ma_slopes, redundant vix_percentiles
- [ ] Align feature sets between features.py and collect_training_data.py
- [ ] Train XGBoost with 3-fold anchored walk-forward
- [ ] Evaluate G1-G4 gates
- [ ] Write tests: test_collect_training_data.py (8+ tests)

---

## 9. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Only 353 trades for XGBoost training | HIGH | Conservative hyperparams, heavy regularization, realistic expectations |
| Regime imbalance (86.7% bull) | MEDIUM | Stratified sampling, class weights, but limited bear/crash samples remain |
| Feature-target leakage risk | HIGH | Strict temporal ordering, no future data in features |
| VIX data not in IronVault | MEDIUM | Must maintain external VIX source (yfinance or Polygon) for backtest enrichment |
| IC trades skew return metrics | LOW | Filter to CS+SS only for EXP-401 training set |
| Model may not beat rule-based baseline | MEDIUM | G1-G4 gates provide honest go/no-go. Negative result is acceptable. |

---

*Generated by CC-3 ML Pipeline Audit — 2026-03-20*
