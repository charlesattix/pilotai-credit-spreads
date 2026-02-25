# PROPOSAL: Backtest Engine V3 — Fixing the Fatal Flaws

**Author:** Charles (AI Architect)  
**Date:** February 24, 2026  
**Status:** DRAFT — Pending Claude Code review  
**Priority:** P0 CRITICAL  

---

## Context

An expert review of our backtest methodology identified four structural issues that are inflating our reported performance metrics. Our current win rate (84.4%), return (+25.4%), and max drawdown (-24.4%) are synthetic — they do not reflect what would happen in live trading. We must fix these before deploying real capital.

---

## Problem 1: Time-Series Mismatch in Exit Logic (CRITICAL)

### Current Behavior
- **Entries** use 5-minute intraday bars at 14 scan times per day
- **Exits** (stop loss & profit target) check only **daily closing prices**

### Why This Is Fatal
An option spread can spike to 4× credit intraday (triggering a stop in live trading) and revert to 1.5× by the daily close. Our backtest records this as a surviving position. In reality, we'd be stopped out at the worst intraday price.

**Impact:** Win rate is overstated, max drawdown is understated, total P&L is inflated.

### Proposed Fix
Rewrite `_manage_positions()` to perform **intraday exit checks**:

1. For each open position, on each trading day:
   - Fetch 5-min intraday bars for both legs of the spread
   - At each 5-min interval, compute the spread value
   - If spread value triggers stop loss (loss ≥ 2.5× credit) → close at that bar's price
   - If spread value triggers profit target (profit ≥ 50% credit) → close at that bar's price
   - First trigger wins (check chronologically through the day)
2. If no intraday trigger → continue to next day (same as current behavior)
3. Fall back to daily close check if intraday data is unavailable for a given date

### Implementation Notes
- This will significantly increase Polygon API calls (fetching intraday bars for open positions daily, not just at entry)
- The SQLite cache mitigates repeat calls — once fetched, bars are cached permanently
- Estimated additional API calls per backtest year: ~2,000-5,000 (depending on position count)
- Runtime will increase substantially — consider running overnight

### Expected Impact on Metrics
- Win rate: **expect 3-8% decline** (intraday stops catching trades that previously "survived")
- Max drawdown: **expect increase** (losses realized at intraday peaks, not softened by daily close)
- Total P&L: **expect 15-30% decline** (fewer fake wins, larger realized losses)

---

## Problem 2: Flawed Slippage Model

### Current Behavior
Slippage = (bar_high - bar_low) / 2 per leg, derived from 5-min bar range.

### Why This Is Wrong
During volatile periods, a 5-min bar's high-low range reflects **directional price movement**, not the bid/ask spread. A bar that moves $0.80 in one direction doesn't mean the spread is $0.80 — it could be $0.05 with momentum. This **overestimates** slippage in trending moments and **underestimates** it in choppy, illiquid conditions.

### Proposed Fix
Replace with a **conservative fixed percentage of spread width**:

```
slippage = spread_width × slippage_pct

Default: slippage_pct = 5%
Example: $5 spread → $0.25 slippage per spread (both legs combined)
```

### Rationale
- SPY/QQQ options are among the most liquid in the world
- Typical bid/ask for ATM-ish SPY options: $0.02-$0.10 per leg
- 5% of spread width ($0.25 on $5) is conservative — covers both legs plus unfavorable fills
- Simple, consistent, auditable — no dependence on bar microstructure

### Configuration
Add to `config.yaml`:
```yaml
backtest:
  slippage_model: "fixed_pct"    # "fixed_pct" or "bar_range" (legacy)
  slippage_fixed_pct: 5          # % of spread width
```

---

## Problem 3: Missing Volatility Context

### Current Behavior
Entry filter is MA20 on the underlying price:
- Price > MA20 → bull put spread (bullish)
- Price < MA20 → bear call spread (bearish)

### Why This Is Insufficient
We're trading options — a volatility instrument — but our only filter is a price-direction indicator. Credit spreads profit from **selling high implied volatility that mean-reverts**. The MA20 tells us nothing about whether IV is rich or cheap.

