# ML Production Readiness Audit Report

**Date:** 2026-03-19
**Champion baseline:** 0.951 overfit score, ROBUST validated
**Standard:** Nothing ships unless it adds proven, backtested value.

---

## 1. Signal Model (`ml/signal_model.py`)

### What It Does
XGBoost binary classifier predicting credit spread profitability. Calibrated probabilities via `CalibratedClassifierCV`. Feature drift monitoring (3-sigma alerts). Fallback counter with critical threshold at 10.

### Code Quality: 7/10
**Strengths:**
- Proper train/val/test split with separate calibration holdout (no data leakage on test set)
- Early stopping on validation set, not test set
- Path traversal protection on model load (SEC-DATA-03)
- joblib deserialization warning logged
- Feature drift monitoring with 3-sigma alerts
- Thread-safe fallback counter
- Model staleness warning (>30 days)

**Issues:**
- `generate_synthetic_training_data()` is a 150-line method baked into the model class that generates fake data with hardcoded distributions. **This is the ONLY training path that has been exercised** (the saved model `signal_model_20260305.joblib` was trained on synthetic data based on feature_stats means being perfectly centered around textbook values)
- Missing features from `get_feature_names()` are silently filled with 0.0 -- could mask serious data pipeline breaks
- No model versioning beyond date stamp
- `random_state=42` everywhere -- no cross-validation with multiple seeds

### Test Coverage: 6/10
- Pipeline tests mock the SignalModel entirely -- no test exercises actual XGBoost training/prediction
- No test for `generate_synthetic_training_data()`
- No test for feature drift detection
- No test for model save/load round-trip
- No test for `_features_to_array()` with missing features

### Data Readiness: 2/10
- **Saved model is trained on SYNTHETIC data** (confirmed by feature_stats.json: means are textbook-centered, e.g. RSI mean=49.5, IV rank=50.2)
- `data/ml_training/trade_outcomes.jsonl` has only **37 trades** from paper trading (Mar 5-10, 2026)
- All 37 from a single week, 35 wins / 2 losses -- zero diversity across regimes, vol levels, or market conditions
- `ml/collect_training_data.py` exists but output (`ml/training_data.csv`) is not present -- script was never run to completion or output was not saved
- Need minimum ~500-1000 real trades across multiple regimes for any meaningful signal

### Integration Feasibility: 5/10
- Clean interface: `predict(features_dict) -> PredictionResult`
- Already integrated into `MLPipeline.analyze_trade()`
- But predictions are currently noise -- synthetic model has no edge over random

### Verdict: NO-GO
The model exists structurally but is trained on synthetic data. Feature stats confirm it. 37 paper trades is not a training dataset. Until real backtested trade outcomes populate `collect_training_data.py`'s output and the model is retrained + validated with walk-forward, this is a random number generator with XGBoost window dressing.

---

## 2. Feature Engine (`ml/feature_engine.py`)

### What It Does
Builds 47-feature vectors combining technical (RSI, MACD, Bollinger, ATR, momentum), volatility (IV rank, skew, RV-IV spread), market (VIX, SPY trend), event risk (earnings/FOMC/CPI), seasonal, regime, and derived features.

### Code Quality: 7/10
**Strengths:**
- Clean separation of feature categories with dedicated methods
- `data_cache` integration avoids redundant yfinance downloads
- FOMC/CPI dates sourced from `shared.constants` (single source of truth)
- Sensible default values when data unavailable
- RSI computed via `shared.indicators.calculate_rsi` (shared implementation)

**Issues:**
- `put_call_ratio` is hardcoded to 1.0 ("Placeholder") -- a feature that never varies is dead weight in the model
- `_compute_volatility_features()` downloads ticker data again via `_download()` even though `_compute_technical_features()` already fetched it -- duplicate network calls
- OPEX week detection is heuristic (days 15-21) rather than computing 3rd Friday
- No feature normalization/scaling -- model receives raw values
- `build_features()` catches all exceptions and returns `{'ticker': ticker, 'error': str(e)}` -- downstream code may not check for this

### Test Coverage: 3/10
- **No dedicated test file for FeatureEngine**
- Only tested indirectly via mocked MLPipeline tests
- No test for individual feature computation methods
- No test for edge cases (empty options chain, missing VIX data, etc.)

### Data Readiness: 6/10
- Features are well-designed and domain-relevant
- Event calendar dates are maintained in shared constants
- IV analysis integration works when options chain data is available
- However, the put_call_ratio placeholder means 1 of 47 features is always constant

### Integration Feasibility: 8/10
- Already integrated into MLPipeline
- `compute_market_features()` has been optimized for batch analysis (compute once, share across tickers)
- Clean dict-based interface

