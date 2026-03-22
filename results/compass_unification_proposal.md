# COMPASS Unification Proposal

**Date:** 2026-03-20
**Status:** PROPOSAL — architecture decision, no implementation
**Scope:** Merge three intelligence systems into one unified COMPASS platform

---

## PART 1 — DEEP AUDIT OF EACH SYSTEM

### System 1: COMPASS (Macro Intelligence)

**Total:** 2,259 lines across 5 files. **PRODUCTION-READY.**

| File | Lines | Purpose | GO/NO-GO | Reason |
|------|-------|---------|----------|--------|
| `shared/macro_snapshot_engine.py` | 898 | Core engine: Polygon + FRED → 4D macro score (growth, inflation, fed_policy, risk_appetite), sector RS, RRG quadrants | **GO** | Real data only (Polygon + FRED). Thread-safe. Lookahead-protected via `RELEASE_LAG_DAYS`. Resilient HTTP retry. No synthetic fallbacks. |
| `shared/macro_state_db.py` | 569 | SQLite persistence: snapshots, sector_rs, macro_score, macro_events, macro_state tables. Integration API. | **GO** | WAL mode. Idempotent migrations. Velocity computation. Staleness detection. Regime classification (`BULL_MACRO`/`BEAR_MACRO`/`NEUTRAL_MACRO` at score thresholds 65/45). |
| `shared/macro_event_gate.py` | 337 | Event calendar + position-size scaling (FOMC/CPI/NFP proximity → 0.50-1.00× multiplier) | **GO** | Deterministic. Post-event buffers (G5). Per-event-type minimums (G4). Month arithmetic fixed (G7). Only needs annual FOMC date update. |
| `alerts/risk_gate.py` | 358 | Risk rules 0-10. COMPASS rules 8 (macro sizing flags), 9 (RRG quadrant filter), 10 (portfolio limits) | **GO** | Backward compatible — COMPASS rules are no-ops unless explicitly configured. Well-structured. |
| `shared/vix_regime.py` | 97 | VIX-only sizing factor (crisis=0.25×, normal=1.0-1.25×, term structure adjustment) | **NO-GO** | **Never imported or called anywhere.** Dead code. Overlaps with COMPASS macro sizing + strategy regime scales. Kill. |

**Key capabilities:**
- Weekly macro score (0-100) from 4 economic dimensions
- 15-ETF sector RS rankings with RRG quadrant classification (Leading/Improving/Weakening/Lagging)
- Dynamic universe eligibility (macro score veto + RRG filter)
- Event-driven position sizing (FOMC/CPI/NFP proximity scaling)
- Score velocity (week-over-week trend)

**Data sources:** All real — Polygon API (price), FRED public CSV (macro), algorithmic (event dates). Zero synthetic.

**Test coverage:** `test_compass_scanner.py`, `test_risk_gate_macro.py`, `test_macro_state_db.py` — 50+ unit tests.

**Integration points:**
- `main.py`: `_get_compass_universe()`, `_augment_with_compass_state()`, `_analyze_ticker()` direction override
- `backtest/backtester.py`: `_build_compass_series()`, sizing multiplier, RRG quadrant block
- `alerts/risk_gate.py`: Rules 8/9/10
- `alerts/alert_position_sizer.py`: `macro_sizing_flag`

---

### System 2: ML Infrastructure

**Total:** 5,818 lines across 10 files. **BUILT BUT DISCONNECTED.**

