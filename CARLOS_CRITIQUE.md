# Carlos's Expert Critique of exp_058 — MUST ADDRESS ALL POINTS

## What's genuinely strong
* Fixed structural backtester issues that were silently killing trade count. The "Friday fallback + dedup fixes" changed opportunity capture from "missing a ton of valid trades" to "actually executing the intended strategy." That's not curve-fitting; that's repairing the measuring instrument.
* Regime logic is coherent: MA200 gating into bull put spreads vs bear call spreads is simple, interpretable, and matches "don't fight the tape."
* Hardening reality: commissions + slippage model, stop logic, profit target, and drawdown circuit breaker are the right "don't lie to yourself" components.

## The brutal truth: the "breakthrough" is mostly RISK AND THROUGHPUT, not magic edge
* 10% risk/trade uncapped is "the single biggest return driver." The headline 66% is NOT "we discovered alpha" — it's "we increased leverage/position sizing and took more bets."
* This is closer to "a high-throughput premium-selling engine with aggressive sizing" than a delicate predictive model.
* Premium-selling looks amazing until it doesn't. Lots of small wins, occasional large losses. The avg loss is multiples larger than avg win.

## RED FLAGS TO ADDRESS

### 1) "ROBUST ✅" is arguable — key robustness checks FAILED
* Walk-forward validation fails (1/3 folds pass; average ratio 0.539).
* Parameter sensitivity fails with cliff parameters (target_dte, spread_width).
* Regime diversity check fails due to concentration flags.
* A weighted average can say "0.737" while reality says the two most important "this will work later" tests are shaky.
* **FIX:** Walk-forward + sensitivity must become GATES (must pass), or composite must heavily penalize failures (not "partial credit" that still clears 0.70).

### 2) SPY expiration assumption is WRONG
* Report states "SPY expirations only occur on M/W/F." But SPY has had Tue/Thu expirations since 2022 — now has expirations EVERY trading day.
* The "Friday fallback" might be compensating for data gaps, but in real life you'd choose another listed expiration (including Tue/Thu).
* **FIX:** Either incorporate Tue/Thu expirations post-2022, or explicitly declare "we only trade M/W/F by design" and test whether that helps/hurts.

### 3) Execution realism: option OHLC bars are NOT bid/ask
* Slippage using (high − low) as "bid/ask spread proxy" is wrong. High/low are trade prints, not quotes. On illiquid strikes this can be wildly off.
* **FIX:** Move toward quote-based fills if possible. If not, run "brutality tests": multiply slippage by 2× and 3× and see if the strategy survives.

### 4) Portfolio-level margin / overlapping risk is under-specified
* 10% risk per trade × 5 concurrent positions = 50% max-loss exposure = hidden leverage.
* No simulation of broker margin requirements.
* **FIX:** Track sum of max losses across ALL concurrent open positions. Add max portfolio exposure cap (e.g., 30%). Simulate Reg-T margin.

### 5) 2021 100% win rate needs verification
* 40 trades, 100% WR, profit factor ~999. Possible but uncommon enough to demand:
  - Random spot-checks of individual trades against raw Polygon data
  - Verification that stops CAN trigger in that year under the pricing model
  - A "replay" tool that reconstructs entry/exit prices from raw data

## Carlos's verdict
* This is promising engineering progress, not "we found a money printer."
* Current headline performance is plausibly explained by: aggressive sizing, optimistic execution assumptions, incomplete constraints, short sample window (6 years) with one monster outlier (2022).

## Carlos's EXACT plan (in order):

1. **Lock down realism constraints**
   - Portfolio-level max exposure (sum of max losses across open trades)
   - Conservative "stop fill penalty" model (fast markets = worse fills)
   - Track whether a trade could realistically be opened with available margin

2. **Fix the expiration calendar assumption**
   - Either incorporate Tue/Thu expirations post-2022, or explicitly declare MWF-only as design choice
   - Quantify how often Friday fallback triggers and whether it biases results

3. **Replace the OHLC-based spread proxy**
   - Move toward quote-based fills if possible
   - If not, run brutality tests: 2× and 3× slippage multipliers

4. **Rework overfit gauntlet logic**
   - Make walk-forward and parameter sensitivity GATES or much heavier penalties
   - Use median or trimmed mean for walk-forward to reduce 2022 outlier effect

5. **Find a "stability plateau," not a cliff**
   - Map a grid (DTE 21–60, width $3–$10, credit floor variations)
   - Look for regions where returns degrade smoothly, not cliff edges
   - A real strategy has a "good enough" basin, not a razor's edge

6. **Forward validation in paper only**
   - Reveals fill ugliness, assignment quirks, market microstructure, operational friction

## The Monte Carlo DTE Randomization (HIGHEST PRIORITY)

* Remove hardcoded target_dte = 35
* On every entry signal, generate random integer between 28 and 42
* Run the entire 6-year pipeline 100 separate times with different seeds
* Calculate MEDIAN return and worst-case drawdown across all 100 runs
* If median drops from 66% to 20%, then 20% IS THE REAL EDGE
* A world-class AI system builder accepts the real number and scales it with appropriate capital

## Additional Directives
* Reinstate 5% risk cap — edge must prove itself through statistical expectancy, not leverage
* Strip outlier months (March 2020, January 2023) and run on only boring sideways months
* Introduce DTE randomization layer (28-42) to eradicate parameter cliffs
* The 66% number is DEAD. Find the REAL edge.

**CREATE A DETAILED PLAN addressing every single point above, then execute in priority order.**
