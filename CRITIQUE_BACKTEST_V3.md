# Critique: PROPOSAL_BACKTEST_V3.md

**Reviewer:** Claude Code
**Date:** February 24, 2026
**Status:** For Carlos review before implementation

---

## Summary Verdict

The core diagnosis is correct — exit granularity mismatched with entry granularity is a real bias, and the bar-range slippage model has legitimate flaws. Problems 1 and 2 are worth fixing. The multi-asset validation (Problem 4) is genuinely needed.

The execution details need sharpening in several places. Problem 3 is misclassified entirely. And the proposal's recommended implementation order makes performance attribution harder, not easier. Specific issues below.

---

## Problem 1 (Intraday Exits) — Directionally Right, Incomplete in Details

### The diagnosis is correct.
Exit granularity mismatched with entry granularity is a real structural bias. Fixing it is warranted.

### Holes in the proposed fix:

**1. The fix oversimulates exit precision relative to live trading.**
The live scanner runs every 30 minutes — not every 5 minutes. If a stop triggers at 10:47, you won't know until 11:00 and will fill at 11:00's price. The proposal simulates stops at every 5-min bar, which tests a better execution system than we actually have. This understates how late we catch exits in live trading vs. how precisely the backtest would catch them. The fix may overcorrect relative to actual live behavior.

**2. The data availability assumption is fragile.**
Option intraday bars are spotty on Polygon, especially for OTM contracts. The proposal says "fall back to daily close if intraday data is unavailable" — but if 30–40% of position-days fall back (common for the specific OTM strikes we trade), we've added significant complexity without actually fixing the problem for the most at-risk contracts. Before implementing, we need to measure what the actual fallback rate would be on a sample backtest run. If it's high, the "fix" is mostly a no-op with extra runtime.

**3. "Close at that bar's price" is undefined.**
Which price in the bar — open, close, high, low? For a stop triggered because the bar's high exceeded the threshold, a realistic fill would be somewhere between the high and the bar's close — not the high itself, and not necessarily the close. The proposal doesn't specify this. It matters for accurate P&L and for comparing runs before/after the fix.

**4. Pre-entry bar checks are not guarded against.**
If a position was entered at 13:00, the intraday exit loop must not check 9:30–12:55 bars on that same day. The implementation needs to slice intraday bars starting from `entry_scan_time`, not from market open. The proposal doesn't mention this edge case.

**5. The profit target effect runs in the opposite direction.**
Moving profit targets from daily-close to intraday means profit is taken *earlier* — at the first 5-min bar that crosses 50% credit decay, not at end-of-day. This will *increase* profitable-trade P&L relative to the current model. This partially offsets the stop-loss worsening, potentially making the net P&L impact significantly smaller than the "15–30% decline" estimate. The estimate appears to assume only stops are affected, ignoring the profit target acceleration.

**6. The "15–30% P&L decline" estimate has no empirical basis.**
We have no data on how frequently our specific positions spike intraday and recover before close. That number could be 5% or 50% depending on position behavior. The only honest path is to implement the fix and measure the actual impact. Putting a range on it in the proposal creates an expectation that may anchor the wrong interpretation of results.

---

## Problem 2 (Fixed Slippage) — Wrong Direction for Min-Credit Trades

### The flaw diagnosis is correct.
The bar-range proxy (high − low) / 2 does conflate directional price movement with bid/ask spread during volatile periods. That's a real issue.

### Holes in the proposed fix:

**1. 5% of width ($0.25) is disproportionately harsh at minimum credit.**
The minimum viable trade has credit = 10% of width = $0.50. After $0.25 slippage, net credit = $0.25 — a 50% haircut on the minimum-viable trade. Meanwhile, a high-credit trade at $1.50 takes only a 17% haircut. The fixed model is most punishing at exactly the threshold where trades are borderline, creating an artificial filter bias that doesn't reflect market reality.

**2. The SPY liquidity argument doesn't apply to the specific contracts we trade.**
"SPY options are among the most liquid in the world" is true for ATM and near-ATM options. Our OTM=3% short strikes at 35 DTE — particularly in low-IV environments when VIX is 12–15 — have materially wider bid/ask spreads because market makers price illiquidity into low-demand expirations. The liquidity claim is strongest for the options we're not trading and weakest for the ones we are.

**3. No separate entry vs. exit slippage.**
Slippage at entry (opening a spread in normal conditions) is structurally different from slippage at exit (closing under a stop loss in adverse, often illiquid conditions). A single fixed number for both understates exit friction and overstates entry friction. The worst fills happen at stops, not entries.

**4. The fixed model discards real signal in the bar-range data.**
Wider intraday bar ranges do correlate with wider bid/ask spreads in options — that's not noise, it's signal. The proposal correctly identifies that bar range conflates momentum with spread, but "therefore discard it entirely and use a flat number" doesn't follow. A better fix would cap the bar-range model (e.g., slippage = min(bar_range/2, 0.15 per leg)) to prevent outlier bars from inflating slippage, while keeping the correlation between vol and spread.

