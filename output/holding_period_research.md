# Holding Period Research: Credit Spreads & Iron Condors
## Do Our Backtester Results Match Real-World Expectations?

**Research Date:** March 10, 2026
**Author:** Claude Code (automated research)
**Purpose:** Validate backtester holding period and win rate data against published research

---

## Executive Summary

Our backtester reports the following for SPY/ETF credit spreads entered at 35 DTE with a 50% profit target and 3.5x stop loss:

| Strategy | Avg Hold | Win Rate | Primary Exit |
|---|---|---|---|
| Bull put spreads | ~12-14 days | 95% | Profit target |
| Bear call spreads | ~8-10 days | 100% | Profit target |
| Iron condors | ~19-20 days | 37% | Stop loss |

The research synthesis below evaluates each of these against available published studies, practitioner data, and academic findings.

**Bottom line upfront:** The bull put spread figures are broadly credible. The bear call spread 100% win rate is almost certainly a regime-selection artifact, not a real edge. The iron condor 37% win rate combined with 19-20 day holds is the most alarming finding — it is substantially below any published benchmark and is a strong signal of a structural problem with either the IC setup or the stop loss trigger.

---

## Section 1: What Real-World Practitioners Report for Holding Periods

### The Tastytrade Framework (Most Cited Reference)

Tastytrade is the dominant practitioner research source for credit spread holding periods. Their well-documented approach:

- **Entry:** 45 DTE (they consider this the optimal window where theta decay begins accelerating meaningfully)
- **Profit target:** 50% of credit received
- **Time-based exit:** 21 DTE (regardless of P&L)
- **Rule:** Close at whichever comes first — 50% profit OR 21 DTE

The 21 DTE rule is critical. Tastytrade's research found that at 21 days remaining, the ratio of gamma risk to remaining theta reward shifts unfavorably. Holding past 21 DTE exposes the trade to accelerating directional risk for diminishing marginal theta gain.

**Implied holding period from this framework:** An entry at 45 DTE that exits at 21 DTE (worst case) produces a 24-day maximum hold. A position that hits 50% profit early exits sooner. Tastytrade reports that managing at 50% profit "returns capital faster for redeployment" and is statistically superior to holding to expiration.

For a 35 DTE entry (as in our backtester) with a 25 DTE minimum close:
- Maximum hold before forced DTE exit: 10 days
- Expected hold for profit target hits: roughly 7-14 days

**Our 12-14 day bull put spread hold is consistent with this framework.** A 35 DTE entry with a 25 DTE minimum and a 50% profit target should naturally produce an average hold in the 10-17 day range, depending on how quickly theta erodes the premium.

### DTR Trading Research (96,624 SPX Iron Condor Trades)

DTR Trading published one of the most comprehensive iron condor backtests available, covering 96,624 trades on SPX from January 2007 through September 2016 (weekly options). Key findings:

- **At the 50% profit target level:** Winning trades were typically held **16-26 days** for 45 DTE iron condors
- **Shortest average DIT:** 16 days (achieved with 8-delta short strikes, 50% profit taking)
- **Key pattern:** Higher delta short strikes = longer average time in trade

For a 35 DTE entry (vs. their 45 DTE), scaling proportionally suggests a 50% profit target is typically reached in **10-20 days** — again consistent with our bull put spread data.

### Projectfinance Iron Condor Study (71,417 Trades, SPY)

Projectfinance analyzed 71,417 SPY iron condor trades across 16 management combinations:

- **16-delta iron condors:** Average days in trade ranged 18-44 days depending on management approach
- **30-delta iron condors:** Average days 15-40 days
- **Early profit-taking reduced holding periods by 40-50%** compared to hold-to-expiration approaches
- The 50-75% profit target approaches produced the best P/L expectancy for 16-delta condors

### Spintwig Research (Short Vertical Puts, 45 DTE)

Spintwig's backtesting on SPX vertical put spreads at 45 DTE found that:

> "Managing trades at 50% max profit or 21 DTE yielded average trade durations less than half those of holding till expiration."

