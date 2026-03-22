# exp_031 Adversarial Audit — Sub-Agent 1: Reproducibility

**Audit date**: 2026-03-12
**Config**: `configs/exp_031_compound_risk15.json`
**Auditor**: SA1 (Reproducibility)

---

## 1. Config Under Test

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
  "max_risk_per_trade": 15.0,
  "max_contracts": 35,
  "direction": "bull_put",
  "trend_ma_period": 50,
  "compound": true,
  "sizing_mode": "flat"
}
```

Note: `regime_mode` is NOT specified in this config.

---

## 2. Original Run (Prior Result)

- **Run ID**: `exp_031_compound_risk15`
- **Timestamp**: 2026-02-26T22:34:19 (February 26, 2026)
- **Mode**: real data (Polygon, offline/cached)
- **Note**: "Phase 2: compounding 15% flat risk"

| Year | Return% | Trades | WR% | MaxDD% |
|------|---------|--------|-----|--------|
| 2020 | +81.11  | 107    | 97.2 | -25.36 |
| 2021 | +44.80  | 44     | 100.0 | -6.83 |
| 2022 | -20.71  | 12     | 66.7 | -23.24 |
| 2023 | +36.17  | 36     | 100.0 | -11.08 |
| 2024 | +69.74  | 119    | 89.1 | -21.49 |
| 2025 | +171.90 | 160    | 90.0 | -22.55 |
| **AVG** | **+63.84** | **80** | — | **-25.36** |

Summary: 5/6 profitable, overfit_score=0.834, verdict=ROBUST

---

## 3. Re-Run Results (This Audit)

- **Run ID**: `exp_031_audit_rerun`
- **Timestamp**: 2026-03-12 (today)
- **Mode**: real data (Polygon, offline/cached)
- **Code version**: HEAD (commit 822ab63)

| Year | Return% | Trades | WR% | MaxDD% |
|------|---------|--------|-----|--------|
| 2020 | +28.21  | 38     | 65.8 | -46.20 |
| 2021 | +73.75  | 102    | 99.0 | -2.96  |
| 2022 | +9.09   | 86     | 87.2 | -23.29 |
| 2023 | +17.05  | 62     | 93.5 | -18.86 |
| 2024 | +31.29  | 109    | 89.0 | -18.27 |
| 2025 | -26.48  | 17     | 64.7 | -32.13 |
| **AVG** | **+22.15** | **69** | — | **-46.20** |

Summary: 5/6 profitable

---

## 4. Year-by-Year Delta Table

| Year | Return ORIG | Return RERUN | Delta | Trades ORIG | Trades RERUN | Delta | WR ORIG | WR RERUN |
|------|------------|--------------|-------|------------|--------------|-------|---------|---------|
| 2020 | +81.11%  | +28.21%  | -52.90pp | 107 | 38  | -69   | 97.2% | 65.8% |
| 2021 | +44.80%  | +73.75%  | +28.95pp | 44  | 102 | +58   | 100.0% | 99.0% |
| 2022 | -20.71%  | +9.09%   | +29.80pp | 12  | 86  | +74   | 66.7% | 87.2% |
| 2023 | +36.17%  | +17.05%  | -19.12pp | 36  | 62  | +26   | 100.0% | 93.5% |
| 2024 | +69.74%  | +31.29%  | -38.45pp | 119 | 109 | -10   | 89.1% | 89.0% |
| 2025 | +171.90% | -26.48%  | -198.38pp| 160 | 17  | -143  | 90.0% | 64.7% |
| **AVG** | **+63.84%** | **+22.15%** | **-41.69pp** | **80** | **69** | **-11** | — | — |

---

## 5. Root Cause Analysis

### CRITICAL: Regime Mode Code Change

The original run (Feb 26, 2026) was executed **before** the ComboRegimeDetector was introduced (Mar 8, 2026, commit `b01ac4a`). At the time of the original run, `regime_mode` defaulted to the legacy `"ma"` behavior (single-MA filter using `trend_ma_period=50`).

By the time of this re-run, `run_optimization.py` defaults `regime_mode` to `"combo"` (line 143):
```python
"regime_mode": params.get("regime_mode", "combo"),
```

The exp_031 config file does NOT specify `regime_mode`, so it silently picks up the new `"combo"` default.

**Effect**: The ComboRegimeDetector uses a 3-signal voting system (price_vs_MA200, RSI momentum, VIX structure) with asymmetric BULL/BEAR thresholds and 10-day hysteresis. The legacy MA50 filter just checked whether SPY > MA50.

This is not a random fluctuation. This is a **systematic code change** that altered the effective regime filter across all 6 years:

- **2020**: Old regime (MA50) allowed 107 bull-put trades in the post-COVID bull run. New combo regime fired BEAR signals during March 2020 VIX spike and restricted entries. 107 → 38 trades, return collapsed from +81% to +28%.
- **2022**: Old regime (MA50) blocked most entries in the 2022 bear (bear market below MA50), yielding only 12 trades at -20.7%. New combo regime (MA200-based BULL) apparently found more BULL windows in 2022 recoveries: 86 trades at +9.1%.
- **2025**: Old regime with MA50 + compounded equity from strong 2024 led to 160 high-value trades at +171.9%. New combo regime blocked most 2025 entries (only 17 trades), resulting in -26.5%.
- **2021**: Improved under new regime (44 → 102 trades), return +44.8% → +73.75%.

### Secondary: Look-Ahead Bias Fix (commit 822ab63)

The most recent commit fixed a 1-day lookahead in `price_vs_ma200` signal. This has marginal impact per MEMORY.md (7-day cooldowns make 1-day shifts immaterial), but it is another difference between original and current code.

### Secondary: Backtester Scan-Logic Changes (commit 949d9a0)

Commit `949d9a0` includes scan-logic improvements (continue-inside-success-branch, `max_positions_per_expiration`). These affect trade counting per scan time and could contribute to some of the trade count deltas.

---

## 6. Verdict

**RED FLAG: NOT REPRODUCIBLE**

The results differ materially across all 6 years:
- Average return: **+63.84%** (original) vs **+22.15%** (rerun) — delta of **-41.7 percentage points**
- Worst-year drawdown: **-25.36%** (original) vs **-46.20%** (rerun)
- 2025 return: **+171.9%** (original) vs **-26.5%** (rerun) — completely inverted

However, this is **not a sign of stochastic noise or data corruption**. The non-reproducibility has a clear, documented, deterministic cause:

1. **The exp_031 config does not pin `regime_mode`**, so it inherits whatever the codebase default is.
2. The codebase default changed from `"ma"` (legacy MA50) to `"combo"` (ComboRegimeDetector v2) between the original run (Feb 26) and today (Mar 12).
3. Every leaderboard entry from before Mar 8, 2026 that lacks an explicit `regime_mode` field in its config is similarly non-reproducible under the current codebase.

---

## 7. Implications

1. **exp_031 as originally reported (+63.84% avg, ROBUST 0.834) cannot be reproduced today** with the same config file.
2. **The "corrected" exp_031 under current code** yields +22.15% avg — still 5/6 profitable, but significantly weaker.
3. **The overfit score from the original run is invalid** under the current regime filter, since the validation jitter also ran under the old regime.
4. **This is a systemic issue**: any config from before Mar 8, 2026 that lacks `regime_mode: "ma"` will now silently run under the combo regime and produce different results.
5. **Recommendation**: All pre-Mar-8 leaderboard entries should be re-tagged with `regime_mode: "ma"` in their config files, or clearly marked as "pre-combo" results that are not reproducible with the current codebase.

---

## 8. Additional Observations

- The 2022 swing from -20.71% to +9.09% under the new regime is counterintuitive: the combo regime (MA200-based) allowed more trades in what was a deep bear market year. This warrants separate investigation — the combo regime's BULL signal in 2022 may be problematic.
- The 2025 collapse from +171.9% to -26.5% with only 17 trades is concerning. The combo regime appears to have been BEAR-locked for most of 2025, blocking nearly all entries, then the 17 trades that were allowed mostly lost. This suggests the combo regime's 2025 behavior may need review.