| File | Lines | Purpose | GO/NO-GO | Reason |
|------|-------|---------|----------|--------|
| `ml/signal_model.py` | 770 | XGBoost binary classifier (profitable/unprofitable). Calibrated probabilities. Feature drift monitoring. | **NEEDS-WORK** | Well-architected (calibration, drift detection, path traversal protection). BUT: `generate_synthetic_training_data()` violates no-synthetic directive. Current saved model (`signal_model_20260305.joblib`) trained on synthetic data → **useless**. Needs retrain on real data. |
| `ml/feature_engine.py` | 564 | 47-feature builder (technical, vol, market, event, seasonal, regime, derived) | **NEEDS-WORK** | Comprehensive feature set. BUT: uses yfinance (not IronVault), has synthetic fallbacks (RSI=50, vol=20%), IV skew approximated (±10% strikes, not delta-25). Market features re-downloaded every call (inefficient). |
| `ml/ml_pipeline.py` | 633 | Orchestrator: RegimeDetector → IVAnalyzer → FeatureEngine → SignalModel → PositionSizer → SentimentScanner → enhanced score + recommendation | **NEEDS-WORK** | Good architecture (batch optimization, ThreadPoolExecutor). BUT: enhanced_score thresholds hardcoded and uncalibrated. Falls back to synthetic training if no saved model. **Not called by any strategy or paper trader.** |
| `ml/regime_detector.py` | 417 | HMM + Random Forest ensemble (4 regimes: low_vol_trending, high_vol_trending, mean_reverting, crisis) | **NO-GO** | **Never imported outside ml/.** Heavy dependencies (hmmlearn, sklearn). Regime labels don't match anything else. Thresholds are heuristic (VIX>30→crisis). Daily retraining overhead for no consumer. Kill. |
| `ml/iv_analyzer.py` | 415 | IV surface analysis: skew, term structure, IV rank/percentile | **NEEDS-WORK** | Useful IV metrics (contango/backwardation, skew ratio, term slope). BUT: uses HV as IV proxy (not true IV). 24hr cache. Would add value to feature engineering if wired to IronVault options data. |
| `ml/sentiment_scanner.py` | 547 | Event risk calendar: earnings (yfinance), FOMC (hardcoded), CPI (approx). Risk scoring + position size adjustment. | **NO-GO** | **Redundant with COMPASS `macro_event_gate.py`**. Both maintain independent FOMC date lists and CPI approximations. COMPASS version is superior (post-event buffers, per-event-type minimums, DB persistence). Earnings detection is unique but SPY/QQQ/IWM don't have earnings. Kill module, migrate earnings logic if ever needed for single-stock expansion. |
| `ml/position_sizer.py` | 556 | Kelly Criterion + IV-scaled sizing. `calculate_dynamic_risk()` + `get_contract_size()`. | **GO (partial)** | `calculate_dynamic_risk()` and `get_contract_size()` are actually used by backtester and alert system. Kelly/ML-confidence sizing is unused. Keep the two utility functions, kill the class. |
| `ml/combo_regime_detector.py` | 230 | 3-signal voting (MA200, RSI, VIX/VIX3M). Asymmetric voting, hysteresis, VIX circuit breaker. | **GO** | Well-tested (8 tests). Elegant design. Used by legacy paper trader and `strategy/spread_strategy.py`. BUT: outputs UPPERCASE labels (BULL/BEAR/NEUTRAL) while strategies expect lowercase 5-regime system. Needs label standardization. |
| `ml/collect_training_data.py` | 686 | Runs EXP-400 backtest → extracts 249 trades with 39 features + market context | **GO** | Real data pipeline. Produces `training_data.csv`. Needs update to also run EXP-401 config for SS trades. |
| `ml/__init__.py` | 25 | Package exports | GO | — |

**Saved artifacts:**
- `ml/models/signal_model_20260305.joblib` (299KB) — **DELETE.** Trained on synthetic data.
- `ml/models/signal_model_20260305.feature_stats.json` (3.3KB) — DELETE (companion to synthetic model).
- `ml/training_data.csv` (62KB) — **KEEP.** 249 real trades with 39 features.
- `ml/feature_analysis.md` — KEEP. Feature quality report.

**Critical finding:** The ML pipeline is a **dead code path**. No strategy, backtester, or paper trader calls `MLPipeline.analyze_trade()`. The signal model was trained on synthetic data. The only production value currently extracted from `ml/` is:
1. `calculate_dynamic_risk()` / `get_contract_size()` (position sizing utilities)
2. `ComboRegimeDetector` (regime voting for legacy paper trader)
3. `collect_training_data.py` (data harvesting)

---

### System 3: ComboRegimeDetector / engine/regime.py

**Total:** 1,342 lines across 5 files. **FRAGMENTED.**

