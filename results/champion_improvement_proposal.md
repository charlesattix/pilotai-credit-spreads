# Champion Improvement Proposal — COMPASS + ML Enhancement

**Date:** 2026-03-20
**Status:** PROPOSAL — no implementation until approved
**Baseline:** EXP-401 (CS 12% + SS 3%, regime-optimized) — +40.7% avg, 6/6 yrs, -7.0% DD, ROBUST 0.951

---

## Executive Summary

The champion strategy (EXP-401) is already a strong performer with ROBUST 0.951 validation. Two enhancement systems are available: **COMPASS** (macro intelligence — production-ready) and **ML** (XGBoost signal filter — needs retraining on real data). This proposal defines the exact test plans, success criteria, and execution roadmap for each, both separately and combined.

**Bottom line:** COMPASS is ready to test TODAY. ML needs ~5 days of prep work before testing. The combined approach has the highest expected impact but must be validated incrementally — never deploy both untested systems simultaneously.

---

## 1. COMPASS Enhancement — Test Plan

### 1.1 What We Have

| Asset | Status | Detail |
|-------|--------|--------|
| `macro_state.db` | Populated | 324 weekly macro snapshots (2020-2026), 4,860 sector RS records |
| `shared/macro_snapshot_engine.py` | Production-ready | 4D macro score (growth, inflation, fed_policy, risk_appetite), 15-ETF RRG |
| `shared/macro_state_db.py` | Production-ready | WAL-mode SQLite, velocity computation, regime classification |
| `shared/macro_event_gate.py` | Production-ready | FOMC/CPI/NFP proximity scaling (0.50-1.00x multipliers) |
| `backtest/backtester.py` | COMPASS-integrated | `_build_compass_series()`, risk_appetite sizing, RRG quadrant filter |
| `scripts/run_compass_backtest.py` | A/B test framework | exp_090 (baseline) vs exp_101 (COMPASS-enabled), 2020-2025 |
| `macro_events` table | **EMPTY** | Only 1 future event — historical FOMC/CPI/NFP dates NOT backfilled |

### 1.2 Three COMPASS Capabilities to Test

**Capability A — Macro Score Sizing:**
- Risk appetite score (0-100) modulates position size
- Fear (score < 45) → 1.2x sizing boost (more premium = bigger edge)
- Greed (score > 75) → 0.85x sizing reduction (complacency = danger)
- Neutral → 1.0x (no change)
- **Hypothesis:** Counter-cyclical sizing improves risk-adjusted returns. More edge when fear is elevated (wider spreads, more premium), less exposure when everyone is complacent.

**Capability B — RRG Sector Filter:**
- XLI (Industrials) + XLF (Financials) RRG quadrant monitoring
- Both in Lagging/Weakening → block bull put signals
- **Hypothesis:** When cyclical sectors (XLI + XLF) are both deteriorating, bull puts face elevated risk of underlying decline. Blocking trades during these periods avoids the worst losses.

**Capability C — Event Scaling:**
- FOMC: 0.50-1.00x (5-day ramp), CPI: 0.65-1.00x (2-day ramp), NFP: 0.75-1.00x (2-day ramp)
- Post-event buffers: +1 day at reduced sizing after each event
- **Hypothesis:** Gamma exposure + event vol crush make spreads unpredictable near macro events. Reducing size preserves capital for normal-environment trades.
- **BLOCKER:** `macro_events` table needs historical backfill before this can be tested.

### 1.3 Test Configurations

We need **5 experiment configs** tested via `run_compass_backtest.py`, each running all 6 years (2020-2025):

| Config ID | Macro Sizing | RRG Filter | Event Scaling | Purpose |
|-----------|-------------|------------|---------------|---------|
| **C-000** | OFF | OFF | OFF | **Baseline** (reproduces EXP-401 exactly) |
| **C-001** | ON | OFF | OFF | Isolate macro sizing impact |
| **C-002** | OFF | ON | OFF | Isolate RRG filter impact |
| **C-003** | ON | ON | OFF | Combined macro + RRG (no events) |
| **C-004** | ON | ON | ON | Full COMPASS (requires event backfill) |

**Config parameters for each COMPASS-enabled run:**

