# exp_031 Adversarial Audit — SA4: Realistic Slippage Model

**Date**: 2026-03-12
**Agent**: Sub-Agent 4 — Slippage Stress Test
**Config**: `configs/exp_031_compound_risk15.json` (bull_put, 15% risk, compound, MA50, 6yr)

---

## Baseline Notes

Two baseline runs exist in the leaderboard:

| Run ID | Source | Avg Return | Worst DD | Note |
|---|---|---|---|---|
| `exp_031_compound_risk15` | Original | +63.8% | -25.4% | Earlier run, possibly different code revision |
| `exp_031_audit_rerun` | SA1 rerun (Mar 12, 2026) | +22.2% | -46.2% | Reproduced today with current code |

**The SA1 rerun (+22.2%) is the authoritative baseline** — it reflects the current codebase including all backtester fixes. The original +63.8% result should be considered stale.

---

## Slippage Stress Results

| Scenario | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | Avg | Worst DD | Profitable Yrs |
|---|---|---|---|---|---|---|---|---|---|
| Baseline (1x, SA1 rerun) | +28.2% | +73.8% | +9.1% | +17.1% | +31.3% | -26.5% | **+22.2%** | -46.2% | 5/6 |
| 1.5x (bid-entry proxy) | +11.2% | +44.5% | -5.3% | +3.9% | +8.3% | -29.3% | **+5.5%** | -51.1% | 4/6 |
| 2x slippage | -18.3% | +20.7% | -27.9% | -7.2% | -11.7% | -26.5% | **-11.8%** | -68.5% | 1/6 |
| 3x slippage | -20.6% | -17.3% | -20.2% | -21.4% | -19.4% | -33.9% | **-22.1%** | -43.5% | 0/6 |

---

## Run IDs (leaderboard)
- Baseline: `exp_031_audit_rerun`
- 1.5x: `exp_031_bid_entry`
- 2x: `exp_031_slippage2x`
- 3x: `exp_031_slippage3x`

---

## Key Findings

### 1. Extreme slippage fragility — NOT the same as exp_036

Prior slippage tests on `exp_036` (the MA200 champion) showed:
- 2x slippage → avg dropped ~20% (from +172% to +138%)
- 3x slippage → avg dropped ~41% (to +101%)

**exp_031 is categorically different**: 2x slippage renders it **loss-making in 5/6 years** (-11.8% avg). The baseline +22.2% return is entirely consumed at 2x. This is not just a partial reduction — it is a complete loss of edge.

### 2. Why exp_031 is so fragile

- **15% risk per trade** with **compound=True**: slippage costs are amplified every time a position compresses credit. Because positions are sized at 15% of growing equity, even a small extra per-trade cost compounds into large capital destruction.
- **MA50 direction filter**: MA50 is a fast filter that generates ~100+ trades/year in trending markets. High trade frequency means slippage friction accumulates faster than in lower-frequency strategies.
- **Thin credit margin**: `min_credit_pct=8` is a relatively low bar. When slippage doubles, many trades that cleared 8% credit at entry become net negative after costs.
- **2025 is already negative (-26.5%) at baseline** — at 1x slippage, 2025 produced only 17 trades, most likely stopped out. This fragility was pre-existing before stress testing.

### 3. No `extra_slippage_per_leg` parameter exists

The backtester has no `fixed_slippage` or `extra_slippage_per_leg` field. The `slippage_multiplier` is the only per-trade friction dial. A separate $0.02/leg test was not run because:
- The multiplier already encompasses bid/ask spread dynamics modeled from intraday bars
- Adding fixed costs would require code changes outside the scope of this audit

### 4. 1.5x (bid-entry proxy) — barely positive, not viable

At 1.5x slippage (proxy for always filling at bid rather than mid):
- Avg return: **+5.5%** (vs. baseline +22.2%)
- 2 loss years (2022: -5.3%, 2025: -29.3%)
- 2020 worst DD widens to -51.1%

A 5.5% average annual return with -51% intra-year drawdowns is not a viable risk/reward profile.

---

## Verdict

**exp_031 FAILS slippage stress testing. The strategy has no edge at realistic transaction costs.**

The baseline +22.2% return (SA1 rerun) is already modest. At 1.5x slippage — a conservative estimate for real-world execution at bid rather than mid — the edge collapses to +5.5%. At 2x slippage — which is realistic for illiquid strikes or volatile market days — the strategy loses money in 5 of 6 years.

**Recommended action**: Do not advance exp_031 to live trading. The slippage sensitivity reveals the strategy is profitable only in the narrow band between modeled mid-price fills and real-world bid/ask friction. The 15% compound risk combined with the MA50 high-frequency approach creates compounding fragility that amplifies friction far more severely than lower-risk champion configs.

Compare to exp_213 champion (risk=23%, compound=True, MA200): that config produced +820% avg at baseline and remained profitable well above 2x slippage because the premium quality (min_credit_pct=28%) provides far more cushion per trade.
