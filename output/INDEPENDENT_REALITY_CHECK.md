# INDEPENDENT REALITY CHECK — Credit Spread Backtester Audit
**Auditor:** Claude (acting independently of prior project work)
**Date:** March 12, 2026
**Verdict: CARLOS IS RIGHT. The headline returns are not achievable in the real world.**

---

## Executive Summary

The champion config (exp_213) claims:
- 2020: +1,075%
- 2021: +2,643%
- 2022: +536%
- Average: +820%/year

After code analysis, this audit identifies **2 confirmed code bugs** and **4 structural model failures** that together make these figures meaningless as a real-world trading forecast. The returns are produced by mathematical compounding of a leverage regime that would be impossible at any real broker.

---

## CONFIRMED BUG #1: Commission Not Scaled by Contract Count (100x Error)

**File:** `backtest/backtester.py` lines 1606, 1359
**Code:**
```python
commission_cost = self.commission * 2  # Two legs
```

This charges **$0.65 × 2 = $1.30 per trade** regardless of how many contracts are opened.

**Reality for 100 contracts:**

| | Backtester | Reality |
|---|---|---|
| Spread round trip (100 contracts) | $2.60 | $260.00 |
| IC round trip (100 contracts) | $5.20 | $520.00 |
| Understatement per spread trade | — | **$257.40** |
| Understatement per IC trade | — | **$514.80** |

**Impact on 2021 (198 trades: 102 spreads + 96 ICs):**
- Missing commissions: **~$76,000** (76% of the $100K starting capital)
- These 76K in commissions simply don't exist in the backtester's P&L

This bug alone would wipe out most of the profit from smaller position sizes and significantly reduce headline percentages.

---

## CONFIRMED BUG #2: Exposure Cap is Completely Disabled

**File:** `backtest/backtester.py` lines 768–781
**Code:**
```python
def _exposure_ok(pos) -> bool:
    if self._max_portfolio_exposure_pct >= 100.0:
        return True  # ← BYPASS: no check at all
```

The champion config sets `max_portfolio_exposure_pct=100`, which **completely disables** the safety check. This function was designed to prevent over-leverage, but at 100% it returns `True` without inspecting anything.

Combined with `max_positions=50` (see below), this means the backtester will happily pile on unlimited simultaneous positions with no exposure constraint whatsoever.

---

## STRUCTURAL FAILURE #1: max_positions=50 is Hardcoded and Hidden

**File:** `scripts/run_optimization.py` line 165
**Code:**
```python
"max_positions": 50,  # hardcoded — not in config, not optimizable
```

This is a **critical risk parameter that is hidden from the optimizer and the config**. There is no way to set it from exp_213 or any other config JSON. It is always 50.

**Consequence: The backtester can hold up to 50 simultaneous 100-contract positions.**

| Metric | Value |
|---|---|
| max_positions | 50 |
| max_contracts | 100 |
| Max loss per spread contract | $470 |
| **Theoretical max total loss at $100K** | **$2,350,000** |
| **Leverage ratio** | **23.5× capital** |

No retail broker would extend this margin to a $100K account. In practice:
- A $5-wide, 100-contract spread requires **$50,000 in maintenance margin**
- 50 simultaneous positions → **$2,500,000 in margin required**
- Your $100K would be margin-called into oblivion after the first 2 positions

---

## STRUCTURAL FAILURE #2: No Margin Model — Capital Is Never Reserved at Entry

The backtester's capital (`self.capital`) is only updated when positions **close**. Opening a position deducts only commissions ($1.30) from capital. No margin hold, no capital reservation.

```python
self.capital -= commission_cost  # $1.30 — that's ALL that's deducted at entry
```

**Real-world mechanics:**
- Open a $5-wide bull put spread, 100 contracts → need $50,000 in margin reserved
- Backtester deducts: $1.30
- That $50,000 of unreserved "capital" is then used to size the NEXT position

This is how 50 simultaneous 100-contract positions become possible on a $100K account. Each position is sized as if the prior ones don't exist.

**The arithmetic that explains +2,643% in 2021:**
- 50 positions × 100 contracts = ~27 average simultaneously open (given 35-day DTE)
- Each IC win with $2.80 credit at 100 contracts, 50% PT: **$14,000 per win**
- 86 IC wins × $14,000 = $1,204,000 from ICs alone
- 92 spread wins × $1,500 = $138,000 from spreads
- Total: ~$1.34M on a $100K account = roughly +1,300%
- Add compounding (capital grows mid-year, sizing grows): pushes toward +2,643%

This is not "alpha." This is a no-margin-required leverage engine running in a computer simulation.

---

## STRUCTURAL FAILURE #3: Execution at Last Trade Price (Not Bid Side)

**File:** `backtest/historical_data.py` line 413–427
**Code:**
```python
short_close = self.get_contract_price(short_sym, date)  # returns daily close = last trade
spread_value = short_close - long_close  # no bid/ask adjustment in daily mode
```

