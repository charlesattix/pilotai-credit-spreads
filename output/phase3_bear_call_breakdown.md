# Phase 3: Bear Call Breakdown Analysis

Source run: IC=OFF (`run_20260311_090726_524e0b`) — regime=combo, IC disabled, stop=2.5x

Using IC=OFF isolates directional trade behavior without IC interference.

---

## Year-by-Year Bear Call Table

| Year | Bear Call Count | Win Rate | Reliability   | Notes                                           |
|------|-----------------|----------|---------------|-------------------------------------------------|
| 2020 | 46              | 58.7%    | RELIABLE      | COVID crash + recovery; unanimous BEAR regime fired |
| 2021 | 0               | N/A      | N/A           | Pure bull year; combo regime never hit unanimous BEAR |
| 2022 | 0               | N/A      | N/A           | Bear market but bear_requires_unanimous=True blocked all bear calls |
| 2023 | 0               | N/A      | N/A           | Recovery year; MA200 below price, RSI recovering — no unanimous BEAR |
| 2024 | 0               | N/A      | N/A           | Strong bull year; no BEAR signals                |
| 2025 | 10              | 90.0%    | UNRELIABLE*   | Small sample (n=10); likely late-year correction |

*Flag: 2025's 90% WR on 10 trades is statistically unreliable.

## Critical Observation: Unanimous Bear Requirement Nearly Eliminates Bear Calls

The `bear_requires_unanimous=True` setting in combo regime requires ALL 3 signals to agree for BEAR:
1. price < MA200 (by more than 0.5% band)
2. RSI below 45
3. VIX3M/VIX ratio > 1.05 (backwardation)

This is an extremely high bar. In 6 years, it fired meaningfully only in 2020 (COVID crash). Even the 2022 bear market — where SPY fell 20%+ — did NOT trigger enough unanimous BEAR days to produce bear calls.

**Why 2022 has 0 bear calls despite being a bear market:**
- 2022 was a slow grind lower with VIX often NOT in backwardation (VIX structure remained flat)
- RSI during steady declines can stay above 45 for weeks
- The regime detector's VIX structure check likely kept many 2022 days as NEUTRAL or BULL

This explains why ICs are so important: NEUTRAL dominates when BEAR requirements aren't met.

## What Drives Bear Call Availability

The combo regime's BEAR fires primarily during:
1. Sharp crash events (COVID-type: VIX spikes, price collapses, RSI tanks simultaneously)
2. Extreme VIX: VIX > 40 overrides and forces BEAR (the vix_extreme circuit breaker)

In normal bear markets (2022), the system defaults to NEUTRAL → ICs, not BEAR → bear calls.

## Bear Call Win Rate Interpretation

Only 2020's 46-trade sample is statistically meaningful. At 58.7% WR with 46 trades, bear calls are:
- Better than random (50%)
- But significantly lower than bull puts (94.3% that same year)
- The COVID bear trades captured real downside but also caught recoveries mid-trade

**2025's 90% WR on 10 trades is noise** — a handful of end-of-year corrections where the regime briefly hit unanimous BEAR conditions.

## Is 100% WR in Certain Years an Artifact of Small Sample?

Yes — years with 0 bear calls trivially report N/A (not 100%). The only year that could show 100% WR is if very few bear calls happened to all expire worthless. 2025's 10-trade 90% is the closest to this scenario.

The real concern is 2020's 58.7% WR: this is the only real stress test of bear calls, and it's marginal. Bear calls with combo regime are not a reliable edge — they're an occasional signal in extreme conditions.

## Implication for IC vs Bear Call Strategy

With combo regime:
- **Bull puts dominate** in bull/neutral markets (92%+ WR typically)
- **ICs capture neutral regime** when neither direction is clear (55-84% WR depending on year)
- **Bear calls are rare and marginally profitable** — only meaningful in crash scenarios

The system is functionally a bull-put + IC machine. Bear calls are a minor add-on. This is appropriate given the asymmetric BULL/BEAR voting requirements.
