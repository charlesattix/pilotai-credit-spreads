# COMPASS Integration Experiment Proposal
### Systematic Re-Testing of COMPASS Signals on All Champion Configurations

**Author**: Claude Code
**Date**: 2026-03-08
**Status**: PROPOSAL — awaiting Carlos approval before any runs
**Prerequisite reading**: `output/compass_fix_proposal.md`, `output/compass_integration_analysis.md`

---

## 0. Executive Summary

Sprint 1 + Sprint 2 implemented and validated all COMPASS code changes. The post-Sprint-2 test on
`exp_102_compass_v2` returned **+26.2% avg, 6/6 years profitable**, vs the exp_090 baseline at
**+34.1% avg, 5/6 years profitable**. That 7.9pp drag looks like COMPASS is hurting — but the
comparison is apples-to-oranges for three reasons:

1. **exp_102_compass_v2 runs without `regime_mode: combo`**, so the RRG regime-confirmation gate
   never fires. The RRG filter blocks bull puts unconditionally in any regime.
2. **exp_090 baseline uses MA200 direction filter**, which produced exceptional 2022 results
   (+145.1%) by switching cleanly to bear calls. exp_102 uses the same MA200 filter BUT ALSO adds
   RRG blocks — an incoherent double-filter.
3. **The correct COMPASS baseline is exp_126/exp_154**, not exp_090. Both champions already use
   `regime_mode: combo`, making COMPASS regime-gate integration clean and semantically consistent.

The real question is: **does COMPASS improve exp_126 or exp_154's MC P50 and DD profile?**
That's what this proposal tests.

**Expected thesis**: COMPASS sizing (fear boost / complacency reduction) should reduce pre-crash
exposure and increase post-crash recovery sizing. Net effect on P50: neutral to modestly positive.
Net effect on max DD: materially improved in crash years (2020, 2025 tariff shock).

---

## 1. Current Baseline: What We Know

### 1.1 Champion Configs (Phase 6 Final)

| Config | Risk | IC Risk | avg det | max DD | MC P50 | Status |
|--------|------|---------|---------|--------|--------|--------|
| exp_090 | 10% flat | — | +34.1% | -26.9% | ~+21% est | Pre-Phase-6 reference |
| exp_126 | 8% flat | 8% IC (neutral) | +51.6% | -25.5% | **+32.5% ✓** | Carlos champion (opt.1) |
| exp_154 | 5% dir | 12% IC (neutral) | +54.6% | -28.9% | **+31.1% ✓** | Carlos champion (opt.2) |

### 1.2 exp_090 Year-by-Year (reference baseline)

| Year | Return | Max DD | Trades | Notes |
|------|--------|--------|--------|-------|
| 2020 | +37.5% | -26.9% | 188 | COVID crash + recovery |
| 2021 | +13.9% | -0.6% | 102 | Mild bull year |
| 2022 | +145.1% | -12.3% | 215 | Bear call bonanza |
| 2023 | -12.0% | -19.1% | 67 | Losing year |
| 2024 | +3.7% | -2.8% | 109 | Flat |
| 2025 | +16.3% | -10.1% | 164 | Tariff shock year |
| **Avg** | **+34.1%** | **-26.9%** | — | 5/6 profitable |

### 1.3 COMPASS v2 State (post Sprint 1+2)

Currently implemented in the backtester (all live after Sprint 2):

| Signal | Config Key | What It Does |
|--------|------------|--------------|
| **Risk Appetite Sizing** | `compass_enabled: true` | risk_appetite < 30 → 1.2×; < 45 → 1.1×; > 75 → 0.85×; > 65 → 0.95× |
| **XLI+XLF RRG Gate** | `compass_rrg_filter: true` | Blocks bull puts when XLI AND XLF both Lagging/Weakening AND `regime_mode: combo` confirms BEAR |
| **Event Gate** | *(not in backtester yet)* | Scales position size near FOMC/CPI/NFP events — requires Sprint 3 implementation |

### 1.4 Critical Architectural Note

**The COMPASS RRG regime-confirmation gate requires `regime_mode: combo`.** Without it, the code
path hits `_rrg_block = True` unconditionally — no regime confirmation. This is why exp_102's
performance was lower than expected: it ran RRG without the safety gate.