When using daily bars (no intraday data available), the backtester fills at the **last trade price**. When you SELL an option spread:
- Reality: you fill at the **bid** (below last trade)
- Backtester: fills at **close** (last trade, which could be the ask or mid)
- For OTM options with low turnover: the "last trade" could be stale by hours

Intraday bars do apply slippage via `(H-L)/2 per leg`, which is a reasonable proxy. But daily-mode fallback fills — used whenever intraday data is missing — have **zero bid-ask modeling**.

---

## STRUCTURAL FAILURE #4: No Market Impact Model

At 100 contracts per trade, you are executing a significant fraction of daily volume:

| Typical daily volume for 3% OTM SPY puts | 200–2,000 contracts |
|---|---|
| Backtester order size | 100 contracts |
| You as % of daily volume | **5–50%** |

The backtester assumes you fill **100 contracts at a single price** with no market impact. In practice:
- You would work the order over time
- The spread widens as you consume liquidity
- You'd get progressively worse fills on larger orders
- For 100-contract orders, realistic market impact could be $0.05–$0.20 per share additional slippage (vs. the $0.05–$0.10 currently modeled)

---

## WHAT WOULD A REAL $100K ACCOUNT ACTUALLY PRODUCE?

Strip out the leverage fantasies and apply realistic constraints:

| Parameter | Backtester | Reality ($100K Account) |
|---|---|---|
| max_positions | 50 (hardcoded) | 5–10 (margin-constrained) |
| max_contracts | 100 | 5–10 (capital-constrained) |
| Commission per trade | $1.30 (bug) | $13–52 (per-contract) |
| Margin held per position | $0 | $5,000–$50,000 |
| Total capital at risk | Up to $2.35M | Up to $50K–100K |

**Revised return estimate with realistic constraints:**

From existing murder tests (which still use compound=True and the leverage engine):
- 2x slippage: +138% average
- 3x slippage: +101% average

These still have the 50-position, no-margin problem. With proper constraints:

| Year | Realistic Annual Return (estimate) |
|---|---|
| 2020 (COVID crash, bull recovery) | -30% to +60% |
| 2021 (relentless bull) | +40% to +80% |
| 2022 (bear market) | +60% to +120% (bear calls + ICs) |
| 2023 (chop) | -20% to +20% |
| 2024 (low VIX, few qualifying trades) | 0% to +30% |
| 2025 (bull) | +30% to +60% |

These are rough estimates based on the strategy's structural edge (high-probability OTM credit spreads) applied realistically. The strategy likely does have an edge — just not a 820% per year edge.

---

## ROOT CAUSE SUMMARY

| Issue | Cause | Impact |
|---|---|---|
| Bug: Commission 100x understatement | Missing `× contracts` in formula | ~76K drag on 2021 result, unreported |
| Bug: Exposure cap disabled | `if pct >= 100: return True` short-circuit | No leverage limit enforced |
| Design: max_positions=50 hardcoded | Buried in `_build_config`, not configurable | 23x leverage enabled |
| Design: No margin model | Capital not reserved at entry | 50 positions funded by "phantom capital" |
| Design: Last trade price fills | `get_contract_price` returns `close` | Systematic credit overstatement (daily fallback) |
| Design: No market impact | Linear fill assumption | Slippage understated for 100-contract orders |

---

## THE HONEST ANSWER

**Q: Is +820% average annual return real?**
A: No. It cannot be replicated at any real broker because:
1. You cannot hold 50 simultaneous 100-contract spreads on a $100K account
2. The commissions alone would be 76x higher than modeled
3. The fills assume mid-price execution with no market impact

**Q: Does the strategy have an edge?**
A: Probably yes — selling OTM credit spreads with regime filters and disciplined stops is a legitimate strategy. The edge is real but modest.

**Q: What should we present to Carlos?**
A: The non-compound, 10-contract, properly-margined version with correct commissions. The murder test result of **+101% avg at 3x slippage** (still with some structural issues) is probably the ceiling of honest representation. The floor might be **+20–50% annually** in normal years with realistic position sizing.

**Q: What is paper trading going to show?**
A: When paper trading starts (flat sizing, 25 max_contracts, $100K), returns will likely be in the range of **+15–40% annually** in favorable conditions. This is a perfectly respectable result for a credit spread strategy — just not +820%.

---

## RECOMMENDED FIXES

1. **Commission bug**: Change `commission_cost = self.commission * 2` to `commission_cost = self.commission * 2 * contracts` in both `_find_real_spread` and `_find_iron_condor_opportunity`

2. **max_positions**: Move to config with a realistic default of 5–10 for a $100K account

3. **Exposure cap**: Fix `_exposure_ok` to always compute exposure (remove the short-circuit at 100%), or remove the parameter and enforce margin-based limits

4. **Margin model**: Deduct `spread_width × 100 × contracts` from available capital at entry, refund at close

5. **Realistic benchmark**: Run the strategy with `max_positions=5`, `max_contracts=10`, correct commissions, and present THAT as the performance claim

---

*This audit was produced by independent code analysis of the backtester source. No assumptions about strategy validity were made — only the math and execution model were audited.*
