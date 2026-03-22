# ML Integration Proposal — EXP-500 Series

## Problem Statement

EXP-400 (CS+IC) and EXP-401 (CS+SS) use purely rule-based signal generation:
fixed MA trend filter, momentum filter, IV/RSI thresholds. The `Signal.score`
field is hardcoded to `50.0` everywhere. The existing ML pipeline
(`ml/signal_model.py`, `ml/feature_engine.py`, `ml/ml_pipeline.py`) is fully
built but disconnected from the strategy `generate_signals()` path.

**Goal**: Create new experiments (EXP-500, EXP-501) where ML acts as a
**confidence overlay** on existing rule-based signals — filtering out low-quality
trades and modulating position size — without modifying the underlying
EXP-400/401 strategies.

---

## Architecture: ML as Confidence Overlay

```
Rule-based signal generation (unchanged)
            │
            ▼
    ┌───────────────────┐
    │  ML Confidence     │  ← NEW: scores each signal 0.0–1.0
    │  Overlay           │
    └───────┬───────────┘
            │
            ▼
    ┌───────────────────┐
    │  Gate + Modulate   │  Signal.score = ml_probability
    │                    │  Drop if confidence < threshold
    │                    │  Scale position size by confidence
    └───────┬───────────┘
            │
            ▼
    Portfolio backtester / paper trader (unchanged)
```

**Key principle**: The rule-based strategies remain the primary signal source.
ML cannot generate new trades — it can only *suppress* or *scale down* existing
ones. This makes the ML layer strictly risk-reducing: worst case, it filters too
aggressively and reduces returns; it cannot create novel risk.

---

## Proposed Experiments

### EXP-500: ML-Enhanced CS + IC (base: EXP-400)
- Same strategies, tickers, and params as EXP-400
- ML confidence overlay gates signals (threshold: 0.45 probability)
- Position sizing scaled by `ml_confidence * base_size`
- Target: Same or better returns with reduced drawdown

### EXP-501: ML-Enhanced CS + SS (base: EXP-401)
- Same strategies, tickers, and params as EXP-401
- ML confidence overlay gates signals (threshold: 0.45 probability)
- Position sizing scaled by `ml_confidence * base_size`
- Target: Improve 2022 bear-year performance (currently +2.2% after slippage)

---

## Feature Set

### Already Available (FeatureEngine — 47 features)

The existing `FeatureEngine.build_features()` produces everything we need.
Grouped by predictive category:

| Category | Features | Predictive Value |
|----------|----------|-----------------|
| **Volatility** | `iv_rank`, `iv_percentile`, `current_iv`, `rv_iv_spread`, `vol_premium`, `vol_premium_pct`, `realized_vol_10d/20d/60d` | **HIGH** — vol premium (IV > RV) is the core edge for credit spreads |
| **Regime** | `regime_id`, `regime_confidence`, one-hot regime flags | **HIGH** — regime already drives direction in EXP-400/401 |
| **Technical** | `rsi_14`, `macd/signal/histogram`, `bollinger_pct_b`, `atr_pct`, `return_5d/10d/20d`, `dist_from_sma20/50/200_pct` | **MEDIUM** — trend confirmation, mean-reversion signals |
| **Event Risk** | `days_to_earnings`, `days_to_fomc`, `days_to_cpi`, `event_risk_score` | **MEDIUM** — binary catalyst risk windows |
| **Market** | `vix_level`, `vix_change_1d`, `spy_return_5d/20d`, `spy_realized_vol` | **MEDIUM** — market-wide context |
| **Seasonal** | `day_of_week`, `is_opex_week`, `is_monday`, `is_month_end` | **LOW** — calendar effects |
| **Derived** | `rsi_oversold/overbought`, `iv_rank_high/low`, `risk_adjusted_momentum` | **LOW** — redundant with base features, useful for tree splits |

### New Features to Add (strategy-specific)