| File | Lines | Purpose | GO/NO-GO | Reason |
|------|-------|---------|----------|--------|
| `engine/regime.py` | 235 | `RegimeClassifier`: VIX + MA-50 trend → 5 regimes (bull, bear, high_vol, low_vol, crash) | **GO** | Simple, effective. **The one actually used by champion backtester.** Drives all regime-adaptive sizing (CS: bull=1.0, bear=0.3, etc.). BUT: **zero test coverage.** Hardcoded thresholds. No lookahead protection (implicit via MA lag). |
| `ml/combo_regime_detector.py` | 230 | (Covered above) 3-signal voting. Used by legacy paper trader. | **GO** | See above. |
| `ml/regime_detector.py` | 417 | (Covered above) HMM + RF. Unused. | **NO-GO** | See above. |
| `shared/vix_regime.py` | 97 | (Covered above) VIX sizing factor. Unused. | **NO-GO** | See above. |
| `strategy/market_regime.py` | 402 | Legacy 7-regime detector (TRENDING_BULL/BEAR, HIGH/LOW_VOL, CHOPPY, CRASH, RECOVERY) | **NO-GO** | **Never imported.** 402 lines of dead code. 7 regimes with untested heuristic thresholds. Kill. |

**Critical finding: FOUR redundant regime systems with incompatible labels:**

| System | Regimes | Labels | Used By |
|--------|---------|--------|---------|
| `engine/regime.py` | 5 | bull, bear, high_vol, low_vol, crash (lowercase) | Portfolio backtester → strategies |
| `ml/combo_regime_detector.py` | 3 | BULL, BEAR, NEUTRAL (uppercase) | Legacy paper trader → `strategy/spread_strategy.py` |
| `ml/regime_detector.py` | 4 | low_vol_trending, high_vol_trending, mean_reverting, crisis | **Nobody** |
| `strategy/market_regime.py` | 7 | TRENDING_BULL, etc. | **Nobody** |
| COMPASS `macro_state_db.py` | 3 | BULL_MACRO, BEAR_MACRO, NEUTRAL_MACRO | Universe eligibility only |

**Bugs found:**
1. **Case mismatch:** ComboRegimeDetector outputs `BULL`; strategies expect `bull`. Currently masked because backtester uses `engine/regime.py` (lowercase), and live path converts.
2. **Optimistic fallback:** `main.py` line 415 defaults to `BULL` on ComboRegimeDetector failure. Should default to `NEUTRAL`.
3. **VIX3M often missing:** When unavailable, `vix_structure` signal abstains → 2-of-2 voting instead of 2-of-3 → lower consensus threshold.

---

## PART 2 — OVERLAP & REDUNDANCY ANALYSIS

### 2.1 Regime Detection: 4 Systems, 1 Consumer

```
                    ┌─────────────────────────────┐
                    │   WHO ACTUALLY USES REGIME?  │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
  CreditSpread              IronCondor              StraddleStrangle
  direction mapping         crash guard             sizing scale
  sizing scale              (crash → skip)          regime metadata
  (regime_adaptive)
```

All three strategies consume `snapshot.regime` — a **single lowercase string** from `engine/regime.py`.

The other three regime systems (ComboRegimeDetector, HMM RegimeDetector, MarketRegimeDetector) either:
- Produce incompatible labels (different case, different regime taxonomy)
- Are never consumed (HMM, MarketRegime)
- Are consumed only by the legacy paper trader path (Combo)

**Verdict: Keep `engine/regime.py` as primary. Enhance it by absorbing ComboRegimeDetector's best ideas (hysteresis, VIX/VIX3M term structure, asymmetric voting). Kill the rest.**

COMPASS macro regime (`BULL_MACRO`/`BEAR_MACRO`/`NEUTRAL_MACRO`) serves a different purpose: universe eligibility gating. It's complementary, not redundant. Keep as a separate concern.

### 2.2 Event Calendars: Dual Maintenance

| Feature | COMPASS `macro_event_gate.py` | ML `sentiment_scanner.py` |
|---------|-------------------------------|---------------------------|
| FOMC dates | Hardcoded 2020-2026 ✓ | Hardcoded 2025-2026 (partial) |
| CPI dates | 12th of next month, weekend-adjusted ✓ | Monthly range heuristic (less precise) |
| NFP dates | First Friday of next month ✓ | Not tracked |
| Earnings | Not tracked | yfinance Ticker.calendar |
| Post-event buffers | Yes (G5 fix) | No |
| Per-event-type minimums | Yes (G4 fix) | No |
| DB persistence | Yes (macro_events table) | No |
| Position scaling | Composite 0.50-1.00× | 0.0-1.0× (more aggressive) |