### Verdict: NEEDS-WORK
Good feature design, but no tests, a dead placeholder feature, and duplicate data fetching. Fix the low-hanging fruit before relying on it for production signals.

---

## 3. ML Pipeline Orchestrator (`ml/ml_pipeline.py`)

### What It Does
Central orchestrator that chains: regime detection -> IV analysis -> feature building -> ML prediction -> event risk scan -> position sizing -> enhanced score -> recommendation.

### Code Quality: 8/10
**Strengths:**
- Clean orchestration with pre-computed regime and market features for batch analysis
- ThreadPoolExecutor for parallel per-ticker analysis
- Synthetic model warning propagated to recommendation output
- Fallback counter with critical threshold
- `ModelError` properly re-raised, other exceptions caught with graceful degradation
- Batch analysis computes regime once (O(1) not O(n))

**Issues:**
- `retrain_models()` trains on synthetic data with no option for real data
- Enhanced score formula is heuristic (not learned) -- the score combines ML prediction + regime + IV + event risk with hardcoded weights. This is a reasonable heuristic but it's not validated
- Regime-direction mismatch penalty only fires above 95% confidence -- a very high bar

### Test Coverage: 8/10
- **53 tests, all passing** across test_ml_pipeline.py
- Tests cover: initialization, auto-init, synthetic training fallback, precomputed regime passthrough, fallback on exception, all sub-component invocation, batch empty input, batch regime computed once, batch sorted by score, enhanced score range, crisis penalty, IV rank bonus, extreme clamping, vol premium bonus, recommendation classification (strong_buy/buy/consider/pass), event avoidance, regime-direction mismatch
- Good mocking strategy -- each sub-component independently mocked

**Gaps:**
- No integration test with real (unmocked) components
- No test for `get_summary_report()`

### Data Readiness: N/A (orchestrator)

### Integration Feasibility: 8/10
- Already the intended integration point for `main.py`
- `analyze_trade()` and `batch_analyze()` have clean signatures
- Status/monitoring via `get_pipeline_status()` and `get_fallback_stats()`

### Verdict: NEEDS-WORK
Well-architected orchestrator with good test coverage. But it's only as good as its weakest component (SignalModel), which is currently trained on synthetic data. The orchestrator is production-ready; the model it wraps is not.

---

## 4. Regime Detector (HMM) (`ml/regime_detector.py`)

### What It Does
HMM + Random Forest ensemble for 4-state regime detection: low_vol_trending, high_vol_trending, mean_reverting, crisis. Uses SPY, VIX, TLT for training features. Retrains daily.

### Code Quality: 6/10
**Strengths:**
- HMM for unsupervised state discovery + RF for interpretable classification
- Heuristic state-to-regime mapping based on VIX/RV/trend thresholds
- Daily retraining cadence
- Data cache integration

**Issues:**
- HMM states are mapped to regimes via `_map_states_to_regimes()` which uses hardcoded thresholds that ignore the HMM output entirely -- the HMM is basically decorative. The RF trains on heuristic labels, making it a complex way to replicate simple rules
- VIX term structure approximated as `VIX / 60-day MA(VIX)` instead of actual VIX/VIX3M ratio
- No persistence of trained models -- retrains from scratch every session
- `StandardScaler` is fit on training data but must be available at predict time (stored in-memory only)
- `_fetch_training_data()` does `.copy()` correctly but `_get_current_features()` also copies -- inconsistently handled

### Test Coverage: 6/10
- 6 tests covering: fit returns True, detect_regime returns valid dict, confidence in range, fallback on empty data, feature columns present, data_cache integration
- No test for `_map_states_to_regimes()` heuristic logic
- No test for regime stability or consistency
- No test for daily retrain skip logic

### Data Readiness: 5/10
- Uses live yfinance data (SPY, VIX, TLT) -- works when market is open
- VIX term structure approximation reduces signal quality
- 252-day lookback provides reasonable history

### Integration Feasibility: 6/10
- Integrated into MLPipeline but **NOT used by the actual backtester** -- the portfolio backtester uses `engine/regime.py` (RegimeClassifier), which is a completely separate, simpler rule-based system
- Two competing regime systems create confusion

### Verdict: NO-GO
The HMM is essentially decorative -- the RF trains on heuristic labels that don't use HMM outputs. Meanwhile, the production backtester uses an entirely different regime system (`engine/regime.py`). This creates a confusing dual-system architecture. If the rule-based RegimeClassifier in `engine/regime.py` already produces validated results with the 0.951 champion, adding an HMM that wraps the same heuristics adds complexity without value.