**Rule for all COMPASS experiments going forward**: Any experiment with `compass_rrg_filter: true`
MUST also include `regime_mode: combo`. A COMPASS config without combo mode is architecturally
inconsistent and will produce unpredictable results.

---

## 2. How COMPASS Modifies Each Experiment

### 2.1 Signal A: Risk Appetite Sizing (`compass_enabled: true`)

This multiplies `trade_dollar_risk` at line 1643-1644 of `backtester.py`:
```python
if self._compass_enabled:
    trade_dollar_risk *= self._current_compass_mult
```

**risk_appetite history** (from 323-week COMPASS dataset):

| Period | risk_appetite | Multiplier | Impact on Credit Spreads |
|--------|--------------|------------|--------------------------|
| 2020-02-21 (pre-crash) | **76.0** | **0.85×** | Smaller positions before COVID crash — DD protection |
| 2020-03-20 (COVID bottom) | **7.3** | **1.2×** | Larger positions during bounce — correctly contrarian |
| 2021 full year | ~55–70 | 0.95–1.0× | Mostly neutral, minimal drag |
| 2022 bear year | 36–48 | 1.0–1.1× | Slight size boost on bear calls — correct |
| 2025-01-03 (pre-tariff) | **76.3** | **0.85×** | Smaller positions before tariff shock — DD protection |
| 2025-04-04 (tariff bottom) | 47.1 | 1.0× | No adjustment (fear not extreme) |

**Concrete examples per champion config:**

**exp_126 (8% flat risk):**
- Feb 2020: 0.85 × 8% = **6.8% effective risk** (vs 8% baseline) — protects before COVID
- March 2020 recovery: 1.2 × 8% = **9.6% effective risk** — sells more premium at peak IV
- 2021 average: ~0.97× → ~7.8% effective risk — negligible drag
- 2022 fear weeks: 1.1 × 8% = **8.8% effective risk** — correct boost on bear calls

**exp_154 (5% dir + 12% IC):**
- Feb 2020: directional = 0.85 × 5% = **4.25%**; IC = 0.85 × 12% = **10.2%** — both legs reduced
- March 2020 recovery: directional = 1.2 × 5% = **6%**; IC = 1.2 × 12% = **14.4%**
- Note: the COMPASS multiplier applies to both directional and IC legs identically

### 2.2 Signal B: XLI+XLF RRG Gate (`compass_rrg_filter: true` + `regime_mode: combo`)

This only blocks bull puts when **both conditions are true simultaneously**:
1. XLI AND XLF are both in Lagging or Weakening quadrant
2. The combo regime detector says BEAR

**Structural reality** (323-week dataset): Only 4 XLI/XLF combos exist:
| Combo | Weeks | Years concentrated |
|-------|-------|-------------------|
| Leading + Improving | 98 wks | 2021, 2023, 2024 |
| Weakening + Lagging | 90 wks | 2020 Q1, 2022 H1, spread across all years |
| Leading + Lagging | 63 wks | Mixed (bull market sector rotations) |
| Weakening + Improving | 62 wks | Transitions |

XLF is never "Leading" or "Weakening" — it stays in {Leading, Improving, Lagging}. XLI is
never "Lagging" — it stays in {Leading, Improving, Weakening}.

Wait — CORRECTION (per Sprint 2 discussion): The data shows "XLI Weakening + XLF Lagging" as
the key pattern (90 weeks). This fires during genuine bear markets AND during bull-market sector
rotations. The regime confirmation gate (BEAR required) prevents the bull-market false blocks.

**Impact per champion config:**
- **exp_126 (IC-in-NEUTRAL mode)**: In BULL regime → bull puts; in NEUTRAL regime → ICs; in BEAR → bear calls. RRG gate only fires in BEAR regime. When regime=BEAR, the config already blocks bull puts (doing bear calls). So the RRG gate in exp_126 is essentially a **no-op** — the regime already handles it.
- **exp_154 (IC-in-NEUTRAL mode)**: Same architecture as exp_126. RRG gate also a near no-op.
- **exp_090 (direction: both, no IC-in-neutral)**: WOULD benefit more from RRG gate since it allows both directions and the RRG gate adds an additional filter.

**Conclusion on Signal B**: For our two champion configs (which use IC-in-NEUTRAL), the RRG gate
adds minimal additional filtering since the combo regime already handles direction. Its value is
higher for configs without strict IC-in-NEUTRAL mode (e.g., plain `direction: both`).