**Verdict: COMPASS event gate is strictly superior.** Kill `sentiment_scanner.py`. If single-stock expansion ever needs earnings, add an earnings method to the COMPASS event gate.

### 2.3 Position Sizing: 4 Competing Modifiers

Currently, a trade's size can be modified by up to **four independent systems**:

```
Strategy regime_size_scale (e.g., bear=0.3)
  × COMPASS macro_sizing_flag (boost/reduce)
    × ML PositionSizer Kelly confidence scaling
      × Event scaling factor (0.50-1.00)
        = Final position size
```

In practice, only two are active:
1. **Strategy regime_size_scale** — validated in Phase 4 (bull=1.0, bear=0.3, etc.)
2. **COMPASS event scaling** — integrated in backtester and risk gate

The ML PositionSizer Kelly scaling is unused (pipeline disconnected). The COMPASS macro_sizing_flag is wired but has minimal impact (just informational logs).

**Verdict: Formalize the sizing chain as exactly two multipliers:**
1. Regime scale (from strategy params, based on regime classification)
2. Event scale (from COMPASS event gate, based on calendar proximity)

Kill ML PositionSizer class. Keep `calculate_dynamic_risk()` and `get_contract_size()` as standalone utilities.

### 2.4 Feature Overlap

| Domain | COMPASS | ML FeatureEngine | Overlap? |
|--------|---------|------------------|----------|
| VIX level | `risk_appetite` dimension input | `vix_level` feature | **YES** — both use VIX but differently (COMPASS as one input to composite score, ML as raw feature) |
| Realized vol | Not used | `realized_vol_5d/10d/20d` | No |
| RSI | Not used | `rsi_14` | No |
| MACD | Not used | `macd`, `macd_signal`, `macd_histogram` | No |
| FRED macro data | Core input (CFNAI, CPI, rates, HY OAS) | Not used | No |
| Sector rotation | 15-ETF RS + RRG quadrants | Not used | No |
| IV surface | Not used | `iv_rank`, `iv_percentile`, `put_call_skew_ratio` | No |
| Event proximity | `macro_event_gate` (FOMC/CPI/NFP) | `sentiment_scanner` (FOMC/CPI/earnings) | **YES** — redundant |
| Term structure | Not used directly | `vix_change_1d` (indirect) | Minimal |

**Verdict: COMPLEMENTARY, not redundant.** COMPASS owns macro/sector intelligence. ML FeatureEngine owns technical/volatility/microstructure. The only real overlaps are VIX (different usage) and event calendars (consolidate to COMPASS).

---

## PART 3 — UNIFIED COMPASS ARCHITECTURE

### 3.0 Design Principles

1. **One regime, one label set.** The 5-regime system (bull, bear, high_vol, low_vol, crash) from `engine/regime.py` becomes the single source of truth.
2. **Layers don't fight.** Macro intelligence informs; strategies decide. No competing sizing modifiers.
3. **Real data only.** Every component uses IronVault or FRED. Zero synthetic fallbacks.
4. **Kill switch at every layer.** Each COMPASS feature can be disabled independently.

### 3.1 Module Hierarchy

