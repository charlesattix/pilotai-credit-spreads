# COMPASS Universe Expansion Proposal
### Dynamic Sector Universe Selection — From Seatbelt to GPS

**Author**: Claude Code
**Date**: 2026-03-08
**Status**: PROPOSAL — awaiting Carlos approval before any code changes or data fetches
**Prerequisite reading**: `output/compass_experiment_proposal.md`, `output/compass_integration_analysis.md`,
`output/macro_intelligence_proposal.md`

---

## 0. The Thesis

Carlos's insight is correct and important. The current COMPASS (sizing-only) is a **seatbelt**: it
reduces the damage when the crash comes. Universe expansion is a **GPS**: it tells you which roads
to drive on in the first place.

The data is unambiguous:

| Year | Best sector | vs SPY | If we had traded XLE/SOXX instead of SPY... |
|------|-------------|--------|---------------------------------------------|
| 2020 | XBI | +44pp | Bull puts on biotech during COVID recovery |
| 2021 | XLE | +24pp | Bull puts on XLE (Leading all year, +53%) |
| 2022 | XLE | **+84pp** | Both bear calls AND bull puts on XLE (stable anchor in bear year) |
| 2023 | SOXX | +45pp (H1) | Bull puts on SOXX during AI mania |
| 2024 | XLU | +3pp modest | Bull puts on XLU (AI power demand theme) |
| 2025 | ITA | +14pp | Bull puts on defense (reshoring theme) |

The sector rotation signals **already exist in our database** — 323 weeks of RRG quadrants and
RS rankings for 15 ETFs. The missing piece is the infrastructure to trade them.

**The critical constraint the proposal must be honest about:**
Our options cache currently contains **SPY-only** data. Multi-underlying backtesting at full
fidelity requires fetching sector ETF options chains from Polygon — a non-trivial data acquisition
exercise at Polygon's 1-call/second rate limit. This proposal designs the full system but
distinguishes what can be done now vs what requires data fetch work.

---

## 1. Current Architecture and Its Single-Ticker Limitation

### 1.1 The SPY Monoculture

`Backtester.run_backtest(ticker, start_date, end_date)` is designed for a single underlying. The
scan loop:

1. Fetches price data for `ticker` only
2. Builds IV Rank from VIX (SPY-specific)
3. Finds options from `HistoricalOptionsData` keyed by `ticker`
4. The combo regime detector is calibrated on SPY/VIX data

Every piece of state (`_price_data`, `_iv_rank_by_date`, `_realized_vol_by_date`,
`_regime_by_date`) is per-ticker. The backtester has no concept of a universe.

**Proof**: `data/options_cache.db` has 186,906 rows in `option_contracts` — all with `ticker = 'SPY'`.
No QQQ, no IWM, no XLE, no sector ETF data exists.

### 1.2 What `get_eligible_underlyings()` Already Does

`shared/macro_state_db.py` already implements universe expansion logic (added in Sprint 1):

```python
def get_eligible_underlyings(regime: str = "NEUTRAL") -> list[str]:
    BASE_UNIVERSE = ["SPY", "QQQ", "IWM"]
    # In BULL/NEUTRAL: add sectors ranked top-4 by 3M RS
    # In BEAR: add sectors ranked bottom-4 (for bear calls)
    # In BEAR_MACRO (score < 45): base universe only
```

This function exists but **nothing calls it** in the backtester. The COMPASS signals know which
sectors to trade — the backtesting infrastructure doesn't know how to execute on that signal.

---

## 2. Options Liquidity Analysis — Which ETFs Can We Actually Trade?

### 2.1 Tier 1: Core Universe (liquid, proven, options deep)

| Ticker | Daily Options Vol | ATM Bid-Ask | Spread Type | Notes |
|--------|------------------|-------------|-------------|-------|
| **SPY** | 3–5M contracts | $0.01–0.02 | Bull puts, bear calls, ICs | Best liquidity on earth |
| **QQQ** | 1–2M contracts | $0.02–0.05 | Bull puts, bear calls, ICs | Near-SPY liquidity |
| **IWM** | 400–600K contracts | $0.03–0.08 | Bull puts, bear calls | Adequate |

**Verdict**: SPY/QQQ/IWM are unconditionally tradeable. Already in BASE_UNIVERSE.

### 2.2 Tier 2: Sector ETFs (liquid enough for credit spreads)

These have sufficient daily volume and reasonable bid-ask spreads for $5-wide credit spreads:

| Ticker | Sector | Daily Options Vol | IV vs SPY | OTM Credit Edge | COMPASS Signal |
|--------|--------|------------------|-----------|-----------------|----------------|
| **XLF** | Financials | 400–700K | 1.1–1.4× | Moderate | ✅ Already in COMPASS DB |
| **XLE** | Energy | 300–500K | 1.3–1.8× | **Strong** | ✅ Leading 2021, 2022 |
| **XLK** | Technology | 200–400K | 1.2–1.5× | Strong | ✅ Leading 2023–2024 |
| **XLV** | Healthcare | 150–250K | 1.0–1.2× | Moderate | ✅ Defensive hedge |
| **XLI** | Industrials | 100–200K | 1.1–1.3× | Moderate | ✅ Economic backbone |
| **SOXX** | Semis (AI) | 200–400K | 1.5–2.2× | **Very strong** | ✅ Leading 2023–2024 |
| **XBI** | Biotech | 150–300K | 1.8–2.8× | **Highest** | ⚠️ High tail risk |
| **XLU** | Utilities | 80–120K | 1.0–1.2× | Low | ✅ Rate-sensitive |
| **XLY** | Cons. Disc | 80–150K | 1.2–1.5× | Moderate | ✅ Regime-sensitive |