```json
{
  "compass_enabled": true,         // C-001, C-003, C-004
  "compass_rrg_filter": true,      // C-002, C-003, C-004
  "compass_event_scaling": true,   // C-004 only

  // All configs inherit EXP-401 champion params:
  "strategies": {
    "credit_spread": { "risk_pct": 0.12, "direction": "regime_adaptive", ... },
    "straddle_strangle": { "risk_pct": 0.03, ... }
  },
  "regime_scales_cs": { "bull": 1.0, "bear": 0.3, "high_vol": 0.3, "low_vol": 0.8, "crash": 0.0 },
  "regime_scales_ss": { "bull": 1.5, "bear": 1.5, "high_vol": 2.5, "low_vol": 1.0, "crash": 0.5 }
}
```

### 1.4 Integration Work Required

Before running C-001 through C-004, the backtester needs adaptation for EXP-401's architecture:

1. **Adapt `run_compass_backtest.py` for portfolio backtester** — current script uses the old single-strategy `Backtester` class, not `PortfolioBacktester`. Must port to run CS + SS blend with regime scales.
2. **Wire COMPASS sizing into `PortfolioBacktester`** — the `_build_compass_series()` and sizing multiplier exist in `backtest/backtester.py` but NOT in `engine/portfolio_backtester.py`. Need to port the `_build_compass_series()` logic and apply `compass_mult` in the sizing step.
3. **Wire RRG filter into strategy signal generation** — add `compass_rrg_block` to `MarketSnapshot` and check in `CreditSpreadStrategy.generate_signals()` before emitting bull put signals.
4. **Backfill `macro_events` table** (for C-004 only) — write script to populate historical FOMC/CPI/NFP dates from `macro_event_gate.py`'s hardcoded calendar into the DB, covering 2020-2025.

**Estimated effort:** 2-3 days for items 1-3, +1 day for item 4.

### 1.5 Metrics to Compare

For each config (C-000 through C-004), capture:

| Metric | How Computed | Why It Matters |
|--------|-------------|----------------|
| Avg annual return (%) | Mean of 6 yearly returns | Raw alpha |
| Worst annual drawdown (%) | Max intra-year peak-to-trough | Risk measure |
| Years profitable (N/6) | Count of years with return > 0 | Consistency |
| Win rate (%) | Winning trades / total trades | Signal quality |
| Trade count per year | Total trades / 6 | COMPASS shouldn't kill trade flow |
| 2022 return specifically | Bear year performance | Stress test |
| ROBUST overfit score | Full 7-check validation | Must remain >= 0.90 |
| Sharpe ratio | Mean return / std(returns) | Risk-adjusted quality |
| Return delta vs C-000 | (Cx return - C000 return) | Marginal value of COMPASS |
| DD delta vs C-000 | (Cx DD - C000 DD) | Marginal risk reduction |

### 1.6 Success Criteria

#### Hard Gates (MUST pass or config is rejected)

| Gate | Criterion | Rationale |
|------|-----------|-----------|
| **H1** | ROBUST score >= 0.90 | Cannot regress from champion's 0.951 beyond tolerance |
| **H2** | 6/6 years profitable | Non-negotiable consistency |
| **H3** | Trade count >= 250 (across 6 years) | COMPASS must not kill >30% of trade flow |
| **H4** | 2022 return >= +5.0% | Bear year must remain profitable after COMPASS filtering |

#### Value Criteria (at least 1 must pass for COMPASS to "add value")

| Criterion | Threshold | What It Proves |
|-----------|-----------|----------------|
| **V1** | Avg return delta >= +2.0pp | COMPASS adds meaningful alpha |
| **V2** | Worst DD improved by >= 1.5pp | COMPASS reduces tail risk |
| **V3** | Win rate improvement >= 2pp | COMPASS improves signal quality |
| **V4** | Sharpe improvement >= 0.3 | COMPASS improves risk-adjusted returns |

#### Verdict Logic

```
IF any Hard Gate fails:
    → REJECT config (COMPASS hurts or destabilizes)

IF H1-H4 pass AND V1 OR V2 OR V3 OR V4 passes:
    → ACCEPT — "COMPASS ADDS VALUE"

IF H1-H4 pass AND NO value criterion passes:
    → NEUTRAL — "COMPASS is benign but not helpful"
    → Do NOT deploy (adds complexity without benefit)
```