---

## 5. Combo Regime Detector (`ml/combo_regime_detector.py`)

### What It Does
Rule-based multi-signal regime classifier for backtester direction filtering. Three signals: price_vs_ma200, rsi_momentum, vix_structure. Asymmetric voting (2/3 for BULL, 3/3 unanimous for BEAR). Hysteresis cooldown. VIX circuit breaker.

### Code Quality: 9/10
**Strengths:**
- Clean, well-documented architecture with explicit signal abstention logic
- MA200 confidence band prevents whipsawing near moving average
- Asymmetric voting is a smart design -- bullish bias with high bar for bearish call
- VIX circuit breaker bypasses hysteresis for extreme events
- All computations use shifted (T-1) data -- zero lookahead
- Configurable via dict with sensible defaults
- `VALID_SIGNALS` frozenset with unknown-signal warnings

**Issues:**
- Minor: `ma_crossover` signal is defined but not in default set -- dead code path unless explicitly enabled
- No persistence or logging of regime transitions

### Test Coverage: 9/10
- 8 focused scenario tests: all-agree BULL, unanimous BEAR, bear blocked by supermajority, 2023 recovery, 2024 dip, VIX circuit breaker, hysteresis prevention, MA200 confidence zone
- Tests use realistic multi-hundred-day synthetic price series
- Each test validates a specific market scenario with clear assertions

### Data Readiness: 8/10
- Works with pre-loaded data (no network calls)
- Needs VIX and VIX3M data by date -- VIX3M may not always be available in backtester data cache
- Graceful abstention when VIX3M missing

### Integration Feasibility: 9/10
- Already integrated into portfolio backtester
- `compute_regime_series()` returns dict of timestamps -> regime labels
- Used for direction filtering in all experiments

### Verdict: GO
This is production-quality. Clean design, excellent test coverage, no lookahead. The only regime system that should be in production.

---

## 6. Engine Regime Classifier (`engine/regime.py`)

### What It Does
Simple rule-based classifier: VIX thresholds + SPY trend direction -> 5 regimes (BULL, BEAR, HIGH_VOL, LOW_VOL, CRASH). Works on pre-loaded data with zero network calls.

### Code Quality: 8/10
**Strengths:**
- Pure, no side effects -- takes VIX + price series, returns regime
- Enum-based regimes with strategy recommendations
- `classify_series()` for batch tagging
- `summarize()` for distribution stats
- Clean default-to-constructive logic for ambiguous zones

**Issues:**
- Trend threshold of 5% annualized is relatively sensitive
- Ambiguous zone logic defaults to BULL aggressively (mild pullback + low VIX = BULL)
- No tests in the codebase (tested via integration with backtester only)

### Test Coverage: 4/10
- No dedicated test file
- Validated indirectly through backtester results (the 0.951 champion uses this)

### Data Readiness: 9/10
- Works entirely on pre-loaded data
- No external dependencies at runtime

### Integration Feasibility: 9/10
- Core component of the validated portfolio backtester
- Used by regime-adaptive strategies in champion config

### Verdict: NEEDS-WORK
Battle-tested via the 0.951 champion, but lacks dedicated unit tests. Should add tests for edge cases (VIX exactly at thresholds, insufficient price history) before calling it fully production-ready.

---

## 7. IV Analyzer (`ml/iv_analyzer.py`)

### What It Does
Analyzes IV surface structure: skew steepness (put vs call), term structure (contango/backwardation), IV rank/percentile. Generates directional signals.

### Code Quality: 7/10
**Strengths:**
- Proper IV rank calculation delegated to `shared.indicators`
- 24-hour cache for IV history
- Term structure classification (contango/backwardation/flat)
- Clean signal generation with reasoning

**Issues:**
- IV rank uses HV as proxy for historical IV (acceptable approximation but should be documented as such)
- 25-delta approximated as 10% OTM -- could be off significantly in high-vol environments
- Copy of options_chain done inside `_compute_term_structure` but not in `_compute_skew_metrics` (inconsistent mutation protection)

### Test Coverage: 2/10
- **No dedicated test file**
- Only tested via mocked MLPipeline

### Data Readiness: 5/10
- Requires live options chain with `iv`, `bid`, `ask`, `strike`, `type`, `expiration` columns
- HV-as-IV-proxy reduces accuracy

### Integration Feasibility: 7/10
- Integrated into MLPipeline
- Clean interface

### Verdict: NEEDS-WORK
Useful analysis module but undertested. The IV surface signals could add real value to trade selection if validated, but zero tests means zero confidence.

---