### Proposed Fix
Add an **IV Rank (IVR) filter** as a gate before any trade entry:

1. **IV Rank calculation**: Where does current IV sit relative to its 52-week range?
   ```
   IVR = (current_IV - 52w_low_IV) / (52w_high_IV - 52w_low_IV) × 100
   ```

2. **Proxy implementation**: Use VIX as the IV proxy for SPY/QQQ/IWM (they're highly correlated)
   - Fetch VIX daily history from Yahoo Finance
   - Compute rolling 252-day (1 year) high and low
   - Calculate IVR for each trading day

3. **Entry gate**:
   ```
   if IVR < min_ivr_threshold:
       skip entry (IV too cheap, premiums not worth the risk)
   ```
   Default threshold: IVR ≥ 25 (IV is in the top 75% of its 1-year range)

4. **Keep MA20 as secondary filter**: MA20 still determines spread direction (put vs call), but IVR determines whether we trade at all.

### Configuration
Add to `config.yaml`:
```yaml
strategy:
  iv_filter:
    enabled: true
    min_ivr: 25              # Minimum IV Rank to enter trades
    vix_proxy: true          # Use VIX as IV proxy
    lookback_days: 252       # Rolling window for IVR calculation
```

### Expected Impact
- **Fewer trades** in low-IV environments (this is correct — we shouldn't be selling cheap premium)
- **Higher average credit** per trade (only entering when IV is elevated)
- **Better win rate** on remaining trades (selling rich vol that mean-reverts)
- Some previously "active" weeks may become inactive (but the trades we skip would have been marginal)

---

## Problem 4: Single-Asset Validation

### Current Behavior
Parameter sweep was run exclusively on SPY for 2024 (in-sample), with out-of-sample on SPY 2025/2026.

### Why This Is Risky
SPY 2024 was a specific market regime (grinding bull, low vol). Parameters optimized for this window may not generalize.

### Proposed Fix
After implementing fixes 1-3, run the full backtest on:

1. **SPY** 2024, 2025, 2026 (re-validation with corrected engine)
2. **QQQ** 2024, 2025 (different vol profile, tech-heavy)
3. **IWM** 2024, 2025 (small caps, higher vol, different dynamics)

If the winning config is profitable across all three underlyings, the edge is structural. If it only works on SPY, it's curve-fit.

### Stretch Goal (if Polygon data goes back far enough)
- **SPY 2022** — Bear market, high vol (stress test)
- **SPY 2020** — COVID crash + recovery (extreme stress test)

---

## Implementation Order

| Phase | Task | Est. Time | Dependency |
|-------|------|-----------|------------|
| 1 | Intraday exit simulation | 4-6 hours | None |
| 2 | Fixed slippage model | 30 min | None (parallel with 1) |
| 3 | IVR filter | 2-3 hours | None (parallel with 1) |
| 4 | Re-run all backtests | 2-4 hours (API calls) | Phases 1-3 complete |
| 5 | Multi-asset validation | 4-8 hours (API calls) | Phase 4 complete |

**Total estimated time: 1-2 days**

---

## Success Criteria

After all fixes are implemented, the backtest must produce:

1. ✅ Intraday exit checks on every 5-min bar for open positions
2. ✅ Conservative fixed slippage (5% of spread width)
3. ✅ IVR gate filtering out low-IV entries
4. ✅ Honest metrics that will be LOWER than current numbers — and that's the point
5. ✅ Profitable across SPY + at least one other underlying (QQQ or IWM)
6. ✅ Updated MASTERPLAN with revised performance expectations

---

## Risk: What If The Edge Disappears?

It's possible that after fixing the fatal flaw, the strategy is break-even or negative. If that happens:

- The current live paper trades are based on synthetic metrics and should be paused
- We go back to the parameter sweep with the corrected engine
- We explore different strategy structures (wider spreads, different DTE, etc.)

**This is a feature, not a bug.** Better to discover this in backtesting than with real money.

---

*"The first principle is that you must not fool yourself — and you are the easiest person to fool."*  
— Richard Feynman