These features capture **signal-specific context** that FeatureEngine doesn't
currently produce because it operates at the ticker level, not the trade level:

| Feature | Source | Why |
|---------|--------|-----|
| `spread_type_is_bull_put` | Signal metadata | Direction matters for regime interaction |
| `otm_distance_pct` | `(price - short_strike) / price` | How far OTM; tighter = more risk |
| `credit_to_width_ratio` | `net_credit / spread_width` | Premium captured relative to risk |
| `dte_at_entry` | Signal.dte | Time decay profile |
| `regime_direction_alignment` | regime vs spread_type | 1.0 if aligned, 0.0 if not |
| `iv_rank_x_regime_confidence` | interaction term | High IV + confident regime = strong signal |
| `vol_premium_x_dte` | interaction term | Vol premium decays with time |
| `vix_term_structure_slope` | VIX vs VIX3M ratio | Contango/backwardation = complacency/fear |

**For straddle/strangle (EXP-501 only):**

| Feature | Source | Why |
|---------|--------|-----|
| `event_type_fomc` | SS metadata | FOMC vs CPI have different IV crush magnitudes |
| `pre_event_iv_rank` | IV rank at signal time | Higher pre-event IV = bigger crush |
| `historical_event_move_pct` | Lookback table | How much did SPY move last N events? |
| `days_since_last_event` | Calendar | Event clustering effects |

---

## Integration Point: Where ML Plugs In

### Option A: Strategy Wrapper (Recommended)

Create `MLEnhancedStrategy` that wraps any `BaseStrategy`:

```python
# strategies/ml_enhanced.py

class MLEnhancedStrategy(BaseStrategy):
    """Wraps a rule-based strategy with ML confidence overlay."""

    def __init__(self, base_strategy: BaseStrategy, signal_model: SignalModel,
                 feature_engine: FeatureEngine, min_confidence: float = 0.45):
        self.base = base_strategy
        self.model = signal_model
        self.features = feature_engine
        self.min_confidence = min_confidence

    def generate_signals(self, market_data: MarketSnapshot) -> List[Signal]:
        # 1. Get rule-based signals (unchanged)
        raw_signals = self.base.generate_signals(market_data)

        # 2. Score each signal with ML
        scored = []
        for signal in raw_signals:
            features = self._build_signal_features(signal, market_data)
            prediction = self.model.predict(features)

            # 3. Gate: drop low-confidence signals
            if prediction['probability'] < self.min_confidence:
                continue

            # 4. Stamp score onto signal
            signal.score = prediction['probability']
            signal.metadata['ml_confidence'] = prediction['confidence']
            signal.metadata['ml_probability'] = prediction['probability']
            scored.append(signal)

        return scored

    def size_position(self, signal, portfolio_state) -> int:
        # Base sizing, then scale by ML confidence
        base_contracts = self.base.size_position(signal, portfolio_state)
        ml_conf = signal.metadata.get('ml_confidence', 1.0)
        return max(1, int(base_contracts * ml_conf))

    def manage_position(self, position, market_data) -> PositionAction:
        # Pass through — ML doesn't modify exit logic
        return self.base.manage_position(position, market_data)
```

**Why wrapper, not subclass**: Keeps ML logic in one place. Works identically
for CS, IC, and SS strategies. Zero changes to existing strategy files.

### Option B: Pipeline Hook (Alternative)

Inject ML scoring at the `portfolio_backtester.py` level, between signal
generation and order execution. Simpler but less portable to paper trading.

**Recommendation**: Option A. The wrapper is clean, testable, and works in both
backtester and paper trader contexts.

---

## Training Data: Where It Comes From

### Phase 1: Backtest Outcomes (offline, bootstrap the model)

Run EXP-400 and EXP-401 backtests across 2020-2025, capture every trade:

```python
# For each trade in backtest results:
training_sample = {
    'features': feature_engine.build_features(ticker, price, chain, ...),
    'signal_features': {  # new trade-specific features
        'spread_type_is_bull_put': ...,
        'otm_distance_pct': ...,
        'credit_to_width_ratio': ...,
    },
    'label': 1 if trade.pnl > 0 else 0,     # binary: profitable?
    'pnl_pct': trade.pnl / trade.max_loss,   # continuous: for future regression
}
```

**Expected sample size**: ~200-400 trades from CS (weekly scan, 6 years),
~50-100 from IC, ~30-60 from SS. This is small. Mitigations:
- Use shallow trees (max_depth=4, not 6)
- Strong regularization (high gamma, min_child_weight)
- Cross-validate with purged time-series splits (not random)
- Augment with synthetic data from SignalModel.generate_synthetic_training_data()

### Phase 2: Paper Trade Outcomes (online, continuous improvement)

Once EXP-500/501 are paper trading, each closed trade becomes a new training
sample. Retrain weekly with expanding window.

### Phase 3: Walk-Forward Retraining

Train on years [T-3, T-1], validate on year [T]. Matches the existing
walk-forward validation framework from `scripts/validate_regime_adaptive.py`.

---

## Training Pipeline

### Data Collection Script

```
scripts/collect_ml_training_data.py
├── Run EXP-400 backtest → capture trade-level features + outcomes
├── Run EXP-401 backtest → capture trade-level features + outcomes
├── Merge, deduplicate
├── Save to output/ml_training_data.parquet
└── Print stats (N trades, win rate, feature coverage)
```

### Training Script

```
scripts/train_signal_model.py
├── Load training data
├── Purged time-series cross-validation (no random splits for time-series!)
├── Train XGBoost with conservative hyperparameters
├── Calibrate probabilities (CalibratedClassifierCV, already in SignalModel)
├── Log feature importance, AUC, precision/recall
├── Save model to ml/models/
└── Run walk-forward backtest to validate
```

### Key Change from Existing SignalModel.train()

The current `train()` uses random `train_test_split` with `stratify=y`. For
time-series trading data, this leaks future information. Replace with:

```python
from sklearn.model_selection import TimeSeriesSplit

# Purged walk-forward splits
tscv = TimeSeriesSplit(n_splits=3, gap=20)  # 20-day gap prevents leakage
for train_idx, val_idx in tscv.split(X):
    ...
```

---

## Validation Requirements

Before deploying EXP-500/501 to paper trading, they must pass the same gates
as EXP-400/401:

| Check | Threshold | Method |
|-------|-----------|--------|
| A. Backtest return | > 0% avg across 6 years | Portfolio backtester |
| B. Walk-forward | 2/3 folds profitable | TimeSeriesSplit, 3 folds |
| C. Sensitivity | Score ≥ 0.70 | ±10% param perturbation |
| D. Out-of-sample | 2020-2021 profitable | Train on 2022-2025 only |
| E. Monte Carlo | 95% of 10K shuffles profitable | Bootstrap resampling |
| F. Max drawdown | < -25% | Portfolio backtester |
| G. Tail risk | Worst month > -10% | Monthly P&L analysis |

**Additional ML-specific checks:**

| Check | Threshold | Why |
|-------|-----------|-----|
| AUC > 0.55 | On held-out time-series fold | Model must beat random |
| Precision > 0.60 | At chosen confidence threshold | Don't let through bad trades |
| Feature stability | No feature > 40% importance | Avoid single-feature dependence |
| Backtest improvement | DD reduction > 10% OR return increase > 5% vs base | ML must earn its complexity |
| Filtered trade count | > 60% of base signals pass | Don't over-filter |

---

## Implementation Phases

### Phase 1: Data Collection (1 session)
- [ ] Write `scripts/collect_ml_training_data.py`
- [ ] Run EXP-400 backtest, capture per-trade features + outcomes
- [ ] Run EXP-401 backtest, capture per-trade features + outcomes
- [ ] Save to `output/ml_training_data.parquet`
- [ ] Verify: print feature matrix shape, win rates, missing values

