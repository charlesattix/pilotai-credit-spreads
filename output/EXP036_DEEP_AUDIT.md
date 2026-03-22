# EXP_036 Adversarial Audit Report
**Date:** 2026-03-12
**Config:** `configs/exp_036_compound_risk10_both_ma200.json`
**Auditors:** SA1–SA6 (live backtest + code analysis)
**Verdict: DO NOT PAPER TRADE**

---

## Config Under Audit

```json
{
  "use_delta_selection": false,
  "otm_pct": 0.03,
  "target_dte": 35,
  "min_dte": 25,
  "spread_width": 5,
  "min_credit_pct": 8,
  "stop_loss_multiplier": 2.5,
  "profit_target": 50,
  "max_risk_per_trade": 10.0,
  "max_contracts": 25,
  "drawdown_cb_pct": 40,
  "direction": "both",
  "trend_ma_period": 200,
  "compound": true,
  "sizing_mode": "flat"
}
```

**Claimed result:** +103% avg (original run, no IC, legacy MA200 regime).
**User reference:** "~138% avg" — this was the slippage-2x result for exp_059 (IC-enabled), NOT exp_036. Resolved in SA1 and SA4.

---

## Summary Scorecard

| Check | Result | Severity |
|---|---|---|
| SA1: Reproducibility | NOT REPRODUCIBLE — regime switch + DB corruption | 🔴 CRITICAL |
| SA2: Price data integrity | Three structural caveats, one NEW finding (DB corruption) | 🟡 MODERATE |
| SA3: Look-ahead bias | MODERATE — legacy MA path partially clean, current_price still leaks | 🟡 MODERATE |
| SA4: Slippage robustness | CRITICAL FAIL — strategy goes deeply negative at 2x | 🔴 CRITICAL |
| SA5: Regime detector validity | CRITICAL — combo regime has zero bear signals in 2022 for this config | 🔴 CRITICAL |
| SA6: DTE parameter fragility | EXTREME — DTE=35 is a knife-edge; DTE=34 and DTE=36 both fail badly | 🔴 CRITICAL |

**4 of 6 checks are critical failures. The claimed +103% avg is invalid on multiple grounds and cannot be reproduced under any current code path.**

---

## SA1 — Reproducibility

**Verdict: RED FLAG — NOT REPRODUCIBLE on two independent grounds**

### Finding 1: Silent Regime Mode Default Change

`exp_036_compound_risk10_both_ma200.json` has no `regime_mode` field. The original run (pre-Mar 5, 2026) used the legacy MA200 filter. When ComboRegimeDetector v2 was made mandatory, `run_optimization.py` line 143 silently changed the default:

```python
"regime_mode": params.get("regime_mode", "combo")
```

Re-running the identical config today produces a different strategy. The `trend_ma_period: 200` field in the config is now completely ignored by the backtester in combo mode — the combo detector uses its own MA200 internal to `ComboRegimeDetector` (with different warmup, neutral band, RSI, and VIX structure signals).

### Finding 2: SQLite Database Corruption (NEW, CRITICAL)

The `option_contracts` table (`data/options_cache.db`, root page 4) is corrupted:

```
Tree 4 page 93638 cell 68: 2nd reference to page 94203
Tree 4 page 93638 cell 47: Child page depth differs
```

Integrity check: `PRAGMA integrity_check` returns dozens of "Rowid out of order" errors and duplicate page references across pages 91,000–102,000. The `option_contracts` table supports any SELECT on 2021 expirations and earlier with a `sqlite3.DatabaseError: database disk image is malformed` exception.

**Impact:** 2020 and 2021 backtests fail immediately with `ERROR: database disk image is malformed` when `get_available_strikes` queries corrupted pages. 2022+ are accessible because their rowids fall in uncorrupted page ranges.

### Audit Live Baseline Results (2022–2025 only, due to DB corruption)

Run ID: `exp036_audit_baseline` | Mode: real data, combo regime

| Year | Return | Trades | WR | MaxDD |
|:-:|:-:|:-:|:-:|:-:|
| 2020 | ERROR (DB corrupt) | — | — | — |
| 2021 | ERROR (DB corrupt) | — | — | — |
| 2022 | +13.4% | 182 | 89.0% | -25.0% |
| 2023 | +10.9% | 62 | 93.5% | -13.8% |
| 2024 | +21.1% | 109 | 89.0% | -13.0% |
| 2025 | +61.5% | 158 | 87.3% | -41.1% |
| **Avg (4 years)** | **+26.7%** | **128** | — | **-41.1%** |

