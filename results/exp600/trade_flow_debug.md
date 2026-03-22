# EXP-600 Trade Flow Debug
Generated: 2026-03-16T21:49:13.750853

## Mystery
For config DTE=45, W=$10, OTM=5%, PT=50%, SL=2.5x, risk=2%:
- 2020: 49 trades | 2021: **2 trades** | 2022: 68 trades
- 2023: **2 trades** | 2024: 8 trades | 2025: 58 trades

Hypothesis: DB has contracts listed but missing daily pricing bars for 2021/2023.


## Expiration Frequency by Year

W=$10 OTM=5% DTE=45 targets specific expirations.
If expirations are only monthly, there are fewer entry opportunities.

**2020**: 159 expirations, avg interval 2.3d (min=1d, max=4d) → **WEEKLY**
**2021**: 157 expirations, avg interval 2.3d (min=1d, max=4d) → **WEEKLY**
**2022**: 170 expirations, avg interval 2.1d (min=1d, max=4d) → **WEEKLY**
**2023**: 250 expirations, avg interval 1.4d (min=1d, max=4d) → **DAILY**
**2024**: 252 expirations, avg interval 1.5d (min=1d, max=4d) → **DAILY**
**2025**: 251 expirations, avg interval 1.5d (min=1d, max=4d) → **DAILY**

## Daily Bar Density for DTE 40-50 Contracts

How many days of pricing data does each contract have?

| Year | Contracts | Avg Bars/Contract | Median | Min | Max | 0-bar contracts |
|------|-----------|-------------------|--------|-----|-----|-----------------|
| 2020 | 200 sampled | 25.6 | 17 | 0 | 236 | 19 (10%) |
| 2021 | 200 sampled | 25.7 | 21 | 0 | 147 | 9 (4%) |
| 2022 | 200 sampled | 19.4 | 9 | 0 | 239 | 21 (10%) |
| 2023 | 200 sampled | 9.6 | 4 | 0 | 160 | 37 (18%) |
| 2024 | 200 sampled | 9.0 | 4 | 0 | 142 | 51 (26%) |
| 2025 | 200 sampled | 16.6 | 8 | 0 | 249 | 25 (12%) |

## Intraday Bar Coverage

The backtester uses 14 scan times per day (9:30-16:00 ET).
If intraday bars are missing, it falls back to daily bars.

| Year | Intraday Bars | Contracts w/ Intraday | Dates w/ Intraday |
|------|--------------|----------------------|-------------------|
| 2020 | 0 (EMPTY) | 0 | 0 |
| 2021 | 0 (EMPTY) | 0 | 0 |
| 2022 | 0 (EMPTY) | 0 | 0 |
| 2023 | 0 (EMPTY) | 0 | 0 |
| 2024 | 0 (EMPTY) | 0 | 0 |
| 2025 | 0 (EMPTY) | 0 | 0 |

## Year 2020

### Contract Coverage
- Total expirations with put contracts: **159**
- Avg strikes per expiration: 111
- First: 2020-01-03, Last: 2020-12-31

### Daily Bars by Month
| Month | Bars | Status |
|-------|------|--------|
| 2020-01 | 32,807 | OK |
| 2020-02 | 33,422 | OK |
| 2020-03 | 51,095 | OK |
| 2020-04 | 37,600 | OK |
| 2020-05 | 31,791 | OK |
| 2020-06 | 37,262 | OK |
| 2020-07 | 31,692 | OK |
| 2020-08 | 32,551 | OK |
| 2020-09 | 30,519 | OK |
| 2020-10 | 28,326 | OK |
| 2020-11 | 30,871 | OK |
| 2020-12 | 29,828 | OK |
| **Total** | **407,764** | |