### 1.7 COMPASS-Specific Risk Factors

| Risk | Mitigation |
|------|------------|
| Weekly macro scores forward-filled to daily → stale data for 1-4 days | Acceptable — macro trends change slowly. Document as known limitation. |
| Historical macro score range (36.2-82.1) means 45/75 thresholds rarely trigger | Check how many trading days actually get non-1.0 multipliers. If <10%, sizing is effectively a no-op. |
| RRG quadrants only available for 15 ETFs (XLI, XLF critical) | Verify XLI + XLF have continuous RRG data across all 324 weeks. |
| Event scaling cannot be backtested without backfill | Run C-001/C-002/C-003 first; C-004 is stretch goal. |
| COMPASS thresholds (45/55/65/75 for sizing, Lagging/Weakening for RRG) may not be optimal | Do NOT optimize these on the same 6-year window — accept default thresholds or run walk-forward sensitivity. |

---

## 2. ML Enhancement — Test Plan

### 2.1 What We Have

| Asset | Status | Detail |
|-------|--------|--------|
| `ml/signal_model.py` | Needs retrain | XGBoost binary classifier, calibrated probabilities, drift monitoring |
| `ml/feature_engine.py` | Needs refactor | 47 features (tech, vol, market, event, seasonal, regime, derived) |
| `ml/training_data.csv` | 249 trades | EXP-400 backtest (CS + IC, SPY, 2020-2025), real Polygon data |
| EXP-401 trades | Untapped | 353 trades available but not yet extracted with features |
| `ml/collect_training_data.py` | Works | Can re-run for EXP-401 config to harvest SS trades |
| `ML_INTEGRATION_PROPOSAL.md` | Designed | MLEnhancedStrategy wrapper pattern, integration points identified |
| `ml/models/signal_model_*.joblib` | **INVALID** | Trained on synthetic data — must delete and retrain |

### 2.2 Pre-Test Work (Before Any ML Experiments)

These steps MUST complete before running ML-enhanced backtests:

| Step | Description | Effort | Dependency |
|------|-------------|--------|------------|
| **P1** | Delete synthetic model artifacts | 5 min | None |
| **P2** | Re-run `collect_training_data.py` with EXP-401 config → harvest 353 trades with features | 1-2 hrs | None |
| **P3** | Merge EXP-400 (249) + EXP-401 (353) datasets, deduplicate CS overlap | 1 hr | P2 |
| **P4** | Feature engineering: add credit-to-width ratio, regime duration, VIX change 5d; drop zero-variance features | 2-3 hrs | P3 |
| **P5** | Train XGBoost with anchored walk-forward CV (3 folds, 30-day purge gaps) | 2-3 hrs | P4 |
| **P6** | Evaluate model gates G1-G4 (per `results/ml_retrain_proposal.md`) | 1 hr | P5 |
| **P7** | If G1-G4 pass: implement `MLEnhancedStrategy` wrapper in backtester | 3-4 hrs | P6 |

**Total estimated prep:** ~5 days elapsed (2-3 days active work).

**CRITICAL DECISION POINT after P6:** If model AUC < 0.55 on any test fold, ABORT ML integration. Data is too scarce. This is an honest possibility — 350 samples with 35 features is borderline for XGBoost.

### 2.3 Model Training Specification

**Dataset:** ~350-400 unique trades after dedup (EXP-400 CS/IC + EXP-401 CS/SS)

**Walk-Forward CV:** (matches Phase 5 validation protocol)

| Fold | Train | 30-day Gap | Test | Est. Train N | Est. Test N |
|------|-------|------------|------|-------------|-------------|
| 1 | 2020-2022 | Jan 2023 | Feb-Dec 2023 | ~120-160 | ~42-60 |
| 2 | 2020-2023 | Jan 2024 | Feb-Dec 2024 | ~180-220 | ~41-62 |
| 3 | 2020-2024 | Jan 2025 | Feb-Dec 2025 | ~230-280 | ~37-55 |