### 2.3 Signal C: Event Gate (NOT YET IN BACKTESTER)

The `macro_events` table is populated (192 rows, 2020–2025). The FOMC/CPI/NFP scaling factors
are live in `macro_event_gate.py`. **BUT the backtester does not yet load or apply this data.**

Implementing the event gate requires Sprint 3 (see Section 5.2). Do not run event gate experiments
until Sprint 3 is complete.

**Expected impact when implemented** (from integration analysis):
- ~25–30% of trading days are within an event window
- Average scaling factor during windows: ~0.75×
- Net position size impact: 0.75 × 0.25 + 1.0 × 0.75 = **0.94× average** (6% drag)
- Expected return drag: ~3–5pp per year
- Expected DD improvement: smoother equity curve around FOMC decision days

---

## 3. Experiment Matrix

### 3.1 Naming Scheme

Since we're at exp_159, COMPASS integration experiments begin at **exp_200**. This clearly marks
a new research phase and avoids confusion with Phase 1–6 parameter sweeps.

Group assignments:
- **exp_200–209**: exp_090 ablation series (COMPASS on pre-Phase-6 baseline, diagnostic only)
- **exp_210–219**: exp_126 ablation series (8% flat champion + COMPASS variants)
- **exp_220–229**: exp_154 ablation series (5% dir + 12% IC champion + COMPASS variants)
- **exp_230–239**: Cross-champion signal tuning (threshold adjustments)
- **exp_240–249**: Event gate experiments *(future — requires Sprint 3)*

### 3.2 Group 1: exp_090 Ablation (Diagnostic Only)

**Purpose**: Understand COMPASS impact on the pre-Phase-6 baseline. Corrects the exp_102 hybrid
design flaw by adding `regime_mode: combo` for consistency.

| Exp | Base | COMPASS Features | Config Key Differences |
|-----|------|-----------------|----------------------|
| **exp_200** | exp_090 | Sizing only | `compass_enabled: true`, regime_mode: combo |
| **exp_201** | exp_090 | RRG only | `compass_rrg_filter: true`, regime_mode: combo |
| **exp_202** | exp_090 | Sizing + RRG | Both above, regime_mode: combo |

**Why run these?** exp_102 is the only COMPASS test so far and it was architecturally flawed
(no combo mode). These provide clean data on COMPASS-per-feature impact on a simple 10% flat
base. Results are diagnostic — not expected to beat exp_126/exp_154 on Carlos metrics.

**Note**: These DO NOT include IC-in-NEUTRAL mode. They are direction: both + combo regime →
BULL/NEUTRAL → bull puts, BEAR → bear calls. This is pure directional with COMPASS overlay.

### 3.3 Group 2: exp_126 Champion + COMPASS (PRIMARY)

**Purpose**: Test whether COMPASS improves the **MC P50 champion** (exp_126: +32.5% MC P50).
Goal: maintain MC P50 ≥ 30% while reducing max DD.

| Exp | Base | COMPASS Features | Hypothesis |
|-----|------|-----------------|------------|
| **exp_210** | exp_126 | Sizing only | Pre-crash size reduction improves DD; fear boost helps 2022/2020 recovery |
| **exp_211** | exp_126 | RRG only | Near no-op (IC-in-NEUTRAL already handles direction); validates this theory |
| **exp_212** | exp_126 | Sizing + RRG | Combines both; RRG adds marginal value over sizing alone |
| **exp_213** | exp_126 | Full COMPASS (sizing + RRG) | Most complete; baseline for MC validation if det results are good |

**Key feature flags per experiment:**

**exp_210** — Sizing only:
```json
{
  "compass_enabled": true,
  "compass_rrg_filter": false,
  [all other exp_126 params unchanged]
}
```

**exp_211** — RRG only:
```json
{
  "compass_enabled": false,
  "compass_rrg_filter": true,
  [all other exp_126 params unchanged]
}
```

**exp_212** — Sizing + RRG:
```json
{
  "compass_enabled": true,
  "compass_rrg_filter": true,
  [all other exp_126 params unchanged]
}
```

Note: exp_126 already has `regime_mode: combo` — the RRG regime gate is active by default.

### 3.4 Group 3: exp_154 Champion + COMPASS (PRIMARY)

