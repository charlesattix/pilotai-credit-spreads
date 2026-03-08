# Liquidity-Aware Backtester Upgrade — PROPOSAL FOR CRITIQUE

## Problem
The backtester fills trades regardless of market volume, overstating returns 3-5×. It never checks daily volume or open interest before filling. At 25-35 contracts per trade, we're filling 20%+ of daily volume — completely unrealistic.

**Evidence from Polygon data:**
- Median daily volume for SPY puts 3% OTM, DTE 25-45: **170 contracts**
- At 35 contracts we'd be 20.6% of daily volume per leg
- Only 7% of trading days have enough volume (3,500+) to fill 35 contracts at 1% impact rule
- Iron condors (4 legs × 25 contracts = 100 options) are 59% of median daily volume

## Proposed Fix — 3 Phases

### Phase 1: Volume Gate (backtester.py)
**Goal:** Reject trades that can't realistically fill.

In `_build_spread()` and `_build_iron_condor()`, BEFORE creating the position:
1. Query `option_daily` table for the SHORT leg's daily volume on that date
2. If `daily_volume < min_volume_ratio × contracts`: skip the trade, log it
3. New config param: `"min_volume_ratio": 50` (default, meaning order < 2% of volume)
4. Also query long leg volume — use min(short_vol, long_vol) as the constraint
5. Track skipped trades in results for analysis: `{"skipped_low_volume": count}`

**Key implementation detail:** The volume data already exists in `option_daily` table in SQLite cache. Query via `historical_data.py` — add a `get_daily_volume(contract_symbol, date)` method.

### Phase 2: Volume-Based Slippage (backtester.py)
**Goal:** Penalize large orders proportional to their market impact.

Replace/augment the current slippage model:
1. Calculate `order_pct = contracts / daily_volume` (0.0 if volume unknown)
2. If `order_pct < 0.01` (< 1%): use current slippage unchanged
3. If `order_pct` 0.01-0.05 (1-5%): `extra_slip = base_slip × sqrt(order_pct / 0.01)`
4. If `order_pct > 0.05` (> 5%): `extra_slip = base_slip × (order_pct / 0.01)`
5. Apply to BOTH entry and exit slippage
6. New config: `"volume_slippage": true` (default false for backward compat)

**Rationale:** Square-root impact model is standard in market microstructure literature (Kyle 1985). Linear above 5% is conservative.

### Phase 3: Adaptive Position Sizing (backtester.py)
**Goal:** Size positions based on what the market can actually absorb.

New sizing mode `"sizing_mode": "volume_aware"`:
1. Before sizing, get rolling 5-day avg volume for the target strikes
2. `volume_max = avg_volume × max_volume_pct` (default `max_volume_pct = 0.02`, i.e., 2%)
3. Final contracts = `min(risk_based_contracts, volume_max)`
4. At median volume 170: max = 3 contracts
5. At 75th pct volume 519: max = 10 contracts  
6. At 90th pct volume 1,950: max = 39 contracts
7. Strategy naturally adapts — bigger on liquid days, smaller on thin days

**New config params:**
```json
{
  "sizing_mode": "volume_aware",
  "max_volume_pct": 0.02,
  "volume_lookback_days": 5
}
```

### Phase 4: Re-Run & Validate
1. Re-run top 5 configs with `"volume_aware": true` + all 3 fixes
2. Side-by-side comparison: old returns vs liquidity-adjusted returns
3. Regenerate leaderboard with honest numbers
4. Re-run overfit/walk-forward validation

## Implementation Notes
- **Backward compatible:** All new features default OFF. Old configs unchanged.
- **Master config flag:** `"volume_aware": true` enables phases 1+2+3 together
- **Files to modify:** `backtest/backtester.py`, `backtest/historical_data.py`
- **No new dependencies**
- Volume data already in SQLite cache — just need query methods

## Questions for Critique
1. Is the 1% volume rule too conservative? Should we use 2% or 5%?
2. Should we use daily volume or also factor in open interest?
3. For the rolling average, should we exclude zero-volume days?
4. Is the sqrt impact model appropriate, or should we use something else?
5. Any edge cases where volume gate would incorrectly skip good trades?
6. Should partial fills be modeled (fill N of M contracts)?

## Expected Impact
- Returns drop from 135%/yr → ~30-50%/yr (still excellent)
- Position sizes: 25-35 → 3-15 contracts (realistic)
- Overfit scores should improve
- Walk-forward more likely to pass

**PLEASE CRITIQUE THIS PROPOSAL. Poke holes. What am I missing? What could go wrong?**