**Hyperparameters (tightened for small N):**

```python
{
    'max_depth': 4,           # Was 6 — reduce to prevent memorization
    'learning_rate': 0.05,    # Keep
    'n_estimators': 100,      # Was 200 — with early stopping
    'min_child_weight': 10,   # Was 5 — need larger leaf groups
    'subsample': 0.8,         # Keep
    'colsample_bytree': 0.7,  # Was 0.8 — force feature diversity
    'gamma': 2,               # Was 1 — more conservative splits
    'reg_alpha': 1.0,         # Was 0.1 — stronger L1
    'reg_lambda': 5.0,        # Was 1.0 — stronger L2
}
```

**Feature Selection:** Start with top 15-20 features by SHAP importance from Fold 1. Prune features that are unstable across folds (importance rank change > 10 positions).

**Target:** Binary classification — `win` (pnl > 0) = 1, else 0. No regression on return_pct (too noisy with IC outlier losses).

### 2.4 ML Test Configurations

After model training passes G1-G4, test via `MLEnhancedStrategy` wrapper in `PortfolioBacktester`:

| Config ID | min_confidence | Position Scaling | Purpose |
|-----------|---------------|-----------------|---------|
| **M-000** | 0.0 (disabled) | None | **Kill switch** — must reproduce C-000 exactly |
| **M-001** | 0.40 | None | Minimal filter — only reject lowest-confidence trades |
| **M-002** | 0.50 | None | Moderate filter — reject below-average signals |
| **M-003** | 0.55 | None | Aggressive filter — reject marginal signals |
| **M-004** | 0.60 | None | Very aggressive — only high-confidence trades |
| **M-005** | 0.50 | Confidence-scaled contracts | Filter + sizing (confidence modulates position size) |

**How confidence-scaled contracts work (M-005):**
```
base_contracts = strategy.size_position(signal, portfolio_state)
ml_confidence = prediction['confidence']  # 0.0-1.0, distance from 0.5

if ml_confidence > 0.5:    # Very confident
    scale = 1.0            # Full size
elif ml_confidence > 0.3:  # Moderately confident
    scale = 0.75           # Reduce 25%
else:                      # Low confidence (but above min_confidence)
    scale = 0.50           # Half size

final_contracts = max(1, round(base_contracts * scale))
```

### 2.5 Success Criteria

#### Model Quality Gates (G1-G4) — Must pass BEFORE backtesting

| Gate | Criterion | Kill If |
|------|-----------|---------|
| G1 | Test-fold AUC >= 0.60 on all 3 folds | Any fold < 0.55 |
| G2 | Calibration error < 0.10 (ECE) | ECE > 0.15 |
| G3 | Feature importance stable: top 5 overlap >= 3/5 across folds | < 2/5 overlap |
| G4 | Train AUC - Test AUC < 0.25 | Gap > 0.30 (severe overfit) |

#### Integration Gates (G5-G9) — Backtest results

| Gate | Criterion | Rationale |
|------|-----------|-----------|
| G5 | M-000 (kill switch) reproduces C-000 exactly | Safety verification |
| G6 | Best ML config: avg return >= 40.7% | Must not destroy alpha |
| G7 | Best ML config: worst DD <= -7.0% | Must maintain risk profile |
| G8 | Best ML config: 6/6 years profitable | Must maintain consistency |
| G9 | Best ML config: win rate improvement >= 2pp on filtered trades | Proves ML adds signal quality |

#### Value Criteria (at least 1 for "ML adds value")

| Criterion | Threshold |
|-----------|-----------|
| V1 | Avg return >= +43% (>= 2.3pp over baseline) |
| V2 | Worst DD improved to <= -5.5% (>= 1.5pp improvement) |
| V3 | 2022 bear year return >= +10% (vs +8.1% baseline) |
| V4 | Sharpe >= 3.5 (vs baseline ~2.96) |

#### Kill Criteria (abort ML integration entirely)

- Any test fold AUC < 0.52 — model is fitting noise
- Feature importance dominated by `year` or `spy_price` — memorizing market level
- Best filtered return < 35% at any threshold — ML destroying more good than bad signals
- Trade count drops below 200 at best-performing threshold — over-filtering