**Purpose**: Test COMPASS on the **5% nominal risk champion** (exp_154: +31.1% MC P50).
Same ablation structure as Group 2.

| Exp | Base | COMPASS Features | Hypothesis |
|-----|------|-----------------|------------|
| **exp_220** | exp_154 | Sizing only | 0.85× pre-crash reduces 2020 IC losses; 1.2× post-crash boosts recovery |
| **exp_221** | exp_154 | RRG only | Near no-op (same IC-in-NEUTRAL architecture as exp_126) |
| **exp_222** | exp_154 | Sizing + RRM | Combines both signals |
| **exp_223** | exp_154 | Full COMPASS (sizing + RRG) | Preferred version for MC test if det results pass |

### 3.5 Group 4: Signal Tuning (Run After Groups 2+3)

**Purpose**: Optimize COMPASS thresholds based on Group 2+3 results. Only run on the
best-performing base config from Groups 2+3.

| Exp | Modification | Rationale |
|-----|-------------|-----------|
| **exp_230** | Velocity multiplier: score_velocity < -8 → 0.90× additional | Cliff drops precede crashes (2020-02-21: RA was still 76 but dropping) |
| **exp_231** | Tighter complacency: ra > 70 → 0.85× (vs current ra > 75) | More fire coverage in 2021 peak; captures more greed weeks |
| **exp_232** | Softer complacency: ra > 80 → 0.85× (vs current ra > 75) | Reduces false positives in mild complacency; 2021 bullish trend preserved |
| **exp_233** | No fear boost: ra < 30 → 1.0× (disable the 1.2× boost) | Tests whether the fear boost helps or adds crash-period volatility |
| **exp_234** | Extended fear: ra < 45 → 1.2×; ra < 30 → 1.3× | More aggressive fear boost on the 16 extreme-fear weeks |

**Run order**: Run exp_230 first (velocity is the fix proposal's highest-conviction signal
enhancement). Then run the threshold variants in order only if the previous shows improvement.

### 3.6 Group 5: Event Gate Experiments (Future — Sprint 3 Required)

Do not run these until the backtester has `compass_event_gate` implementation. Listed here
for planning purposes.

| Exp | Base | Features | Notes |
|-----|------|----------|-------|
| **exp_240** | exp_126 | Event gate only | Sizing disabled; pure FOMC/CPI/NFP scaling |
| **exp_241** | exp_126 | Sizing + Event gate | Skip RRG (near no-op for IC-in-NEUTRAL) |
| **exp_242** | exp_126 | Full COMPASS (all 3) | Complete system validation |
| **exp_243** | exp_154 | Full COMPASS | Same for 5% champion |

### 3.7 Priority Order

```
PHASE A (run first — core tests):
  exp_210 → exp_220 → exp_212 → exp_222

PHASE B (ablations + comparison):
  exp_200 → exp_201 → exp_202 → exp_211 → exp_221

PHASE C (MC validation — only if Phase A det results look good):
  MC runs on best of {exp_210, exp_212, exp_220, exp_222}

PHASE D (signal tuning):
  exp_230 → exp_231 → exp_232

PHASE E (event gate — Sprint 3 first):
  exp_240 → exp_241 → exp_242 → exp_243
```

---

## 4. Expected Outcomes

### 4.1 Per-Experiment Forecasts

**Methodology**: Using the 323-week risk_appetite distribution and the known year-by-year
COMPASS state from the integration analysis.

#### Group 2: exp_126 + COMPASS

**exp_210 (exp_126 + sizing only)**:

Year-by-year sizing impact estimate:
- 2020: RA=76 in Feb → 0.85× → smaller pre-crash positions (-DD). RA=7 at bottom → 1.2× → bigger recovery sizing. Net 2020: slight improvement, maybe -2 to +5pp vs baseline +53%
- 2021: RA averaged ~62 → mostly 1.0×. A few weeks at RA>75 get 0.85×. Net 2021: -0 to -3pp vs baseline +60%
- 2022: RA averaged ~42 → 1.1× on bear calls. Net 2022: +3 to +8pp vs baseline +79%
- 2023: RA mostly neutral → minimal impact. Net 2023: ~+10% (unchanged)
- 2024: RA mostly neutral → minimal impact. Net 2024: ~+17% (unchanged)
- 2025: RA=76 in Jan → 0.85× → smaller pre-tariff positions. RA<45 during tariff shock → 1.1×. Net 2025: slight improvement on DD

