# Proposal: Slippage Model Fix (Problem 2)

**Author:** Claude Code
**Date:** February 24, 2026
**Status:** DRAFT — Pending Carlos review before implementation
**Depends on:** Problem 1 (intraday exits) — already implemented

---

## Current Model

Slippage is estimated from 5-min intraday bar high-low ranges in `historical_data.get_intraday_spread_prices()`:

```python
sh_hl = short_bar["high"] - short_bar["low"]
lg_hl = long_bar["high"]  - long_bar["low"]
slippage = sh_hl / 2 + lg_hl / 2
```

This is applied **only at entry** in `_find_real_spread()`:
```python
slippage = prices.get("slippage", self.slippage)   # self.slippage = config fallback $0.05
credit -= slippage
```

When no intraday bar data is available (18% of position-days), the config fallback fires: `slippage = $0.05` flat per spread (both legs combined).

**Exit slippage is not modeled.** The close at stop loss or profit target uses the intraday bar's close price directly, with no bid/ask cost added.

---

## The Problem

### What bar-range actually measures in a 5-min option bar

A 5-min bar's high-low range reflects **everything that happened to the price** during those 5 minutes — directional moves, incoming orders, bid/ask crossing, all of it. In a quiet bar where the option drifts $0.03, the bar range is ~$0.03 and slippage is ~$0.015/leg. Accurate. In a volatile bar where the underlying SPY drops 0.5% and the option reprices $0.80 higher, the bar range is $0.80 and slippage comes out to $0.40/leg. That's not the bid/ask — that's the option moving against the position due to directional momentum. The model treats directional price movement as friction cost, which is wrong.

### Concrete impact on minimum-credit trades

The winning config's minimum trade credit is 10% of $5 spread = **$0.50**. In high-vol bars (the exact conditions when stops trigger), the current model can assign $0.20–$0.50+ of slippage per spread. On a $0.50 credit trade, even $0.20 slippage is a 40% haircut on the net credit that was actually collected. This is unrealistic — actual bid/ask friction on OTM SPY options is $0.02–$0.15/leg in practice.

### Two separate biases in opposite directions

| Condition | Bar range | Model's slippage | Actual bid/ask | Error |
|-----------|-----------|-----------------|----------------|-------|
| Quiet entry (normal conditions) | Small | $0.00–$0.03 | $0.03–$0.08 | **Understates** friction at entry |
| Volatile exit (stop loss conditions) | Large | $0.20–$0.50 | $0.08–$0.20 | **Overstates** friction at exit |

The model makes it look like entering is nearly frictionless (good) while exiting in bad markets is catastrophically expensive (bad). Both distortions are wrong. They partially cancel each other in aggregate, which may be why the current numbers look reasonable, but neither is accurate.

---

## Option A: Cap the Bar-Range Model at $0.10/leg

**Change:** In `historical_data.get_intraday_spread_prices()`, cap the per-leg slippage contribution before summing:

```python
slippage = min(sh_hl / 2, 0.10) + min(lg_hl / 2, 0.10)
# Max: $0.20 per spread
```

**Config change:** Add `backtest.slippage_per_leg_cap: 0.10` to make the cap configurable.

### Pros
- Preserves real signal: in quiet markets (low bar range), slippage stays low. In moderately volatile markets, slippage rises. Only extreme outlier bars are capped.
- Minimum change to existing behavior — same code path, just bounded.
- $0.10/leg cap maps to realistic outer bound for OTM SPY option bid/ask (empirically: $0.02–$0.10 in normal conditions, up to $0.15–$0.20 in high-vol).

### Cons
- Still overstates slippage on high-vol bars compared to actual bid/ask (just less severely).
- On a min-credit $0.50 trade with the cap active: $0.20 slippage = 40% haircut. This is better than the uncapped model but still harsh relative to reality.
- The cap value ($0.10/leg) is a judgment call — needs empirical validation.

### Impact on min-credit trades