**5. A simpler defensible alternative exists.**
The current `config.yaml` already has `slippage: 0.05` as a flat fallback. A per-leg flat of $0.05 ($0.10 total per spread) is more consistent with actual SPY option bid/ask in normal markets, and is already in the codebase as a fallback. The proposal should justify why 5% of width is better than $0.05 per leg before replacing it.

**6. The fixed model introduces a mechanical minimum-credit floor.**
If slippage = $0.25 always, trades with credit < $0.25 (after slippage applied) become unprofitable by definition and get filtered. This creates an implicit minimum credit of $0.50 (spread filter) + $0.25 (slippage floor) = $0.75 effective net credit before any position is viable. In live trading, you'd still attempt those trades — you just might get worse fills. Pre-filtering them in backtesting isn't realistic.

---

## Problem 3 (IVR Filter) — Misclassified as a Backtester Fix

### This is not fixing the backtester. This is changing the strategy.

Problems 1 and 2 correct how the *existing* strategy's performance is measured. Problem 3 changes *which trades the strategy takes*. Measuring-tool fixes and strategy changes belong in separate categories and should be evaluated independently. Combining them makes it impossible to know which change drove which outcome.

### Specific issues:

**1. The IVR filter may be redundant with min_credit_pct.**
In 2024, the 26 empty weeks (Jan–Jun, VIX 12–18) were empty because no spread passed the 10% minimum credit threshold. IVR would also be low during those same weeks. The filter may block exactly the same dates the credit filter already blocks. This needs to be tested — if IVR provides no independent signal beyond min_credit_pct, it adds configuration complexity for zero benefit.

**2. Look-ahead bias in the 252-day rolling window.**
The IVR calculation requires 252 trading days of prior VIX data before it yields a valid value. For a backtest starting January 1, 2024, you need VIX history back to January 1, 2023 — that's available, so no problem there. But for the 2020 stress test (mentioned in Problem 4 as a stretch goal), you'd have no valid IVR for the first year of the COVID crash period. The proposal doesn't address how the warmup period is handled.

**3. Regime blindness during structural vol transitions.**
In a shift from a high-vol regime (2022, VIX averaging 25) to a low-vol regime (2024, VIX averaging 15), IVR is persistently low for the entire first year of the new regime — not because IV is genuinely cheap, but because the 52-week high is anchored to the old high-vol period. You'd avoid the market during an entire regime transition. That's not risk management; it's a mechanical lag in the filter.

**4. The IVR=25 threshold is completely unvalidated.**
The proposal picks 25 with zero analysis. This is exactly the kind of arbitrary parameter selection that led to the current state. At minimum, test IVR = 15, 20, 25, 30, 35 and verify there's a monotonic relationship between threshold and out-of-sample performance before picking a number. Otherwise we're adding a new parameter to overfit.

**5. VIX is a weak proxy for QQQ and IWM IV.**
VIX is specifically SPY's 30-day implied vol. It's a reasonable proxy for SPY, but QQQ's IV is driven meaningfully by mega-cap tech earnings cycles (NVDA, MSFT, META) that diverge from VIX, and IWM's IV routinely runs 5–10 vol points above VIX. Using VIX-derived IVR for QQQ/IWM backtests introduces material inaccuracy for exactly the assets the filter is supposed to improve.

**6. Deprioritizing MA20 is unsupported by evidence.**
The proposal says to "deprioritize MA20" in favor of IVR. But 109 trades from the winning config were all MA20-directional — 60 bull puts and 49 bear calls based on price vs MA20. That filter generated real edge in the validated backtest. There's no evidence MA20 should be subordinated to IVR. Adding IVR as a prerequisite gate could filter out trades that were genuinely profitable. The proposal asserts this is the right hierarchy without testing it.

---

## Problem 4 (Multi-Asset Validation) — Sound Instinct, Weak Framing

### Calling this a "fatal flaw" overstates it.
This isn't a bug in the backtester — it's a validation scope issue. The engine is correct; we just haven't run it on enough assets. Including it as a "fatal flaw" alongside the genuinely structural Problems 1 and 2 dilutes the urgency framing.

**1. QQQ and IWM in 2024 are not independent validation.**
SPY/QQQ correlation was ~0.90 in 2024. Both were driven by the same macro regime (soft landing narrative, rate cut expectations). Finding that the config works on both in 2024 tells us almost nothing about generalizability — we're testing two correlated tickers in the same regime, not the same strategy in different regimes.

**2. The 2022 and 2020 stress tests are what actually matter — and they're buried as a stretch goal.**
If the strategy works in 2024 (grinding bull, VIX 12–18) but fails in 2022 (trending bear, VIX 25–35) or 2020 (COVID crash, VIX 80+), we don't have a strategy — we have a bull market artifact. The stress tests should be required validation, not optional. They're the only way to know if the edge is structural or regime-specific. Burying them as a stretch goal is backwards.