**Projected det avg**: +52–58% (vs +51.6% baseline) — approximately flat to small positive
**Projected max DD**: -21 to -25% (vs -25.5% baseline) — expect improvement in 2020 and 2025
**MC P50 hypothesis**: +33–35% (vs +32.5% baseline) — small improvement from better DD profile

**exp_212 (exp_126 + sizing + RRG)**:

Additional RRG filter vs exp_210:
- In exp_126, IC-in-NEUTRAL means: BULL→puts, NEUTRAL→ICs, BEAR→calls
- RRG gate only fires in BEAR regime (combo gate active)
- In BEAR regime, exp_126 already wants calls, not puts
- RRG gate blocking `_want_puts = False` in BEAR is redundant (puts already unwanted)
- **Conclusion: RRG adds ~0pp impact on IC-in-NEUTRAL configs**

**Projected det avg**: Same as exp_210 (±1pp noise)
**MC P50 hypothesis**: Same as exp_210 (±0.5pp)

#### Group 3: exp_154 + COMPASS

**exp_220 (exp_154 + sizing only)**:

Same logic as exp_210 but at 5% dir / 12% IC risk:
- 0.85× on 5% dir = 4.25% effective before pre-crash
- 0.85× on 12% IC = 10.2% effective — IC exposure reduced when complacency high
- 1.2× on 5% dir = 6% effective during fear recovery — correct
- 2022: 1.1× on 5% dir = 5.5%, 1.1× on IC = 13.2% — slight boost in bear year

**Projected det avg**: +55–60% (vs +54.6% baseline)
**Projected max DD**: -24 to -28% (vs -28.9% baseline) — slight improvement from 2020 pre-crash
**MC P50 hypothesis**: +31–33% (vs +31.1% baseline) — modest improvement

**Biggest risk**: The IC in NEUTRAL during 2022 gets 1.1× sizing. 2022 was exp_154's best year
(+126% det). If the IC legs get BIGGER during the high-volatility FOMC-driven NEUTRAL weeks in
2022, this could boost 2022 returns further. But could also increase the occasional IC blowout.

#### exp_200 Series (exp_090 + COMPASS — diagnostic)

These are diagnostic only. With direction: both + combo regime:
- 2022: BEAR regime → bear calls → compass 1.1× → slightly bigger → 2022 probably +150%+
- 2020: BULL/NEUTRAL → bull puts → Feb 2020 RA=76 → 0.85× → pre-crash slightly smaller
- 2021: NEUTRAL → 1.0× mostly → no IC here, bull puts in neutral → ~+15%

**Projected exp_200 (sizing only)**: 2022 improves, 2020 similar, overall avg ~+35–38%
**Projected exp_202 (sizing + RRG)**: With combo mode, RRG fires in BEAR and blocks puts.
In BEAR regime, bear calls are preferred anyway. So still ~+35–38%.

### 4.2 Which Years Benefit Most from COMPASS?

| Year | Mechanism | COMPASS Impact | Direction |
|------|-----------|----------------|-----------|
| **2020** | Pre-crash: RA=76 → 0.85× before COVID. Post-crash: RA<30 → 1.2× in recovery | Smaller positions before crash, bigger during recovery | **Positive net** |
| **2021** | RA averaged ~62 → mostly 1.0×. A few weeks at 75+ get 0.85× | Minimal impact; slight drag if sizing restricted in late 2021 rally | **Neutral to slight negative** |
| **2022** | RA averaged 36–48 → 1.1× on bear calls. Fear signal fires correctly | Bigger positions on bear calls during high-fear rate-hike year | **Positive** |
| **2023** | RA mostly neutral (55–65) → 1.0× throughout | No impact | **Neutral** |
| **2024** | RA mostly neutral, occasional mild complacency | Minimal impact | **Neutral** |
| **2025** | RA=76 in Jan → 0.85× before tariff shock. RA~47 during shock | Smaller positions before tariff event; marginal improvement | **Small positive** |

**Net verdict**: COMPASS sizing is slightly net-positive for the champion configs. The
complacency reduction in 2021 is the one risk (could drag +60% to +58%), but 2020 and 2022
improvements likely offset this.

### 4.3 Hypotheses Being Tested

