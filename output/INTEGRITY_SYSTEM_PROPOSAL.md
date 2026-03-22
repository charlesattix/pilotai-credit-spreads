# Backtest Integrity System — Design & Implementation Summary

**Date:** March 13, 2026
**Status:** IMPLEMENTED — all components live and tested

---

## What Was Built

Four files were created to make unrealistic backtest results impossible to slip through undetected:

| File | Purpose |
|---|---|
| `scripts/backtest_validator.py` | Post-backtest validation CLI — PASS/WARN/FAIL grading |
| `tests/test_backtest_integrity.py` | 25 unit tests for commission math, leverage, position limits |
| `shared/realistic_benchmarks.py` | Reference data and grading functions |
| `scripts/run_optimization.py` | Added `--integrity-check` flag |

---

## Component 1: `scripts/backtest_validator.py`

Reads leaderboard.json (or a specific entry) and runs 7 checks per year:

### Checks performed

| Check | Condition | Grade |
|---|---|---|
| `check_mode` | heuristic mode | WARN (100% WR is fabricated) |
| `check_win_rate` | WR ≥ 90% | WARN; WR ≥ 98% in real mode | FAIL |
| `check_return_bound` | return > 500% | FAIL; > 200% | WARN |
| `check_commission_math` | expected commission > 50% of capital | WARN |
| `check_margin_and_leverage` | max_positions × max_contracts × width × 100 / capital > 3x | FAIL |
| `check_sharpe` | Sharpe > 3.5 | FAIL; > 2.0 | WARN |
| `check_position_count_vs_config` | trades >> (252/DTE) × max_positions | WARN |
| `check_volume_feasibility` | max_contracts > 100 | WARN; > 500 | FAIL |
| `benchmark_grade` | avg_return vs published ranges | REALISTIC/OPTIMISTIC/FANTASY |

### Leverage formula

```
leverage = max_positions × max_contracts × spread_width × 100 / starting_capital
```

The exp_213 champion: `50 × 100 × $5 × 100 / $100,000 = **25×**` → FAIL

A realistic account: `5 × 5 × $5 × 100 / $100,000 = **0.125×**` → OK

### Usage

```bash
# Validate entire leaderboard
python scripts/backtest_validator.py

# Validate specific run
python scripts/backtest_validator.py --run-id <run_id>

# Validate raw result file
python scripts/backtest_validator.py --result-file output/some_result.json

# Verbose (show all PASS checks too)
python scripts/backtest_validator.py -v
```

Returns **exit code 1** if any FAIL-grade issues found (blocks CI pipeline).

---

## Component 2: `tests/test_backtest_integrity.py` (25 tests)

Tests organized in 6 classes:

| Class | Tests | What it verifies |
|---|---|---|
| `TestCommissionScaling` | 5 | Commission increases linearly with contract count |
| `TestCapitalReservation` | 3 | Capital deducted at entry scales with contracts |
| `TestPositionCountEnforcement` | 3 | max_positions from config is honored |
| `TestKnownCommissionScenario` | 3 | 200 trades × 100 contracts = $52K expected commission |
| `TestLeverageRatio` | 4 | Leverage math correct; aggressive configs flagged |
| `TestBenchmarkGrading` | 7 | Grade functions classify REALISTIC/OPTIMISTIC/FANTASY |

### Key documented scenario (regression test)

```python
# 200 trades × 100 contracts × $0.65 × 2 legs × 2 round-trips = $52,000
# Old bug: 200 × $0.65 × 2 = $260 (100× wrong)
# Ratio = exactly 100× understatement
```

---

## Component 3: `shared/realistic_benchmarks.py`

Published reference data:

| Metric | Realistic Range | Source |
|---|---|---|
| Credit spread annual return | 8–35% | CBOE BuyWrite/PutWrite indices |
| Iron condor annual return | 12–45% | Industry practitioner research |
| Max Sharpe ratio | 1.5–2.0 | Options selling theory (Deng 2020) |
| Leverage (max) | 3× | Reg T margin rules |
| Max contracts before market impact | 100 | 5–10% of typical OTM daily volume |

Functions:
- `grade_annual_returns(avg_pct, has_iron_condors)` → `BenchmarkResult(grade, message, deviation_factor)`
- `compute_leverage_ratio(max_pos, max_cont, width, capital)` → float
- `is_leverage_realistic(leverage)` → `(bool, label)`
- `is_volume_feasible(contracts)` → `(bool, label, message)`

---

## Component 4: `--integrity-check` flag in `run_optimization.py`

```bash
python scripts/run_optimization.py --config configs/exp_213_champion_maxc100.json --integrity-check
```

Behavior:
1. Runs the backtest normally
2. Calls `validate_entry()` on the result
3. Prints the integrity report
4. **Refuses to add to leaderboard.json if grade is FAIL**
5. Prints: `❌ INTEGRITY CHECK FAILED — results NOT added to leaderboard.`

To force-add without checking (not recommended): omit `--integrity-check`.

---

## Immediate Findings (Running Against Current Leaderboard)

The first leaderboard entry tested (`endless_20260309_054247_4ce3`) produces **FAIL** on:

- **Leverage 3.8×**: max_positions=50 × max_contracts=15 × $5 width = $375K margin on $100K capital
- **Sharpe > 7**: Impossible for any real options strategy (realistic ceiling ~2.0)
- **WINs**: 100% WR in heuristic mode (expected — heuristic is fabricated)

This confirms the validator correctly identifies the structural problems documented in `INDEPENDENT_REALITY_CHECK.md`.

---

## What the Integrity System Does NOT Fix

The validator **detects** problems but does not fix them. The underlying bugs still exist:

1. **Commission bug** (if present): `commission = self.commission * 2` instead of `× contracts` — check `backtest/backtester.py` lines ~1709, 1773. Current code appears to have this fixed already.
2. **max_positions=50 hardcoded** in `run_optimization.py` line 165 — not configurable from config JSON
3. **No margin model** — capital is not reserved at position entry
4. **Exposure cap bypass** — `if pct >= 100: return True` short-circuits all leverage checks

To produce results suitable for presentation to Carlos, run with:
```json
{
  "max_contracts": 10,
  "max_positions": 5,
  "compound": false
}
```
And verify leverage ≤ 1.0× before accepting results.

---

## Running the Integrity Tests

```bash
python3 -m pytest tests/test_backtest_integrity.py -v
```

All 25 tests pass. The project-level coverage failure is expected (this file covers integrity math, not the full backtester).