### Phase 2: Model Training (1 session)
- [ ] Extend `FeatureEngine` with trade-specific features (in a subclass, not modifying original)
- [ ] Write `scripts/train_signal_model.py` with time-series CV
- [ ] Train model, log metrics (AUC, precision, recall, feature importance)
- [ ] Verify: AUC > 0.55 on held-out fold, no feature > 40% importance
- [ ] Save model to `ml/models/exp500_signal_model.joblib`

### Phase 3: Strategy Wrapper (1 session)
- [ ] Write `strategies/ml_enhanced.py` (MLEnhancedStrategy wrapper)
- [ ] Write `configs/exp500.json` and `configs/exp501.json`
- [ ] Write tests: `tests/test_ml_enhanced.py`
- [ ] Verify: wrapper passes through signals correctly when model is neutral

### Phase 4: Backtest Validation (1 session)
- [ ] Run EXP-500 through portfolio backtester, compare vs EXP-400 baseline
- [ ] Run EXP-501 through portfolio backtester, compare vs EXP-401 baseline
- [ ] Run full validation suite (checks A-G + ML-specific checks)
- [ ] Sweep `min_confidence` threshold: 0.40, 0.45, 0.50, 0.55
- [ ] Write `scripts/validate_ml_experiments.py`
- [ ] Decision gate: proceed to paper only if ML improves DD or return

### Phase 5: Paper Trading (ongoing)
- [ ] Write `configs/paper_exp500.yaml` and `configs/paper_exp501.yaml`
- [ ] Deploy EXP-500/501 alongside EXP-400/401 (separate Alpaca accounts)
- [ ] Log ML predictions for every signal (score, features, outcome) for monitoring
- [ ] Weekly model retrain with expanding window
- [ ] 8-week evaluation period

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| **Overfitting on small sample** | Shallow trees (depth=4), strong regularization, time-series CV with gap, augment with synthetic data |
| **Feature leakage** | Purged time-series splits, 20-day gap between train/test, no future data in features |
| **Model staleness** | Weekly retrain, feature drift monitoring (already in SignalModel._check_feature_distribution) |
| **ML makes things worse** | Confidence overlay is strictly risk-reducing (can only filter, not create trades). Hard kill-switch: set min_confidence=0.0 to disable ML filtering |
| **Complexity tax** | Wrapper pattern keeps ML isolated. Can A/B test ML-on vs ML-off trivially |
| **Sparse training data for IC/SS** | Pool CS+IC features for EXP-500 model; train separate model for SS (EXP-501) only if sample size > 100, else use CS model with spread_type feature |

---

## Success Criteria for EXP-500/501

An ML experiment "wins" vs its base experiment if ANY of:

1. **Same return, less drawdown**: Avg return within 90% of base, max DD improved > 15%
2. **More return, same drawdown**: Avg return > 110% of base, max DD within 110% of base
3. **Better risk-adjusted**: Sharpe ratio > 110% of base

If none of these hold after backtesting, ML integration is **not worth the
complexity** and we document the negative result.

---

## File Structure (new files only)

```
strategies/ml_enhanced.py          # MLEnhancedStrategy wrapper
ml/trade_feature_engine.py         # Trade-specific feature extensions
scripts/collect_ml_training_data.py # Backtest → training data
scripts/train_signal_model.py      # Time-series CV training
scripts/validate_ml_experiments.py  # A-G + ML checks
configs/exp500.json                # EXP-500 config
configs/exp501.json                # EXP-501 config
configs/paper_exp500.yaml          # Paper trading config
configs/paper_exp501.yaml          # Paper trading config
tests/test_ml_enhanced.py          # Wrapper + integration tests
output/ml_training_data.parquet    # Training data artifact
```