### 2.6 ML-Specific Risk Factors

| Risk | Probability | Mitigation |
|------|------------|------------|
| Data too scarce (350 samples) for meaningful ML | **HIGH** | Aggressive regularization, shallow trees, honest kill criteria. Negative result is acceptable. |
| Class imbalance (83% wins / 17% losses) | Medium | Model learns to predict "always win" → useless. Monitor per-class precision/recall. |
| Feature leakage (future information in features) | Low | 30-day purge gap between folds, all features computed at entry date only. |
| Regime-dependent model (good in bull, bad in bear) | Medium | Check per-regime AUC. If bear-year AUC < 0.50, the model adds no value where it matters most. |
| Model confidence becomes a self-fulfilling prophecy | Low | Model is filter-only, cannot create trades. Worst case: filters too many → lower returns, never higher risk. |

---

## 3. Combined Approach — COMPASS + ML Together

### 3.1 How They Interact

COMPASS and ML operate at **different layers** of the decision chain — they are complementary, not competing:

```
Signal Generation (strategy.generate_signals)
    │
    ▼
┌──────────────────────────────┐
│ LAYER 1: COMPASS (macro)     │  ← Market-level intelligence
│  • RRG filter: block/allow   │     "Is the macro environment favorable?"
│  • Macro sizing: 0.85-1.20x  │
│  • Event scaling: 0.50-1.00x │
└──────────────┬───────────────┘
               │ signals that pass macro filter
               ▼
┌──────────────────────────────┐
│ LAYER 2: ML (micro)          │  ← Trade-level intelligence
│  • XGBoost confidence: 0-1   │     "Is THIS specific trade likely profitable?"
│  • min_confidence gate        │
│  • Confidence-scaled sizing   │
└──────────────┬───────────────┘
               │ signals that pass ML filter
               ▼
┌──────────────────────────────┐
│ LAYER 3: Regime Sizing       │  ← Already validated (Phase 4)
│  • bull=1.0, bear=0.3, etc.  │
└──────────────┬───────────────┘
               │
               ▼
         EXECUTE TRADE
```

**Key design principle:** Each layer can only REDUCE exposure, never increase beyond what the layer above allows. This means combining them cannot create novel risk — the worst case is over-filtering (fewer trades, lower returns), never over-exposure.

### 3.2 Potential Interactions

| COMPASS State | ML Confidence | Expected Outcome |
|---------------|--------------|-------------------|
| Fear (boost 1.2x) + No RRG block | High (>0.6) | Best-case: oversized position on high-quality trade in fearful market. Likely max profit. |
| Fear (boost 1.2x) + No RRG block | Low (<0.5) | ML filter blocks the trade. COMPASS size boost never applies. Good — prevents false-signal entries during volatile markets. |
| Greed (reduce 0.85x) | High (>0.6) | Conservative position on quality trade. Correct — preserves capital in complacent environments. |
| RRG block | Any | Trade blocked entirely by COMPASS before ML even sees it. Correct — macro veto overrides micro confidence. |
| Neutral (1.0x) | Moderate (0.5-0.6) | Normal-sized position. ML provides marginal quality improvement. |

**Expected compounding effect:** COMPASS prevents macro-level mistakes (e.g., bull puts when cyclicals are deteriorating). ML prevents micro-level mistakes (e.g., trades with poor IV/vol/RSI profiles). Together, they should reduce both "wrong environment" losses and "wrong trade" losses.

### 3.3 Combined Test Configurations

| Config ID | COMPASS | ML | Purpose |
|-----------|---------|-----|---------|
| **X-000** | OFF | OFF | Baseline (= C-000 = M-000) |
| **X-001** | Best-C | OFF | Best COMPASS-only config from Section 1 |
| **X-002** | OFF | Best-M | Best ML-only config from Section 2 |
| **X-003** | Best-C | Best-M | Full combined |

### 3.4 Combined Success Criteria

All of Section 1 and Section 2 hard gates still apply. Additionally:

| Gate | Criterion | Rationale |
|------|-----------|-----------|
| **X1** | X-003 return >= max(X-001, X-002) | Combined must beat each alone (or what's the point?) |
| **X2** | X-003 DD <= min(X-001, X-002) | Combined must improve risk vs each alone |
| **X3** | X-003 ROBUST >= 0.90 | Combined must remain validated |
| **X4** | X-003 trade count >= 200 | Double-filtering must not kill flow |

**If X1 and X2 fail:** COMPASS and ML interfere destructively. Deploy the better one solo.

### 3.5 Test Order (Critical — Do Not Skip Steps)

```
Phase 1: COMPASS solo (Days 1-5)
  ├── Adapt run_compass_backtest.py for PortfolioBacktester
  ├── Run C-000 through C-003
  ├── Evaluate per Section 1.6
  ├── If any config passes → identify "Best-C"
  └── Backfill macro_events → run C-004 (stretch)

Phase 2: ML solo (Days 6-12)
  ├── Data prep: harvest EXP-401 trades, merge, dedup
  ├── Feature engineering: add new, drop dead
  ├── Train model: 3-fold walk-forward
  ├── Evaluate G1-G4 (DECISION POINT: continue or abort)
  ├── If pass → implement MLEnhancedStrategy wrapper
  ├── Run M-000 through M-005
  └── Evaluate per Section 2.5 → identify "Best-M"

Phase 3: Combined (Days 13-15)
  ├── Run X-000 through X-003
  ├── Evaluate per Section 3.4
  └── Register winning config as EXP-502

Phase 4: Validation (Days 16-18)
  ├── Run full ROBUST validation on EXP-502
  ├── Walk-forward, Monte Carlo, slippage, tail risk
  └── If ROBUST >= 0.90 → approve for paper trading
```

---

## 4. Improvement Roadmap

### 4.1 Priority-Ordered Experiments

| Priority | Experiment | Prerequisite | Est. Effort | Expected Impact |
|----------|-----------|-------------|-------------|-----------------|
| **P0** | **COMPASS macro sizing (C-001)** | Adapt script for PortfolioBacktester | 2-3 days | Low-medium: sizing change is subtle (0.85-1.20x range). May improve 2022 (+fear boost) and dampen 2021 greed overexposure. |
| **P1** | **COMPASS RRG filter (C-002)** | Same as P0 | +0 (parallel) | Medium: RRG filter could prevent 5-15% of losing bull puts. Biggest value in 2022 bear market. |
| **P2** | **COMPASS combined (C-003)** | P0 + P1 results | +1 day | Sum of P0 + P1, check for interference |
| **P3** | **ML data harvest + training** | None (independent of COMPASS) | 3-4 days | DECISION POINT — determines if ML path is viable |
| **P4** | **ML confidence filter sweep (M-001 to M-005)** | P3 passes G1-G4 | 2 days | Medium-high if model generalizes: 2-5pp return, 1-2pp DD improvement |
| **P5** | **COMPASS event scaling (C-004)** | Backfill macro_events table | 1-2 days | Low: affects ~50 trading days/year near events. Position size reduction, not trade blocking. |
| **P6** | **Combined COMPASS + ML (X-003)** | Best-C from P0-P2 + Best-M from P4 | 1-2 days | Potentially highest: if both add independent value, combined should compound |
| **P7** | **Full ROBUST validation of winner** | P6 complete | 1-2 days | Must validate before paper trading |
| **P8** | **Paper trading deployment** | P7 passes | 1 day setup | 8-week live validation |

### 4.2 Estimated Timeline

```
Week 1 (Days 1-5):   COMPASS testing (P0-P2) + ML data prep (P3 parallel)
Week 2 (Days 6-10):  ML training + evaluation (P3 decision) + ML sweep (P4)
Week 3 (Days 11-15): Combined testing (P6) + COMPASS events (P5) + Validation (P7)
Week 4 (Days 16-18): Paper trading deployment prep (P8)
```

**Total: ~18 days to completion** (3.5 weeks, assumes 5 working days/week).

Parallel execution is critical — COMPASS testing and ML data prep should run simultaneously in Week 1.

### 4.3 Realistic Improvement Targets

Let me be brutally honest about what's achievable:

#### What the Data Suggests

| Metric | Current | Realistic Best | Stretch (Low Probability) | Unrealistic |
|--------|---------|---------------|---------------------------|-------------|
| Avg annual return | +40.7% | +43-45% | +47-50% | +55%+ |
| Worst annual DD | -7.0% | -5.5% to -6.0% | -4.0% to -5.0% | < -3.0% |
| Sharpe ratio | ~2.96 | 3.2-3.5 | 3.5-4.0 | > 6.0 |
| 2022 bear year | +8.1% | +10-12% | +15%+ | +20%+ |
| Years profitable | 6/6 | 6/6 (maintain) | 6/6 | 6/6 |

#### Why These Targets Are What They Are

**+43-45% avg return is realistic because:**
- COMPASS sizing (0.85-1.20x) affects position size by at most 20%. On 353 trades, that's +/- ~2-4pp on annual returns.
- ML filter at 50% confidence might reject 15-25% of trades. If those are disproportionately losers (the hypothesis), that's +1-3pp.
- Combined effect: +2-5pp over baseline = +43-46%.

**+50% avg is a stretch because:**
- The strategy is signal-constrained (not capital-constrained). COMPASS and ML can only improve QUALITY of existing signals, not QUANTITY.
- Adding new signals would require new strategies (calendar spreads, debit spreads) — but EXP-604 proved these are net drags.
- The 2022 bear year (+8.1%) is the binding constraint. Any filter that improves 2022 likely also reduces some bull-market trades, capping upside.

**Sharpe > 6 is unrealistic because:**
- Current Sharpe ~2.96 with std ~14%. To reach Sharpe 6 at +40% return, std must drop to ~6.7%.
- That requires eliminating nearly ALL losing months, which means either (a) never trading in uncertain conditions (killing trade flow) or (b) having a crystal ball.
- Sharpe 3.5-4.0 is an excellent target. Above 4.0 starts looking like overfitting.

**DD < 3% is unrealistic because:**
- Current worst DD (-7.0%) occurs during a bear market regime (2022).
- Regime scaling already reduces CS sizing to 0.3x in bear markets. Further reduction approaches zero (no trades = no returns = no Sharpe).
- DD of -5% to -5.5% is achievable by filtering the worst 2-3 losing trades per bear year. Below -5% requires data that doesn't exist (predicting which specific trades will lose in real-time).

### 4.4 Risk of Over-Optimization

This is the most important section. With 600+ experiments already tested across EXP-600 through EXP-604, and now proposing COMPASS + ML optimization on the SAME 6-year dataset, overfitting risk is elevated.

#### Known Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Data snooping:** We've already seen 2020-2025 hundreds of times. Any "improvement" may be noise. | HIGH | Walk-forward validation is mandatory (train on 2020-2022, test on 2023-2025). ROBUST score must remain >= 0.90. |
| **Threshold tuning on in-sample data:** COMPASS thresholds (45/55/65/75 for sizing) were not optimized for this strategy. | MEDIUM | Do NOT optimize COMPASS thresholds. Use defaults. If defaults don't add value, COMPASS doesn't add value. |
| **ML hyperparameter mining:** Sweeping min_confidence from 0.40 to 0.60 is mild (5 configs), but combined with COMPASS creates 5x5 = 25 configs. | MEDIUM | Test COMPASS and ML SEPARATELY first. Only test combined with the single best from each. Never grid-search combined. |
| **Confirmation bias:** We WANT COMPASS and ML to work. Easy to cherry-pick the one config that looks good. | HIGH | Pre-register success criteria (this document). Evaluate ALL configs against criteria, not just the best-looking one. Report ALL results. |
| **Paper trading divergence:** Backtest improvements may not survive real-world fills and timing. | MEDIUM | 8-week paper trading validation remains mandatory. Deviation tracker (`scripts/paper_trading_deviation.py`) monitors backtest-to-live drift. |

#### Staying Honest: The Honesty Protocol

1. **Pre-register all configs** (done in this document). No adding configs after seeing results.
2. **Report ALL results**, not just winners. If C-001 through C-003 all fail, that's a valid finding.
3. **No threshold optimization** on COMPASS. Use published defaults or walk-forward validated thresholds only.
4. **ML kill criteria are binding.** If AUC < 0.55 on any fold, ML is dead. No "well, if we try just one more feature..."
5. **Combined (X-003) must beat BOTH individual configs.** If it only beats one, deploy the better individual config.
6. **ROBUST >= 0.90 is non-negotiable.** Any config that drops below 0.90 is rejected regardless of returns.
7. **After optimization, freeze.** Once a winning config is found, run ROBUST validation, register as EXP-502, and stop optimizing. The next improvement comes from paper trading feedback, not more backtesting.

---

## 5. Summary Decision Matrix

| Outcome | Action |
|---------|--------|
| COMPASS adds value, ML fails model gates | Deploy COMPASS-enhanced champion (EXP-502a) |
| COMPASS neutral, ML adds value | Deploy ML-enhanced champion (EXP-502b) |
| Both add value independently | Test combined → deploy if combined beats both (EXP-502c) |
| Both add value but combined is worse | Deploy whichever individual is better |
| Neither adds meaningful value | **Keep EXP-401 as-is.** +40.7% avg with ROBUST 0.951 is already excellent. Adding complexity without benefit is a net negative. |
| Either breaks hard gates (ROBUST < 0.90, loss year) | **Reject immediately.** Do not try to "fix" a failing enhancement. |

**The honest expected outcome:** COMPASS has a ~60% chance of adding marginal value (1-3pp return or DD improvement). ML has a ~40% chance of adding value (limited by small training set). Combined has a ~30% chance of being better than either alone. There is a ~25% chance that neither meaningfully improves the champion, and that's an acceptable result.

**The champion is already validated and profitable. Enhancement is upside exploration, not a requirement.**

---

## Appendix A: Data Availability Checklist

| Data | Available | Coverage | Notes |
|------|-----------|----------|-------|
| macro_score (overall, 4 dimensions) | Yes | 324 weekly snapshots (2020-2026) | Forward-filled to daily |
| sector_rs (15 ETFs) | Yes | 4,860 records | RRG quadrants included |
| macro_events (FOMC/CPI/NFP) | **NO** | 1 future event only | Must backfill from hardcoded calendar |
| options_cache.db (Polygon) | Yes | 905MB, 5.67M bars, 168K contracts | 2020-2025 coverage |
| ML training_data.csv | Yes | 249 trades (EXP-400) | Need EXP-401 harvest (+353) |
| VIX/VIX3M history | Yes | Full 2020-2025 | In IronVault |
| SPY/QQQ/IWM OHLCV | Yes | Full 2020-2025 | In IronVault |

## Appendix B: File Locations Reference

```
COMPASS:
  shared/macro_snapshot_engine.py    # Macro score engine (898 lines, production-ready)
  shared/macro_state_db.py           # SQLite persistence (569 lines, production-ready)
  shared/macro_event_gate.py         # Event scaling (337 lines, production-ready)
  data/macro_state.db                # Populated database (324 snapshots, 4,860 sector RS)
  scripts/run_compass_backtest.py    # A/B test framework (needs adaptation)
  backtest/backtester.py             # COMPASS integration (lines 388-396, 583-584, 648-667, 790-795)

ML:
  ml/signal_model.py                 # XGBoost classifier (771 lines, needs retrain)
  ml/feature_engine.py               # 47-feature builder (565 lines, needs IronVault wiring)
  ml/collect_training_data.py        # Data harvester (687 lines, works)
  ml/training_data.csv               # 249 real trades (62KB)
  ml/feature_analysis.md             # Feature quality report
  ML_INTEGRATION_PROPOSAL.md         # MLEnhancedStrategy wrapper design

Backtester:
  engine/portfolio_backtester.py     # Multi-strategy backtester (champion uses this)
  engine/regime.py                   # RegimeClassifier (drives all regime-adaptive sizing)

Validation:
  scripts/exp401_robust_score.py     # ROBUST scoring (7 checks)
  output/exp401_robust_score.json    # Current validation results (0.951)
  output/final_validation_results.json # Phase 5 full validation

Configs:
  configs/champion.json              # EXP-400 params (CS + IC)
  configs/paper_champion.yaml        # EXP-400 paper config
  configs/paper_exp401.yaml          # EXP-401 paper config
```