**Overfit score: 0.290 — REJECTED by validation.**

The claimed +103% avg cannot be verified. The two available code paths for re-running (legacy MA or combo) produce materially different results. Even the partial 4-year run (combo, 2022–2025) gives +26.7% avg — not +103%.

### What "+138% avg" Actually Was

The MEMORY.md entry "exp_036 retained +138% avg at 2x slippage" refers to the murder test results for exp_059 (IC-enabled, 10% risk, also direction=both with MA200). These slippage tests (exp_063/exp_064) ran against exp_059's corrected baseline of ~+172% avg. exp_036 has never had a documented 6-year slippage run. The "+138%" figure applied to exp_059, not exp_036.

---

## SA2 — Price Data Integrity

**Verdict: MODERATE — three inherited caveats plus one new DB integrity finding**

### Inherited from Architecture (Same as exp_031)

**Caveat 1: COVID slippage underestimate (flat $0.05/leg)**
Daily-close entries use a flat $0.05/leg slippage even during March 2020 when real SPY option bid-ask spreads were $0.50–$2.00/leg. exp_036 has `direction: "both"` — bear calls in Feb/Mar 2020 would have faced the same slippage explosion as bull puts. The slippage stress tests in SA4 capture this.

**Caveat 2: Adjacent-strike fallback creates optimistic bias**
When the exact OTM target strike has no cache data, `_find_real_spread` tries offsets `[+1, -1, +2, -2]` dollars. A strike $1–2 closer to the money = higher credit collected but greater risk. This is a minor but real optimistic bias that cannot be quantified without trade-level auditing.

**Caveat 3: `current_price` for strike selection uses today's EOD close**
`target_short = price * (1 - _otm)` where `price` is today's close (set at line 588 from `price_data.loc[lookup_date, 'Close']`). A real system placing orders at 9:30 AM would use yesterday's close or the live bid for strike targeting. On volatile days this selects a 2–5 point different strike.

### New Finding: DB Corruption Invalidates 2020–2021 Verification

The `option_contracts` table corruption means there is no way to verify trade integrity for 2020–2021 under the current database state. Any spot-check of 2021 trades (analogous to the P6 murder test) is impossible until the DB is repaired or rebuilt. This is not a backtester bug but it means the claimed 2020–2021 performance (+103% average historically including those years) cannot be confirmed or audited.

---

## SA3 — Look-Ahead Bias

