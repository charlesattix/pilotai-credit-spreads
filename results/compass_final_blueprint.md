# COMPASS Final Blueprint

**Date:** 2026-03-20
**Version:** 1.0
**Status:** DEFINITIVE — awaiting Carlos sign-off
**Scope:** Unify three intelligence systems into one COMPASS platform

---

## 1. THE FINAL STATE — COMPASS AFTER MERGE

### 1.1 Module Inventory

The unified `compass/` package contains 10 modules totaling ~4,630 lines (down from 7,714 pre-merge).

```
compass/
├── __init__.py              ~40 lines    Public API exports
├── regime.py               ~320 lines    Single regime classifier (enhanced)
├── macro.py                ~899 lines    Macro intelligence engine
├── macro_db.py             ~570 lines    SQLite persistence layer
├── events.py               ~338 lines    Event calendar + position scaling
├── risk_gate.py            ~359 lines    Risk rules 0-10
├── features.py             ~500 lines    ML feature engineering (refactored)
├── signal_model.py         ~620 lines    XGBoost trade filter (cleaned)
├── iv_surface.py           ~416 lines    IV surface analysis
├── sizing.py               ~120 lines    Position sizing utilities
└── collect_training_data.py ~687 lines   Real-data harvesting pipeline
```

### 1.2 Module Detail Cards

---

#### `compass/__init__.py` (~40 lines)

**Purpose:** Public API surface for the unified COMPASS package.

**Public Exports:**
```python
from compass.regime import Regime, RegimeClassifier
from compass.macro import MacroSnapshotEngine
from compass.macro_db import (
    init_db, get_current_macro_score, get_sector_rankings,
    get_event_scaling_factor, get_eligible_underlyings,
)
from compass.events import get_upcoming_events, compute_composite_scaling, run_daily_event_check
from compass.risk_gate import RiskGate
from compass.signal_model import SignalModel
from compass.features import FeatureEngine
from compass.iv_surface import IVAnalyzer
from compass.sizing import calculate_dynamic_risk, get_contract_size
```

**Dependencies:** All other compass modules.

---

#### `compass/regime.py` (~320 lines)

**Source:** `engine/regime.py` (236 lines) enhanced with best ideas from `ml/combo_regime_detector.py` (231 lines).

**What it does:** Single source of truth for market regime classification. Classifies each trading day into one of 5 regimes: `bull`, `bear`, `high_vol`, `low_vol`, `crash`. Drives all regime-adaptive sizing in strategies.

**Public API:**
```python
class Regime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    CRASH = "crash"

REGIME_INFO: Dict[Regime, Dict]  # metadata per regime

class RegimeClassifier:
    def __init__(self, config: dict = None)
    def classify(self, vix: float, spy_prices: pd.Series, date: pd.Timestamp,
                 rsi: float = None, vix3m: float = None) -> Regime
    def classify_series(self, spy_data: pd.DataFrame, vix_series: pd.Series,
                        rsi_series: pd.Series = None, vix3m_series: pd.Series = None) -> pd.Series
    @staticmethod
    def summarize(regime_series: pd.Series) -> Dict
```

**Enhancement over current:** Adds configurable thresholds (via config dict), 10-day hysteresis (from ComboRegimeDetector), RSI momentum signal, VIX/VIX3M term structure signal, explicit shift-by-1 lookahead protection, and debug-level logging for regime transitions. Output always lowercase. Single label set consumed by all strategies.

**Dependencies:** `pandas`, `enum`, `logging`

---

#### `compass/macro.py` (~899 lines)

**Source:** `shared/macro_snapshot_engine.py` — moved as-is.

**What it does:** Core macro intelligence engine. Fetches price data from Polygon and economic data from FRED public CSV. Computes 4-dimensional macro score (growth, inflation, fed_policy, risk_appetite, each 0-100), 15-ETF sector relative strength rankings, and RRG quadrant classification (Leading/Improving/Weakening/Lagging).

**Public API:**
```python
class MacroSnapshotEngine:
    def __init__(self, polygon_key: str, fred_key: str = None, cache_dir: str = "data/macro_cache")
    def prefetch_all_data(self, start_date: date, end_date: date) -> None
    def prefetch_prices(self, tickers: List[str], start_date: date, end_date: date) -> None
    def prefetch_fred(self, start_date: date, end_date: date) -> None
    def generate_snapshot(self, as_of_date: date) -> Dict
    def save_to_db(self, snap: Dict, db_path: str = None) -> None
    def refresh_price_cache(self, days_back: int = 20) -> None
    def refresh_fred_cache(self) -> None
    def close(self) -> None
```

**Dependencies:** `requests`, `pandas`, `numpy`, `sqlite3`, `logging`
**Data sources:** Polygon REST API (prices), FRED public CSV (macro). Zero synthetic.

---

#### `compass/macro_db.py` (~570 lines)

**Source:** `shared/macro_state_db.py` — moved as-is.

**What it does:** SQLite persistence for COMPASS data. Five tables: `snapshots`, `sector_rs`, `macro_score`, `macro_events`, `macro_state`. Provides integration API for live trading and backtesting.

**Public API:**
```python
def get_db(path: str = None) -> sqlite3.Connection
def init_db(path: str = None) -> None
def migrate_db(path: str = None) -> None
def wal_checkpoint(path: str = None) -> None
def save_snapshot(snap: dict, db_path: str = None) -> None
def set_state(key: str, value: str, db_path: str = None) -> None
def get_state(key: str, default: str = None, db_path: str = None) -> Optional[str]
def upsert_events(events: List[Dict], db_path: str = None) -> None
def get_current_macro_score(db_path: str = None, max_staleness_days: int = 10) -> float
def get_sector_rankings(db_path: str = None) -> List[Dict]
def get_event_scaling_factor(db_path: str = None) -> float
def get_eligible_underlyings(regime: str = "NEUTRAL", db_path: str = None) -> List[str]
def get_latest_snapshot_date(db_path: str = None) -> Optional[str]
def get_snapshot_count(db_path: str = None) -> int
def backfill_macro_score_velocities(db_path: str = None) -> int
```

**Dependencies:** `sqlite3`, `json`, `logging`, `shared.constants`
**Data sources:** SQLite database at `data/macro_state.db` (WAL mode).

---

#### `compass/events.py` (~338 lines)

**Source:** `shared/macro_event_gate.py` — moved as-is.

**What it does:** Deterministic event calendar for FOMC, CPI, and NFP releases. Computes position-size scaling factors (0.50-1.00x) based on proximity to macro events. Includes post-event buffers.