## 8. Position Sizer (`ml/position_sizer.py`)

### What It Does
Kelly Criterion position sizing with ML confidence adjustment, portfolio-level risk constraints, and IV-scaled dynamic risk budgeting.

### Code Quality: 8/10
**Strengths:**
- Proper Kelly implementation with fractional Kelly for safety
- IV-scaled sizing tiers with 40% portfolio heat cap
- Portfolio constraint enforcement (total risk, correlated exposure)
- `calculate_dynamic_risk()` and `get_contract_size()` as standalone functions (testable, reusable)
- Detailed reasoning in output dict

**Issues:**
- Correlation groups are hardcoded lists (tech stocks, financials, index ETFs) -- not computed from actual returns
- `get_size_recommendation_text()` assumes ~$1000 per contract -- incorrect for most spreads
- The ML confidence adjustment (`fractional_kelly * ml_confidence`) means a synthetic model outputting 0.5 probability with 0.0 confidence produces 0.0 position size -- effectively disabling the system. This is actually a safety feature given the synthetic model.

### Test Coverage: 3/10
- No dedicated test file
- Only tested via mocked MLPipeline

### Data Readiness: 7/10
- Standalone functions work without ML model
- IV-rank-based sizing works with just VIX/IV data

### Integration Feasibility: 8/10
- `calculate_dynamic_risk()` already used by paper trader
- Clean interface

### Verdict: NEEDS-WORK
Solid sizing logic, especially the IV-scaled path. Needs tests. The hardcoded correlation groups should be flagged as a known limitation.

---

## 9. Sentiment Scanner (`ml/sentiment_scanner.py`)

### What It Does
Event risk scanner for earnings, FOMC, CPI. Position size adjustment based on event proximity. ETF skip list to avoid unnecessary yfinance calls.

### Code Quality: 7/10
**Strengths:**
- Risk scoring by event proximity (well-calibrated tiers)
- ETF skip list (`_NO_EARNINGS_TICKERS`) avoids unnecessary API calls
- Position size multipliers decrease with risk (0.8->0%, 0.6->25%, 0.4->50%)
- `should_avoid_trade()` convenience method with clear return type
- 24-hour earnings cache

**Issues:**
- CPI detection uses day-of-month heuristic (days 10-14) rather than actual release dates
- No NFP (non-farm payrolls) or GDP release tracking
- `_generate_recommendation()` doesn't use events list parameter

### Test Coverage: 3/10
- No dedicated test file
- Only tested via mocked MLPipeline

### Data Readiness: 6/10
- FOMC dates from shared constants
- Earnings from yfinance (live API dependency)
- CPI dates approximate

### Integration Feasibility: 8/10
- Clean interface, already integrated
- Event risk score flows through to position sizing

### Verdict: NEEDS-WORK
Useful safety layer. CPI heuristic is the weakest link. Needs tests.

---

## 10. Sector Data Infrastructure (`scripts/fetch_sector_options.py`)

### What It Does
Polygon API fetcher for historical options contracts + daily OHLCV. Strike filtering by OTM range. Checkpoint/resume for long-running fetches. SQLite storage.

### Code Quality: 8/10
**Strengths:**
- Rate limiting (1 req/sec) with 429 retry
- Checkpoint every 200 contracts with full resume capability
- OTM strike filtering reduces data volume significantly
- Friday enumeration for contract discovery (handles weeklies)
- ETA calculation during fetch
- Shared DB schema with HistoricalOptionsData

**Issues:**
- `get_underlying_prices()` uses raw `curl` subprocess instead of requests -- inconsistent with rest of codebase
- `datetime.utcfromtimestamp()` is deprecated
- Single retry on 429 (recursive, unbounded in theory)
- No data validation on bars received from Polygon

### Test Coverage: 0/10
- No test file

### Data Readiness: 7/10
- Well-designed for building the options cache needed by backtester
- Supports custom date ranges and discover-only mode
- Default 2020-2026 range covers backtest period

### Integration Feasibility: 7/10
- Populates the same `options_cache.db` used by the backtester
- CLI-only (no programmatic API)

### Verdict: NEEDS-WORK
Good data infrastructure. The curl subprocess is odd but functional. Needs validation tests and data integrity checks.

---

## 11. Feature Logger (`shared/feature_logger.py`, tested by `tests/test_feature_logger.py`)

### What It Does
SQLite-based trade feature logging for future ML training. Logs feature vectors at entry, outcomes at exit.

### Code Quality: 8/10
- Upsert-safe (no duplicates)
- Never raises exceptions (safety for scanner integration)
- `get_stats()` for monitoring