```
compass/                          # NEW unified package
├── __init__.py                   # Public API exports
│
├── regime.py                     # SINGLE regime classifier (enhanced)
│   └── class RegimeClassifier    # engine/regime.py + combo hysteresis + VIX term structure
│       ├── classify()            # Single-date regime → "bull"|"bear"|"high_vol"|"low_vol"|"crash"
│       ├── classify_series()     # Batch regime series for backtesting
│       └── THRESHOLDS            # Configurable (not hardcoded)
│
├── macro.py                      # Macro intelligence (from COMPASS)
│   └── class MacroEngine         # shared/macro_snapshot_engine.py (renamed, unchanged)
│       ├── generate_snapshot()   # Weekly: Polygon + FRED → 4D score + sector RS + RRG
│       └── prefetch_all_data()   # Bulk data download for backtests
│
├── macro_db.py                   # Persistence (from COMPASS)
│   └── (shared/macro_state_db.py — move, unchanged)
│
├── events.py                     # Event calendar + sizing (from COMPASS)
│   └── class EventGate           # shared/macro_event_gate.py (renamed, unchanged)
│       ├── get_upcoming_events() # FOMC/CPI/NFP proximity
│       └── compute_scaling()     # Position size multiplier (0.50-1.00)
│
├── features.py                   # ML feature engineering (from ml/)
│   └── class FeatureEngine       # ml/feature_engine.py (refactored)
│       ├── build_features()      # Technical + vol + market features
│       └── (IronVault data source instead of yfinance)
│
├── signal_model.py               # ML trade filter (from ml/)
│   └── class SignalModel         # ml/signal_model.py (cleaned up)
│       ├── predict()             # Binary classifier (profitable/not)
│       └── (synthetic generation method REMOVED)
│
├── iv_surface.py                 # IV analysis (from ml/)
│   └── class IVAnalyzer          # ml/iv_analyzer.py (refactored for IronVault)
│
├── risk_gate.py                  # Risk rules (from alerts/)
│   └── class RiskGate            # alerts/risk_gate.py (unchanged)
│
└── sizing.py                     # Position sizing utilities
    ├── calculate_dynamic_risk()  # From ml/position_sizer.py
    └── get_contract_size()       # From ml/position_sizer.py
```

### 3.2 What Gets Kept, Enhanced, or Killed

| Component | Action | Destination | Rationale |
|-----------|--------|-------------|-----------|
| `shared/macro_snapshot_engine.py` | **KEEP as-is** | `compass/macro.py` | Production-ready. Real data. No changes needed. |
| `shared/macro_state_db.py` | **KEEP as-is** | `compass/macro_db.py` | Production-ready. Move location only. |
| `shared/macro_event_gate.py` | **KEEP as-is** | `compass/events.py` | Production-ready. Absorbs `sentiment_scanner` responsibility. |
| `alerts/risk_gate.py` | **KEEP as-is** | `compass/risk_gate.py` | Production-ready. Already has COMPASS rules 8-10. |
| `engine/regime.py` | **ENHANCE** | `compass/regime.py` | Add: configurable thresholds, hysteresis from ComboRegimeDetector, VIX3M term structure signal, test coverage. |
| `ml/signal_model.py` | **CLEAN UP** | `compass/signal_model.py` | Remove `generate_synthetic_training_data()`. Remove synthetic fallback in pipeline. Hard-fail if no real model. |
| `ml/feature_engine.py` | **REFACTOR** | `compass/features.py` | Replace yfinance → IronVault data source. Remove synthetic fallback defaults. Add COMPASS macro features as inputs. |
| `ml/iv_analyzer.py` | **REFACTOR** | `compass/iv_surface.py` | Wire to IronVault options chain data instead of yfinance approximations. |
| `ml/collect_training_data.py` | **KEEP** | `compass/collect_training_data.py` | Update to run both EXP-400 and EXP-401 configs. |
| `ml/position_sizer.py` | **EXTRACT** | `compass/sizing.py` | Keep `calculate_dynamic_risk()` and `get_contract_size()` only. Kill `PositionSizer` class and Kelly logic. |
| `ml/combo_regime_detector.py` | **ABSORB** | Merged into `compass/regime.py` | Best ideas (asymmetric voting, hysteresis, VIX circuit breaker) merged into enhanced RegimeClassifier. Delete standalone module. |
| `shared/vix_regime.py` | **KILL** | — | Dead code. Never imported. Redundant with regime sizing scales. |
| `ml/regime_detector.py` | **KILL** | — | Unused HMM+RF. Heavy dependencies. Wrong regime labels. |
| `ml/sentiment_scanner.py` | **KILL** | — | Redundant with COMPASS event gate (which is superior). |
| `ml/ml_pipeline.py` | **KILL** | — | Orchestrator for dead code. Enhanced score is uncalibrated heuristic. Replace with thin `MLEnhancedStrategy` wrapper (per ML_INTEGRATION_PROPOSAL.md). |
| `strategy/market_regime.py` | **KILL** | — | 402 lines of unused legacy code. |
| `ml/models/signal_model_20260305.joblib` | **DELETE** | — | Trained on synthetic data. Violates core directive. |