**Public API:**
```python
# Constants
ALL_FOMC_DATES: Set[date]
FOMC_SCALING: Dict[int, float]   # days_out → scaling factor
CPI_SCALING: Dict[int, float]
NFP_SCALING: Dict[int, float]

def get_upcoming_events(as_of: date = None, horizon_days: int = 14) -> List[Dict]
def compute_composite_scaling(events: List[Dict]) -> float
def run_daily_event_check(as_of: date = None, db_path: str = None) -> Tuple[float, List[Dict]]
```

**Dependencies:** `datetime`, `logging`
**Data sources:** Hardcoded FOMC dates (2020-2026), algorithmic CPI/NFP dates. No external API.
**Maintenance:** Requires annual FOMC date update each December.

---

#### `compass/risk_gate.py` (~359 lines)

**Source:** `alerts/risk_gate.py` — moved as-is.

**What it does:** Enforces 10+ risk rules before trade execution. Core rules (0-7) cover circuit breakers, per-trade risk caps, exposure limits, loss limits, cooldowns, drawdown CB, VIX gate. COMPASS rules (8-10) add macro sizing flags, RRG quadrant filtering, and portfolio limits.

**Public API:**
```python
class RiskGate:
    def __init__(self, config: dict = None)
    def check(self, alert: Alert, account_state: dict) -> Tuple[bool, str]
    def weekly_loss_breach(self, account_state: dict) -> bool
```

**Dependencies:** `alerts.alert_schema`, `shared.constants`, `logging`, `datetime`

---

#### `compass/features.py` (~500 lines)

**Source:** `ml/feature_engine.py` (565 lines) — refactored. Synthetic fallback defaults removed and replaced with explicit None + skip logic. yfinance calls replaced with IronVault data source.

**What it does:** Builds ~35 numerical features per trade for ML signal model. Categories: technical (RSI, MACD, Bollinger, ATR, returns, MA distances), volatility (realized vol, IV rank/percentile, skew), market (VIX, SPY momentum), seasonal (day-of-week, OPEX, month-end), regime (one-hot encoded), and derived (vol premium, risk-adjusted momentum).

**Public API:**
```python
class FeatureEngine:
    def __init__(self, data_provider=None)     # IronVault or DataCache
    def build_features(self, ticker: str, current_price: float,
                       options_chain: pd.DataFrame = None,
                       regime_data: dict = None,
                       iv_analysis: dict = None) -> Optional[Dict]
    def compute_market_features(self) -> Optional[Dict]
    def get_feature_names(self) -> List[str]
```

**Key change from current:** `build_features()` returns `None` (not synthetic defaults) when data is unavailable. Caller must handle None = skip trade. This enforces the "cache miss = skip trade" directive.

**Dependencies:** `pandas`, `numpy`, IronVault (or DataCache), `shared.indicators`

---

#### `compass/signal_model.py` (~620 lines)

**Source:** `ml/signal_model.py` (771 lines) — cleaned. `generate_synthetic_training_data()` method (~150 lines) deleted. Synthetic fallback initialization path removed; hard-fails if no trained model exists.

**What it does:** XGBoost binary classifier predicting trade profitability. Calibrated probability output (0.0-1.0). Feature distribution drift monitoring (3-sigma alerts). Thread-safe prediction with fallback counting. Path traversal protection on model load.

**Public API:**
```python
class SignalModel:
    def __init__(self, model_dir: str = "compass/models")
    def train(self, features_df: pd.DataFrame, labels: np.ndarray,
              calibrate: bool = True, save_model: bool = True) -> Dict
    def predict(self, features: Dict) -> PredictionResult
    def predict_batch(self, features_df: pd.DataFrame) -> np.ndarray
    def backtest(self, features_df: pd.DataFrame, labels: np.ndarray) -> Dict
    def load(self, filename: str = None) -> bool
    def save(self, filename: str) -> None
    def get_fallback_stats(self) -> Dict[str, int]
```

**Dependencies:** `xgboost` (optional), `sklearn`, `joblib`, `numpy`, `pandas`, `threading`

---

#### `compass/iv_surface.py` (~416 lines)

**Source:** `ml/iv_analyzer.py` — refactored to use IronVault options chain data instead of yfinance approximations.

**What it does:** IV surface structure analysis: put-call skew metrics, term structure slope (contango/backwardation), IV rank and percentile (52-week). Generates directional signals (bull_put_favorable, bear_call_favorable).

**Public API:**
```python
class IVAnalyzer:
    def __init__(self, lookback_days: int = 252, data_provider=None)
    def analyze_surface(self, ticker: str, options_chain: pd.DataFrame,
                        current_price: float) -> Dict
```

**Dependencies:** `pandas`, `numpy`, IronVault (or DataCache), `shared.indicators`

---

#### `compass/sizing.py` (~120 lines)

**Source:** Extracted from `ml/position_sizer.py` (557 lines). Only the two utility functions that are actually used in production.

**What it does:** Computes per-trade risk budget based on IV rank and portfolio heat cap. Converts dollar risk to contract count.

**Public API:**
```python
def calculate_dynamic_risk(account_value: float, iv_rank: float,
                           current_portfolio_risk: float,
                           flat_risk_pct: float = None,
                           max_risk_pct: float = None) -> float

def get_contract_size(trade_dollar_risk: float, spread_width: float,
                      credit_received: float, max_contracts: int = 5) -> int
```

**Dependencies:** `logging`

---

#### `compass/collect_training_data.py` (~687 lines)

**Source:** `ml/collect_training_data.py` — updated to run both EXP-400 and EXP-401 configs.

**What it does:** Runs portfolio backtests and extracts trade-level features for ML training. Enriches each closed trade with 39 market-context features at entry time. Outputs chronologically-ordered CSV with no shuffling.

**Public API:**
```python
def load_champion_params() -> Dict
def run_year_backtest(year: int) -> Tuple[PortfolioBacktester, Dict]
def enrich_trades(bt: PortfolioBacktester, year: int) -> List[Dict]
def generate_feature_analysis(df: pd.DataFrame) -> str
def main()
```

**Dependencies:** `engine.portfolio_backtester`, `strategies`, `pandas`, `numpy`, `yfinance`

---

### 1.3 Dependency Graph