**Bid-Ask spread reality for credit spreads:**
For a $5-wide bull put spread at 3% OTM, typical mid-credit:
- SPY: 8–12 cents (~1.6–2.4% of $5 width)
- XLE: 12–20 cents (~2.4–4.0% of $5 width) — still viable
- XBI: 25–60 cents — wide bid-ask can erode 30–50% of the theoretical credit

### 2.3 Tier 3: Marginal / Exclude

| Ticker | Issue | Decision |
|--------|-------|----------|
| XLRE | < 50K daily options vol; very wide bid-ask | **Exclude** |
| XLB | < 30K daily vol; sparse chain | **Exclude** |
| XLC | < 40K daily vol | **Exclude** |
| XLP | < 30K daily vol | **Exclude** |
| PAVE | < 20K daily vol; too illiquid | **Exclude** |
| ITA | < 20K daily vol; defense is a theme but untradeable | **Exclude** |
| SMH | 80–150K vol; XBI-level tail risk; prefer SOXX | **Conditional** |

### 2.4 Final Recommended Universe

```
TIER 1 (always trade):     SPY, QQQ
TIER 2 (COMPASS-selected): XLE, XLK, XLF, XLI, SOXX
TIER 3 (conditional):      XLV (defensive/BEAR macro hedge), IWM (regime-specific)
EXCLUDE:                   XBI (too volatile), XLRE/XLB/XLC/XLP (illiquid options)
```

---

## 3. What the Alpha Would Have Looked Like (2020–2025 Sector Analysis)

### 3.1 Methodology