If a 45 DTE spread held to expiration averages ~44 days, then managing at 50%/21 DTE yields approximately 20-22 days average hold. For a 35 DTE entry, this projects to 15-18 days average hold when managed.

**Summary on holding periods:** The weight of evidence suggests 10-20 day average holds are realistic and expected for 35-45 DTE entries managed at 50% profit. Our backtester's 12-14 day bull put and 19-20 day iron condor holding periods are within the documented range.

---

## Section 2: Is 12-20 Day Average Hold Realistic?

**Short answer: Yes, for the duration figures alone.**

The key variables driving time-to-50%-profit are:

1. **Delta of short strikes:** Higher delta = more premium but slower decay to target
2. **Market direction:** Favorable moves can hit profit target in days; adverse moves may never reach it
3. **Entry DTE:** Earlier entry means more time for theta to work, but slower decay initially
4. **Spread width relative to OTM distance:** Wider spreads with further OTM strikes collect less relative premium and decay more slowly

For a 35 DTE bull put spread with an OTM short strike:
- In a neutral-to-bullish market, theta decay alone (no directional help) typically produces ~50% premium erosion in **15-25 days**
- With directional tailwind (market rising for bull puts), the position can reach target in **3-10 days**
- Averaging fast wins (3-7 days) and slower wins (15-24 days) across market conditions plausibly produces a 12-14 day average

**The 12-14 day average hold is mechanically plausible.** It implies a mix of fast-moving wins and slower grind-to-target trades, which is consistent with practitioner experience.

---

## Section 3: Published Win Rates for Credit Spreads

### Bull Put Spreads

| Source | Win Rate | Setup |
|---|---|---|
| DTR Trading | 91-95% | 8 delta, 45 DTE, 50% profit target, no stop loss |
| Projectfinance | 77.6% | 16 delta, 30-60 DTE, long at 5 delta |
| Option Alpha | 93% | SPY put credit spread, no consecutive losses over 5 years |
| Data Driven Options | 85-90% | 20/13 delta, expires worthless without management |
| SJ Options backtest | 61% | SPX, 45 DTE, 50% profit, 200% stop loss (IVR 50-100 filter) |

The 95% win rate in our backtester for bull put spreads is at the optimistic end of the distribution. The DTR Trading study did find 91-95% win rates, but only for low-delta (8 delta) strikes with no stop loss. Our setup uses a 3.5x stop loss with what appears to be higher delta strikes (given the OTM pct config).

**Assessment:** The 95% bull put win rate is plausible but high. It would be consistent with:
- Far OTM strikes (small delta, low short strike)
- A regime filter that successfully avoids bear markets (our MA200 filter)
- The strong SPY bull trend 2020-2025 providing directional tailwind

It is NOT consistent with a fair representation of all market conditions. The MA200 regime filter likely plays a substantial role in producing this figure.

### Bear Call Spreads

| Source | Win Rate | Notes |
|---|---|---|
| Practitioner consensus | ~60-80% in bearish/sideways environments | Regime-dependent |
| Bull market periods | Near 100% in sustained uptrends | Calls expire worthless when market keeps rising |
| DTR Trading (call side of condors) | Similar to put side for symmetric setups | |

**The 100% win rate on bear calls is almost certainly a survivorship/selection artifact, not a real edge.** This requires direct examination:

Bear call spreads profit when the market stays below the short call strike. A 100% win rate means every single bear call spread entered expired or was closed profitably — no exceptions. There are two explanations:

1. **The MA200 regime filter selects only bear markets for bear call entries, and those bear markets were consistently short-lived with OTM calls expiring worthless.** Given the 2020-2025 period, this is implausible for multi-year data — the bear markets (2022 particularly) had violent rallies within downtrends that would have triggered bear call stop losses.

2. **The regime filter successfully timed all bear market entries, AND the 8-10 day average hold + 50% profit target means these trades are entered and exited quickly enough to avoid counter-trend rallies.** More plausible but requires testing.