```
                     ┌──────────────────┐
                     │    IronVault     │  data/options_cache.db (905 MB)
                     │   (singleton)    │  data/macro_state.db
                     └────────┬─────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                     ▼
  ┌──────────────┐   ┌───────────────┐    ┌────────────────┐
  │ compass/     │   │ compass/      │    │ compass/       │
  │ regime.py    │   │ macro.py      │    │ features.py    │
  │ (VIX+trend)  │   │ (Polygon+FRED)│    │ (tech+vol+IV)  │
  └──────┬───────┘   └───────┬───────┘    └────────┬───────┘
         │                    │                     │
         │            ┌───────┴───────┐             │
         │            ▼               ▼             │
         │    ┌──────────────┐ ┌────────────┐       │
         │    │ compass/     │ │ compass/   │       │
         │    │ macro_db.py  │ │ events.py  │       │
         │    └──────────────┘ └─────┬──────┘       │
         │                           │              │
         └────────────┬──────────────┘              │
                      ▼                             ▼
              ┌──────────────┐             ┌──────────────┐
              │ MarketSnapshot│             │ compass/     │
              │ (strategies/) │             │ signal_model │
              └──────┬───────┘             └──────┬───────┘
                     │                            │
                     ▼                            ▼
              ┌──────────────┐             ML confidence
              │  Strategy    │             gate (optional)
              │ .generate()  │                    │
              └──────┬───────┘                    │
                     │◄───────────────────────────┘
                     ▼
              ┌──────────────┐   ┌──────────────┐
              │ regime_scale │ × │ event_scale  │ = FINAL SIZE
              │ (strategy)   │   │ (events.py)  │
              └──────────────┘   └──────────────┘
                                        │
                                        ▼
                                 ┌──────────────┐
                                 │ compass/     │
                                 │ risk_gate.py │
                                 └──────┬───────┘
                                        │
                                        ▼
                                  EXECUTE TRADE
```

### 1.4 Import Tree

```
compass/__init__.py
├── compass.regime          → pandas, enum, logging
├── compass.macro           → requests, pandas, numpy, sqlite3, logging
│   └── compass.macro_db    → sqlite3, json, logging, shared.constants
├── compass.events          → datetime, logging
│   └── compass.macro_db    (deferred import in run_daily_event_check)
├── compass.risk_gate       → alerts.alert_schema, shared.constants, logging, datetime
├── compass.features        → pandas, numpy, shared.indicators, IronVault
├── compass.signal_model    → xgboost (optional), sklearn, joblib, numpy, pandas, threading
├── compass.iv_surface      → pandas, numpy, shared.indicators, IronVault
├── compass.sizing          → logging
└── compass.collect_training_data → engine.portfolio_backtester, strategies, pandas, numpy
```

No circular dependencies. `compass.macro_db` is imported lazily in `compass.events` to avoid import-time cycles.

---

## 2. INSTITUTIONAL-GRADE SCORING

Scale: 1-10, where 1=non-functional, 5=works-but-fragile, 7=production-acceptable, 9=institutional-grade, 10=perfect.

### 2.1 Module Scorecards

#### `compass/macro.py` (MacroSnapshotEngine)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **8** | Clean architecture. Per-call DB connections (E1 fix). Retry strategy with jitter. 15+ magic numbers for piecewise scoring should be named constants. Circular import workaround in `generate_snapshot()`. |
| Test Coverage | **7** | Tested via `test_compass_scanner.py` (25 tests) and `test_macro_state_db.py` (20 tests). No direct unit tests for snapshot generation or FRED fetching. Network-dependent paths tested via mocks only. |
| Data Integrity | **9** | Real data only (Polygon + FRED). RELEASE_LAG_DAYS prevents lookahead. NaN→50.0 neutral fallback. Staleness detection. Forward-fill documented as known limitation. |
| Production Readiness | **9** | Thread-safe. Resilient HTTP retry (4 attempts, 429/5xx). 5s connect / 30s read timeout. Rate limiting (4 req/s). Graceful degradation on API downtime. |
| Integration Maturity | **8** | Integrated into main.py (live), backtester (backtest), risk_gate (rules 8-10). save_to_db() bridges to persistence layer. |
| Documentation | **6** | Module docstring exists. Individual method docs are sparse. Scoring breakpoints undocumented. No usage examples. |

**Overall Grade: B+ (7.8 avg)**
Production-ready. Main gaps: magic number cleanup and API documentation.

---

#### `compass/macro_db.py` (Persistence Layer)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **8** | WAL mode, idempotent migrations, per-call connections. Velocity logic duplicated in `save_snapshot()` and `backfill_macro_score_velocities()`. Regime boundary thresholds (65/45) are magic numbers. |
| Test Coverage | **8** | 20 tests in `test_macro_state_db.py`. Covers CRUD, velocity, rankings, eligibility. Uses real in-memory SQLite. Good edge case coverage. |
| Data Integrity | **8** | WAL mode prevents corruption. Busy timeout 5s. Foreign keys ON. Staleness warning at 10 days. First-row velocity = 0.0 (documented edge case). |
| Production Readiness | **8** | Auto-checkpoint (1000 pages). Explicit `wal_checkpoint()` for long-running processes. Per-call connections (thread-safe). Schema versioning with migrations. |
| Integration Maturity | **9** | Used by macro engine, event gate, risk gate, main.py, backtester. Central persistence layer for all COMPASS state. |
| Documentation | **5** | Schema defined in code but no external schema doc. Function signatures clear. No usage examples. |

**Overall Grade: B+ (7.7 avg)**
Solid persistence layer. Needs schema documentation and velocity logic deduplication.

---

#### `compass/events.py` (Event Calendar)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **7** | Pure functions (stateless). G4/G5/G7 fixes applied. Logger imported but unused. Manual date arithmetic instead of dateutil. Post-event buffer logic could be cleaner. |
| Test Coverage | **4** | No dedicated test file. Tested only indirectly via `test_macro_state_db.py` (upsert_events). Event scaling logic, CPI/NFP date generation, and composite scoring are untested. |
| Data Integrity | **7** | Deterministic (no external data). FOMC dates hardcoded (accurate through 2026). CPI approximation (12th ± weekends) may differ from actual BLS schedule by ±3 days. |
| Production Readiness | **7** | No external dependencies. Post-event buffers (G5). Per-event-type minimums (G4). Requires annual FOMC update (manual process). |
| Integration Maturity | **7** | `run_daily_event_check()` persists to macro_db. Scaling factor read by risk_gate and backtester. Not yet integrated into PortfolioBacktester (only legacy backtester). |
| Documentation | **4** | Scaling tables in code but no module docstring. FOMC date maintenance process undocumented. No examples. |

**Overall Grade: B- (6.0 avg)**
Functional but under-tested and under-documented. Biggest gap: zero dedicated tests.

---