| Trade credit | Cap active? | Slippage | Net credit | Haircut |
|-------------|-------------|----------|-----------|---------|
| $0.50 (min) | Yes (quiet bar) | $0.02 | $0.48 | 4% |
| $0.50 (min) | Yes (volatile bar, capped) | $0.20 | $0.30 | 40% |
| $1.00 | Yes (volatile bar, capped) | $0.20 | $0.80 | 20% |
| $2.00 | No (bar range small) | $0.05 | $1.95 | 2.5% |

---

## Option B: Flat $0.05/leg (Both Legs Combined = $0.10)

**Change:** Replace bar-range computation with a constant:

```python
slippage = 0.10  # $0.05/leg × 2 legs, always
```

Note: this is **identical to the existing config fallback** (`backtest.slippage: 0.05` currently applies to the whole spread, not per leg — but changing it to $0.10 brings it in line with the per-leg semantics used elsewhere). A clean implementation would remove the bar-range logic from `get_intraday_spread_prices()` entirely and always return a fixed value.

### Pros
- Simple, auditable, zero ambiguity about what the model does.
- Consistent: every trade, every exit, same friction assumption.
- $0.10 total is defensible for SPY OTM options in normal markets (2× the typical $0.05 bid/ask per leg).
- Removes the directional-momentum-as-slippage bias entirely.

### Cons
- Throws away real signal: wider intraday bars *do* correlate with wider bid/ask on options — discarding that entirely loses a real relationship.
- Same slippage for a trade entered in VIX 12 vs VIX 35. Real friction is materially different.
- On a $0.50 min-credit trade: $0.10 slippage = 20% haircut. Better than Option A's worst case but still meaningful.

### Impact on min-credit trades

| Trade credit | Slippage | Net credit | Haircut |
|-------------|----------|-----------|---------|
| $0.50 (min) | $0.10 | $0.40 | 20% |
| $1.00 | $0.10 | $0.90 | 10% |
| $2.00 | $0.10 | $1.90 | 5% |

---

## Option C: Separate Entry vs. Exit Slippage

**Premise:** Opening a spread in normal conditions (entry) is structurally different from closing under a stop loss (exit in adverse, potentially illiquid conditions). The worst fills in real trading happen at stops, not entries.

**Change:** Two-part implementation:

**Part 1 — Entry slippage (Option A or B applied to entry only):**
Use capped bar-range (Option A) or flat (Option B) for computing `credit` when the position opens.

**Part 2 — Exit slippage at stop loss:**
In `_check_intraday_exits()` and the daily-close exit path, when the exit reason is `stop_loss`, apply an additional exit debit:

```python
exit_slippage = 0.10   # $0.05/leg × 2, added to the spread cost to close
if reason == 'stop_loss':
    effective_spread_value = spread_value + exit_slippage
    pnl = (pos['credit'] - effective_spread_value) * pos['contracts'] * 100 - pos['commission']
```

Profit target exits don't take the additional exit slippage — those happen in favorable conditions (position is winning, market moving your way).

### Pros
- Most realistic: correctly penalizes stop-loss exits more than normal exits.
- Addresses the biggest real-world friction point: closing in a fast, adverse market is genuinely harder and more expensive than opening in calm conditions.
- Profit target exits (the majority of our trades at 84%+ WR) remain at standard friction.

### Cons
- Adds complexity — slippage logic in two separate places (entry in `historical_data.py`, exit in `backtester.py`).
- The exit slippage amount ($0.10) is still a judgment call.
- Any bug in "what exit reason am I in right now" could silently apply wrong slippage.
- Partially addresses an issue that the critique already flagged as a meta-level problem ("exit slippage unaddressed in PROPOSAL_BACKTEST_V3"). Fixing it here makes Problem 2 scope larger than originally defined.

---

## What's Missing from All Three Options

**Exit slippage at expiration is also unmodeled.** When a position expires with the short leg slightly OTM, it closes for near-zero value and the model records max profit. In live trading, the closing debit to get out before assignment risk (especially on Fridays near expiration) adds friction. None of the three options above address this. It's a smaller effect than stop-loss slippage and is noted for completeness — it can be handled separately.

---