3. **Selection bias:** If bear call entries are rare (filtered heavily by the MA200 + ComboRegimeDetector), a small sample size can show 100% WR by chance. Our memory notes that in 2023, bear calls were 13 trades with only 46.15% WR — which contradicts the "100% win rate" figure. This strongly implies the 100% figure is period-specific, not universal.

**Red flag:** Any 100% win rate in backtesting over multiple years across different market regimes should trigger immediate scrutiny. This is a well-documented overfitting/selection bias signal.

### Iron Condors

| Source | Win Rate | Setup | Notes |
|---|---|---|---|
| DTR Trading (best) | 91-95% | 8 delta, 45 DTE, no stop loss, 50% PT | Low delta, no SL |
| Projectfinance 16-delta | 65-77% | 30-60 DTE, combined mgmt | With combined P/L management |
| Theoretical (hold to expiration) | ~68% | 16-delta short strikes | Based on probability of expiring OTM |
| Projectfinance 30-delta | ~40-50% | Higher delta, 30-60 DTE | More aggressive setup |
| Tastytrade best practices | 65-80% | 20 delta, 45 DTE, 50% PT, 21 DTE exit | Combined management |
| Our backtester | **37%** | 35 DTE, 50% PT, 3.5x SL | **BELOW ALL BENCHMARKS** |

**The 37% iron condor win rate is a serious red flag.** It is:
- 30+ percentage points below the DTR Trading benchmark
- 28+ percentage points below the Projectfinance 16-delta study
- Below even the theoretical probability for 30-delta short strikes (~40%)
- Consistent with a broken stop loss trigger — specifically, a stop loss that fires too aggressively during the volatile portion of the trade

---

## Section 4: Diagnosing the Iron Condor Problem

### Hypothesis 1: Stop Loss at 3.5x Credit Is Too Tight

The 3.5x credit stop loss is more aggressive than most published research recommends. Tastytrade's own guideline evolved from "2x credit" to "2x credit for strangles" and generally "200% of credit" for defined-risk spreads. The projectfinance study found that a 200% (2x) stop loss already produced "close to maximum loss" outcomes for most trades.

A 3.5x credit stop loss on an iron condor means:
- **If you collected $1.00 credit total, you stop out at a $3.50 debit** — meaning the spread is trading at $4.50
- For a typical $5 wide iron condor, this stop fires at roughly **90% of maximum loss**
- This is essentially holding to near-max-loss on every loser

At 3.5x, you are taking the full loss on losers while only capturing 50% of max profit on winners. The math becomes:

```
Expected Value = (Win Rate × 0.5 × Credit) - (Loss Rate × 3.5 × Credit)
For breakeven: Win Rate = 3.5 / (3.5 + 0.5) = 87.5%
```

**A 3.5x stop loss on a 50% profit target requires an 87.5% win rate just to break even.** The 37% win rate would produce catastrophic losses. This strongly suggests either: (a) the stop loss is triggering on intraday noise and the real exit is worse than 3.5x, OR (b) the 37% win rate itself is correct but the strategy is net profitable because actual losses are less than 3.5x on average.

### Hypothesis 2: IC Stop Loss Triggers on Bid-Ask Spread / Intraday Noise

Iron condors have four legs. The bid-ask spread on each leg contributes to the "marked value" of the spread. If the backtester marks the position using mid prices during the day but stop loss logic checks against something noisier (last trade, ask side, or worst-case mid), the stop can trigger prematurely on normal bid-ask fluctuation even when the position would have recovered.

This is a well-documented backtesting artifact for multi-leg strategies. Signs of this problem:
- Average hold for stopped-out ICs would be short (a few days) — much less than the 19-20 days reported
- Stop losses trigger disproportionately during high-VIX / wide-spread periods
- Removing or loosening the IC stop loss dramatically improves the IC win rate

### Hypothesis 3: The Iron Condor Construct Doesn't Work With the Regime Filter

Our system only enters ICs when no bull put AND no bear call opportunity was found. This means ICs are a residual strategy entered in "regime-unclear" conditions. If the regime filter correctly identifies directional periods and assigns them to single-leg spreads, the remaining IC opportunities may be entered in genuinely difficult market conditions where neither side has a clear advantage — producing lower win rates structurally.

