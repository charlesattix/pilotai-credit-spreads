# ML Retrain Proposal — EXP-500 Phase 2

**Date:** 2026-03-20
**Status:** PROPOSAL — no implementation until approved

---

## 1. Current State: What Real Data We Have

### Primary Dataset: `ml/training_data.csv` (249 trades)
- **Source:** EXP-400 backtest (CS + IC, SPY, 2020-2025) via `ml/collect_training_data.py`
- **Pricing:** Real Polygon data through IronVault — no synthetic pricing
- **39 features** per trade (market context, vol surface, trade structure, outcome)
- **Breakdown:**
  - CS: 236 trades (84.7% WR), IC: 13 trades (46.2% WR)
  - By year: 2020=30, 2021=71, 2022=28, 2023=42, 2024=41, 2025=37
  - By regime: bull=216, bear=22, high_vol=5, low_vol=6
- **Class imbalance:** 206 wins / 43 losses (82.7% / 17.3%)

### Untapped Dataset: EXP-401 Phase 4 Validation (353 trades)
- **Source:** `output/final_validation_results.json` confirms 353 trades (CS + SS, regime-scaled)
- **Trade-level data NOT yet extracted** — only aggregate stats in validation file
- **Must re-run** `collect_training_data.py` with EXP-401 config to harvest features
- **Breakdown** (from validation summary):
  - 2020=51, 2021=86, 2022=39, 2023=60, 2024=62, 2025=55
  - Includes straddle/strangle trades (absent from current 249)

### Aggregate-Only Data (NOT usable for trade-level ML)
- **EXP-600 sweeps:** 600+ parameter configs, 54K+ aggregate trade counts — but no per-trade features
- **EXP-601/602/603/604:** Same — aggregate yearly stats per config, no trade logs
- **Leaderboards:** Config-level performance summaries only

### What's Useless
- **`signal_model_20260305.joblib`** — trained on `generate_synthetic_training_data()`: hand-crafted distributions with rule-based labels. Violates the "no synthetic data" directive. Delete it.
- **`output/champion_trade_log.json`** (560 trades) — old heuristic backtester output, synthetic pricing. Invalid.
- **`output/leaderboard_500run.json` / `leaderboard_aggressive.json`** — heuristic-era runs. Invalid.

---

## 2. Feature Engineering Plan

### Keep from Current 39 Features (Proven Predictors)
Per `ml/feature_analysis.md`, strongest correlates with win/loss:

| Feature | Correlation | Keep? |
|---------|------------|-------|
| `iv_rank` | -0.30 | Yes |
| `vix` | -0.29 | Yes |
| `realized_vol_20d` | -0.27 | Yes |
| `dte_at_entry` | -0.24 | Yes |
| `otm_pct` | -0.22 | Yes |
| `dist_from_ma200_pct` | +0.22 | Yes |
| `rsi_14` | +0.17 | Yes |
| `momentum_10d_pct` | +0.16 | Yes |
| `dist_from_ma80_pct` | +0.18 | Yes |

### Drop (Low Signal or Redundant)
- `spread_width` — constant at 12.0 across all EXP-400 trades (zero variance)
- `vix_percentile_20d/50d/100d` — redundant with `iv_rank` and `vix`
- `ma20_slope_ann_pct`, `ma50_slope_ann_pct` — noisy, correlated with momentum

### Add New Features (from IronVault data at entry time)
1. **Vol term structure slope:** `iv_rank_30d - iv_rank_60d` (contango/backwardation)
2. **Credit-to-width ratio:** `net_credit / spread_width` (edge quality metric)
3. **Regime duration:** days since last regime change (regime stability)
4. **Recent strategy performance:** rolling 10-trade win rate (momentum/mean-reversion of strategy itself)
5. **VIX change 5d:** short-term vol trend (not just level)
6. **Day-of-week encoding:** currently raw int; convert to `is_monday`, `is_friday` (known patterns)

### Target Variable
- **Binary classification:** `win` (pnl > 0) = 1, else 0
- Do NOT use regression on `return_pct` — too noisy with IC outliers (-1249% single trade)
- Consider secondary target: `win AND return_pct > 5%` (quality wins vs barely-profitable)

### Final Feature Count: ~35 (after drops + additions)

---

## 3. Train/Test Split Strategy

### Hard Constraint: Time-Series Only — NO Random Splits
Random CV leaks future market regime information into training. Mandatory purged walk-forward.

### Proposed Split: Anchored Walk-Forward (matches Phase 5 validation)

| Fold | Train | Gap | Test | Train Trades (est.) | Test Trades (est.) |
|------|-------|-----|------|--------------------|--------------------|
| 1 | 2020-2022 | 30 days | 2023 | ~100-130 | ~42-60 |
| 2 | 2020-2023 | 30 days | 2024 | ~140-190 | ~41-62 |
| 3 | 2020-2024 | 30 days | 2025 | ~180-250 | ~37-55 |