### 3.3 Data Flow: Single Source of Truth

```
                        ┌─────────────┐
                        │  IronVault  │ ← Single data source (Polygon options + prices)
                        └──────┬──────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
     ┌────────────┐   ┌──────────────┐   ┌──────────────┐
     │   REGIME   │   │    MACRO     │   │   FEATURES   │
     │ classifier │   │   engine     │   │   engine     │
     │(VIX+trend) │   │(FRED+Polygon)│   │(tech+vol+IV) │
     └─────┬──────┘   └──────┬───────┘   └──────┬───────┘
           │                  │                   │
           ▼                  ▼                   ▼
     regime: "bull"     macro_score: 72      47 features
           │           sector_rs: [...]           │
           │           event_scale: 0.80          │
           │                  │                   │
           └────────┬─────────┘                   │
                    ▼                              │
           ┌──────────────┐                       │
           │ MarketSnapshot│ ← regime + macro context
           └──────┬───────┘                       │
                  │                                │
                  ▼                                ▼
           ┌──────────────┐               ┌──────────────┐
           │  Strategy    │               │ SignalModel   │
           │generate_sigs │               │  .predict()   │
           └──────┬───────┘               └──────┬───────┘
                  │                               │
                  ▼                               ▼
           raw signals ──────────────────→ ML filter
                                          (confidence gate)
                                                │
                                                ▼
                                         filtered signals
                                                │
                                    ┌───────────┴───────────┐
                                    ▼                       ▼
                              regime_size_scale      event_scale
                              (strategy params)    (COMPASS events)
                                    │                       │
                                    └───────────┬───────────┘
                                                ▼
                                          FINAL SIZE
                                                │
                                                ▼
                                           RiskGate
                                          (rules 0-10)
                                                │
                                                ▼
                                          EXECUTE TRADE
```

### 3.4 Regime: Single Classifier Design

The enhanced `compass/regime.py` merges `engine/regime.py` (the champion) with the best of `ml/combo_regime_detector.py`:

```
Inputs:
  - VIX (daily)
  - VIX3M (daily, optional — abstain if missing)
  - SPY price history (for MA + RSI)

Signals (3, with abstain):
  1. VIX + MA-50 trend  (from engine/regime.py — the champion logic)
  2. RSI momentum       (from combo_regime_detector — RSI > 55 bull, < 45 bear)
  3. VIX term structure  (from combo_regime_detector — VIX/VIX3M ratio)

Classification:
  - VIX > 40 → CRASH (circuit breaker, bypasses voting)
  - VIX > 30 → HIGH_VOL
  - Otherwise: vote from 3 signals → bull/bear/neutral
  - Neutral + VIX < 15 → LOW_VOL

Enhancements over current:
  - Configurable thresholds (not hardcoded)
  - 10-day hysteresis (from combo_regime_detector)
  - Explicit lookahead protection (shift-by-1)
  - Single lowercase label set: bull, bear, high_vol, low_vol, crash

Output: always lowercase, always one of 5 values.
```

### 3.5 Sizing: Exactly Two Multipliers

```
base_risk_pct (from strategy config, e.g., 12% for CS)
  × regime_size_scale (from strategy params — validated in Phase 4)
  × event_scale (from COMPASS event gate — 0.50-1.00)
  = effective_risk_pct

contracts = get_contract_size(effective_risk_pct * account_value, spread_width, credit)
```

No Kelly scaling. No ML confidence sizing. No macro_sizing_flag. Two multipliers, both validated, both with kill switches.

---

## PART 4 — PRODUCTION READINESS PLAN

### Priority 1: Kill Dead Code (Day 1)

| Action | Files | Risk |
|--------|-------|------|
| Delete `ml/regime_detector.py` (HMM+RF) | 417 lines | None — never imported |
| Delete `strategy/market_regime.py` | 402 lines | None — never imported |
| Delete `shared/vix_regime.py` | 97 lines | None — never imported |
| Delete `ml/models/signal_model_20260305.joblib` | Model file | None — synthetic model, violates directive |
| Delete `ml/models/signal_model_20260305.feature_stats.json` | Stats file | None — companion to deleted model |

**Total: 916 lines of dead code + 302KB of synthetic model artifacts removed.**
**Test impact: Zero** — none of these are tested or imported in production.