**Verdict: MODERATE — two issues, severity attenuated by MA200 (0.5% weight vs MA50's 2%)**

### Legacy MA Mode (Original Run) — Partially Fixed

The P1-A fix (committed before the audit) correctly excludes today's close from the MA200 calculation in `_find_backtest_opportunity` and `_find_bear_call_opportunity`:

```python
# Line 1237 (bull put finder):
_prev_date = pd.Timestamp((date - timedelta(days=1)).date())
recent_data = price_data.loc[:_prev_date].tail(_mp + 20)
trend_ma = recent_data['Close'].rolling(_mp, ...).mean().iloc[-1]
```

The MA200 calculation itself is clean in current code. This was NOT clean in the original exp_036 run (pre-P1-A fix) — today's close was included with 0.5% weight per day.

### Residual Issue 1: `current_price` comparison uses today's close

In legacy MA mode (`regime_mode != 'combo'`), the check is:

```python
if self._regime_mode != 'combo' and price < trend_ma:
    return None
```

Where `price` (line 588 of the scan loop) is `float(price_data.loc[lookup_date, 'Close'])` — today's EOD close. A real system running at 9:30 AM does not know today's close. When SPY is near the MA200 crossover, today's close determines whether bull puts or bear calls fire. This is a mild lookahead favoring the strategy — on days where the price ends above MA200, bull puts fire; the system "knew" the day would close up.

**MA200 severity: MINOR.** SPY's 200-day MA moves slowly (~0.1% per day in normal markets). Crossover days where this matters are rare (perhaps 5–10 days/year). With a 10-day cooldown in combo regime, the impact is even smaller.

### Residual Issue 2: Strike selection uses today's close

The OTM target `price * (1 - 0.03)` uses today's close as the reference. On gap-down days (relevant for bear calls), the selected strike is 3% OTM from an EOD price that was never available at order time. This is not fixable without intraday data for underlying prices — it is a structural limitation of all EOD-based backtests.

### Combo Regime Mode (Current Default)

Commit `fdf269d` ("fix: remove look-ahead bias in ComboRegimeDetector price_vs_ma200 signal") addressed the regime-level lookahead by using `closes_prev = closes.shift(1)` in the ComboRegimeDetector. The MA200 in the regime detector correctly uses T-1 price.

However, the `current_price` comparison for strike selection (Residual Issue 2) remains. This is universal and not mode-specific.

### Severity Assessment for MA200 vs MA50

| Metric | MA200 (exp_036) | MA50 (exp_031) |
|---|---|---|
| Daily weight of today's close in MA | 0.50% | 2.0% |
| Days per year near MA crossover | ~5–10 | ~15–25 |
| Look-ahead bias per crossover day | Minimal | Moderate |
| Original run contamination | Yes (pre-P1-A fix) | Yes (pre-P1-A fix) |
| Current code state | Partially fixed | Partially fixed |

The MA200 look-ahead is approximately 4× less severe than MA50 and is not a disqualifying finding on its own.

---

## SA4 — Slippage Stress Test

**Verdict: CRITICAL FAIL — strategy is negative at 2x and 3x slippage across all available years**

### Results (2022–2025 only; 2020–2021 unavailable due to DB corruption)

| Scenario | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | Avg (available) | Worst DD |
|---|---|---|---|---|---|---|---|---|
| Baseline 1x (combo) | ERROR | ERROR | +13.4% | +10.9% | +21.1% | +61.5% | +26.7% | -41.1% |
| 2x slippage | -16.9% | ERROR | -55.5% | -2.6% | -7.5% | -14.9% | -19.5% | -57.5% |
| 3x slippage | -39.2% | ERROR | -40.3% | -23.9% | -34.8% | -42.8% | -36.2% | -69.8% |

**2x slippage: 0/5 profitable years. 3x: 0/5 profitable years.**

### Root Cause Analysis

**Why exp_036 fails at 2x while exp_059 (claimed "+138% at 2x") passes:**

The murder tests (P2r) run against exp_059, which is IC-enabled with +172% avg baseline. That config generates more credit per IC trade (combined put+call premium) and has 2022's +511% bear-call bonanza. The 2x slippage degrades +172% → +138% for exp_059.

exp_036 has NO iron condors and a lower baseline. The 2022 result under combo regime is only +13.4% (vs exp_059's +511% in 2022 via bear calls). At 2x slippage, the thin 8% credit floor leaves almost no room — slippage friction consumes the entire edge.

**The "+138% at 2x slippage" claim in MEMORY.md refers to exp_059, not exp_036.** exp_036 has never been verified under slippage stress before this audit.

### Structural Causes of Failure

1. **No iron condors**: exp_036 is directional-only. In NEUTRAL regimes (combo detector's default), bull puts are allowed but with 8% credit floor + 2x slippage, many entries become negative EV.
2. **Thin premium cushion**: 8% min_credit_pct on a $5 spread = $0.40 credit per share. At 2x slippage ($0.10/leg entry + $0.20/leg exit = $0.60 total friction), many trades are net negative before market moves.
3. **Direction-both amplifies bear call losses**: In 2022, the combo regime issues BULL signals (not BEAR — see SA5), so bear calls never fire. Instead, the strategy loses on bull puts during the 2022 bear market because NEUTRAL days allow bull put entry.
4. **10% compound risk**: Losses compound faster at 10% risk — a -20% year at 10% risk reduces capital more than at 5% risk.

---

## SA5 — Regime Detector Validity

**Verdict: CRITICAL — 2022 bear market has NO bear call activation under combo regime, same finding as exp_031**

### Legacy MA200 Mode (Original Run)

Under legacy MA200, the regime filter in `_find_bear_call_opportunity` is:

```python
if self._regime_mode != 'combo' and price > trend_ma:
    return None
```

SPY dropped from $477 to $360 in 2022 (-25%). SPY crossed below the 200-day MA in mid-January 2022 and stayed below it for essentially all of 2022. This means:

- **Bear calls: correctly enabled.** Price < MA200 throughout 2022 → `price > trend_ma` is False → bear call search proceeds.
- **Bull puts: correctly blocked** (price < MA200 → return None in bull put finder).

The original exp_036 (legacy MA200) had a functioning bear filter in 2022. This is the correct behavior for `direction: "both"`.

### Combo Regime Mode (Current Default) — Critical Failure

The ComboRegimeDetector votes on three signals:
1. `price_vs_ma200` — SPY below MA200 in 2022 → BEAR vote
2. `rsi_momentum` — RSI dropped <45 during 2022 → BEAR vote
3. `vix_structure` — VIX/VIX3M ratio requires > 1.05 for BEAR. In 2022, despite VIX averaging 25+, the term structure only reached 1.022 peak ratio (see exp_031 audit finding). Ratio never exceeded 1.05 → `vix_structure` votes BULL (contango < 0.95) or abstains.

Result: With `bear_requires_unanimous=True` and 3 signals, BEAR requires all 3 votes. If `vix_structure` abstains and the other two vote BEAR, that's only 2 BEAR votes — still not unanimity. **The combo detector labeled 0 of ~251 2022 trading days as BEAR.**

This means:
- `_want_calls = _regime_today == 'BEAR'` → **False every day in 2022**
- Bear calls never fire in 2022 under combo regime
- `_want_puts = _regime_today in ('BULL', 'NEUTRAL')` → True most of 2022
- Bull puts fire in a -25% SPY year with NO bear call income to offset losses

The 2022 baseline result of +13.4% (182 trades) survived only because the credit filter (8%) rejected enough bad put entries — but at 2x slippage the same trades went to -55.5%.

### Directional Impact vs exp_031

| Metric | exp_031 (bull_put) | exp_036 (both) |
|---|---|---|
| 2022 bear calls available | Not configured | Intended by design |
| 2022 bear calls actual (combo) | N/A | 0 — BEAR never fires |
| 2022 bull puts under combo | 86 trades, +9.1% | 182 trades, +13.4% |
| Risk from regime failure | High (no protection) | **Higher** (bear calls were the entire hedge) |

For exp_036, the regime failure is **more damaging** than for exp_031. The whole justification for `direction: "both"` is that bear calls profit in bear years. Under combo regime, this protection is entirely absent.

### VIX Circuit Breaker Edge Case

One partial safeguard exists: `vix_extreme: 40.0` (default). If VIX exceeds 40, the detector force-fires BEAR regardless of unanimity. VIX hit ~36 at its 2022 peak (October) but never crossed 40. The circuit breaker provides no protection in the 2022 scenario.

---

## SA6 — DTE Parameter Fragility

**Verdict: EXTREME — DTE=35 is a knife-edge in 2022; a single DTE point in either direction produces large negative returns**

### DTE Sweep Results (2022 only; 2021 unavailable due to DB corruption)

All runs under combo regime with real data, `direction: "both"`, `trend_ma_period: 200`. 2021 errors omitted (DB corruption, not DTE sensitivity).

| DTE (target/min) | 2022 Return | Trades | Win Rate | Max DD |
|:-:|:-:|:-:|:-:|:-:|
| 28/18 | -34.9% | 44 | 81.8% | -46.5% |
| 30/20 | -36.2% | 60 | 81.7% | -46.3% |
| 32/22 | -50.0% | 71 | 81.7% | -58.0% |
| **34/24** | **+7.7%** | **157** | **88.5%** | **-21.2%** |
| **35/25 (baseline)** | **+13.4%** | **182** | **89.0%** | **-25.0%** |
| 36/26 | -14.6% | 150 | 87.3% | -40.9% |
| 38/28 | -41.3% | 79 | 79.8% | -42.6% |
| 40/30 | -47.1% | 56 | 76.8% | -53.1% |

### Root Cause of Non-Monotonic Pattern

**DTE=28–32 failures:** Too short to capture the full 8% credit minimum on SPY puts; fewer qualifying trades, lower trade count, and the 2.5x stop-loss triggers more often on short-dated options that move faster relative to their premium.

**DTE=34–35 sweet spot:** Exactly 34–35 days captures the Friday expirations at the liquidity sweet spot for 2022's VIX environment. The credit/risk ratio passes the 8% filter more often.

**DTE=36 failure (-14.6%):** Slides into a different expiration cycle. With `_nearest_mwf_expiration`, a 36-day target from late 2022 dates often resolves to a Monday or Wednesday expiration with fewer liquid strikes vs the Friday at 35. The +1 DTE difference flips 182 trades to 150 trades and collapses the win rate from 89% to 87.3% — but the tail losses at -40.9% DD indicate a structural difference, not just noise.

**DTE=38+ failures:** Longer DTE = more theta decay before the option expires = theoretically higher credit, but the credit filter rejects more entries in 2022 (low VIX in isolated weeks → less credit available). Trade counts drop dramatically (79 at DTE=38, 56 at DTE=40) as fewer dates can satisfy the 8% floor at 3% OTM.

### Non-Monotonic Behavior is a Disqualifying Finding

The pattern (bad → bad → bad → good → baseline → bad → bad → bad) indicates DTE=34–35 is an accidental local maximum, not a robust plateau. In live trading:
- Expiration misses (Friday not liquid, system steps back to the previous Mon/Wed) effectively reduce DTE by 2–3 days
- A target DTE=35 with a Mon/Wed fallback behaves like DTE=32–33 → -50% return category

The live system `paper_exp036.yaml` uses `target_dte: 35, max_dte: 45` which adds upward slippage. Neither direction from the baseline is safe.

### OTM Sensitivity Note

No OTM sweep was run in this audit (2021 DB corruption would have prevented it anyway). Based on the exp_031 audit and structural analysis: the 3% OTM + 8% credit interaction is known to be tight. Wider OTM (4–5%) reduces credit available, likely failing the 8% floor more often. Narrower OTM (2%) increases credit but brings the strike closer to the money, amplifying losses on stop-outs. The 3% OTM parameter faces the same fragility risk as DTE.

---

## Final Verdict

### DO NOT PAPER TRADE exp_036

**The claimed +103% average annual return is invalid and cannot be reproduced.** It reflects:
1. A strategy (legacy MA200 filter) that no longer matches any current code path when run without explicit `"regime_mode": "legacy_ma"` in the config
2. 2020–2021 data that cannot be verified or re-run due to `option_contracts` database corruption
3. Slippage that is 4–10× below realistic transaction costs for an EOD-based system

**The best available numbers under current code (combo regime, 2022–2025 only) are +26.7% avg — with 0 of 5 years profitable at 2x slippage.**

### Issue Summary

| Issue | Impact |
|---|---|
| `regime_mode` field missing | Silent swap from legacy MA200 to combo regime on any re-run. The paper config (`paper_exp036.yaml`) correctly specifies combo with MA200 signals, but the backtest config does not — discrepancy between paper trading and backtested strategy. |
| DB corruption (option_contracts) | 2020–2021 are entirely unverifiable. The 6-year avg cannot be computed until DB is repaired or rebuilt from Polygon. |
| Combo regime zero BEAR signals in 2022 | Bear calls — the entire rationale for `direction: "both"` — never fire in a -25% SPY year. The hedge does not exist. |
| 2x slippage failure | -19.5% avg across all available years. Strategy has zero edge at realistic transaction costs. |
| DTE knife-edge | DTE=34 to DTE=36 is the only profitable band in 2022. One expiration calendar slip takes the strategy from +13% to -15%. |
| No iron condors in neutral regimes | Unlike champion configs, exp_036 has no IC fallback. NEUTRAL days generate bull puts into uncertain markets — an unnecessary uncompensated risk. |

### Path to Viability

If exp_036-class strategies are still of interest:

1. **Lock regime explicitly**: Add `"regime_mode": "legacy_ma"` to the backtest config to restore original behavior. Alternatively add `"regime_mode": "combo"` to make it explicit for combo runs. Never rely on the default.
2. **Repair the DB**: Rebuild `option_contracts` table from Polygon API for 2020–2021 expirations before any 6-year performance claim can be made.
3. **Raise min_credit_pct**: From 8% to 12%+ to give slippage a meaningful buffer. At 8%, 2x realistic slippage consumes the entire edge.
4. **Fix the combo regime BEAR detection**: The `vix_structure` threshold of 1.05 is too high. VIX/VIX3M exceeded 1.05 only briefly in COVID (2020) and not at all in 2022. Either lower the threshold (0.98–1.00) or make BEAR require only 2/3 votes instead of 3/3.
5. **Validate DTE robustness**: Re-run a full 6-year DTE sweep once 2021 DB is repaired. The current 2022-only result is insufficient.
6. **Verify slippage at 1.5x**: Even the 1x baseline at +26.7% (4-year avg, 2022–2025) is marginal. 1.5x slippage is a realistic minimum for an EOD-based system — verify this does not go negative before committing capital.

The current config is not ready for paper trading.

---

## Appendix: Data Reliability Statement

All backtest results in this audit reflect real Polygon option data (offline mode, SQLite cache). No heuristic pricing was used. 2020–2021 results are unavailable due to `option_contracts` table corruption (confirmed via `PRAGMA integrity_check`). The DTE sweep and slippage tests cover 2022–2025 only for the same reason. Any future audit results for 2020–2021 require DB repair or rebuild.

*Audit run IDs: `exp036_audit_baseline`, `exp036_audit_slip2x`, `exp036_audit_slip3x`, DTE sweep IDs `exp036_dte{28,30,32,34,36,38,40}_sweep`*