**3. Polygon data availability for 2020–2022 is unverified.**
The proposal says "if Polygon data goes back far enough." This needs to be confirmed before planning tests around it. Our sandbox Polygon account's historical depth is unknown for options data specifically. We should check this before committing to 2020/2022 backtests.

---

## Meta-Level Issues with the Proposal Structure

**1. Problems 1 and 3 are entangled — the proposed implementation order makes attribution impossible.**
The proposal suggests implementing Problems 1, 2, and 3 in parallel. If win rate drops from 84.4% to 65%, we won't know: Did intraday stops cause the drop? Did the IVR filter remove good trades? Did both effects cancel each other? Each change must be isolated, measured, then combined. The correct order is: fix 1, rerun, record delta. Fix 2, rerun, record delta. Then add 3 as a deliberate strategy change, not a backtester fix.

**2. The most dangerous missing piece isn't in the proposal at all: assignment risk.**
Our `_close_at_expiration_real()` treats any spread value < $0.05 at expiration as "expired worthless = max profit." But if a short put expires $0.50 OTM on a Friday, there's a real probability of pin risk and assignment over the weekend — especially for ETFs around rebalancing dates. The backtest models this as max profit; live trading would not. This isn't addressed in the proposal and it inflates every expiration-profit trade.

**3. Exit slippage is unaddressed after the entry slippage fix.**
Problem 2 improves how we model entry slippage. But when closing a position at a stop or profit target, we still use the intraday bar's transaction price as the fill. In reality, closing a spread requires crossing the bid/ask on both legs — under adverse conditions (stop-loss scenario) or thin expiration-day markets. Exit fill quality is often materially worse than entry. The proposal fixes one side of the slippage equation while leaving the other entirely unmodeled.

**4. Tasks in the prompt and Tasks in the proposal conflict.**
The user's prompt (Tasks 1–4) and the proposal's Problems 1–4 largely overlap but differ in scope and framing. The prompt asks to implement the fixes; the proposal critiques the same fixes. If the critique surfaces that 5% slippage is too aggressive (which it is for min-credit trades), implementing it anyway per the prompt's Task 2 doesn't make sense. Carlos needs to adjudicate the slippage model before implementation proceeds.

**5. The P&L decline estimates have no empirical basis.**
"15–30% P&L decline from intraday exits" and "3–8% win rate decline" are stated as predictions without any supporting analysis. They anchor expectations in a way that could lead to misinterpreting results — if the actual decline is 5%, does that mean the fix "worked less than expected," or does it mean positions genuinely don't spike-and-recover as often as assumed? Running the fix and measuring is the only honest answer. Remove the estimates from the proposal.

---

## What the Proposal Gets Right

- The exit granularity mismatch (Problem 1) is a real structural bias and should be fixed.
- The bar-range slippage model has a legitimate flaw as described (Problem 2), even if the proposed fix needs refinement.
- The instinct on multi-asset validation (Problem 4) is correct — we need more than one asset and we need stress-test periods.
- The overall framing — "honest metrics will be lower, and that's the point" — is exactly the right mindset before deploying real capital.

---

## Recommended Path Forward

1. **Fix Problem 1 first, in isolation.** Implement intraday exits with 30-min scan granularity (matching live behavior, not 5-min). Measure the actual win rate and P&L impact on the 2024 baseline. This is the highest-signal change and should be understood alone.

2. **Reconsider Problem 2.** Don't use 5% of spread width. Options: (a) cap the bar-range model at $0.10/leg max slippage, (b) use $0.05/leg flat (already in config as fallback), or (c) use a regime-tiered model (lower slippage in low-VIX, higher in high-VIX). Discuss with Carlos before picking a number.

3. **Treat Problem 3 as a separate strategy experiment, not a backtester fix.** After Problems 1 and 2 are done, run a clean A/B: winning config with IVR filter vs. without. Test IVR thresholds empirically. Only adopt IVR if it demonstrably improves out-of-sample Sharpe without reducing trade count to the point of statistical insignificance.

4. **Move 2022 stress test to required, not stretch.** Confirm Polygon data availability for 2022 options. Run the fixed backtester on SPY 2022 before expanding to QQQ/IWM. If it fails the 2022 bear market test, multi-asset 2024 validation is irrelevant.

5. **Add assignment risk modeling before calling the backtester "fixed."** It's a smaller bias than exit granularity but it's real and easy to address: at expiration, if the short leg is within $1 of the underlying, model a 20% probability of assignment and apply the associated cost.

---

*"The first principle is that you must not fool yourself — and you are the easiest person to fool."*
— Richard Feynman

*Critique written February 24, 2026. All points are based on analysis of the current codebase, backtest results, and PROPOSAL_BACKTEST_V3.md. No implementation has been started.*