#### `compass/risk_gate.py` (Risk Rules)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **7** | Well-structured sequential rule evaluation. Comprehensive logging (warning for every block). Deep nested `.get()` chains reduce readability. BUG #19 comment indicates known issue. No try/except — datetime parsing unprotected. |
| Test Coverage | **8** | 25 tests in `test_risk_gate_macro.py`. Good coverage of COMPASS rules 8-10. Backward compatibility tested. |
| Data Integrity | **7** | No data fetching (pure rule evaluation). Relies on caller-provided `account_state`. No validation of account_state schema. |
| Production Readiness | **8** | All COMPASS rules are opt-in (backward compatible). Kill switch pattern (config absent = rules off). Informational logging. |
| Integration Maturity | **9** | Called from main.py scan cycle, backtester entry logic. Already handles all 3 COMPASS capabilities (sizing flags, RRG filter, portfolio limits). |
| Documentation | **5** | Rules numbered and commented inline. No external documentation of rule semantics or interaction effects. |

**Overall Grade: B (7.3 avg)**
Well-integrated and well-tested. Needs code cleanup (nested gets, BUG #19) and external documentation.

---

#### `compass/regime.py` (Enhanced RegimeClassifier)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **6** | Current `engine/regime.py`: clean but all VIX thresholds hardcoded (40, 30, 25, 20, 15, 22, 18 scattered through classify()). Zero logging. Ad-hoc fallback cascade. After enhancement: configurable thresholds, hysteresis, logging → estimated 7.5. |
| Test Coverage | **2** | **ZERO tests** for `engine/regime.py` — the module that drives ALL regime-adaptive sizing in the champion strategy. ComboRegimeDetector has 8 tests, but that module is being absorbed, not tested directly. |
| Data Integrity | **7** | Uses only VIX + price data (real, from IronVault/yfinance). Implicit lookahead protection via MA lag. After enhancement: explicit shift-by-1. |
| Production Readiness | **5** | Works in backtester (proven by Phase 4 results). But: no error handling, no logging, no config-driven thresholds, no hysteresis. Brittle in live trading where data quality varies. |
| Integration Maturity | **8** | Consumed by PortfolioBacktester → MarketSnapshot → all 3 strategies (CS, IC, SS). Central to regime-adaptive sizing (the feature that makes the champion work). |
| Documentation | **5** | Module docstring lists VIX thresholds. No API docs. Regime semantics undocumented beyond enum labels. |

**Overall Grade: C+ (5.5 avg) → B (7.0 target after enhancement)**
Critical module with zero test coverage. Enhancement plan adds tests, logging, configurable thresholds, and hysteresis. The current 5.5 is a red flag; post-enhancement target is 7.0.

---

#### `compass/signal_model.py` (XGBoost Classifier)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **8** | Well-architected: calibrated probabilities, feature drift monitoring (3-sigma), thread-safe prediction lock, fallback counting with critical alerts at 10, path traversal protection (SEC-DATA-03). After cleanup: remove synthetic generation method. |
| Test Coverage | **6** | 10 tests in `test_signal_model.py`. Covers train/predict/load/save, calibration. Missing: edge cases for noisy data, model corruption, extreme probabilities. |
| Data Integrity | **3** | **CRITICAL: Current model trained on synthetic data.** `generate_synthetic_training_data()` creates fake feature distributions with rule-based labels. Violates "no synthetic data" directive. After cleanup + retrain on real data: estimated 7. |
| Production Readiness | **7** | Model staleness warning (30 days). Feature drift detection. Graceful fallback on prediction failure. After removing synthetic path: hard-fail on missing model (correct behavior). |
| Integration Maturity | **3** | **Currently disconnected.** No strategy, backtester, or paper trader calls `predict()`. After integration via MLEnhancedStrategy wrapper: estimated 7. |
| Documentation | **6** | Good inline comments. PredictionResult type documented. Feature importance logging. No external API docs or usage guide. |

**Overall Grade: C+ (5.5 avg) → B (7.2 target after cleanup + retrain + integration)**
Good architecture hamstrung by synthetic data and zero integration. Needs retrain on ~350 real trades + MLEnhancedStrategy wrapper.

---

#### `compass/features.py` (Feature Engineering)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **6** | Comprehensive 47-feature builder. But: yfinance called per-feature-group (inefficient), `put_call_ratio` hardcoded to 1.0 (placeholder), multiple synthetic fallback defaults (RSI=50, vol=20%, IV=50%). After refactor: IronVault data source, None-on-miss. |
| Test Coverage | **7** | 14 tests in `test_feature_engine.py`. Good coverage of technical, volatility, market features. Uses mocks for yfinance. |
| Data Integrity | **4** | **Multiple synthetic fallbacks:** vol=20.0%, IV_rank=50.0%, put_call_ratio=1.0 when data unavailable. Violates "cache miss = skip trade" directive. After refactor: None return (estimated 8). |
| Production Readiness | **5** | Works as standalone builder. But: downloads data fresh every call (no caching), yfinance not suitable for production (rate limits, reliability). After IronVault wiring: estimated 8. |
| Integration Maturity | **4** | Used only by ml_pipeline (dead code path) and collect_training_data. Not wired into backtester or paper trader. After integration: estimated 7. |
| Documentation | **6** | Feature names documented. Category breakdown clear. No description of what each feature means or why it's predictive. |

**Overall Grade: C+ (5.3 avg) → B (7.2 target after refactor + IronVault)**
Solid feature catalog, but data integrity violations must be fixed before production use.

---

#### `compass/iv_surface.py` (IV Analysis)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **7** | Clean structure: skew, term structure, IV rank computed independently. Signal generation combines all three. 24-hour cache. Moneyness filtering. Skew ratio edge cases handled. Uses HV as IV proxy (known limitation). |
| Test Coverage | **8** | 19 tests in `test_iv_analyzer.py`. Excellent edge case coverage: empty chains, missing IV column, short history, skew detection, term structure classification. |
| Data Integrity | **5** | Uses historical vol (HV) as IV proxy — different from actual implied volatility. 25-delta approximated at ±10% strikes (not true delta-25). After IronVault wiring with real IV data: estimated 8. |
| Production Readiness | **6** | 24-hour cache. Graceful fallback to default analysis. But: yfinance for historical data, HV≠IV approximation. After refactor: estimated 8. |
| Integration Maturity | **4** | Used only by ml_pipeline (dead code path). Feeds into feature engineering. Not directly consumed by strategies. |
| Documentation | **7** | Output dict well-documented in code. Signal generation logic clear. skew_ratio thresholds explained. |

**Overall Grade: B- (6.2 avg) → B+ (7.5 target after IronVault refactor)**
Well-tested, well-documented. Main gap: real IV data instead of HV proxy.

---

#### `compass/sizing.py` (Position Sizing Utilities)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **7** | Two clean utility functions. IV-rank tiered sizing with portfolio heat cap. Contract size calculation with max_loss protection. Hardcoded 2% base risk and 40% heat cap. |
| Test Coverage | **5** | 7 tests in `test_position_sizer.py`, but these test the PositionSizer class (being killed). The two utility functions have indirect coverage via backtester tests. No dedicated tests for `calculate_dynamic_risk()` or `get_contract_size()`. |
| Data Integrity | **8** | No external data — purely algorithmic. Inputs validated (trade_dollar_risk, spread_width, credit). |
| Production Readiness | **8** | Used in production by backtester and alert system. Conservative defaults. Max contracts cap prevents runaway sizing. |
| Integration Maturity | **9** | Called by `backtest/backtester.py` and `alerts/alert_position_sizer.py`. Well-established production usage. |
| Documentation | **5** | IV-rank tiers documented in code comments. No external docs. |

**Overall Grade: B (7.0 avg)**
Simple, proven utilities. Needs dedicated tests and documentation.

---

#### `compass/collect_training_data.py` (Data Harvester)

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Code Quality | **6** | Functional-style (not class-based). Multiple standalone helper functions. Minimal error handling (logs warning, continues with None). Hardcoded year range (2018-2026). |
| Test Coverage | **3** | **No dedicated tests.** Validated only by running it and inspecting output. Feature enrichment logic (39 features) completely untested. |
| Data Integrity | **7** | Uses real backtest outcomes (not synthetic labels). Enriches with market context from real data. VIX percentile defaults to 50% with <10 samples (data quality masked). |
| Production Readiness | **5** | Works as offline script. Not designed for automated pipeline. Hardcoded paths. No progress reporting beyond print statements. |
| Integration Maturity | **5** | Standalone script. Produces `training_data.csv` consumed by signal_model training. Needs update for EXP-401 config support. |
| Documentation | **5** | Feature analysis output is good. Script itself has minimal inline docs. |

**Overall Grade: C+ (5.2 avg)**
Essential pipeline tool. Needs tests, error handling, and EXP-401 config support.

---

### 2.2 Overall COMPASS Platform Grade

| Category | Avg Score (Current) | Avg Score (Post-Merge Target) |
|----------|--------------------|-----------------------------|
| Code Quality | 7.0 | 7.5 |
| Test Coverage | 5.8 | 7.5 |
| Data Integrity | 6.5 | 8.0 |
| Production Readiness | 6.8 | 8.0 |
| Integration Maturity | 6.6 | 7.8 |
| Documentation | 5.4 | 6.5 |

**Current Platform Grade: B- (6.4 avg)**
**Post-Merge Target Grade: B+ (7.6 avg)**

The platform is architecturally sound but dragged down by three issues: (1) zero tests on the critical regime classifier, (2) synthetic data contamination in ML modules, and (3) ML pipeline completely disconnected from production. The merge plan addresses all three.

---

## 3. GAP ANALYSIS — WHAT'S MISSING TO REACH INSTITUTIONAL GRADE

### 3.1 Per-Module Gaps to Grade A

| Module | Current | Target | Gap | What Closes It |
|--------|---------|--------|-----|----------------|
| `macro.py` | B+ | A- | Name magic numbers (15+ scoring thresholds). Add unit tests for snapshot generation. Add module-level API docs. | 1 day |
| `macro_db.py` | B+ | A- | Deduplicate velocity logic. Document schema externally. Add transaction wrapping for batch inserts. | 0.5 day |
| `events.py` | B- | B+ | Write 10+ dedicated tests. Add module docstring. Document FOMC update process. Fix unused logger. | 1 day |
| `risk_gate.py` | B | B+ | Fix BUG #19. Add try/except around datetime parsing. Extract nested `.get()` chains to helper. Document rule semantics. | 0.5 day |
| `regime.py` | C+ | B+ | **Write 15+ tests.** Add configurable thresholds. Add hysteresis (10-day cooldown). Add RSI + VIX term structure signals. Add debug logging. | 2 days |
| `signal_model.py` | C+ | B+ | **Delete synthetic data method.** Retrain on ~350 real trades. Wire into MLEnhancedStrategy. Add edge case tests. | 3 days |
| `features.py` | C+ | B+ | **Replace yfinance → IronVault.** Remove all synthetic fallback defaults (return None on miss). Add feature caching across batch. | 2 days |
| `iv_surface.py` | B- | B+ | Wire to IronVault options chain for real IV (not HV proxy). Add real delta-25 strike lookup. | 1 day |
| `sizing.py` | B | B+ | Write 5+ dedicated tests for both utility functions. Document IV-rank tiers and heat cap. | 0.5 day |
| `collect_training_data.py` | C+ | B | Write 8+ tests for feature enrichment. Add EXP-401 config support. Add error handling. Remove hardcoded year range. | 1.5 days |

### 3.2 Priority-Ordered Remediation List

| Priority | Gap | Effort | Impact | Modules |
|----------|-----|--------|--------|---------|
| **P0** | Add tests for regime classifier | 1 day | Critical — untested module drives all champion sizing | regime.py |
| **P1** | Delete synthetic data artifacts | 0.5 day | Compliance — violates core directive | signal_model.py, models/ |
| **P2** | Remove synthetic fallback defaults | 1 day | Data integrity — features return garbage when data missing | features.py |
| **P3** | Write event calendar tests | 1 day | Safety — event scaling modifies live position sizes untested | events.py |
| **P4** | Wire IronVault into feature engine | 1.5 days | Production requirement — yfinance unsuitable for live trading | features.py, iv_surface.py |
| **P5** | Enhance regime classifier | 1.5 days | Quality — adds hysteresis, configurable thresholds, logging | regime.py |
| **P6** | Retrain ML on real data | 2 days | ML enablement — current model is useless | signal_model.py, collect_training_data.py |
| **P7** | Fix risk_gate BUG #19 + datetime parsing | 0.5 day | Robustness — known bug + unhandled exception | risk_gate.py |
| **P8** | Name magic numbers in macro scoring | 0.5 day | Maintainability — 15+ unnamed thresholds | macro.py |
| **P9** | Document all modules | 1 day | Knowledge transfer — sparse docs across all modules | all |

**Total remediation effort: ~11 days**

---

## 4. EXECUTION PLAN

### Phase 1: CLEAN (Days 1-2)

**Objective:** Remove dead code, fix bugs, enforce data integrity.

| Task | Files | Lines Removed | Dependency | Deliverable |
|------|-------|---------------|------------|-------------|
| Delete `ml/regime_detector.py` | 1 file | 417 | None | File deleted |
| Delete `strategy/market_regime.py` | 1 file | 402 | None | File deleted |
| Delete `shared/vix_regime.py` | 1 file | 97 | None | File deleted |
| Delete `ml/sentiment_scanner.py` | 1 file | 547 | None | File deleted |
| Delete `ml/ml_pipeline.py` | 1 file | 633 | None | File deleted |
| Delete `ml/models/signal_model_20260305.joblib` | 1 file | — | None | Synthetic model purged |
| Delete `ml/models/signal_model_20260305.feature_stats.json` | 1 file | — | None | Companion artifact purged |
| Remove `generate_synthetic_training_data()` from `ml/signal_model.py` | Method | ~150 | None | Synthetic code path eliminated |
| Update `ml/__init__.py` to remove dead exports | 1 file | ~15 | Above deletions | Clean package exports |
| Standardize regime labels: ComboRegimeDetector outputs → lowercase | 1 file | 0 (edit) | None | Case mismatch bug fixed |
| Fix `main.py` fallback from `'BULL'` to `'neutral'` | 1 file | 0 (edit) | None | Optimistic bias bug fixed |
| Fix `risk_gate.py` BUG #19 + wrap datetime parsing in try/except | 1 file | 0 (edit) | None | Known bugs resolved |

**Exit Criteria:**
- `PYTHONPATH=. python3 -m pytest tests/ -v --ignore=tests/run_phase*.py` passes (all existing tests green)
- `grep -r "generate_synthetic" ml/` returns zero results
- `grep -r "import.*ml.regime_detector\|import.*ml.sentiment_scanner\|import.*ml.ml_pipeline\|import.*vix_regime\|import.*market_regime" .` returns zero results (excluding tests for deleted modules)
- No `.joblib` files in `ml/models/`

**Total: ~2,261 lines deleted + 4 bug fixes. Zero functional regression.**

---

### Phase 2: CONSOLIDATE (Days 3-5)

**Objective:** Create `compass/` package, move files, update all imports.

| Task | From | To | Import Updates |
|------|------|----|----------------|
| Create `compass/` directory + `__init__.py` | — | `compass/__init__.py` | — |
| Move macro snapshot engine | `shared/macro_snapshot_engine.py` | `compass/macro.py` | main.py, backtester, scripts |
| Move macro state DB | `shared/macro_state_db.py` | `compass/macro_db.py` | main.py, backtester, events.py, risk_gate |
| Move event gate | `shared/macro_event_gate.py` | `compass/events.py` | main.py, macro_db |
| Move risk gate | `alerts/risk_gate.py` | `compass/risk_gate.py` | main.py, backtester |
| Enhance + move regime classifier | `engine/regime.py` | `compass/regime.py` | portfolio_backtester, strategies |
| Move signal model | `ml/signal_model.py` | `compass/signal_model.py` | (new consumers after Phase 3) |
| Refactor + move feature engine | `ml/feature_engine.py` | `compass/features.py` | collect_training_data |
| Refactor + move IV analyzer | `ml/iv_analyzer.py` | `compass/iv_surface.py` | (new consumers after Phase 3) |
| Extract sizing utilities | `ml/position_sizer.py` | `compass/sizing.py` | backtester, alert_position_sizer |
| Move training data collector | `ml/collect_training_data.py` | `compass/collect_training_data.py` | standalone script |
| Absorb ComboRegimeDetector into regime.py | `ml/combo_regime_detector.py` | merged into `compass/regime.py` | main.py, strategy/spread_strategy |
| Leave compatibility shims (1 release) | — | Old paths re-export from compass/ | Prevents import breakage |

**Exit Criteria:**
- All tests pass with new import paths
- `from compass import RegimeClassifier, MacroSnapshotEngine, RiskGate` works
- `from compass.macro_db import get_current_macro_score` works
- Legacy `from shared.macro_state_db import ...` still works (via shim, one release only)
- Full backtester run produces identical results to pre-consolidation

**Note:** Do this on a dedicated branch. Run full test suite + one backtester regression run before merging.

---

### Phase 3: ENHANCE (Days 6-12)

**Objective:** Add tests, wire IronVault, retrain ML.

| Task | Effort | Dependencies | Deliverable |
|------|--------|--------------|-------------|
| **Write 15+ tests for compass/regime.py** | 1 day | Phase 2 | `tests/test_regime_classifier.py` — VIX thresholds, hysteresis, crash override, classify_series, edge cases |
| **Write 10+ tests for compass/events.py** | 1 day | Phase 2 | `tests/test_event_gate.py` — FOMC/CPI/NFP dates, scaling, composite, post-event buffers |
| **Write 5+ tests for compass/sizing.py** | 0.5 day | Phase 2 | Tests for `calculate_dynamic_risk()` and `get_contract_size()` |
| **Wire IronVault into features.py** | 1.5 days | Phase 2 | Replace yfinance calls with IronVault data source. Return None on cache miss. |
| **Wire IronVault into iv_surface.py** | 0.5 day | Phase 2 | Use IronVault options chain for real IV data |
| **Update collect_training_data.py for EXP-401** | 0.5 day | Phase 2 | Support both EXP-400 and EXP-401 configs |
| **Harvest EXP-401 training data (353 trades)** | 0.5 day | Above | `compass/training_data_exp401.csv` |
| **Merge + dedup EXP-400 + EXP-401 datasets** | 0.5 day | Above | `compass/training_data_combined.csv` (~350-400 trades) |
| **Feature engineering: add new, drop dead** | 0.5 day | Above | Credit-to-width ratio, regime duration, VIX change 5d. Drop spread_width, vix_percentiles, ma_slopes. |
| **Train XGBoost with anchored walk-forward** | 1 day | Above | 3-fold CV (train 2020-22→test 2023, etc.). Evaluate G1-G4 gates. |
| **If G1-G4 pass: implement MLEnhancedStrategy wrapper** | 1 day | Above | Wrapper in strategies that filters signals via signal_model.predict() |
| **Name magic numbers in macro.py** | 0.5 day | Phase 2 | Named constants for all 15+ scoring thresholds |
| **Write 8+ tests for collect_training_data.py** | 0.5 day | Phase 2 | Test feature enrichment, year splitting, VIX percentile computation |

**Exit Criteria:**
- `tests/test_regime_classifier.py`: 15+ tests, all green
- `tests/test_event_gate.py`: 10+ tests, all green
- `tests/test_sizing.py`: 5+ tests, all green
- `compass/features.py`: zero `yfinance` imports, zero synthetic fallback defaults
- `compass/training_data_combined.csv`: ~350-400 rows with 35+ features
- ML model evaluation report: AUC per fold, calibration error, feature importance stability
- **Decision point: G1-G4 gates determine if ML integration proceeds**

---

### Phase 4: VALIDATE (Days 13-16)

**Objective:** Prove the unified COMPASS doesn't break the champion strategy, then test enhancements.

| Task | Effort | Dependencies | Deliverable |
|------|--------|--------------|-------------|
| **Regression backtest: COMPASS-off** | 0.5 day | Phase 2 | Verify identical results to pre-merge EXP-401 baseline (+40.7% avg, 6/6, -7.0% DD) |
| **COMPASS A/B tests: C-001 through C-003** | 1 day | Phase 3 | Macro sizing (C-001), RRG filter (C-002), combined (C-003) vs baseline |
| **Evaluate COMPASS hard gates (H1-H4)** | 0.5 day | Above | ROBUST ≥ 0.90, 6/6 profitable, trade count ≥ 250, 2022 ≥ +5.0% |
| **If ML G1-G4 passed: ML backtest M-001 through M-005** | 1 day | Phase 3 | Confidence threshold sweep (0.40-0.60), evaluate G5-G9 |
| **If best-C and best-M exist: Combined test X-003** | 0.5 day | Above | Combined return ≥ max(C, M), DD ≤ min(C, M) |
| **Full ROBUST validation of winner** | 0.5 day | Above | Walk-forward 3/3, Monte Carlo 10K, slippage, tail risk |
| **Register winning config as EXP-502** | 0.5 day | Above | Entry in MASTERPLAN.md experiment registry |

**Exit Criteria (per champion_improvement_proposal.md):**
- Regression backtest: ±0.1% of baseline (floating-point tolerance only)
- Winner config: ROBUST ≥ 0.90, 6/6 years profitable
- If no config improves on baseline: document negative result, keep EXP-401 as-is
- EXP-502 registered in MASTERPLAN.md with full year-by-year breakdown

---

### Phase 5: DEPLOY (Days 17-19)

**Objective:** Deploy unified COMPASS to paper trading.

| Task | Effort | Dependencies | Deliverable |
|------|--------|--------------|-------------|
| **Create paper_exp502.yaml config** | 0.5 day | Phase 4 | COMPASS-enabled paper trading config |
| **Update main.py imports to compass/** | 0.5 day | Phase 2 (should be done, verify) | Live scanner uses compass package |
| **Deploy paper trader with EXP-502 config** | 0.5 day | Above | launchd service running alongside EXP-400/401 |
| **Verify deviation tracker works with COMPASS** | 0.5 day | Above | `scripts/paper_trading_deviation.py` produces valid report |
| **Remove compatibility shims (old import paths)** | 0.5 day | 1 release cycle after Phase 2 | Clean imports, no legacy paths |
| **Update MEMORY.md with COMPASS architecture** | 0.5 day | All phases | Session memory reflects new structure |

**Exit Criteria:**
- Paper trader running with unified COMPASS package
- First deviation report generated successfully
- Old import shims removed
- 8-week validation clock starts

---

## 5. NORTH STAR METRICS

### 5.1 Platform Health Metrics (Post-Merge Monitoring)

| Metric | Measurement | Healthy Range | Alert Threshold |
|--------|-------------|---------------|-----------------|
| **Regime classification latency** | Time from market data → regime label | < 50ms | > 200ms |
| **Macro snapshot freshness** | Days since last successful snapshot | ≤ 7 days | > 10 days (triggers staleness warning) |
| **Event scaling accuracy** | Scaling factor matches expected for known events | 100% for FOMC (hardcoded) | Any FOMC date missed |
| **Feature engine coverage** | % of trades where all features are non-None | ≥ 95% | < 90% (IronVault cache gaps) |
| **ML model prediction rate** | Predictions / fallbacks per day | > 95% predictions | Fallback counter > 10 (triggers critical alert) |
| **ML model drift score** | Features within 3σ of training distribution | ≥ 90% of features | Any feature > 5σ consistently |
| **Test suite pass rate** | All COMPASS tests green | 100% | Any failure blocks merge |
| **Regime transition frequency** | Regime changes per month | 1-4 changes/month | > 8 (possible whipsaw) or 0 (possible stuck) |
| **Risk gate block rate** | % of signals blocked by risk rules | 5-20% | > 40% (over-filtering) or < 2% (rules not firing) |

### 5.2 Performance Targets

**Honest ranges based on data:**

| Metric | Current (EXP-401) | COMPASS-Only Target | COMPASS+ML Target | Stretch (Low Prob) |
|--------|-------------------|--------------------|--------------------|---------------------|
| Avg annual return | +40.7% | +41-43% | +43-46% | +47-50% |
| Worst annual DD | -7.0% | -6.0 to -7.0% | -5.0 to -6.5% | -4.0 to -5.0% |
| Sharpe ratio | ~2.96 | 3.0-3.2 | 3.2-3.5 | 3.5-4.0 |
| 2022 bear year | +8.1% | +8-10% | +10-13% | +15%+ |
| Years profitable | 6/6 | 6/6 (maintain) | 6/6 (maintain) | 6/6 |
| Win rate | ~83% | ~83-84% | 84-86% | 87%+ |
| ROBUST score | 0.951 | ≥ 0.90 | ≥ 0.90 | ≥ 0.95 |

**Why these are honest:**
- COMPASS sizing (0.85-1.20x) changes size by ≤ 20%, translating to ≤ 2-4pp return impact
- ML filter at ~50% confidence might reject 15-25% of trades. If those are disproportionately losers: +1-3pp
- Combined: +3-6pp over baseline, with diminishing returns from double-filtering
- Sharpe > 4.0 starts looking like overfitting. Do not target.
- DD < 4.0% requires near-perfect loss avoidance in bear markets — unrealistic with 350 training samples

### 5.3 Monitoring and Alerting Design

```
┌─────────────────────────────────────────────────┐
│                 COMPASS HEALTH DASHBOARD         │
├─────────────────────────────────────────────────┤
│                                                  │
│  REGIME: bull ● (last change: 12 days ago)       │
│  MACRO SCORE: 67.3 / 100 (NEUTRAL_MACRO)       │
│  EVENT SCALING: 1.00 (no upcoming events)        │
│  ML MODEL: loaded ● (trained 2026-03-18)        │
│    ├─ Predictions today: 5 / Fallbacks: 0       │
│    └─ Feature drift: 0/35 features > 3σ         │
│                                                  │
│  RISK GATE (last 24h):                           │
│    ├─ Signals evaluated: 8                       │
│    ├─ Passed: 6                                  │
│    ├─ Blocked (risk): 1 (exposure limit)        │
│    └─ Blocked (COMPASS): 1 (RRG filter)         │
│                                                  │
│  ALERTS:                                         │
│    ⚠ Macro snapshot 8 days old (update due)     │
│    ✓ All 179 tests passing                      │
│    ✓ Feature coverage: 97% (1/35 missing: VIX3M)│
│                                                  │
└─────────────────────────────────────────────────┘
```

**Alert channels (via Telegram, existing infrastructure):**

| Alert | Severity | Trigger | Action |
|-------|----------|---------|--------|
| Macro snapshot stale | WARNING | > 10 days since last snapshot | Run `MacroSnapshotEngine.generate_snapshot()` |
| ML model fallback spike | CRITICAL | > 10 fallbacks in 1 hour | Check IronVault data availability, restart if needed |
| ML feature drift | WARNING | Any feature > 5σ for > 3 consecutive predictions | Investigate data source, consider retrain |
| ML model stale | WARNING | Model age > 30 days | Evaluate if retrain needed (check AUC on recent data) |
| Regime stuck | INFO | Same regime for > 60 days | Review — likely valid (extended bull/bear), but verify classifier is receiving data |
| Risk gate blocking > 40% | WARNING | > 40% of signals blocked in 1 week | Review blocking reasons — may indicate market stress or misconfigured thresholds |
| FOMC dates need update | WARNING | December 1st each year | Update `FOMC_DATES_{YEAR+1}` in `compass/events.py` |

### 5.4 What Success Looks Like

**Minimum viable success (justifies the merge effort):**
- Unified `compass/` package with clean imports — no more 4 competing regime systems
- 2,246 lines of dead code eliminated
- 30+ new tests covering previously-untested critical paths (regime classifier, events, sizing)
- Synthetic data artifacts permanently purged
- ML model either retrained on real data with honest evaluation, or honestly declared infeasible

**Full success (justifies paper trading deployment):**
- At least one enhancement config (COMPASS or ML) passes all hard gates and at least one value criterion
- EXP-502 registered with ROBUST ≥ 0.90
- Paper trader running unified COMPASS alongside EXP-400/401

**The outcome we must be honest about:**
There is a ~25% chance that neither COMPASS nor ML meaningfully improves the champion. The champion is already a strong system at +40.7% avg with 0.951 ROBUST. Enhancement is upside exploration, not a rescue mission. A well-validated negative result (clean code, real data, honest evaluation, conclusion: "the rule-based system is sufficient") is a perfectly acceptable outcome of this work.

---

## APPENDIX A: Kill List (Files to Delete)

| File | Lines | Reason |
|------|-------|--------|
| `ml/regime_detector.py` | 417 | Unused HMM+RF regime detector |
| `strategy/market_regime.py` | 402 | Unused 7-regime legacy detector |
| `ml/sentiment_scanner.py` | 547 | Redundant with compass/events.py |
| `ml/ml_pipeline.py` | 633 | Orchestrator for dead code |
| `shared/vix_regime.py` | 97 | Never imported anywhere |
| `ml/signal_model.py` synthetic method | ~150 | Violates no-synthetic directive |
| `ml/models/signal_model_20260305.joblib` | — | Trained on synthetic data |
| `ml/models/signal_model_20260305.feature_stats.json` | — | Companion to synthetic model |
| **Total** | **~2,246 lines + 302KB artifacts** | |

## APPENDIX B: Test Inventory (Current State)

| Test File | Lines | Tests | Module Covered | Assessment |
|-----------|-------|-------|----------------|------------|
| `test_compass_scanner.py` | 595 | 25 | main.py COMPASS integration | GOOD |
| `test_risk_gate_macro.py` | 352 | 25 | alerts/risk_gate.py (rules 8-10) | GOOD |
| `test_macro_state_db.py` | 277 | 20 | shared/macro_state_db.py | GOOD |
| `test_signal_model.py` | 154 | 10 | ml/signal_model.py | PARTIAL |
| `test_feature_engine.py` | 210 | 14 | ml/feature_engine.py | GOOD |
| `test_iv_analyzer.py` | 364 | 19 | ml/iv_analyzer.py | EXCELLENT |
| `test_ml_pipeline.py` | 1011 | 29 | ml/ml_pipeline.py (being killed) | N/A after Phase 1 |
| `test_combo_regime_detector.py` | 308 | 8 | ml/combo_regime_detector.py | GOOD |
| `test_regime_detector.py` | 106 | 6 | ml/regime_detector.py (being killed) | N/A after Phase 1 |
| `test_sentiment_scanner.py` | 248 | 16 | ml/sentiment_scanner.py (being killed) | N/A after Phase 1 |
| `test_position_sizer.py` | 128 | 7 | ml/position_sizer.py | GOOD |
| **engine/regime.py** | — | **0** | **RegimeClassifier** | **NONE — CRITICAL GAP** |
| **shared/macro_event_gate.py** | — | **0** | **Event calendar + scaling** | **NONE — HIGH GAP** |
| **compass/sizing.py utilities** | — | **0** | **calculate_dynamic_risk, get_contract_size** | **NONE — MEDIUM GAP** |

**Post-merge tests to write:** ~30+ new tests across 3-4 new test files.

## APPENDIX C: Timeline Summary

```
           Week 1              Week 2              Week 3             Week 4
    ┌───────────────┐   ┌───────────────┐   ┌───────────────┐   ┌──────────────┐
    │ Phase 1: CLEAN│   │ Phase 3: ENH  │   │ Phase 4: VAL  │   │ Phase 5: DEP │
    │ (Days 1-2)    │   │ (Days 6-12)   │   │ (Days 13-16)  │   │ (Days 17-19) │
    │               │   │               │   │               │   │              │
    │ Delete 2,246  │   │ Write 30+ tests│   │ Regression test│   │ Paper config │
    │ lines dead    │   │ Wire IronVault │   │ COMPASS A/B   │   │ Deploy       │
    │ code          │   │ Retrain ML     │   │ ML sweep      │   │ Verify       │
    │ Fix 4 bugs    │   │ Enhance regime │   │ Combined test  │   │ Monitor      │
    │               │   │               │   │ ROBUST score   │   │              │
    ├───────────────┤   │ ML DECISION   │   │ Register       │   │ 8-week       │
    │ Phase 2: MOVE │   │ POINT: G1-G4  │   │ EXP-502       │   │ validation   │
    │ (Days 3-5)    │   │ pass/fail     │   │               │   │ starts       │
    │               │   │               │   │               │   │              │
    │ Create compass/│   │               │   │               │   │              │
    │ Move 10 files │   │               │   │               │   │              │
    │ Update imports │   │               │   │               │   │              │
    │ Regression run │   │               │   │               │   │              │
    └───────────────┘   └───────────────┘   └───────────────┘   └──────────────┘
```

**Total: 19 working days (4 weeks). ML decision point at Day 11.**