## Recommendation: Option A with a Tighter Cap ($0.05/leg)

**Recommended implementation:**

```python
# In historical_data.get_intraday_spread_prices():
cap = 0.05  # per leg — configurable as backtest.slippage_per_leg_cap
slippage = min(sh_hl / 2, cap) + min(lg_hl / 2, cap)
# Max: $0.10 per spread, same total as Option B's flat model
```

### Why this specific formulation

Capping at $0.05/leg (rather than the $0.10/leg discussed in the critique) gives the best of both worlds:

1. **In quiet markets** (low bar range): slippage stays low, e.g., $0.01–$0.04 total. Captures real liquidity signal.
2. **In volatile markets** (bar range > $0.10/leg): slippage caps at $0.10 total. Identical to Option B's flat model at the upper bound.
3. **Min-credit trade impact**: $0.50 credit → max $0.10 slippage → $0.40 net. 20% haircut — same as Option B flat, but most trades in calm conditions will see much less ($0.02–$0.05 total).
4. **No new parameters to tune** beyond the cap value itself.

The $0.05/leg cap is the same as the existing config fallback value. This is not a coincidence — the fallback was set at a level consistent with actual SPY OTM bid/ask. The cap aligns the intraday model's worst-case with what the fallback already assumes.

### What to add alongside this: Option C's core insight (stop-loss exit slippage)

This should be implemented in the same PR as the entry fix. It's a single-line change per exit path:

```python
# In _check_intraday_exits() and daily-close exit, for stop_loss exits only:
exit_slippage_per_spread = 0.10   # add to closing cost in adverse conditions
if reason == 'stop_loss':
    spread_value_for_pnl = spread_value + exit_slippage_per_spread
```

This is the most under-modeled friction in the current codebase. Stop-loss exits are by definition happening in adverse conditions. Not charging additional friction here is the primary remaining way the backtest still flatters live performance.

---

## Implementation Scope

| Component | File | Change |
|-----------|------|--------|
| Entry slippage cap | `backtest/historical_data.py` | Cap `sh_hl/2` and `lg_hl/2` at `0.05` before summing |
| Exit slippage at stop | `backtest/backtester.py` | Add `exit_slippage` debit when `reason == 'stop_loss'` in `_check_intraday_exits()` and daily-close path |
| Config | `config.yaml` | Add `backtest.slippage_per_leg_cap: 0.05` and `backtest.exit_slippage: 0.10` |

**What does NOT change:**
- Profit target exit slippage (zero, these are favorable conditions)
- Expiration exit slippage (out of scope for Problem 2)
- Commission model (unchanged)
- Fallback slippage when no intraday data ($0.05 per spread — unchanged)

---

## Validation Plan

After implementing, re-run all three years and compare against the post-Problem-1 baseline from `RESULTS_INTRADAY_EXITS.md`. The metrics to watch:

1. **Average slippage applied at entry** — should be lower than current (bar-range outliers removed)
2. **Stop-loss trade P&L** — will get worse (by ~$10/contract = $0.10 × 100) as exit slippage bites
3. **Win rate** — may decline slightly (tighter net credit on entry, harder stop exits)
4. **Total P&L** — net effect unclear until measured; write a new `RESULTS_SLIPPAGE_FIX.md` with the delta

---

## What Carlos Needs to Decide

1. **Accept or override the $0.05/leg entry cap.** If empirical data shows OTM SPY bid/ask averages $0.08/leg rather than $0.05, use $0.08. The point is to pick a number grounded in market reality, not a formula.

2. **Include or defer Option C's exit slippage.** Including it makes the model more honest but widens the scope of the change. Deferring it is fine if the goal is to change one thing at a time — but it leaves a known gap open.

3. **Whether any of this matters given Problem 1's result.** Problem 1 raised P&L significantly because profit targets fired more. Problem 2 will push P&L back down modestly (more realistic slippage at entry + friction at stop exits). If Problem 1's gains are large enough, Problem 2's correction may be small in aggregate. Run it to find out — don't predict.

---

*Proposal written February 24, 2026. No implementation started. Awaiting review.*