### Priority 2: Standardize Regime Labels (Day 1-2)

1. `ml/combo_regime_detector.py`: Change outputs from `BULL`/`BEAR`/`NEUTRAL` to `bull`/`bear`/`neutral`
2. `main.py` line 415: Change fallback from `'BULL'` to `'neutral'` (fix optimistic bias bug)
3. `main.py` COMPASS direction override: Ensure lowercase regime injected into snapshot
4. Add mapping comment documenting the canonical label set

**Test impact:** Update `test_combo_regime_detector.py` assertions.

### Priority 3: Add Tests for engine/regime.py (Day 2-3)

Currently **zero test coverage** for the module that drives all regime-adaptive sizing in the champion strategy.

Tests needed:
- VIX > 40 → crash (with declining and non-declining variants)
- VIX > 30 → high_vol
- VIX < 20 + uptrend → bull
- VIX > 25 + downtrend → bear
- VIX < 15 + flat → low_vol
- Fallback cascade (ambiguous inputs)
- `classify_series()` batch consistency
- Edge cases: NaN VIX, empty price history, single data point

### Priority 4: Kill ml/sentiment_scanner.py (Day 3)

1. Verify no imports outside `ml/ml_pipeline.py` (which is also being killed)
2. Delete `ml/sentiment_scanner.py` (547 lines)
3. Delete `ml/ml_pipeline.py` (633 lines)
4. Update `ml/__init__.py` to remove exports
5. Keep `ml/collect_training_data.py`, `ml/signal_model.py`, `ml/feature_engine.py`, `ml/iv_analyzer.py`, `ml/combo_regime_detector.py`, `ml/position_sizer.py`

**Total: 1,180 lines removed in this step.**

### Priority 5: Remove Synthetic Data Paths (Day 3-4)

1. `ml/signal_model.py`: Delete `generate_synthetic_training_data()` method (~150 lines)
2. Remove the synthetic fallback in pipeline initialization:
   ```python
   # BEFORE (ml_pipeline.py line 106-121):
   if not self.signal_model.load():
       features_df, labels = self.signal_model.generate_synthetic_training_data(...)
       self.signal_model.train(features_df, labels)

   # AFTER: Hard fail
   if not self.signal_model.load():
       raise ModelError("No trained model found. Run collect_training_data.py + train first.")
   ```
3. `ml/feature_engine.py`: Replace synthetic fallback defaults with explicit `None` + skip logic

### Priority 6: Retrain ML on Real Data (Day 5-7)

Per `results/ml_retrain_proposal.md`:

1. Re-run `collect_training_data.py` with EXP-401 config → ~353 trades with SS included
2. Merge with existing 249 trades, deduplicate CS overlap → ~350-400 unique trades
3. Feature engineering: add credit-to-width ratio, regime duration, VIX change 5d
4. Train XGBoost with anchored walk-forward CV (train 2020-22→test 2023, etc.)
5. Evaluate against hard gates (AUC ≥ 0.60 on all folds, calibration error < 0.10)
6. If gates pass: save as new model file. If not: document negative result, keep rule-based system.

### Priority 7: Wire IronVault into ML Feature Engine (Day 7-8)

Replace yfinance calls in `ml/feature_engine.py`:
- `yfinance.download('SPY')` → `IronVault.instance().get_price_history('SPY', ...)`
- `yfinance.download('^VIX')` → `IronVault.instance().get_vix_history(...)`
- Options chain data → `IronVault.instance().get_options_chain(...)`

This is required before the ML model can be used in backtester or paper trader.

### Priority 8: Create compass/ Package (Day 8-10)

Physical file moves (with import updates throughout codebase):
1. `engine/regime.py` → `compass/regime.py` (enhanced with hysteresis)
2. `shared/macro_snapshot_engine.py` → `compass/macro.py`
3. `shared/macro_state_db.py` → `compass/macro_db.py`
4. `shared/macro_event_gate.py` → `compass/events.py`
5. `alerts/risk_gate.py` → `compass/risk_gate.py`
6. `ml/feature_engine.py` → `compass/features.py`
7. `ml/signal_model.py` → `compass/signal_model.py`
8. `ml/iv_analyzer.py` → `compass/iv_surface.py`
9. Extract `calculate_dynamic_risk()` + `get_contract_size()` → `compass/sizing.py`
10. `ml/combo_regime_detector.py` → absorbed into `compass/regime.py`, then deleted