### Test Coverage: 9/10
- 11 tests covering: table creation, log entry, log outcome, empty stats, stats with data, non-raising on bad paths, upsert dedup, feature extraction from opportunities
- Good edge case coverage

### Data Readiness: 4/10
- Logging infrastructure is ready but **data is sparse** (37 trades from 1 week)
- No systematic pipeline to populate from backtester runs

### Integration Feasibility: 9/10
- Already integrated into paper trader scanning

### Verdict: GO (as infrastructure)
The logger itself is production-ready. But it's an empty bucket waiting to be filled. Need to run `collect_training_data.py` against backtester output to populate meaningful training data.

---

## 12. Trained Artifacts (`ml/models/`, `data/ml_training/`)

### Model File
- `signal_model_20260305.joblib` (305 KB) -- trained 2026-03-05
- `signal_model_20260305.feature_stats.json` -- 47 features with means/stds

### Training Data Assessment
**Feature stats confirm synthetic training:**
- RSI mean: 49.5 (textbook center of RSI range)
- IV rank mean: 50.2 (textbook center)
- IV percentile mean: 50.1 (textbook center)
- Vol premium mean: 4.1 (synthetic noise)
- All stds are symmetric and textbook-perfect

**Trade outcomes file:**
- 37 trades, all from Mar 5-10, 2026 (1 week of paper trading)
- 35 wins, 2 losses (94.6% win rate -- not representative of real distribution)
- SPY only + a few QQQ iron condors
- All exits via `management_dte` or `stop_loss` -- no profit target exits, no expiration holds
- Zero diversity: single market regime, single vol environment

### Verdict: NO-GO
Model is a synthetic artifact. Training data is insufficient by 10-20x minimum.

---

## DECISION MATRIX

| System | Quality | Tests | Data | Integration | Verdict |
|--------|---------|-------|------|-------------|---------|
| **Signal Model** | 7 | 6 | 2 | 5 | **NO-GO** |
| **Feature Engine** | 7 | 3 | 6 | 8 | **NEEDS-WORK** |
| **ML Pipeline** | 8 | 8 | N/A | 8 | **NEEDS-WORK** |
| **Regime Detector (HMM)** | 6 | 6 | 5 | 6 | **NO-GO** |
| **Combo Regime Detector** | 9 | 9 | 8 | 9 | **GO** |
| **Engine Regime Classifier** | 8 | 4 | 9 | 9 | **NEEDS-WORK** |
| **IV Analyzer** | 7 | 2 | 5 | 7 | **NEEDS-WORK** |
| **Position Sizer** | 8 | 3 | 7 | 8 | **NEEDS-WORK** |
| **Sentiment Scanner** | 7 | 3 | 6 | 8 | **NEEDS-WORK** |
| **Sector Fetcher** | 8 | 0 | 7 | 7 | **NEEDS-WORK** |
| **Feature Logger** | 8 | 9 | 4 | 9 | **GO** |
| **Trained Artifacts** | N/A | N/A | 2 | N/A | **NO-GO** |

---

## Executive Summary

**GO systems (2):** ComboRegimeDetector, FeatureLogger -- production-quality, well-tested, safe to ship.

**NO-GO systems (3):** SignalModel, HMM RegimeDetector, Trained Artifacts -- the ML prediction path is built on synthetic data. The HMM regime detector adds complexity over the rule-based system already validated in the 0.951 champion. No value proven.

**NEEDS-WORK systems (7):** Feature Engine, ML Pipeline, Engine Regime Classifier, IV Analyzer, Position Sizer, Sentiment Scanner, Sector Fetcher -- all structurally sound but undertested. The pipeline orchestrator is well-tested but wraps untested/unvalidated components.

### Critical Path to Production
1. **Run `ml/collect_training_data.py`** against backtester with champion config for 2020-2025 to generate real training data (estimated 500-2000 trades)
2. **Retrain SignalModel on real data** with walk-forward validation matching the champion's overfit framework
3. **Prove the ML model adds alpha** over the champion baseline (A/B backtest: champion with ML vs champion without ML)
4. **Kill the HMM RegimeDetector** -- it duplicates the validated `engine/regime.py` with unnecessary complexity
5. **Add tests** for Feature Engine, IV Analyzer, Position Sizer, Sentiment Scanner

### The Hard Truth
The 0.951 champion was validated WITHOUT any ML model involvement. The ML pipeline is an aspirational layer that has never been proven to add value. Until step 3 above shows measurable alpha improvement in walk-forward backtests, **none of the ML prediction components should influence live trading decisions**. The safe default is: ML components log and observe (via FeatureLogger), but do not gate or modify trade execution.