The DTR Trading study and projectfinance studies entered ICs unconditionally based on DTE. Our selective IC entry mode means the ICs we enter are different from those studied in published research.

---

## Section 5: Tastytrade Research Deep Dive

### "Managing Winners" Study (Key Tastytrade Finding)

Tastytrade's research on managing winners established several key quantitative findings:

1. **Closing at 50% profit increases win rate** relative to holding to expiration or 21 DTE exits alone. The combination of "50% profit OR 21 DTE, whichever comes first" showed higher win rates and better P/L per day than either rule alone.

2. **Study on 45 DTE strangles** showed that managing at 50% produced "higher win rates and P/L per day when actively managing strangles opposed to holding until expiration."

3. **Caveat from SJ Options critique:** An 11-year backtest on SPX credit spreads using tastytrade's published rules (sell at 1/3 spread width, 45 DTE, IVR 50-100, manage winners 50%, stop 2x credit) produced **negative total returns** at all capital allocation levels: -7% at 5% allocation, -19% at 10%, -56% at 25%, -93% at 50%. Seven of eleven years produced losses. This underscores that the tastytrade framework requires careful implementation and does not guarantee positive results.

### Tastytrade "Manage at 21 DTE" Study

Tastytrade's own analysis showed that managing early (at 21 DTE) produced "the same P/L but with larger losses while keeping positions 45 days open" — slightly contradicting their own recommendation. This illustrates that the marginal benefit of the 21 DTE rule versus 50% profit rule alone is modest, and that individual market conditions dominate.

---

## Section 6: Academic and Quantitative Research

### Absence of Peer-Reviewed Academic Literature

There is a notable absence of peer-reviewed academic papers that directly measure credit spread holding periods or win rates with specific profit targets. The practitioner literature (tastytrade, DTR Trading, projectfinance, spintwig, ORATS) is substantially richer than academic literature on this specific question.

Academic options research tends to focus on:
- Implied volatility risk premia (why selling options is theoretically profitable on average)
- Skew and term structure dynamics
- Jump risk and tail hedging

The practitioner consensus represents the best available data for our validation purposes.

### Theta Decay Mathematical Expectations

The theoretical expectation for time to 50% premium decay from first principles:

For a typical OTM credit spread entered at 35 DTE:
- Theta decay follows a nonlinear curve, accelerating as expiration approaches
- The first ~60% of calendar time (roughly days 35-15) captures approximately 40% of total theta
- The final ~40% of calendar time (days 15-0) captures ~60% of theta

This means a position entered at 35 DTE targeting 50% premium decay should typically:
- Hit target in **7-20 days** in a neutral market (pure theta)
- Hit target faster if the market moves favorably
- Take longer or never hit if the market moves against the position

This is consistent with our 12-14 day bull put average and confirms the backtester's timing logic is reasonable for winning trades. The key question is what happens to losing trades.

---

## Section 7: Red Flags and Validation Concerns

### Red Flag 1: Bear Call 100% Win Rate

**Severity: HIGH**

A 100% win rate over any multi-year, multi-regime period is an overfitting signal. The 2023 data already shows 46.15% bear call WR during the early-2023 recovery phase. The "100% win rate" aggregate almost certainly represents a subset of years where the regime filter happened to time the market perfectly, combined with a small sample size that makes statistical flukes look like edges.

**Recommended validation:** Isolate bear call trades by year and count. Any single year with fewer than 10 bear call trades can produce 100% WR by chance. Check whether the 100% WR spans the full 2020-2025 period or is dominated by 2022.

### Red Flag 2: Iron Condor 37% Win Rate

**Severity: CRITICAL**

This is below every published benchmark. Possible causes ranked by likelihood:

1. **Stop loss triggers prematurely on bid-ask noise or intraday price spikes** (most likely)
2. **IC entries are structurally disadvantaged by residual selection** (after regime filter removes directional opportunities)
3. **The 3.5x stop loss math requires ~88% WR to break even — 37% WR means the IC strategy is deeply loss-generating at the trade level**