**Note:** This is a major refactor touching many imports. Do it on a dedicated branch with full test suite validation.

### Priority 9: Integration Testing (Day 10-12)

New integration tests:
1. Regime → Strategy → Signal pipeline (end-to-end)
2. COMPASS macro → universe eligibility → signal filtering
3. Event gate → sizing → execution engine
4. ML model → filtered signals (when model exists vs. when disabled)
5. Full backtester run with unified COMPASS package

### Summary: Kill List

| File | Lines | Action |
|------|-------|--------|
| `ml/regime_detector.py` | 417 | DELETE |
| `strategy/market_regime.py` | 402 | DELETE |
| `ml/sentiment_scanner.py` | 547 | DELETE |
| `ml/ml_pipeline.py` | 633 | DELETE |
| `shared/vix_regime.py` | 97 | DELETE |
| `ml/signal_model.py` (synthetic method) | ~150 | REMOVE method |
| `ml/models/signal_model_20260305.joblib` | — | DELETE |
| `ml/models/signal_model_20260305.feature_stats.json` | — | DELETE |
| **Total removed** | **~2,246 lines** | |

### Summary: Keep & Enhance List

| File | Lines | Action | New Location |
|------|-------|--------|--------------|
| `shared/macro_snapshot_engine.py` | 898 | MOVE | `compass/macro.py` |
| `shared/macro_state_db.py` | 569 | MOVE | `compass/macro_db.py` |
| `shared/macro_event_gate.py` | 337 | MOVE | `compass/events.py` |
| `alerts/risk_gate.py` | 358 | MOVE | `compass/risk_gate.py` |
| `engine/regime.py` | 235 | ENHANCE + MOVE | `compass/regime.py` |
| `ml/signal_model.py` | ~620 | CLEAN + MOVE | `compass/signal_model.py` |
| `ml/feature_engine.py` | 564 | REFACTOR + MOVE | `compass/features.py` |
| `ml/iv_analyzer.py` | 415 | REFACTOR + MOVE | `compass/iv_surface.py` |
| `ml/position_sizer.py` | ~50 | EXTRACT 2 functions | `compass/sizing.py` |
| `ml/collect_training_data.py` | 686 | UPDATE | `compass/collect_training_data.py` |
| `ml/combo_regime_detector.py` | 230 | ABSORB into regime.py | Deleted after merge |
| **Total kept** | **~4,962 lines** | (from original 7,714) |

---

## APPENDIX: Component Cross-Reference

### Regime Systems (Before → After)

| Before | Status | After |
|--------|--------|-------|
| `engine/regime.py` (5 regimes, lowercase) | Champion backtester | `compass/regime.py` (enhanced, 5 regimes, lowercase) |
| `ml/combo_regime_detector.py` (3 regimes, UPPERCASE) | Legacy paper trader | Absorbed into `compass/regime.py` |
| `ml/regime_detector.py` (4 regimes, snake_case) | Unused | DELETED |
| `strategy/market_regime.py` (7 regimes) | Unused | DELETED |
| COMPASS `macro_state_db._macro_regime()` (3 regimes) | Universe eligibility | Stays as-is (different concern) |

### Event Systems (Before → After)

| Before | Status | After |
|--------|--------|-------|
| `shared/macro_event_gate.py` | Production | `compass/events.py` (unchanged) |
| `ml/sentiment_scanner.py` | Unused/redundant | DELETED |

### Sizing Systems (Before → After)

| Before | Status | After |
|--------|--------|-------|
| Strategy `regime_size_scale` | Active, validated | Unchanged (stays in strategies) |
| COMPASS event scaling | Active | `compass/events.py` (unchanged) |
| `ml/position_sizer.py` PositionSizer class | Unused | DELETED |
| `ml/position_sizer.py` utility functions | Active | `compass/sizing.py` |
| `shared/vix_regime.py` | Unused | DELETED |
| COMPASS `macro_sizing_flag` | Wired but minimal impact | Evaluate: keep or kill after paper trading data |