| Experiment | Core Hypothesis | Passing Criteria |
|-----------|----------------|-----------------|
| exp_210 | Risk appetite sizing (r=-0.250) translates to measurable DD reduction | 2020 max DD improves by ≥3pp AND MC P50 ≥ +32.5% |
| exp_211 | RRG gate is near no-op on IC-in-NEUTRAL configs | 2020–2025 returns within ±2pp of exp_126 |
| exp_212 | Combined sizing + RRG ≈ sizing only for IC-in-NEUTRAL | Within ±2pp of exp_210 on every year |
| exp_220 | COMPASS sizing on 5% nominal risk config | MC P50 ≥ +31.1% AND max DD ≤ -28.9% |
| exp_200–202 | Clean exp_090 COMPASS ablation (diagnostic) | Understand signal isolation, no specific criteria |
| exp_230 | Score velocity (<-8 → 0.90×) captures cliff drops before RA threshold fires | 2020 DD improves vs exp_210 |
| exp_231 | Tighter complacency at RA>70 fires more often (more 2021 coverage) | 2021 DD decreases; 2021 return stays >50% |

---

## 5. Implementation Requirements

### 5.1 What Can Run Today (Groups 1–4)

All Group 1–4 experiments require **zero code changes**. The backtester already supports:
- `compass_enabled: true` — risk appetite sizing
- `compass_rrg_filter: true` — XLI+XLF RRG gate with regime confirmation (requires combo mode)
- `regime_mode: combo` — already present in exp_126 and exp_154

Estimated run time: ~10 seconds per experiment (6-year full run). A Phase A batch of 4
experiments takes under 2 minutes.

### 5.2 What Requires Sprint 3 (Group 5 — Event Gate)

The backtester currently has no `compass_event_gate` parameter or corresponding data loading.
Sprint 3 requires:

1. **New backtester parameter**: `compass_event_gate: bool` in `__init__`
2. **New data cache**: `self._compass_event_by_date: dict` populated by `_build_compass_series()`
3. **Data loader change**: `_build_compass_series()` must load from `macro_events` table and
   compute event scaling factors by trading date
4. **Sizing integration**: Apply event scale factor in `_calculate_position_size()` after
   COMPASS multiplier (both apply multiplicatively):
   ```python
   if self._compass_event_gate:
       trade_dollar_risk *= self._current_event_scale
   ```
5. **Key design decision**: Event scaling is computed dynamically (trading_date → days_out →
   scaling), NOT read from stored `days_out` column (which reflects run-date, not backtest date)

Sprint 3 is estimated at ~2 hours of work. It should NOT block the Group 1–4 experiments.

### 5.3 MC Validation Plan

Run MC simulation ONLY if the winning experiment from Phase A+B shows:
- Det avg ≥ the baseline det avg of the same config
- Max DD ≤ the baseline max DD of the same config (COMPASS should not make DD worse)
- 6/6 profitable years maintained

If those gates pass, run MC with 200 seeds (U(33,37) DTE range) to get the definitive P50.
MC target: maintain the same P50 as the COMPASS-off version (P50 ≥ 30% for both exp_126 and
exp_154 derivatives).

---

## 6. What Should We Name It?

Carlos asked for a cool name for the COMPASS macro overlay system. Here are 10 options with
rationale, ranked by how well they fit the system's actual function:

---

### Option 1: TIDE ⭐⭐⭐⭐⭐ (recommended)
**T**actical **I**ntelligence for **D**ynamic **E**ntry

**Why**: Macro regimes are like tides — they're real, cyclical, and larger than any individual
trade. High tide (fear/VIX) is when credit spread conditions are richest (premiums elevated).
Low tide (complacency) is when you scale back. The system literally adjusts your "depth" in the
market based on where we are in the macro cycle. Simple word, strong metaphor, easy to say.

**Usage**: "TIDE says 1.2× today — extreme fear, max the bull put sizing."

---

### Option 2: BEACON ⭐⭐⭐⭐
**B**readth, **E**vent, **A**ppetite, **C**onditions **O**verlay **N**ode

**Why**: A beacon guides ships in dangerous conditions — it warns of rocks (FOMC decisions,
sector deterioration) and shows safe passage. The metaphor fits: BEACON tells you when to pull
back (complacency, approaching FOMC) and when to press (fear, sector health strong).

**Usage**: "BEACON is flashing amber — 3 days to FOMC, event scale at 0.70×."