If the IC component is being masked by profitable single-leg spreads, the overall system may appear profitable while the IC component drags returns. Isolating IC P&L by year would reveal this.

**Recommended validation:** Run the backtester with ICs disabled and compare total returns. If disabling ICs improves results, the IC implementation is the problem.

### Red Flag 3: 19-20 Day Average IC Hold Despite Mostly Stop-Loss Exits

**Severity: MEDIUM**

If ICs are exiting primarily via stop loss, you would expect shorter average holds (stop losses typically trigger faster than profit targets on volatile instruments). A 19-20 day average hold combined with mostly stop loss exits suggests the stop losses are triggering in the second half of the position's life — which would occur if the market stays sideways for 2-3 weeks then breaks out and triggers the stop near expiration.

This pattern is consistent with the thesis that the IC regime filter is selecting positions in choppy, range-bound conditions that eventually break out. The real-world IC playbook says to exit these positions before the breakout — which is exactly what the stop loss is doing, just at an expensive 3.5x level.

### Red Flag 4: The 50% Profit Target Math for ICs

For a 35 DTE iron condor with a 50% profit target AND 3.5x stop loss:
- Win: collect 50% of max profit in 19 days on average
- Lose: pay 3.5x credit in stop loss in 19 days on average (same time, different outcomes)

The breakeven win rate is: 3.5 / (3.5 + 0.5) = **87.5%**. Getting 37% when 87.5% is needed to break even means each IC entered loses money in expectation. Over hundreds of IC trades, this would be a significant drag. If the overall strategy is still profitable, it's because the bull put component is doing the heavy lifting.

### Red Flag 5: Regime Selectivity and Sample Size

**Severity: MEDIUM**

The MA200 + ComboRegimeDetector combination may filter out most IC opportunities to a small, unrepresentative sample. Small samples in backtesting produce unstable win rates. If ICs are entered on 15-20 occasions per year and stop losses trigger on 12-13 of them, the "37% win rate" may be a noisy estimate of a true rate that's anywhere from 25-60%.

---

## Section 8: Comparison to Published Studies

| Metric | Our Backtester | Published Benchmark | Assessment |
|---|---|---|---|
| Bull put avg hold | 12-14 days | 10-20 days (DTR, spintwig) | PASS — Within expected range |
| Bear call avg hold | 8-10 days | 7-15 days (theoretical) | PASS — Plausible for fast-moving profits |
| Iron condor avg hold | 19-20 days | 16-26 days (DTR, 45 DTE) | PASS — Duration is fine |
| Bull put win rate | 95% | 77-95% (various) | CONDITIONAL PASS — Requires regime check |
| Bear call win rate | 100% | 60-80% in bear markets | FAIL — Overfitting signal |
| Iron condor win rate | 37% | 65-95% (various setups) | FAIL — Structurally broken |
| IC stop loss level | 3.5x credit | 2x credit (tastytrade standard) | CAUTION — More aggressive than standard |

---

## Section 9: Verdict

### Overall Credibility Assessment

**The bull put spread data is broadly credible.** Holding periods of 12-14 days for 35 DTE entries with 50% profit targets align with multiple published studies. A 95% win rate is at the high end of the range but plausible given the MA200 regime filter selecting primarily bull market environments for bullish trades. The caveat is that this figure is likely artificially elevated by favorable regime selection in the 2020-2025 backtest period.

**The bear call spread 100% win rate is not credible as a general claim.** It is period-specific and/or sample-size-dependent. The 2023 data (46.15% WR on 13 bear calls) already falsifies the "100% win rate" hypothesis for the full period. The 8-10 day average hold is plausible — it suggests these trades are entered and quickly exited for profit, which is consistent with entering during confirmed downtrends where OTM calls decay rapidly.

**The iron condor data has a structural problem.** A 37% win rate is not just below benchmarks — it implies the IC component is reliably losing money per trade. Combined with a 3.5x stop loss that requires 87.5% WR to break even, the IC component is likely a significant P&L drag. The fact that overall strategy results are still positive implies the single-leg spread component is subsidizing the IC losses.

### Recommended Actions