- **30-day purge gap** between train/test to prevent information leakage from overlapping positions
- **Expanding window** (not sliding) — uses all available history, critical with small N
- **No 2020 as test** — only 30 trades, too few for reliable evaluation

### Data Augmentation: Combine EXP-400 + EXP-401 Datasets
- Re-run `collect_training_data.py` with EXP-401 config → ~353 trades with SS included
- Deduplicate CS trades that appear in both (same entry date + ticker + direction)
- Expected unique total: **~350-400 trades** (CS overlap removed, SS trades added)
- Add `strategy_type` as a feature (CS/IC/SS) so model learns strategy-specific patterns

### Small-N Mitigations
With ~350 samples, overfitting is the primary risk:
- **Max depth ≤ 4** (current 6 is too deep for this N)
- **Min child weight ≥ 10** (current 5 too permissive)
- **n_estimators ≤ 100** with early stopping (current 200 risks memorization)
- **Strong L1/L2 regularization** (reg_alpha=1.0, reg_lambda=5.0)
- **Feature selection:** max 15-20 features (use SHAP importance from Fold 1 to prune)
- **Calibration:** Platt scaling on held-out portion of each fold's test set

---

## 4. Success Criteria vs Champion Baseline

### Champion Baseline (EXP-401 Phase 4, no ML)
| Metric | Value |
|--------|-------|
| Avg annual return | +40.7% |
| Worst drawdown | -7.0% |
| Years profitable | 6/6 |
| Overall win rate | ~83% |
| ROBUST score | 0.951 |

### ML Model Must Beat (Hard Gates)

| Gate | Criterion | Rationale |
|------|-----------|-----------|
| G1 | **Test-fold AUC ≥ 0.60** on all 3 folds | Better than random at distinguishing wins/losses |
| G2 | **No test fold < 0.55 AUC** | Model must generalize across regimes (2022 bear, 2023 recovery, 2025 bull) |
| G3 | **Calibration error < 0.10** | Predicted probabilities must be meaningful for position sizing |
| G4 | **Feature importance stable** across folds | Top-5 features should overlap ≥ 3/5 across all folds (not regime-dependent artifacts) |

### ML-Filtered Strategy Must Beat (Integration Test)

| Gate | Criterion | Rationale |
|------|-----------|-----------|
| G5 | **Avg return ≥ 40.7%** (match baseline) at `min_confidence` threshold | ML filter must not destroy alpha |
| G6 | **Worst DD ≤ -7.0%** (match or improve baseline) | Primary value proposition is risk reduction |
| G7 | **6/6 years profitable** maintained | Cannot break consistency |
| G8 | **Win rate improvement ≥ 2pp** on filtered trades vs unfiltered | ML must demonstrably improve signal quality |
| G9 | **Kill switch parity:** `min_confidence=0.0` reproduces exact baseline | Safety net — must be able to fully disable ML |

### Stretch Goals (Nice-to-Have)
- Worst DD improved to ≤ -5.0%
- 2022 bear year return improved from +8.1%
- Model identifies ≥ 50% of losing trades in advance (recall on loss class)

### Kill Criteria (Abort ML Integration)
- **Any test fold AUC < 0.52** — model is noise-fitting
- **Feature importance dominated by `year` or `spy_price`** — fitting to market level, not edge
- **Filtered strategy return < 35%** — ML filter destroying more good signals than bad
- **Train AUC > 0.85 while test AUC < 0.60** — severe overfitting, data too scarce

---

## 5. Implementation Order (When Approved)

1. **Data harvest:** Re-run `collect_training_data.py` for EXP-401 → get 353 trades with features
2. **Merge + dedup:** Combine with existing 249, deduplicate overlapping CS trades
3. **Feature engineering:** Add new features, drop dead ones, verify no leakage
4. **Train + evaluate:** 3-fold anchored walk-forward, check G1-G4
5. **If G1-G4 pass:** Integrate via MLEnhancedStrategy wrapper, sweep `min_confidence` thresholds
6. **Full backtest:** Run integrated strategy through portfolio backtester, check G5-G9
7. **If G5-G9 pass:** Register as EXP-500, run ROBUST validation (same 7-check overfit scoring)

**Estimated total trades for training:** ~350-400 (best case after dedup)
**Honest assessment:** This is a low-N problem. XGBoost with 350 samples and 35 features is borderline. The kill criteria exist because there's a real chance the data is too scarce for ML to add value over the already-strong rule-based system. That's fine — a well-validated negative result is better than a falsely-positive one trained on synthetic data.