---

### Option 3: PRISM ⭐⭐⭐⭐
**P**ositioning **R**isk **I**ntelligence & **S**ector **M**omentum

**Why**: A prism refracts a single beam of white light into its component wavelengths. COMPASS
does the same for market data — it decomposes the macro signal into three distinct sizing signals
(risk appetite, sector health, event proximity) and combines them into a single multiplier.

**Usage**: "PRISM is giving us 0.95× today — mild complacency, sectors healthy."

---

### Option 4: ARBITER ⭐⭐⭐⭐
**A**daptive **R**isk-**B**ased **I**ntelligence for **T**rade **E**ntry **R**egulation

**Why**: The system literally arbitrates whether and at what size a trade happens. It's the
judge — not the strategy, just the regulator. Fits the "optional overlay" design philosophy.

**Usage**: "ARBITER blocked the bull put — XLI and XLF both lagging in BEAR regime."

---

### Option 5: KEEL ⭐⭐⭐⭐
**K**inetic **E**quity-at-risk and **E**vent **L**ayer

**Why**: A keel provides stability — it counteracts the rolling forces that would capsize a boat.
COMPASS/KEEL counteracts the emotional forces that would capsize your account: complacency-driven
oversizing before crashes, and fear-driven undersizing at peak premium opportunities. The
passive-stability metaphor is honest — it's not alpha generation, it's drawdown management.

**Usage**: "KEEL adjusted risk to 6.8% today — complacency signal at 76."

---

### Option 6: ANCHOR ⭐⭐⭐
**A**daptive **N**ews, **C**onditions, **H**orizon, and **O**pportunistic **R**isk **R**egulation

**Why**: An anchor keeps a vessel from drifting in rough seas. The system anchors position sizing
to macro reality, preventing drift toward oversizing in calm markets.

---

### Option 7: PULSE ⭐⭐⭐
**P**ositioning **U**nder **L**ive **S**ector & **E**vents

**Why**: Vital signs metaphor — PULSE monitors the market's health (sector momentum) and
near-term stress events (calendar). A strong pulse → size up. Irregular/weak → scale back.

---

### Option 8: SONAR ⭐⭐⭐
**S**ector **O**verlay, **N**ews, **A**ppetite, & **R**egime

**Why**: Sonar detects what's below the surface — hidden risks (approaching FOMC, sector
deterioration) that aren't visible in price alone. Fits the "detecting macro subsurface risks"
narrative.

---

### Option 9: MERIDIAN ⭐⭐
**M**acro-**E**vent-**R**egime **I**ntelligent **D**ynamic **I**nvestment **A**llocation
**N**ormalizer

**Why**: Meridians are reference lines (like the Prime Meridian) that other measurements are
calibrated against. COMPASS normalizes position sizing against the macro reference state.
More elegant than functional — the acronym is a stretch.

---

### Option 10: COMPASS (keep it) ⭐⭐⭐⭐
**C**omposite **M**acro **P**osition & **S**ector **S**ignal

**Why not change it**: The name already works. COMPASS: it gives you your bearing. North = max
sizing (extreme fear). South = minimum sizing (extreme complacency). It's a known quantity to
Carlos after months of work. Changing it adds friction with zero operational benefit.

---

### Naming Recommendation

**Primary recommendation: TIDE**. Clean four-letter word, excellent metaphor for macro cycles,
contrarian in direction (fear = high tide = richest premiums for credit spread sellers), and it
sounds good in operation: "TIDE is at maximum fear today — 1.2× sizing."

**If Carlos wants to keep COMPASS** for brand continuity but rename the three sub-signals:
- Signal A (risk appetite sizing): **CURRENT** — follows the macro current
- Signal B (sector breadth gate): **REEF** — the XLI/XLF reef warning you off bull puts
- Signal C (event proximity): **SQUALL** — the upcoming storm that reduces exposure

---

## 7. Decision Points for Carlos

Before any runs begin, Carlos should decide:

**D1: Primary test group**
Recommend starting with Group 2 (exp_126 + COMPASS sizing = exp_210) since exp_126 is the
confirmed MC champion. This gives the cleanest signal on COMPASS value-add.

**D2: RRG filter inclusion**
Given the analysis showing RRG is a near-no-op on IC-in-NEUTRAL configs, we recommend running
exp_211 (RRG only) to empirically confirm the no-op hypothesis before including it in any MC run.
If confirmed, skip RRG in the "full COMPASS" experiments for IC-in-NEUTRAL configs.