### Per-Day Probe (15 sample days)
| Date | DTE40-50 Exps | Strikes | Short Leg Bars | Long Leg Bars | Spread OK | Rejection |
|------|--------------|---------|---------------|---------------|-----------|-----------|
| 2020-01-02 | 5 | 4 | $0.43 | MISS | NO | long leg missing (O:SPY200214P00272500: 0 bars total, range  |
| 2020-01-27 | 4 | 55 | MISS | MISS | NO | BOTH legs missing (short: 10 bars 2020-02-25→2020-03-09) (lo |
| 2020-02-19 | 7 | 100 | MISS | MISS | NO | BOTH legs missing (short: 16 bars 2020-02-27→2020-03-27) (lo |
| 2020-03-13 | 5 | 33 | MISS | MISS | NO | BOTH legs missing (short: 24 bars 2020-03-17→2020-04-20) (lo |
| 2020-04-07 | 5 | 3 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2020-04-14→2020-05-14) (lo |
| 2020-04-30 | 5 | 4 | MISS | MISS | NO | BOTH legs missing (short: 12 bars 2020-05-14→2020-06-04) (lo |
| 2020-05-25 | 4 | 2 | MISS | MISS | NO | BOTH legs missing (short: 22 bars 2020-06-02→2020-07-02) (lo |
| 2020-06-17 | 5 | 7 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2020-06-29→2020-07-23) (lon |
| 2020-07-10 | 5 | 3 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2020-07-15→2020-08-17) (lo |
| 2020-08-04 | 5 | 7 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2020-08-10→2020-09-11) (lo |
| 2020-08-27 | 5 | 17 | MISS | MISS | NO | BOTH legs missing (short: 13 bars 2020-09-21→2020-10-07) (lo |
| 2020-09-21 | 4 | 5 | MISS | MISS | NO | BOTH legs missing (short: 25 bars 2020-09-29→2020-11-02) (lo |
| 2020-10-14 | 5 | 15 | MISS | MISS | NO | BOTH legs missing (short: 11 bars 2020-11-02→2020-11-19) (lo |
| 2020-11-06 | 5 | 4 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2020-11-11→2020-12-15) (lo |
| 2020-12-01 | 5 | 6 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2020-12-07→2021-01-08) (lo |

### 2020 Summary
- Days probed: 15
- Days with DTE 40-50 expirations: 15 (100%)
- Days with OTM strikes: 15 (100%)
- Days with short leg bar: 1 (7%)
- Days with long leg bar: 0 (0%)
- Days with valid spread: 0 (0%)

**Rejection breakdown:**
- BOTH legs missing: 14
- long leg missing: 1

## Year 2021

### Contract Coverage
- Total expirations with put contracts: **157**
- Avg strikes per expiration: 114
- First: 2021-01-04, Last: 2021-12-31

### Daily Bars by Month
| Month | Bars | Status |
|-------|------|--------|
| 2021-01 | 29,809 | OK |
| 2021-02 | 31,647 | OK |
| 2021-03 | 32,672 | OK |
| 2021-04 | 34,271 | OK |
| 2021-05 | 34,847 | OK |
| 2021-06 | 37,413 | OK |
| 2021-07 | 40,926 | OK |
| 2021-08 | 43,455 | OK |
| 2021-09 | 43,035 | OK |
| 2021-10 | 41,703 | OK |
| 2021-11 | 42,709 | OK |
| 2021-12 | 44,651 | OK |
| **Total** | **457,138** | |

### Per-Day Probe (15 sample days)
| Date | DTE40-50 Exps | Strikes | Short Leg Bars | Long Leg Bars | Spread OK | Rejection |
|------|--------------|---------|---------------|---------------|-----------|-----------|
| 2021-01-04 | 4 | 6 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2021-01-12→2021-02-16) (lo |
| 2021-01-27 | 5 | 7 | MISS | MISS | NO | BOTH legs missing (short: 24 bars 2021-02-01→2021-03-08) (lo |
| 2021-02-19 | 5 | 48 | $1.96 | $1.41 | NO | credit $0.55 < min $1.00 |
| 2021-03-16 | 5 | 7 | MISS | MISS | NO | BOTH legs missing (short: 24 bars 2021-03-22→2021-04-23) (lo |
| 2021-04-08 | 5 | 8 | MISS | MISS | NO | BOTH legs missing (short: 22 bars 2021-04-19→2021-05-18) (lo |
| 2021-05-03 | 4 | 9 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2021-05-20→2021-06-09) (lon |
| 2021-05-26 | 5 | 8 | MISS | MISS | NO | BOTH legs missing (short: 21 bars 2021-06-02→2021-07-06) (lo |
| 2021-06-18 | 5 | 7 | MISS | MISS | NO | BOTH legs missing (short: 17 bars 2021-06-28→2021-07-26) (lo |
| 2021-07-13 | 5 | 8 | MISS | MISS | NO | BOTH legs missing (short: 22 bars 2021-07-19→2021-08-23) (lo |
| 2021-08-05 | 5 | 10 | MISS | MISS | NO | BOTH legs missing (short: 25 bars 2021-08-11→2021-09-15) (lo |
| 2021-08-30 | 4 | 27 | MISS | MISS | NO | BOTH legs missing (short: 16 bars 2021-09-17→2021-10-08) (lo |
| 2021-09-22 | 5 | 10 | MISS | MISS | NO | BOTH legs missing (short: 15 bars 2021-10-01→2021-10-27) (lo |
| 2021-10-15 | 5 | 7 | MISS | MISS | NO | BOTH legs missing (short: 22 bars 2021-10-20→2021-11-23) (lo |
| 2021-11-09 | 5 | 21 | MISS | MISS | NO | BOTH legs missing (short: 15 bars 2021-11-30→2021-12-20) (lo |
| 2021-12-02 | 5 | 8 | MISS | MISS | NO | BOTH legs missing (short: 20 bars 2021-12-10→2022-01-10) (lo |

### 2021 Summary
- Days probed: 15
- Days with DTE 40-50 expirations: 15 (100%)
- Days with OTM strikes: 15 (100%)
- Days with short leg bar: 1 (7%)
- Days with long leg bar: 1 (7%)
- Days with valid spread: 0 (0%)

**Rejection breakdown:**
- BOTH legs missing: 14
- credit $0.55 < min $1.00: 1

## Year 2022

### Contract Coverage
- Total expirations with put contracts: **170**
- Avg strikes per expiration: 149
- First: 2022-01-03, Last: 2022-12-30

### Daily Bars by Month
| Month | Bars | Status |
|-------|------|--------|
| 2022-01 | 42,529 | OK |
| 2022-02 | 42,915 | OK |
| 2022-03 | 49,837 | OK |
| 2022-04 | 39,340 | OK |
| 2022-05 | 43,828 | OK |
| 2022-06 | 43,883 | OK |
| 2022-07 | 37,494 | OK |
| 2022-08 | 45,956 | OK |
| 2022-09 | 40,896 | OK |
| 2022-10 | 39,280 | OK |
| 2022-11 | 40,223 | OK |
| 2022-12 | 35,467 | OK |
| **Total** | **501,648** | |

### Per-Day Probe (15 sample days)
| Date | DTE40-50 Exps | Strikes | Short Leg Bars | Long Leg Bars | Spread OK | Rejection |
|------|--------------|---------|---------------|---------------|-----------|-----------|
| 2022-01-03 | 4 | 77 | MISS | MISS | NO | BOTH legs missing (short: 11 bars 2022-01-31→2022-02-14) (lo |
| 2022-01-26 | 5 | 50 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2022-02-23→2022-03-07) (lon |
| 2022-02-18 | 6 | 28 | MISS | MISS | NO | BOTH legs missing (short: 26 bars 2022-02-23→2022-03-30) (lo |
| 2022-03-15 | 5 | 20 | MISS | MISS | NO | BOTH legs missing (short: 4 bars 2022-04-14→2022-04-22) (lon |
| 2022-04-07 | 5 | 51 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2022-04-18→2022-05-18) (lo |
| 2022-05-02 | 4 | 44 | MISS | MISS | NO | BOTH legs missing (short: 22 bars 2022-05-12→2022-06-13) (lo |
| 2022-05-25 | 5 | 47 | MISS | MISS | NO | BOTH legs missing (short: 13 bars 2022-06-15→2022-07-05) (lo |
| 2022-06-17 | 5 | 19 | MISS | MISS | NO | BOTH legs missing (short: 2 bars 2022-07-19→2022-07-22) (lon |
| 2022-07-12 | 5 | 5 | MISS | MISS | NO | BOTH legs missing (short: 23 bars 2022-07-15→2022-08-16) (lo |
| 2022-08-04 | 5 | 44 | MISS | MISS | NO | BOTH legs missing (short: 16 bars 2022-08-23→2022-09-14) (lo |
| 2022-08-29 | 4 | 59 | MISS | MISS | NO | BOTH legs missing (short: 22 bars 2022-09-09→2022-10-10) (lo |
| 2022-09-21 | 5 | 38 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2022-10-18→2022-10-28) (lon |
| 2022-10-14 | 7 | 6 | MISS | MISS | NO | BOTH legs missing (short: 21 bars 2022-10-24→2022-11-21) (lo |
| 2022-11-08 | 7 | 17 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2022-12-07→2022-12-16) (lon |
| 2022-12-01 | 8 | 50 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2022-12-28→2023-01-10) (lon |

### 2022 Summary
- Days probed: 15
- Days with DTE 40-50 expirations: 15 (100%)
- Days with OTM strikes: 15 (100%)
- Days with short leg bar: 0 (0%)
- Days with long leg bar: 0 (0%)
- Days with valid spread: 0 (0%)

**Rejection breakdown:**
- BOTH legs missing: 15

## Year 2023

### Contract Coverage
- Total expirations with put contracts: **250**
- Avg strikes per expiration: 135
- First: 2023-01-03, Last: 2023-12-29

### Daily Bars by Month
| Month | Bars | Status |
|-------|------|--------|
| 2023-01 | 32,543 | OK |
| 2023-02 | 31,532 | OK |
| 2023-03 | 38,003 | OK |
| 2023-04 | 29,172 | OK |
| 2023-05 | 32,088 | OK |
| 2023-06 | 29,782 | OK |
| 2023-07 | 30,276 | OK |
| 2023-08 | 37,211 | OK |
| 2023-09 | 26,469 | OK |
| 2023-10 | 28,812 | OK |
| 2023-11 | 24,215 | OK |
| 2023-12 | 16,154 | OK |
| **Total** | **356,257** | |

### Per-Day Probe (15 sample days)
| Date | DTE40-50 Exps | Strikes | Short Leg Bars | Long Leg Bars | Spread OK | Rejection |
|------|--------------|---------|---------------|---------------|-----------|-----------|
| 2023-01-02 | 6 | 9 | MISS | MISS | NO | BOTH legs missing (short: 1 bars 2023-02-09→2023-02-09) (lon |
| 2023-01-25 | 9 | 32 | MISS | MISS | NO | BOTH legs missing (short: 5 bars 2023-02-22→2023-03-03) (lon |
| 2023-02-17 | 7 | 44 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2023-03-16→2023-03-28) (lon |
| 2023-03-14 | 8 | 11 | MISS | MISS | NO | BOTH legs missing (short: 2 bars 2023-04-14→2023-04-17) (lon |
| 2023-04-06 | 9 | 30 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2023-05-03→2023-05-15) (lon |
| 2023-05-01 | 6 | 28 | MISS | MISS | NO | BOTH legs missing (short: 6 bars 2023-05-30→2023-06-07) (lon |
| 2023-05-24 | 8 | 8 | MISS | MISS | NO | BOTH legs missing (short O:SPY230703P00376000: 0 bars ever)  |
| 2023-06-16 | 8 | 26 | MISS | MISS | NO | BOTH legs missing (short: 3 bars 2023-07-19→2023-07-25) (lon |
| 2023-07-11 | 8 | 41 | MISS | MISS | NO | BOTH legs missing (short: 5 bars 2023-08-11→2023-08-18) (lon |
| 2023-08-03 | 9 | 36 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2023-08-31→2023-09-11) (lon |
| 2023-08-28 | 7 | 51 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2023-09-27→2023-10-09) (lon |
| 2023-09-20 | 9 | 54 | MISS | MISS | NO | BOTH legs missing (short: 10 bars 2023-10-17→2023-10-30) (lo |
| 2023-10-13 | 7 | 29 | MISS | MISS | NO | BOTH legs missing (short: 1 bars 2023-11-13→2023-11-13) (lon |
| 2023-11-07 | 7 | 13 | MISS | MISS | NO | BOTH legs missing (short: 2 bars 2023-12-12→2023-12-15) (lon |
| 2023-11-30 | 8 | 17 | MISS | MISS | NO | BOTH legs missing (short O:SPY240109P00421000: 0 bars ever)  |

### 2023 Summary
- Days probed: 15
- Days with DTE 40-50 expirations: 15 (100%)
- Days with OTM strikes: 15 (100%)
- Days with short leg bar: 0 (0%)
- Days with long leg bar: 0 (0%)
- Days with valid spread: 0 (0%)

**Rejection breakdown:**
- BOTH legs missing: 15

## Year 2024

### Contract Coverage
- Total expirations with put contracts: **252**
- Avg strikes per expiration: 119
- First: 2024-01-02, Last: 2024-12-31

### Daily Bars by Month
| Month | Bars | Status |
|-------|------|--------|
| 2024-01 | 9,027 | OK |
| 2024-02 | 16,560 | OK |
| 2024-03 | 35,900 | OK |
| 2024-04 | 37,707 | OK |
| 2024-05 | 34,958 | OK |
| 2024-06 | 30,545 | OK |
| 2024-07 | 38,398 | OK |
| 2024-08 | 43,019 | OK |
| 2024-09 | 38,469 | OK |
| 2024-10 | 41,566 | OK |
| 2024-11 | 37,236 | OK |
| 2024-12 | 36,516 | OK |
| **Total** | **399,901** | |

### Per-Day Probe (15 sample days)
| Date | DTE40-50 Exps | Strikes | Short Leg Bars | Long Leg Bars | Spread OK | Rejection |
|------|--------------|---------|---------------|---------------|-----------|-----------|
| 2024-01-02 | 7 | 22 | MISS | MISS | NO | BOTH legs missing (short O:SPY240212P00438000: 0 bars ever)  |
| 2024-01-25 | 9 | 30 | MISS | MISS | NO | BOTH legs missing (short: 1 bars 2024-02-28→2024-02-28) (lon |
| 2024-02-19 | 7 | 28 | MISS | MISS | NO | BOTH legs missing (short: 2 bars 2024-03-20→2024-03-28) (lon |
| 2024-03-13 | 9 | 40 | MISS | MISS | NO | BOTH legs missing (short: 8 bars 2024-04-09→2024-04-22) (lon |
| 2024-04-05 | 8 | 39 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2024-05-02→2024-05-14) (lon |
| 2024-04-30 | 7 | 25 | MISS | MISS | NO | BOTH legs missing (short O:SPY240610P00466000: 0 bars ever)  |
| 2024-05-23 | 8 | 30 | MISS | MISS | NO | BOTH legs missing (short: 2 bars 2024-06-26→2024-06-28) (lon |
| 2024-06-17 | 7 | 27 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2024-07-17→2024-07-29) (lon |
| 2024-07-10 | 9 | 115 | MISS | MISS | NO | BOTH legs missing (short: 11 bars 2024-08-05→2024-08-19) (lo |
| 2024-08-02 | 8 | 35 | MISS | MISS | NO | BOTH legs missing (short: 4 bars 2024-09-04→2024-09-09) (lon |
| 2024-08-27 | 8 | 30 | MISS | MISS | NO | BOTH legs missing (short: 11 bars 2024-09-23→2024-10-07) (lo |
| 2024-09-19 | 9 | 20 | MISS | MISS | NO | BOTH legs missing (short: 10 bars 2024-10-15→2024-10-29) (lo |
| 2024-10-14 | 6 | 21 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2024-11-15→2024-11-25) (lon |
| 2024-11-06 | 8 | 18 | MISS | MISS | NO | BOTH legs missing (short: 10 bars 2024-12-02→2024-12-16) (lo |
| 2024-11-29 | 8 | 32 | MISS | MISS | NO | BOTH legs missing (short: 6 bars 2024-12-31→2025-01-08) (lon |

### 2024 Summary
- Days probed: 15
- Days with DTE 40-50 expirations: 15 (100%)
- Days with OTM strikes: 15 (100%)
- Days with short leg bar: 0 (0%)
- Days with long leg bar: 0 (0%)
- Days with valid spread: 0 (0%)

**Rejection breakdown:**
- BOTH legs missing: 15

## Year 2025

### Contract Coverage
- Total expirations with put contracts: **251**
- Avg strikes per expiration: 135
- First: 2025-01-02, Last: 2025-12-31

### Daily Bars by Month
| Month | Bars | Status |
|-------|------|--------|
| 2025-01 | 36,577 | OK |
| 2025-02 | 35,141 | OK |
| 2025-03 | 46,190 | OK |
| 2025-04 | 46,540 | OK |
| 2025-05 | 39,965 | OK |
| 2025-06 | 34,841 | OK |
| 2025-07 | 35,734 | OK |
| 2025-08 | 31,083 | OK |
| 2025-09 | 35,719 | OK |
| 2025-10 | 37,344 | OK |
| 2025-11 | 25,889 | OK |
| 2025-12 | 16,222 | OK |
| **Total** | **421,245** | |

### Per-Day Probe (15 sample days)
| Date | DTE40-50 Exps | Strikes | Short Leg Bars | Long Leg Bars | Spread OK | Rejection |
|------|--------------|---------|---------------|---------------|-----------|-----------|
| 2025-01-02 | 8 | 16 | MISS | MISS | NO | BOTH legs missing (short: 5 bars 2025-02-03→2025-02-10) (lon |
| 2025-01-27 | 7 | 61 | MISS | MISS | NO | BOTH legs missing (short: 5 bars 2025-03-04→2025-03-10) (lon |
| 2025-02-19 | 9 | 111 | $2.17 | $1.54 | NO | credit $0.63 < min $1.00 |
| 2025-03-14 | 8 | 143 | MISS | MISS | NO | BOTH legs missing (short: 10 bars 2025-04-09→2025-04-23) (lo |
| 2025-04-08 | 7 | 5 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2025-05-06→2025-05-14) (lon |
| 2025-05-01 | 8 | 12 | MISS | MISS | NO | BOTH legs missing (short: 8 bars 2025-05-27→2025-06-06) (lon |
| 2025-05-26 | 7 | 11 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2025-06-23→2025-07-03) (lon |
| 2025-06-18 | 9 | 14 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2025-07-15→2025-07-25) (lon |
| 2025-07-11 | 8 | 18 | MISS | MISS | NO | BOTH legs missing (short: 9 bars 2025-08-06→2025-08-19) (lon |
| 2025-08-05 | 8 | 86 | MISS | MISS | NO | BOTH legs missing (short: 2 bars 2025-09-11→2025-09-12) (lon |
| 2025-08-28 | 9 | 68 | MISS | MISS | NO | BOTH legs missing (short: 7 bars 2025-09-26→2025-10-07) (lon |
| 2025-09-22 | 7 | 22 | MISS | MISS | NO | BOTH legs missing (short: 11 bars 2025-10-20→2025-11-03) (lo |
| 2025-10-15 | 8 | 44 | MISS | MISS | NO | BOTH legs missing (short: 11 bars 2025-11-10→2025-11-24) (lo |
| 2025-11-07 | 7 | 20 | MISS | MISS | NO | BOTH legs missing (short: 11 bars 2025-12-03→2025-12-17) (lo |
| 2025-12-02 | 0 | - | - | - | NO | no DTE 40-50 expirations |

### 2025 Summary
- Days probed: 15
- Days with DTE 40-50 expirations: 14 (93%)
- Days with OTM strikes: 14 (93%)
- Days with short leg bar: 1 (7%)
- Days with long leg bar: 1 (7%)
- Days with valid spread: 0 (0%)

**Rejection breakdown:**
- BOTH legs missing: 13
- credit $0.63 < min $1.00: 1
- no_expirations_in_DTE_range: 1

## Daily Bar Availability vs DTE

For each year, sample 50 OTM put contracts and check: at what DTE do daily bars first appear?

| Year | Contracts Sampled | Avg First-Bar DTE | Median | Min DTE | Max DTE | Never-Bars |
|------|------------------|-------------------|--------|---------|---------|------------|
| 2020 | 50 | 68 | 35 | 1 | 365 | 7 |
| 2021 | 50 | 65 | 35 | 1 | 365 | 2 |
| 2022 | 50 | 56 | 34 | 0 | 365 | 5 |
| 2023 | 50 | 21 | 11 | 1 | 361 | 13 |
| 2024 | 50 | 43 | 13 | 3 | 363 | 17 |
| 2025 | 50 | 31 | 13 | 1 | 365 | 7 |

**Interpretation**: If avg first-bar DTE is ~20, bars only appear 20 days before expiration.
With target_dte=45, the backtester tries to enter at 45 DTE but bars don't exist until ~20 DTE.
Trades only happen on dates where bars coincidentally exist early (rare).

## Mini Backtest Trace (2021 & 2023)

Running backtester on specific months with DEBUG logging to trace rejections.

**2021 Q1 Jan-Mar**: 1 trades, +0.1% return
  - Debug log entries: 1414
  - 'No strikes': 56
  - 'No price data': 672
  - 'Below minimum credit': 588
  - 'Opened': 14
  - Volume gate rejections: 0

**2021 Q2 Apr-Jun**: 1 trades, +0.1% return
  - Debug log entries: 1472
  - 'No strikes': 56
  - 'No price data': 644
  - 'Below minimum credit': 672
  - 'Opened': 14
  - Volume gate rejections: 0

**2021 Q3 Jul-Sep**: 0 trades, +0.0% return
  - Debug log entries: 1473
  - 'No strikes': 28
  - 'No price data': 826
  - 'Below minimum credit': 546
  - 'Opened': 0
  - Volume gate rejections: 0

**2021 Q4 Oct-Dec**: 0 trades, +0.0% return
  - Debug log entries: 1473
  - 'No strikes': 98
  - 'No price data': 840
  - 'Below minimum credit': 462
  - 'Opened': 0
  - Volume gate rejections: 0

**2022 Q1 Jan-Mar**: 9 trades, +0.8% return
  - Debug log entries: 1583
  - 'No strikes': 98
  - 'No price data': 686
  - 'Below minimum credit': 392
  - 'Opened': 168
  - Volume gate rejections: 0

**2022 Q2 Apr-Jun**: 20 trades, -0.3% return
  - Debug log entries: 1793
  - 'No strikes': 70
  - 'No price data': 644
  - 'Below minimum credit': 252
  - 'Opened': 378
  - Volume gate rejections: 0

**2022 Q3 Jul-Sep**: 16 trades, -0.1% return
  - Debug log entries: 1711
  - 'No strikes': 70
  - 'No price data': 714
  - 'Below minimum credit': 378
  - 'Opened': 238
  - Volume gate rejections: 0

**2022 Q4 Oct-Dec**: 23 trades, +2.4% return
  - Debug log entries: 1837
  - 'No strikes': 98
  - 'No price data': 602
  - 'Below minimum credit': 308
  - 'Opened': 378
  - Volume gate rejections: 0

**2023 Q1 Jan-Mar**: 1 trades, +0.1% return
  - Debug log entries: 1429
  - 'No strikes': 84
  - 'No price data': 644
  - 'Below minimum credit': 602
  - 'Opened': 14
  - Volume gate rejections: 0

**2023 Q2 Apr-Jun**: 1 trades, +0.1% return
  - Debug log entries: 1429
  - 'No strikes': 56
  - 'No price data': 616
  - 'Below minimum credit': 658
  - 'Opened': 14
  - Volume gate rejections: 0

**2023 Q3 Jul-Sep**: 0 trades, +0.0% return
  - Debug log entries: 1487
  - 'No strikes': 28
  - 'No price data': 756
  - 'Below minimum credit': 630
  - 'Opened': 0
  - Volume gate rejections: 0

**2023 Q4 Oct-Dec**: 0 trades, +0.0% return
  - Debug log entries: 1431
  - 'No strikes': 98
  - 'No price data': 826
  - 'Below minimum credit': 434
  - 'Opened': 0
  - Volume gate rejections: 0

**2025 Q1 Jan-Mar**: 9 trades, +0.2% return
  - Debug log entries: 1539
  - 'No strikes': 84
  - 'No price data': 602
  - 'Below minimum credit': 448
  - 'Opened': 168
  - Volume gate rejections: 0

**2025 Q2 Apr-Jun**: 28 trades, +51.1% return
  - Debug log entries: 1849
  - 'No strikes': 112
  - 'No price data': 588
  - 'Below minimum credit': 182
  - 'Opened': 448
  - Volume gate rejections: 0

**2025 Q3 Jul-Sep**: 8 trades, +0.8% return
  - Debug log entries: 1585
  - 'No strikes': 28
  - 'No price data': 812
  - 'Below minimum credit': 448
  - 'Opened': 112
  - Volume gate rejections: 0

**2025 Q4 Oct-Dec**: 12 trades, +1.7% return
  - Debug log entries: 1655
  - 'No strikes': 686
  - 'No price data': 392
  - 'Below minimum credit': 140
  - 'Opened': 182
  - Volume gate rejections: 0


## Cross-Year Comparison (Static Probe)

| Year | Probed | Has Exps | Has Strikes | Short Bar | Long Bar | Valid Spread | Spread Rate |
|------|--------|----------|-------------|-----------|----------|-------------|-------------|
| 2020 | 15 | 15 | 15 | 1 | 0 | 0 | 0% |
| 2021 | 15 | 15 | 15 | 1 | 1 | 0 | 0% |
| 2022 | 15 | 15 | 15 | 0 | 0 | 0 | 0% |
| 2023 | 15 | 15 | 15 | 0 | 0 | 0 | 0% |
| 2024 | 15 | 15 | 15 | 0 | 0 | 0 | 0% |
| 2025 | 15 | 14 | 14 | 1 | 1 | 0 | 0% |

## ROOT CAUSE ANALYSIS

### The Two Bottlenecks

Compare quarterly mini-backtest rejection counts:

| Year-Qtr | Trades | Opened | No Price Data | Below Min Credit |
|-----------|--------|--------|---------------|-----------------|
| 2021 Q1 | 1 | 14 | 672 | **588** |
| 2021 Q2 | 1 | 14 | 644 | **672** |
| 2021 Q3 | 0 | 0 | 826 | **546** |
| 2021 Q4 | 0 | 0 | 840 | **462** |
| **2022 Q1** | **9** | **168** | 686 | **392** |
| **2022 Q2** | **20** | **378** | 644 | **252** |
| **2022 Q3** | **16** | **238** | 714 | **378** |
| **2022 Q4** | **23** | **378** | 602 | **308** |
| 2023 Q1 | 1 | 14 | 644 | **602** |
| 2023 Q2 | 1 | 14 | 616 | **658** |
| 2023 Q3 | 0 | 0 | 756 | **630** |
| 2023 Q4 | 0 | 0 | 826 | **434** |
| **2025 Q1** | **9** | **168** | 602 | **448** |
| **2025 Q2** | **28** | **448** | 588 | **182** |
| **2025 Q3** | **8** | **112** | 812 | **448** |
| **2025 Q4** | **12** | **182** | 392 | **140** |

### Bottleneck 1: Missing Price Data (moderate impact, ~equal across years)
"No price data" counts are relatively stable (588-840) across all years and quarters.
This is the daily bar sparsity issue — bars for deep OTM options only appear ~20-35 DTE
before expiration, but the backtester targets 45 DTE entry. The backtester's ±1/±2 strike
adjustments and Friday fallback partially mitigate this, but it's always a constraint.

### Bottleneck 2: Below Minimum Credit (THE SMOKING GUN)
"Below minimum credit" is the **dominant differentiator** between 2-trade years and 68-trade years:

- **2021 (2 trades)**: 462-672 below-min rejections per quarter (HIGH)
- **2022 (68 trades)**: 252-392 below-min rejections per quarter (LOW)
- **2023 (2 trades)**: 434-658 below-min rejections per quarter (HIGH)
- **2025 (58 trades)**: 140-448 below-min rejections per quarter (LOW)

The minimum credit threshold is $1.00 for W=$10 (10% × $10 width). In calm markets
(2021 bull, 2023 recovery), 5% OTM put spreads generate only $0.50-$0.65 credit — far
below the $1.00 minimum. In volatile markets (2022 bear, 2025 volatile), IV is elevated,
puts are more expensive, and credits easily exceed $1.00.

### Why This Matters

1. **The "winning" W=$10 configs don't win because they're better strategies** — they win
   because they can ONLY open trades when vol is high enough to generate sufficient credit.
   This acts as an **implicit volatility filter** that happens to be profitable.

2. **2025 Q2 (+51.1% return, 28 trades)** was likely a high-vol episode where puts were
   expensive, lots of spreads opened with fat credits, and most expired profitable.

3. **The 2-trade years (2021, 2023) aren't data failures** — they're periods where the
   strategy correctly COULD NOT find profitable spreads with $10 width at 5% OTM.
   The strategy is sitting out calm markets entirely.

4. **W=$5 configs get more trades because the credit threshold is lower** ($0.50 for
   $5 width at 10% min_credit_pct). This is why P0141 (W=$5) gets 240 trades and is
   6/6 profitable while P0195 (W=$10) gets 187 trades but with extreme concentration.

### First-Bar DTE Analysis (confirms bar sparsity)

| Year | Avg First-Bar DTE | Median | Never-Bars |
|------|-------------------|--------|------------|
| 2020 | 68 | 35 | 7/50 |
| 2021 | 65 | 35 | 2/50 |
| 2022 | 56 | 34 | 5/50 |
| 2023 | 21 | 11 | 13/50 |
| 2024 | 43 | 13 | 17/50 |
| 2025 | 31 | 13 | 7/50 |

Median first-bar DTE is 11-35 depending on year. At target DTE=45, most contracts
simply don't have bars yet. But this affects ALL years roughly equally — it's not the
differentiator between 2 and 68 trades.

### Implications for EXP-600

1. **Reduce min_credit_pct from 10% to 5% or lower** — this will dramatically increase
   trade count in 2021/2023 but may hurt win rate (accepting thinner credits)
2. **Test W=$5 with higher risk** — narrower spreads have lower credit threshold,
   more consistent trade flow, and 6/6 year profitability
3. **The 2025 +51% return is NOT generalizable** — it's from a specific vol spike.
   Configs that only trade in high vol are survivorship-biased.
4. **Consider DTE=30 instead of 45** — bars appear earlier at shorter DTE, more
   consistent data availability