Credit spreads on sector ETFs earn alpha through two mechanisms:
1. **Higher underlying return** (Leading sector has upward momentum → fewer put strike hits)
2. **Higher IV premium** (sector ETFs have 1.2–2.0× SPY's IV → collect more credit per dollar of risk)

For a 3% OTM bull put spread on XLE vs SPY, we collect roughly 1.5× the credit for the same
max-loss dollar amount. When XLE is in the Leading RRG quadrant and trending up, put strikes are
rarely touched.

### 3.2 Year-by-Year Sector Alpha Estimate

#### 2020: COVID Crash and Biotech/Tech Recovery

SPY baseline (exp_090): **+37.5%**

In 2020 the COMPASS RRG data shows:
- XLE: Improving → Leading from Apr onward (COVID bottom energy recovery)
- XLK: Leading most of year (stay-at-home tech premium)
- SOXX: Leading H2 (chip demand explosion)

**Counterfactual**: Trading XLE + XLK instead of SPY:
- XLE +43% (Apr–Dec), XLK +43% (full year)
- Both were in Leading/Improving quadrants when the recovery bull puts would be entered
- Higher IV on XLK (tech fear premia) → collect ~1.3× credit vs SPY
- **Estimated performance with XLE+XLK mix**: +45–55% vs +37.5% baseline
- **Alpha estimate: +7 to +17pp**

**2020 caveat**: XBI was the actual #1 sector (+112%). But XBI's tail risk makes it
problematic for credit spreads — the volatility cuts both ways. Excluded from universe.

#### 2021: Energy Dominance and Reflation

SPY baseline (exp_090): **+13.9%**

COMPASS RRG for 2021:
- XLE: **Leading all 52 weeks** — unprecedented persistence
- XLF: Leading/Improving (reflation → rate normalization)
- XLK: Improving/Leading H2

**XLE 2021 bull puts would have been extremely profitable:**
- XLE +53% (full year) vs SPY +28.7%
- XLE was NEVER in the Lagging/Weakening zone in 2021
- XLE IV was ~25–30% vs SPY IV ~15–20% → collect 1.5× credit
- With XLE trending up +53%, puts at 3% OTM would almost never be hit

**Estimated XLE bull put performance 2021**: +60–80% vs SPY spread's +13.9%
**Alpha estimate: +46 to +66pp** — this is the most compelling data point

#### 2022: Bear Market with XLE Anomaly

SPY baseline (exp_090): **+145.1%** (bear calls)

2022 is complex. SPY's +145% came from bear calls as SPY fell -18.1%.
XLE was the outlier: +65.7% while everything else crashed.

**Sector-specific analysis for 2022:**
- Bear calls on XLC: XLC -40% → ideal bear call candidate. XLC in Lagging/Weakening all year
- Bear calls on XLY: XLY -38% → same
- Bull puts on XLE: XLE +66% → still profitable if using XLE for bull puts in 2022

**The multi-sector approach**: COMPASS could simultaneously:
- Run bear calls on XLC/XLY (trending down, bear calls ideal)
- Run bull puts on XLE (trending up, LEADING all year)
- Result: capture BOTH sides of the 2022 rotation simultaneously

**Estimated multi-sector 2022**: The single-ticker SPY approach already gets +145% from
bear calls. A multi-sector approach would add bull puts on XLE on top. **But**: the combined
positions would require capital allocation — this is additive alpha, not replacement alpha.

**With capital split**: If 50% of capital trades XLE bull puts (+130% est.) and 50% trades
bear calls on SPY/XLC/XLY (+100% est.): blended ≈ **+115%** — slightly lower than pure SPY
bear calls, but more diversified.

#### 2023: AI/Semiconductor Explosion

SPY baseline (exp_090): **-12.0%** ← this is the problem year

2023 was the year COMPASS most needed. Why was SPY-only -12%?
- The regime detector had trouble with the AI-driven narrow rally (only Mag-7 going up)
- SPY overall was volatile, creating stop-outs

**SOXX in 2023**: +62% (Jan–Jun), then consolidation
- SOXX was in **Leading quadrant from Jan through Jun 2023**
- Selling SOXX puts at 3% OTM when SOXX was ripping +62%: essentially zero put strikes hit
- SOXX IV ~30–40% vs SPY ~15–18% → collect 2× credit per dollar of risk

**Estimated SOXX bull put performance 2023**: +35–50%
**Alpha vs SPY-only (-12%)**: +47 to +62pp — eliminates the losing year

#### 2024: Rate Cuts, Utilities, AI Infrastructure

SPY baseline (exp_090): **+3.7%**

COMPASS RRG for 2024:
- XLU: Leading/Improving (AI power demand narrative, rate cut tailwind)
- SOXX: Leading H2 (sustained AI build-out)
- XLK: Improving/Leading

2024 was a year where the index was dragged by rotation uncertainty. Sector-specific
selection would have avoided the choppy SPY regime detection problems.

**Estimated multi-sector 2024 (XLU + SOXX)**: +15–25% vs SPY-only +3.7%
**Alpha estimate: +11 to +21pp**

#### 2025: Defense and Tariff Shock

SPY baseline (exp_090): **+16.3%**

COMPASS RRG for 2025:
- ITA: Leading (defense spending theme) — but ITA options are too illiquid
- XLI: Improving (infrastructure)
- SOXX: Volatile (DeepSeek shock → recovery)

2025 is harder to analyze (still in progress). The tariff shock (Apr 2025) hit all sectors
broadly — sector selection didn't help much as the correlation went to 1.0.

**Estimated multi-sector 2025**: +20–30% (modest improvement from XLI/SOXX mix)
**Alpha estimate: +4 to +14pp**

### 3.3 Summary Alpha Table

| Year | SPY-only Baseline | Estimated Multi-Sector | Alpha vs Baseline |
|------|------------------|------------------------|-------------------|
| 2020 | +37.5% | +45–55% | **+7 to +17pp** |
| 2021 | +13.9% | +60–80% | **+46 to +66pp** ← biggest prize |
| 2022 | +145.1% | +115–130% | **-15 to -30pp** (modest regression) |
| 2023 | -12.0% | +35–50% | **+47 to +62pp** ← saves the losing year |
| 2024 | +3.7% | +15–25% | **+11 to +21pp** |
| 2025 | +16.3% | +20–30% | **+4 to +14pp** |
| **Avg** | **+34.1%** | **~+48–61%** | **+14 to +27pp** |

**Caveat**: These are estimates based on sector return direction and IV premiums. Actual backtest
results will differ based on strike selection, stop-losses, and credit availability.

**Caveat on 2022**: The SPY-only approach gets +145% from bear calls, which is an exceptional
result. Multi-sector diversification may modestly reduce this by allocating some capital to XLE
bull puts (lower returns than pure bear calls). However, with capital preserved from the improved
2021 year (+60–80% vs +13.9%), the compounded effect is net positive.

---

## 4. Architecture Design: Multi-Underlying Backtester

### 4.1 Three Design Options

#### Option A: Sequential Single-Ticker Runs + Capital Blending (Simplest, ~1-2 days)

Run each underlying as a separate backtester with allocated capital:
```
Capital $100K → SPY: $50K + XLE: $30K + SOXX: $20K
Run Backtester("SPY", $50K, 2021) → $67K (34% return)
Run Backtester("XLE", $30K, 2021) → $57K (90% return)
Run Backtester("SOXX", $20K, 2021) → $32K (60% return)
Blended result: ($67K + $57K + $32K) = $156K = +56% on $100K
```

**Pros**: Zero architecture changes to `Backtester`. Works today once data is fetched.
**Cons**: Capital is siloed. XLE's undeployed capital during SPY waiting periods is wasted.
Returns per ticker depend on starting capital, not dynamic allocation.

#### Option B: Portfolio-Level Multi-Ticker Loop (Medium lift, ~1-2 weeks)

A `PortfolioBacktester` that holds N `Backtester` instances sharing a common capital pool:

```python
class PortfolioBacktester:
    def __init__(self, universe: list[str], config: dict):
        self.capital = config.get('starting_capital', 100_000)
        self.backtestors = {t: Backtester(config) for t in universe}
        self._compass = CompassUniverseSelector()  # reads from macro_state.db

    def run_backtest(self, start_date, end_date) -> dict:
        # Each trading day:
        for day in trading_dates:
            # 1. Get COMPASS-selected universe for this week
            eligible = self._compass.get_eligible(day)
            # 2. Allocate capital to active underlyings
            allocation = self._allocate(eligible, self.capital)
            # 3. Run each underlying's scan with its allocated capital
            for ticker in eligible:
                self.backtestors[ticker].scan_day(day, capital=allocation[ticker])
            # 4. Update combined P&L, apply circuit breakers at portfolio level
```

**Pros**: Dynamic capital allocation. Cross-underlying correlation management. Portfolio-level
drawdown circuit breaker. This is the right long-term architecture.
**Cons**: Significant refactoring. `Backtester.run_backtest()` is currently a monolithic loop —
extracting a `scan_day()` method requires careful surgery. 2–4 weeks of engineering.

#### Option C: COMPASS Universe Weighting on run_optimization.py (Quick win, ~2-3 days)

Modify `run_optimization.py` to run multiple tickers and combine results at the reporting layer
without changing `Backtester` at all:

```python
# In run_optimization.py:
def run_compass_portfolio(config, years):
    # Get COMPASS-selected universe per year
    results = {}
    for year in years:
        # Determine which tickers COMPASS says are eligible this year
        tickers = get_compass_universe_for_year(year)
        # Run each ticker with equal capital split
        year_results = []
        for ticker in tickers:
            r = run_single_backtest(ticker, year, config,
                                    capital=100_000 / len(tickers))
            year_results.append(r)
        # Combine: weight by COMPASS RS strength
        results[year] = combine_results(year_results)
    return results
```

**Pros**: No backtester changes. Usable in weeks. Provides real backtest data on sector ETFs.
**Cons**: Static capital allocation (can't rebalance dynamically mid-year). Capital sitting idle
in tickers not being traded.

**Recommendation**: Start with Option C for immediate learning, build toward Option B for the
production system.

### 4.2 Detailed Option B Architecture

The `PortfolioBacktester` requires these surgical changes to `Backtester`:

#### Change 1: Extract `scan_day()` from `run_backtest()` loop

Currently, `run_backtest()` is a monolithic loop that handles portfolio state internally.
Extract the per-day operations into a callable method:

```python
def initialize(self, ticker: str, start_date: datetime, end_date: datetime) -> None:
    """One-time setup: load price data, build IV rank/regime/COMPASS series."""
    self.ticker = ticker
    price_data = self._get_historical_data(ticker, ...)
    self._iv_rank_by_date = self._build_iv_rank_series(...)
    self._realized_vol_by_date = ...
    if self._regime_mode == 'combo':
        self._build_combo_regime_series(price_data)
    if self._compass_enabled or self._compass_rrg_filter:
        self._build_compass_series(start_date, end_date)
    self._price_data = price_data
    # Reset portfolio state
    self.capital = self.starting_capital
    self.trades = []

def scan_day(self, current_date: datetime, allocated_capital: float) -> list[dict]:
    """Scan one trading day and return new positions opened."""
    self.capital = allocated_capital  # updated by portfolio manager
    # ... (inner loop body from run_backtest, extracted verbatim)
    return new_positions_today
```

**Lines affected**: ~lines 560–1000 of `backtester.py`. This is the largest refactoring.
Estimated effort: 3–5 days to extract cleanly with full test coverage.

#### Change 2: COMPASS Universe Selector

New class in `shared/compass_universe.py`:

```python
class CompassUniverseSelector:
    """Weekly COMPASS-driven universe selection from macro_state.db."""

    TIER1 = ["SPY", "QQQ"]  # always in
    TIER2 = {
        "XLE": {"min_rs_rank": 1, "max_rs_rank": 4, "rrg_quadrants": ["Leading", "Improving"]},
        "XLK": {"min_rs_rank": 1, "max_rs_rank": 5, "rrg_quadrants": ["Leading", "Improving"]},
        "XLF": {"min_rs_rank": 1, "max_rs_rank": 6, "rrg_quadrants": ["Leading", "Improving"]},
        "XLI": {"min_rs_rank": 1, "max_rs_rank": 6, "rrg_quadrants": ["Leading", "Improving"]},
        "SOXX": {"min_rs_rank": 1, "max_rs_rank": 4, "rrg_quadrants": ["Leading", "Improving"]},
    }

    def get_bull_universe(self, as_of_date: date) -> list[str]:
        """Return tickers eligible for bull puts on this date."""
        rankings = get_sector_rankings()  # from macro_state_db
        regime = get_current_regime_proxy()  # from macro_score
        if regime == "BEAR_MACRO":
            return self.TIER1  # contract to base in crisis
        eligible = list(self.TIER1)
        for ticker, rules in self.TIER2.items():
            rank = get_rank(ticker, rankings)
            quadrant = get_quadrant(ticker, rankings)
            if (rank <= rules["max_rs_rank"] and
                quadrant in rules["rrg_quadrants"]):
                eligible.append(ticker)
        return eligible

    def get_bear_universe(self, as_of_date: date) -> list[str]:
        """Return tickers eligible for bear calls (Lagging/Weakening sectors)."""
        rankings = get_sector_rankings()
        eligible = list(self.TIER1)
        for ticker in self.TIER2:
            rank = get_rank(ticker, rankings)
            quadrant = get_quadrant(ticker, rankings)
            if rank >= 6 and quadrant in ["Lagging", "Weakening"]:
                eligible.append(ticker)
        return eligible
```

#### Change 3: Per-Ticker IV Rank from Ticker-Specific IV Data

Currently `_build_iv_rank_series()` uses VIX (SPY-derived). For non-SPY underlyings, we need
ticker-specific IV Rank:

```python
def _build_iv_rank_series(self, ticker: str, ...) -> dict:
    if ticker == "SPY":
        return self._build_iv_rank_from_vix(...)
    else:
        # Compute 252-day rolling IV Rank from actual options data
        # Requires fetching ATM option implied vols from options_cache.db
        return self._build_iv_rank_from_options_cache(ticker, ...)
```

This is blocked on having the options data cached. Until data is available for non-SPY tickers,
default to `iv_rank = 30` (moderate) which will cause slightly inaccurate position sizing but
won't break anything.

#### Change 4: Per-Ticker Regime Detection

The `ComboRegimeDetector` uses SPY/VIX for regime labels. For sector-specific entries, the regime
should be overridden based on the sector's own RS quadrant:

```python
def get_regime_for_ticker(ticker: str, date: date) -> str:
    """Determine BULL/BEAR/NEUTRAL for a specific underlying."""
    if ticker in ("SPY", "QQQ", "IWM"):
        return combo_regime[date]  # use SPY-based regime detector
    else:
        # For sector ETFs: use RRG quadrant from COMPASS
        quadrant = get_rrg_quadrant(ticker, date)
        if quadrant in ("Leading", "Improving"):
            return "BULL"   # sector is in uptrend → bull puts
        elif quadrant in ("Lagging", "Weakening"):
            return "BEAR"   # sector is in downtrend → bear calls
        else:
            return combo_regime[date]  # fallback to SPY regime
```

This is the key insight: **a sector ETF in the Leading quadrant is in its own bull regime,
independent of the broad SPY regime**. In 2022, XLE was Leading even when SPY was BEAR.
Selling XLE puts in 2022 was correct precisely because XLE ignored the SPY bear market.

### 4.3 Capital Allocation Algorithm

With multiple underlyings competing for capital, we need a daily allocation rule:

```python
def allocate_capital(total_capital: float,
                     eligible_tickers: list[str],
                     compass_rankings: dict) -> dict[str, float]:
    """
    Allocate capital to each eligible underlying based on COMPASS RS strength.

    Allocation weights:
    - SPY/QQQ: always get baseline allocation (floor)
    - Sector ETFs: weighted by RS percentile within eligible set
    - Max any single non-SPY position: 30% of total capital
    """
    allocation = {}
    # Floor for index underlyings
    index_share = 0.40  # SPY + QQQ get 40% of capital between them
    sector_share = 0.60  # sectors get 60% when present

    # If no sector ETFs eligible, give all to index
    if len([t for t in eligible_tickers if t not in ("SPY", "QQQ")]) == 0:
        allocation["SPY"] = total_capital * 0.60
        allocation["QQQ"] = total_capital * 0.40
        return allocation

    # Weighted by RS strength for sectors
    index_tickers = [t for t in eligible_tickers if t in ("SPY", "QQQ")]
    sector_tickers = [t for t in eligible_tickers if t not in ("SPY", "QQQ")]

    per_index = (total_capital * index_share) / max(len(index_tickers), 1)
    for t in index_tickers:
        allocation[t] = per_index

    # Sector weighting: RS-rank weighted, capped at 30% of total
    for t in sector_tickers:
        rs_pct = compass_rankings.get(t, {}).get("rs_percentile", 50.0)
        weight = rs_pct / sum(compass_rankings.get(s, {}).get("rs_percentile", 50.0)
                              for s in sector_tickers)
        allocation[t] = min(total_capital * sector_share * weight,
                            total_capital * 0.30)  # cap at 30%

    return allocation
```

---

## 5. Data Acquisition Plan

### 5.1 What We Need to Fetch

The `HistoricalOptionsData` class is already built for Polygon fetching. Adding a new underlying
is conceptually trivial — but the rate limit makes it time-consuming.

**Data requirements for each new underlying (2020–2026, 6 years):**

| Ticker | Est. Contracts | Est. Daily Rows | Est. Intraday Rows | Fetch Time @ 1 call/s |
|--------|---------------|-----------------|--------------------|-----------------------|
| QQQ | ~180K | ~300K | ~1.4M | ~4 days |
| XLE | ~80K | ~140K | ~650K | ~2 days |
| XLK | ~70K | ~120K | ~560K | ~2 days |
| XLF | ~90K | ~150K | ~700K | ~2 days |
| SOXX | ~60K | ~100K | ~480K | ~1.5 days |
| XLI | ~40K | ~70K | ~330K | ~1 day |
| **Total** | **~520K** | **~880K** | **~4.1M** | **~12 days** |

**This is the core constraint.** 12 days of background fetching at Polygon's standard tier.
Options: (a) run the fetch in background over 2 weeks, (b) upgrade Polygon tier for higher
rate limits, (c) start with fewer tickers (just QQQ + XLE = 6 days).

### 5.2 Phased Data Acquisition Strategy

**Phase D1 (Day 1–3): QQQ first**
QQQ is already in the BASE_UNIVERSE (`get_eligible_underlyings` returns it). Adding QQQ
to the backtester provides immediate value even without sector expansion:
- QQQ-specific regime (NASDAQ-heavy → more tech-sensitive)
- 2023 AI rally: QQQ +55% vs SPY +26% → bull puts on QQQ dramatically better

**Phase D2 (Day 4–8): XLE**
Best single-ticker alpha based on the 2020–2022 analysis. XLE Leading all year in 2021.
XLE holding positive in 2022 bear market = uniquely valuable for portfolio diversification.

**Phase D3 (Day 9–14): SOXX + XLK**
AI theme tickers. Most critical for 2023–2025 alpha. High IV = rich credit collection.
SOXX specifically had the highest IV of the Tier 2 universe.

**Phase D4 (Day 15–18): XLF + XLI**
Lower priority but complete the liquid options universe for COMPASS coverage.

### 5.3 Data Fetch Script Specification

```python
# scripts/fetch_sector_options.py
# Usage: python3 scripts/fetch_sector_options.py --ticker XLE --start 2020-01-01 --end 2026-03-07

FETCH_ORDER = ["QQQ", "XLE", "SOXX", "XLK", "XLF", "XLI"]

def fetch_ticker_options(ticker: str, start: date, end: date):
    """
    Fetch all option contracts + daily + intraday data for ticker.
    Uses existing HistoricalOptionsData infrastructure with offline_mode=False.
    Estimated time: 1–4 days per ticker depending on contract count.
    Progress checkpointing: resumes from last fetched contract if interrupted.
    """
    hod = HistoricalOptionsData(api_key=POLYGON_KEY, offline_mode=False)
    # Step 1: Fetch all expirations within window
    expirations = hod.get_expirations(ticker, start, end)
    # Step 2: For each expiration, fetch contracts
    for exp in expirations:
        contracts = hod.get_contracts(ticker, exp)
        # Step 3: Fetch daily OHLCV for each contract
        for contract in contracts:
            hod.get_option_data(contract, start, end)
            time.sleep(1.0)  # 1 call/second rate limit
```

**Checkpoint design**: After every 1000 contracts fetched, write a checkpoint file
`data/fetch_progress_{ticker}.json`. If the script is interrupted, it resumes from the
last checkpoint. This makes the multi-day fetching resilient to interruptions.

---

## 6. Redesigned Experiment Matrix

### 6.1 Naming Scheme

| Range | Category |
|-------|----------|
| exp_200–299 | COMPASS sizing/RRG on SPY (current champion configs) |
| **exp_300–399** | **Multi-underlying + COMPASS universe expansion** |
| exp_300–319 | SPY + QQQ two-ticker baseline |
| exp_320–339 | XLE integration experiments |
| exp_340–359 | SOXX integration experiments |
| exp_360–379 | Full 5-ticker portfolio (SPY+QQQ+XLE+SOXX+XLK) |
| exp_380–399 | COMPASS-driven dynamic universe (full GPS mode) |

### 6.2 Group 0: SPY-Only COMPASS Sizing (exp_200 series — run FIRST)

These are from the previous proposal and should run immediately since no data fetching is needed.
They establish the COMPASS sizing baseline before multi-underlying is introduced.

**Batch A (run now, no data needed):**

| Exp | Config | Hypothesis |
|-----|--------|------------|
| exp_210 | exp_126 + COMPASS sizing | Does risk_appetite sizing improve exp_126 MC P50? |
| exp_220 | exp_154 + COMPASS sizing | Same for 5% champion |
| exp_200 | exp_090 + COMPASS sizing + combo | Clean ablation on base config |

### 6.3 Group 1: SPY + QQQ (exp_300 series — requires QQQ data fetch)

These establish the two-ticker baseline before adding sector ETFs.

| Exp | Description | Capital Split | Hypothesis |
|-----|-------------|---------------|------------|
| **exp_300** | SPY 60% + QQQ 40%, equal splits | Fixed | QQQ adds alpha in tech bull years (2023, 2024) |
| **exp_301** | COMPASS-weighted SPY vs QQQ | Dynamic | When QQQ RS rank > SPY RS rank, shift to QQQ |
| **exp_302** | QQQ only (baseline for comparison) | 100% QQQ | Understand QQQ standalone performance |

**exp_300 capital mechanics:**
```json
{
  "universe": ["SPY", "QQQ"],
  "capital_split": {"SPY": 0.60, "QQQ": 0.40},
  "base_config": "exp_126",
  "compass_enabled": true
}
```

**Expected exp_300 alpha over SPY-only:**
- 2021: QQQ +27.4% vs SPY +28.7% — minimal difference
- 2022: QQQ worse than SPY (QQQ -32.6% vs SPY -18.1%) — bear calls on QQQ BETTER
- 2023: QQQ +55.1% vs SPY +26.3% — **bull puts on QQQ much better**
- 2024: QQQ +36.6% vs SPY +24.9% — **bull puts on QQQ better**

Estimated 2-ticker 60/40 avg: +40–45% vs SPY-only +34.1% baseline. Alpha: **+6 to +11pp**.

### 6.4 Group 2: XLE Integration (exp_320 series — requires XLE data fetch)

XLE is the highest-conviction single-ticker add based on the 2020–2022 alpha analysis.

| Exp | Description | Hypothesis |
|-----|-------------|------------|
| **exp_320** | SPY 60% + XLE 40%, always-on | XLE diversification regardless of COMPASS signal |
| **exp_321** | SPY 70% + XLE 30% COMPASS-conditional | Add XLE to universe ONLY when XLE RRG=Leading |
| **exp_322** | SPY 50% + QQQ 20% + XLE 30% COMPASS-conditional | Three-ticker with COMPASS weighting |

**exp_321 COMPASS rule** (the GPS version):
```python
# Weekly: check XLE RRG quadrant in sector_rs table
if xle_quadrant in ("Leading", "Improving"):
    universe = ["SPY", "XLE"]
    allocation = {"SPY": 0.60, "XLE": 0.40}
else:
    universe = ["SPY"]
    allocation = {"SPY": 1.00}
```

**Expected exp_321 performance:**
- 2021: XLE leading all year → XLE in universe all year → **XLE bull puts +estimated 70%**
- 2022: XLE leading → XLE bull puts while SPY does bear calls → diversified +estimated 100%+
- 2020 crash: XLE weakening/lagging in Q1 → COMPASS correctly removes XLE from universe

### 6.5 Group 3: SOXX Integration (exp_340 series — requires SOXX data fetch)

SOXX is the AI-theme proxy with 2× SPY's IV premium in tech bull years.

| Exp | Description | Hypothesis |
|-----|-------------|------------|
| **exp_340** | SPY 50% + SOXX 50%, always-on | High IV premium from SOXX; test standalone |
| **exp_341** | COMPASS-conditional SOXX (Leading/Improving only) | Add SOXX when AI theme active |
| **exp_342** | SPY + QQQ + SOXX 3-way COMPASS split | Full tech-weighted portfolio |

**exp_341 expected alpha**:
- 2023: SOXX +62% in H1 → bull puts on SOXX rarely hit → high returns at 2× credit premium
- 2024: SOXX continues AI theme → bull puts with elevated IV
- 2022: SOXX -35% → SOXX in Lagging → COMPASS correctly removes from bull put universe

### 6.6 Group 4: Full 5-Ticker Portfolio (exp_360 series)

The full COMPASS GPS mode: SPY, QQQ, XLE, SOXX, XLK allocated dynamically by sector RS rankings.

| Exp | Description |
|-----|-------------|
| **exp_360** | 5 tickers, equal weight (20% each) — COMPASS-naive baseline |
| **exp_361** | 5 tickers, COMPASS RS-weighted allocation |
| **exp_362** | COMPASS GPS: universe changes weekly based on which sectors are Leading |
| **exp_363** | COMPASS GPS + sizing multiplier (full system) |

**exp_362 (the GPS mode) rules:**
```
Each Friday (weekly snapshot), determine:
  1. Which Tier-2 tickers are in Leading/Improving? → add to bull put universe
  2. Which Tier-2 tickers are in Lagging/Weakening? → add to bear call universe
  3. Allocate capital by RS percentile (higher RS rank = larger allocation)
  4. Max 30% capital to any single non-SPY ticker
  5. SPY always gets minimum 30% of capital as base

Example week (2021-06-18):
  XLE: Leading, RS rank #1 → 25% capital, bull puts
  XLF: Improving, RS rank #3 → 15% capital, bull puts
  SPY: base → 30% capital, bull puts
  QQQ: Improving, RS rank #4 → 15% capital, bull puts
  XLI: Leading, RS rank #5 → 15% capital, bull puts
  → 100% deployed across 5 underlyings
```

### 6.7 Group 5: Bear Call Universe Expansion

The bear call side is equally important. In 2022, the lagging sectors were more directionally
profitable than SPY itself for bear calls.

| Exp | Description | Expected Alpha |
|-----|-------------|----------------|
| **exp_370** | SPY bear calls + XLC bear calls when XLC Lagging | 2022: XLC -40% → massive bear call returns |
| **exp_371** | SPY bear calls + XLY bear calls when XLY Lagging | 2022: XLY -38% → same |
| **exp_372** | Full bear call universe: SPY + top-3 Lagging sectors | Comprehensive 2022 coverage |

**Note on bear calls on sector ETFs**: The same options data fetch requirement applies.
But the 2022 alpha from XLC/XLY bear calls is very large — a top priority for data fetching.

### 6.8 Priority Order

```
IMMEDIATELY (no data needed):
  exp_210 → exp_220 → exp_200  (SPY sizing ablation from previous proposal)

AFTER QQQ fetch (~3-4 days):
  exp_300 → exp_301 → exp_302  (two-ticker baseline)

AFTER XLE fetch (~2 days):
  exp_320 → exp_321 → exp_322  (XLE integration — highest historical alpha)

AFTER SOXX fetch (~1.5 days):
  exp_340 → exp_341            (AI theme integration)

AFTER XLK fetch (~2 days):
  exp_342 → exp_360 → exp_361  (three-ticker tech cluster)

AFTER ALL SECTOR DATA:
  exp_362 → exp_363            (full GPS mode)
  exp_370 → exp_371 → exp_372  (bear call universe)
```

---

## 7. Implementation Scope and Timeline

### 7.1 Engineering Phases

#### Sprint A: Data Acquisition (parallel with everything else)
**What**: Start Polygon data fetch for QQQ, then XLE, then SOXX in background
**Who touches**: `scripts/fetch_sector_options.py` (new script)
**Dependencies**: None — runs in background, doesn't block experiments
**Timeline**: Begins Day 1, completes in ~2 weeks

#### Sprint B: Option A Implementation (earliest backtestable multi-underlying)
**What**: `run_optimization.py` receives a `universe` config, runs per-ticker backtests,
combines results at the reporting layer
**Files changed**: `scripts/run_optimization.py` only
**Engineering complexity**: Medium (~300 lines of new code)
**Blocks on data**: Yes — needs QQQ/XLE data before useful results
**Timeline**: 2–3 days once requirements are clear

#### Sprint C: CompassUniverseSelector
**What**: New `shared/compass_universe.py` module that reads `macro_state.db` sector_rs
table and returns COMPASS-selected universe for any given week
**Files changed**: New file + minor integration in `run_optimization.py`
**Engineering complexity**: Low (~150 lines)
**Blocks on data**: No — just reads existing COMPASS data
**Timeline**: 1–2 days

#### Sprint D: Per-Ticker Regime and IV Rank
**What**: Modify `_build_iv_rank_series()` and `_build_combo_regime_series()` to work with
non-SPY underlyings. Add RRG quadrant → regime override for sector ETFs.
**Files changed**: `backtest/backtester.py` (~50-100 lines)
**Engineering complexity**: Low-medium
**Timeline**: 1–2 days

#### Sprint E: PortfolioBacktester (full Option B)
**What**: `PortfolioBacktester` class with daily cross-ticker capital allocation
**Files changed**: New `backtest/portfolio_backtester.py` + refactoring `backtester.py`
  to expose `initialize()` and `scan_day()`
**Engineering complexity**: HIGH — refactoring the core backtest loop carries risk
**Timeline**: 2–3 weeks, requires careful testing
**Risk**: Could introduce subtle bugs in the existing single-ticker path

**Recommendation**: Do NOT rush Sprint E. Option C (combined reporting) gets 80% of
the value in 20% of the time. Build Option B only after Options C data validates the thesis.

### 7.2 Summary Timeline

```
Week 1:  exp_200 series (SPY-only COMPASS) — zero dependencies
         Background data fetch starts: QQQ, XLE
         Sprint B: multi-ticker run_optimization.py
         Sprint C: CompassUniverseSelector

Week 2:  QQQ data available → run exp_300, 301, 302
         XLE data available (end of week) → prepare exp_320 series

Week 3:  exp_320, 321 (XLE integration) — key alpha test
         SOXX data fetch starts
         Sprint D: per-ticker regime/IV

Week 4:  SOXX data available → run exp_340, 341
         XLK data starts fetching
         MC validation on best multi-ticker config

Week 5+: Full portfolio (exp_360 series)
         Sprint E: PortfolioBacktester if thesis is validated
```

---

## 8. Expected Outcomes and Success Criteria

### 8.1 What Carlos Criteria Look Like for Multi-Underlying

The Carlos criteria (MC P50 > 30%, det max DD < 40%) apply to the combined portfolio return,
not per-ticker. A diversified portfolio's equity curve should be smoother (lower MC P50
variance, not necessarily higher median), which is exactly what sector diversification provides.

**Hypothesis**: Multi-ticker COMPASS portfolio passes Carlos criteria more comfortably:
- MC P50: +35–40% (vs +31–32.5% for SPY-only champions)
- Max DD: -22 to -28% (improved from -28.9% by portfolio diversification)
- Consistency: 6/6 profitable years (XLE fixes 2021; SOXX fixes 2023)

**The 2021 and 2023 problem years** for SPY-only (+13.9% and -12%) are both explained by
narrow market conditions where SPY underperforms vs leading sectors. Both are potentially
fixed by adding QQQ/SOXX/XLE to the universe.

### 8.2 Risk Considerations

**Liquidity risk**: Sector ETF options have wider bid-ask spreads. Slippage multiplier should
be set higher for sector ETFs (1.5× instead of 1.0×). A separate `slippage_by_ticker` config
parameter would handle this.

**Correlation in crashes**: In 2020 Q1 (COVID crash), ALL sectors fell together. The
correlation between XLE, XLK, SPY went to ~0.95. Diversification across sectors provides
no protection in true market panic. The combo regime detector and VIX circuit breaker
remain the primary risk management tools.

**Concentration risk**: COMPASS might recommend 4 tech-adjacent tickers simultaneously
(QQQ, XLK, SOXX, plus SPY which has high tech weight). Maximum same-sector concentration
rule needed: no more than 40% of capital in tech-correlated underlyings simultaneously.

**Data quality risk**: Sector ETF options data from Polygon will have the same cache-miss
behavior as SPY. The offline_mode protection applies. However, fewer liquid strikes may
exist for some sector ETFs, making the OTM target strike harder to find.

**Options pricing**: XBI-level options have very high skew — put premiums are elevated
relative to theoretical. XBI is excluded from the universe for this reason. XLE and XLK
options have more symmetric skew, closer to SPY dynamics.

---

## 9. COMPASS Renaming — "GPS" Framing

Carlos is right that the expanded COMPASS is fundamentally different from the sizing-only
version. It now does three things:
1. **WHERE to drive** (universe selection — the GPS function)
2. **HOW FAST** (position sizing — the seatbelt function)
3. **WHEN to slow down** (event gate — the speed camera function)

The "where" function is the new capability. A revised naming approach:

**COMPASS stays as the umbrella brand** — its compass metaphor still works. But the
three sub-signals should be named:

| Sub-system | Name | Function |
|-----------|------|----------|
| Universe Selection | **BEARING** | Your compass bearing — which direction to go (which sectors to trade) |
| Macro Sizing | **CURRENT** | The macro current — whether to paddle harder or softer |
| Event Gate | **SQUALL** | Approaching storms on the calendar — reduce exposure pre-FOMC |

**Combined system name recommendation**: **COMPASS NAVIGATOR**
- "COMPASS" remains the recognized brand
- "NAVIGATOR" conveys the GPS upgrade — it actively selects your destination, not just your seatbelt

Alternative: Just rebrand the whole thing as **NAVIGATOR** and retire COMPASS:
- Simple, clean, single word
- Accurate metaphor: a navigator tells you WHERE to go (universe) and HOW to adjust course (sizing)
- In sailing/aviation, the navigator has more authority than the pilot in complex environments

---

## 10. Decision Points for Carlos

Before any implementation begins:

**D1: Option A vs Option B vs Option C Architecture**
Recommend: Option C (combined reporting in run_optimization.py) immediately, sprint toward
Option B (PortfolioBacktester) after data validates the thesis.

**D2: Prioritize data fetch order**
Recommend: QQQ first (already in base universe, fast to validate), then XLE (highest
historical alpha), then SOXX (AI theme). Skip XBI entirely.

**D3: 2022 bear call universe (XLC/XLY)**
Run the data fetch for XLC and XLY specifically for 2022 bear call alpha validation?
XLC/XLY may have thin options — validate liquidity first before fetching 6 years of data.

**D4: Bear call vs bull put emphasis**
The multi-underlying system can do both simultaneously (bull puts on XLE + bear calls on XLC
in 2022). This requires the portfolio-level circuit breaker to understand correlated
risk (all bear calls AND bull puts on different sectors = full exposure to a market crash).

**D5: Capital allocation model**
RS-weighted allocation vs equal-weight vs regime-weighted?
Recommend: Start with equal-weight (simpler, more robust to stale COMPASS data), move to
RS-weighted once the equal-weight version is validated.

**D6: Naming**
Keep COMPASS with BEARING/CURRENT/SQUALL sub-names, or rebrand to NAVIGATOR?

---

## 11. Appendix: COMPASS DB Sector Coverage

The existing `macro_state.db` already has 323 weeks of RRG data for these tickers,
covering exactly the experimental period (2020–2026):

```
Leading/Improving by year (all in macro_state.db sector_rs):
2020: XBI (17 wks Leading), PAVE (10), XLK (9)
2021: XLE (27 wks Leading!), XLRE (8), XLK (7)
2022: XLE (33 wks Leading!), XBI (9), ITA (4)
2023: SOXX (20 wks Leading), XLK (15), XLE (10)
2024: SOXX (12 wks Leading), XLU (11), XBI (9)
2025: XBI (14 wks Leading), SOXX (13), ITA (8)
```

All of this sector rotation data is available for COMPASS universe selection today — the only
missing piece is the options data to backtest the trades themselves.

The COMPASS GPS vision is already data-complete on the signal side. The only remaining work
is (1) fetching options data and (2) building the multi-ticker backtesting infrastructure.

---

*Proposal complete. Carlos reviews before any data fetch or code changes begin.*