1. **Immediately test with ICs disabled.** Compare 6-year returns with and without ICs. If removing ICs improves results, the IC implementation needs to be rebuilt.

2. **Audit IC stop loss trigger logic.** Check whether the stop fires on intraday mid-price or on a smoothed/end-of-day price. Multi-leg intraday marking is a common source of false stop triggers.

3. **Reduce stop loss to 2x credit for ICs** (matching tastytrade standard) and re-run. Compare win rates. If win rates improve substantially with a looser stop, the stop was triggering on noise.

4. **Analyze bear call win rate by year.** Determine which years contribute to the "100%" figure and whether 2022 (the only real multi-month bear market in the period) alone is driving it.

5. **Validate bear call entries are entering on quality signals.** The MA200 filter should catch the regime, but if bear calls are entered during short-lived dips in bull markets, the 100% figure disappears quickly in live trading.

6. **For the IC 19-20 day hold + stop loss dominance:** Check the average hold specifically for losing IC trades. If losing ICs average only 5-8 days, that's diagnostic of premature stop loss triggers. If they average 18-20 days (same as winners), the stops are firing near expiration in proper losing scenarios.

---

## Sources

- [Tastytrade — Managing Winners by Managing Earlier (2016)](https://www.tastytrade.com/shows/market-measures/episodes/managing-winners-by-managing-earlier-09-09-2016)
- [DTR Trading — 45 DTE Iron Condor Results Summary](http://dtr-trading.blogspot.com/2017/01/45-dte-iron-condor-results-summary.html)
- [Projectfinance — Iron Condor Management Results from 71,417 Trades](https://www.projectfinance.com/iron-condor-management/)
- [Projectfinance — Short Strangle Management Results (11-Year Study)](https://www.projectfinance.com/short-strangle-management/)
- [Spintwig — Short SPX Vertical Put 45-DTE Options Backtest](https://spintwig.com/short-spx-vertical-put-45-dte-s1-signal-options-backtest/)
- [Spintwig — Short SPX Iron Condor 45-DTE Options Backtest](https://spintwig.com/short-spx-iron-condor-45-dte-s1-signal-options-backtest/)
- [Option Alpha — 8 SPY Put Credit Spread Backtest Results](https://optionalpha.com/blog/spy-put-credit-spread-backtest)
- [SJ Options — Tastytrade Credit Spreads 11-Year Backtest](https://www.sjoptions.com/tastytrade-credit-spreads-do-they-work/)
- [Data Driven Options — The Credit Put Spread](https://datadrivenoptions.com/strategies-for-option-trading/favorite-strategies/credit-put-spread/)
- [Options Trading IQ — Iron Condor Success Rate](https://optionstradingiq.com/iron-condor-success-rate/)
- [Macroption — Iron Condor Success Rate and How to Predict It](https://www.macroption.com/iron-condor-success-rate/)
- [OptionsTradingOrg — 5 Ways to Backtest Options Without Getting Fooled](https://www.optionstrading.org/blog/backtest-options-strategies-without-fooled-by-overfitting/)
- [TalkMarkets — Managing Winners, Managing Early, and Managing Based on Theta](https://talkmarkets.com/content/options/managing-winners-managing-early-and-managing-based-on-theta?post=237791)
- [ORATS — Optimizing Options Backtests: DTE, Deltas, and Technical Indicators](https://orats.com/blog/optimizing-options-backtests-days-to-expiry-deltas-and-technical-indicators)
- [Days to Expiry — Theta Decay DTE Curves Guide](https://www.daystoexpiry.com/blog/theta-decay-dte-guide)
- [Quantified Strategies — Iron Condor Options Trading Strategy Guide](https://www.quantifiedstrategies.com/iron-condor-options-trading-strategy/)
- [Luckbox Magazine — Backtesting the Performance of Short Premium in 0DTE Options](https://luckboxmagazine.com/trades/backtesting-the-performance-of-short-premium-in-0dte-options/)

---

*Report generated: March 10, 2026. All research conducted via web search and page fetch. No direct access to tastytrade platform data or ORATS raw datasets.*