**D3: MC trigger threshold**
How much improvement in det max DD is enough to justify an MC run?
Recommend: if exp_210 or exp_220 shows max DD improvement ≥ 3pp vs baseline with no avg return
regression, run MC immediately.

**D4: Name**
Decide on the name before configuring Phase A experiments, so all new config files use the
correct naming convention (e.g., `exp_210_tide_exp126_sizing.json`).

**D5: Sprint 3 priority**
Should event gate Sprint 3 be implemented before or after Phase A+B results? Recommend
after — Phase A+B take 2 minutes, and their results may change which base config to implement
event gate on. No reason to sprint on event gate before seeing sizing results.

---

## 8. Full Experiment Config Specifications

### exp_200: exp_090 base + COMPASS sizing + combo regime
```json
{
  "base_config": "exp_090",
  "max_risk_per_trade": 10.0,
  "iron_condor_enabled": false,
  "direction": "both",
  "regime_mode": "combo",
  "regime_config": {"signals": ["price_vs_ma200", "rsi_momentum", "vix_structure"],
    "ma_slow_period": 200, "ma200_neutral_band_pct": 0.5,
    "rsi_period": 14, "rsi_bull_threshold": 55.0, "rsi_bear_threshold": 45.0,
    "vix_structure_bull": 0.95, "vix_structure_bear": 1.05,
    "bear_requires_unanimous": true, "cooldown_days": 3, "vix_extreme": 40.0},
  "compass_enabled": true,
  "compass_rrg_filter": false,
  "drawdown_cb_pct": 40,
  "stop_loss_multiplier": 2.5,
  "profit_target": 50,
  "otm_pct": 0.03,
  "target_dte": 35,
  "min_dte": 25,
  "spread_width": 5,
  "min_credit_pct": 8
}
```

### exp_210: exp_126 + COMPASS sizing only
```json
{
  "base_config": "exp_126",
  [all exp_126 params unchanged],
  "compass_enabled": true,
  "compass_rrg_filter": false
}
```

### exp_211: exp_126 + COMPASS RRG only
```json
{
  "base_config": "exp_126",
  [all exp_126 params unchanged],
  "compass_enabled": false,
  "compass_rrg_filter": true
}
```

### exp_212: exp_126 + COMPASS sizing + RRG
```json
{
  "base_config": "exp_126",
  [all exp_126 params unchanged],
  "compass_enabled": true,
  "compass_rrg_filter": true
}
```

### exp_220: exp_154 + COMPASS sizing only
```json
{
  "base_config": "exp_154",
  [all exp_154 params unchanged],
  "compass_enabled": true,
  "compass_rrg_filter": false
}
```

### exp_221–223: same pattern applied to exp_154

---

## 9. Appendix: Key Data References

### risk_appetite by year (for sizing impact estimation)

| Year | RA range | Dominant zone | Avg multiplier est |
|------|----------|--------------|-------------------|
| 2020 | 7–76 | Extreme range | ~1.05× (fear boost offsets complacency) |
| 2021 | 43–82 | Mild complacency | ~0.96× (slight drag) |
| 2022 | 30–70 | Fear/neutral | ~1.05× (fear weeks dominate) |
| 2023 | 45–72 | Neutral | ~1.00× |
| 2024 | 50–78 | Neutral/mild comp | ~0.98× |
| 2025 | 47–76 | Neutral/complacency | ~0.97× |

### COMPASS Data Coverage
- Snapshots: 323 weeks (2020-01-03 → 2026-03-06)
- macro_events: 192 rows FOMC/CPI/NFP backfilled (2020–2025)
- Schema: v2 with score_velocity, risk_app_velocity columns live

### Phase 6 MC Champions Reference
- **exp_126**: 8% flat risk, IC-in-NEUTRAL, SL=3.5×, CB=30%, cooldown=3 → MC P50=+32.5%
- **exp_154**: 5% dir + 12% IC, IC-in-NEUTRAL, SL=3.5×, CB=35%, no-compound → MC P50=+31.1%
- Both use `regime_mode: combo` with standard 3-signal detector

---

*Proposal prepared for Carlos review. No experiments run. Awaiting approval to begin Phase A.*
