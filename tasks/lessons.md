# Lessons Learned — Operation Crack The Code
# Review this file at the START of every session. Update after every mistake.
# Last Updated: 2026-02-26

---

## 🔴 Category: Backtester Accuracy

### Lesson 001: Constant σ kills delta estimation
- **Date**: 2026-02-26
- **What happened**: Used σ=25% constant for Black-Scholes delta estimation across all dates
- **Impact**: 2024 produced only 5 trades (should be 128+). Low-vol years got almost zero trades because strikes were placed too far OTM. High-vol years got too many stops because strikes were too close to ATM.
- **Root cause**: Assumed implied vol was roughly constant. It's not — it ranges from ~12% (2024 low-vol) to ~60% (2020 COVID).
- **Fix**: Replaced with per-date realized vol via ATR(20)/Close × √252, clipped [10%, 100%], NaN fallback to 25%.
- **Rule**: NEVER use constant assumptions for market variables that vary by regime. Always derive from data.
- **Verification**: Spot-checked 2020 COVID dates (~50-60%) and 2024 low-vol dates (~16%). Matches expectations.

### Lesson 002: Backtester P&L must recalculate from current prices
- **Date**: 2026-02-26
- **What happened**: Paper trade P&L values showed as frozen/stale across multiple scans (+$13.96, +$14.84 unchanged for hours)
- **Impact**: Can't trust P&L reporting — positions could be deeply underwater while showing green
- **Root cause**: P&L calculated once at entry and not updated with current option pricing
- **Fix**: TBD — needs live option price lookup on each scan to recalculate spread value
- **Rule**: P&L that doesn't change with market movement is WRONG. Always recalculate.

### Lesson 003: Walk-forward validation catches what in-sample testing misses
- **Date**: 2026-02-26
- **What happened**: Pre-established principle, not a specific incident yet
- **Impact**: Any params optimized on 2020-2025 data could be perfectly curve-fit to those specific price paths
- **Rule**: EVERY param set must be tested with train/test split. If params trained on 2020-2022 don't produce ≥50% of training returns on 2023-2025, they're overfit. No exceptions.

---

## 🔴 Category: System Architecture

### Lesson 004: Max positions cap silently blocks trades
- **Date**: 2026-02-26
- **What happened**: Paper trader had a hardcoded 6-position max that rejected all new entries when hit
- **Impact**: System looked like it was scanning and finding opportunities, but silently dropping them. Only discovered when Carlos noticed.
- **Root cause**: Legacy guard in paper_trader.py lines 305-310 + eligible slice at line 337
- **Fix**: Removed early-return guard and per-scan slice. Kept duplicate-strike filter and 3-per-ticker concentration limit.
- **Rule**: Silent rejections are bugs. If the system decides not to trade, it must LOG WHY prominently. Never silently swallow valid signals.

### Lesson 005: Alpaca buying power runs out fast with many legs
- **Date**: 2026-02-26
- **What happened**: 72 option legs open, options buying power dropped to ~$2K. New orders rejected with "insufficient options buying power"
- **Impact**: Bull put spread at 10:30 AM couldn't execute on Alpaca (recorded as DB-only)
- **Root cause**: Each spread leg holds margin. 72 legs across multiple expirations consumes most of the $100K paper account BP.
- **Fix**: Need to account for available BP when sizing and selecting trades. Don't try to submit if BP is insufficient.
- **Rule**: Always check buying power BEFORE attempting order submission. Size trades to available capital, not theoretical capital.

### Lesson 006: Config keys loaded differently in different contexts
- **Date**: 2026-02-26
- **What happened**: Alpaca API connected fine during scan (main.py) but failed with 401 when called directly via Python script
- **Impact**: Incorrect morning briefing said "API keys not configured" when they were working fine
- **Root cause**: main.py loads keys via .env.local with dotenv, direct scripts don't
- **Fix**: Always use the same config loading path. Or source .env.local before running any Alpaca code.
- **Rule**: Never assume env vars are available. Always trace the config loading path. If the main app works but your script doesn't, the difference is in how config is loaded.

---

## 🔴 Category: Optimization Process

### Lesson 007: Log hypothesis BEFORE running experiment
- **Date**: 2026-02-26
- **What happened**: Pre-established principle
- **Impact**: Without pre-logging, it's easy to post-hoc rationalize results. "I was testing X" becomes "well actually this shows Y"
- **Rule**: Before EVERY optimization run, write to optimization_log.json: what you're testing, why, what you expect. Then run. Then record what actually happened. This prevents confirmation bias.

### Lesson 008: If it looks too good, it's overfit
- **Date**: 2026-02-26
- **What happened**: Pre-established principle
- **Impact**: 500% returns on 12 trades is luck, not alpha. The optimization loop WILL find param sets that look incredible on historical data but are worthless forward.
- **Rule**: Every result goes through the 7-check overfit gauntlet. Minimum 30 trades per year. Must work across regimes. Must survive parameter jitter. No shortcuts.

### Lesson 009: Compounding amplifies EVERYTHING — good and bad
- **Date**: 2026-02-26
- **What happened**: Pre-established principle for Phase 2
- **Impact**: A strategy that returns 50% uncompounded might return 200% compounded — but a 30% drawdown uncompounded becomes a 60% drawdown compounded. Compounding is how we hit 200%, but it's also how we blow up.
- **Rule**: Always analyze compounded AND uncompounded results. If uncompounded max drawdown is >25%, compounding will likely breach the 50% drawdown limit. Fix the base strategy first, then compound.

### Lesson 010: Parameter cliffs are the real danger
- **Date**: 2026-02-26
- **What happened**: Pre-established principle
- **Impact**: If delta_target=0.12 gives 200% but delta_target=0.13 gives -50%, that's a cliff. It means the strategy is balanced on a knife-edge and will fail in live trading where fills aren't exact.
- **Rule**: The jitter test (±10-20% perturbation) catches cliffs. Any param where ±10% change causes >50% return drop is FRAGILE. Prefer param sets in the middle of a "plateau" — where nearby params also work well. Robust > optimal.

---

## 🟡 Category: Process & Management

### Lesson 011: Session context fills up — save state frequently
- **Date**: 2026-02-26
- **What happened**: Claude Code sessions have finite context windows. Long optimization loops will hit the limit.
- **Impact**: Without state saving, all progress is lost when context resets. Must re-derive everything.
- **Rule**: Update optimization_state.json after EVERY experiment. Include: current phase, last experiment ID, best results so far, exact next action. A fresh session should be able to read state.json and continue within 2 minutes.

### Lesson 012: tmux prompt doesn't auto-execute
- **Date**: 2026-02-26
- **What happened**: Sent commands to Claude Code tmux session but they sat at the prompt without executing
- **Impact**: Lost 30+ minutes thinking work was happening when it wasn't
- **Root cause**: tmux send-keys put text in the prompt but didn't always send Enter, or the session was in a state requiring specific input (plan mode approval)
- **Fix**: Always verify execution by checking tmux output after sending commands. Don't assume.
- **Rule**: After sending any tmux command, wait 10-15 seconds and verify the output changed. If unchanged, the command didn't execute. Diagnose why.

### Lesson 013: Don't send thin, lazy deliverables
- **Date**: 2026-02-26
- **What happened**: Sent Carlos a 20-line todo.md and a 15-line lessons.md as "the plan"
- **Impact**: Disappointed Carlos. Lost trust. Looked lazy and unserious about a major initiative.
- **Root cause**: Rushed to deliver instead of thinking deeply about what's actually needed
- **Fix**: Rewrote todo.md to 14KB with 60+ checkboxes, exact schemas, and granular subtasks
- **Rule**: NEVER ship thin deliverables for important work. If it's a major initiative, the planning docs should reflect that. Think: "Would a staff engineer approve this plan?" If no → redo it. Take the time to be thorough. Carlos deserves better.

---

### Lesson 014: IC fallback missing _entered_today dedup causes overtrading
- **Date**: 2026-02-26
- **What happened**: Iron condor fallback (lines 354-360) had no `_entered_today` add and no `continue`. In 2024 with IC enabled, 133 trades were recorded instead of ~22 (expected). 2024 MaxDD hit -61%.
- **Impact**: exp_052 results are invalid. Any IC backtest before the fix is over-counting IC trades per day.
- **Root cause**: Put and call paths both have `_entered_today.add(_key)` + `continue`. IC path had neither.
- **Fix**: Added `_ic_key = (expiration, short_strike, call_short_strike, 'IC')` dedup check + `continue` after opening IC.
- **Rule**: EVERY position-opening branch in the scan loop MUST: (1) check `_entered_today` before appending, (2) add the key after appending, (3) `continue` to advance to next scan time.

### Lesson 015: Lowering credit floor increases trades but reduces quality in high-vol years
- **Date**: 2026-02-26
- **What happened**: Dropped min_credit_pct from 8% to 6% in exp_051. Trade count improved in 2021 (5→15) and 2023 (13→19) BUT 2024 went from +1.48% to -6.1%. 2020 dropped from +5.83% to +0.3%.
- **Impact**: avg_return dropped from 8.9% to 7.0% — WORSE than baseline.
- **Root cause**: 6% credit floor admits marginal trades with negative edge in bull years. At 6% credit with 2.5x stop loss: stop at 15% while credit is only 6% → negative expected value after a few stops.
- **Rule**: Lowering credit floor is a "volume trap" — more trades with worse edge. Keep 8% floor. Trade generation must come from different strategy (IC, calendar spreads) not diluted credit requirements.

### Lesson 016: Pre-hardening returns were execution-cost illusions
- **Date**: 2026-02-26
- **What happened**: exp_036 showed 103.1% avg return with 10% risk, compound, MA200. Same params through hardened backtester (exp_053) show 14.9% avg.
- **Impact**: ~85% of the "alpha" was not paying for slippage or commissions.
- **Root cause**: Each round-trip trade costs $0.05 entry slippage + $0.10 exit slippage + $0.65 × 4 legs = $2.60+/contract commissions. At 25 contracts, that's $65/trade easily.
- **Rule**: NEVER trust backtests that don't include full execution costs. 5% risk results scale roughly 2x per doubling of risk (10% → ~14.9%, 5% → ~8.9%). 2022 with bear calls at 10% risk = 59.8% even with hardening.

### Lesson 017: Same-expiration duplicate positions inflate trade counts across days
- **Date**: 2026-02-26
- **What happened**: `_entered_today` prevents same-day duplication but resets each morning. If day-1 and day-2 both target the same Friday expiration (common when Friday fallback is active), two positions open for the same (expiration, strike) — effectively doubling size invisibly.
- **Impact**: Friday fallback experiment showed 127 trades in 2024 (real: ~40-50). Returns inflated. exp_058 results INVALID.
- **Root cause**: `_entered_today` only covers within-day dedup. Cross-day dedup (against `open_positions` list) was missing.
- **Fix**: Added `_open_keys` set at start of each trading day (built from all currently open positions). Any new position must clear BOTH `_entered_today` AND `_open_keys` before being added.
- **Rule**: ANY position-opening system with continuous overlapping positions MUST check against ALL currently open positions, not just same-day activity. One unique (expiration, strike, type) allowed at a time.

### Lesson 018: HistoricalOptionsData passed dict instead of api_key string
- **Date**: 2026-02-26
- **What happened**: `run_optimization.py` passed entire config dict to `HistoricalOptionsData(hd_config)` instead of the string API key
- **Impact**: URL had `apiKey=polygon&apiKey=backtest` (dict keys, not real key). All experiments with uncached data got 401 errors. Previous experiments ONLY worked because their data was warm in SQLite cache.
- **Root cause**: `hd_config = {"polygon": {...}, "backtest": {...}}` was passed as `api_key` param. Python accepted it (dict is truthy). When requests serialized `params={"apiKey": dict}`, it iterated dict keys → `apiKey=polygon&apiKey=backtest`.
- **Fix**: Changed to `polygon_api_key = os.getenv("POLYGON_API_KEY", "")` then `HistoricalOptionsData(polygon_api_key)`.
- **Rule**: Always verify the TYPE of arguments you're passing, not just that they're non-None. A dict where a string is expected silently corrupts URL params.

### Lesson 019: iron_condor hardcoded False in _build_config
- **Date**: 2026-02-27
- **What happened**: `_build_config` in `run_optimization.py` had `"iron_condor": {"enabled": False}` hardcoded. Even though `iron_condor_enabled: true` was in every IC config, the backtester never saw it.
- **Impact**: ALL leaderboard entries before the fix (including the "ROBUST" exp_059 at 71.3% avg) were computed WITHOUT iron condors. The 2021 year went from 40 trades/+18.8% → 173 trades/+188.8% when ICs were properly enabled. Every year's result is likely significantly different. The entire optimization history is invalid.
- **Root cause**: `_build_config` was initially written without IC support, and when IC support was added to the config files and backtester, the mapping in `_build_config` was not updated — the old `{"enabled": False}` line was simply left in place.
- **Fix**: Changed to `params.get("iron_condor_enabled", False)` and `params.get("ic_min_combined_credit_pct", 20)` in `_build_config`.
- **Rule**: When adding a new feature to the backtester (new strategy params, new risk params), ALWAYS trace the full config pipeline: JSON config file → `_build_config` dict → backtester constructor → internal state. Test that the new param actually reaches the backtester by adding a debug log at the constructor that prints all enabled features.

### Lesson 020: Missing fields in _record_close break downstream consumers
- **Date**: 2026-02-27
- **What happened**: `_record_close` in the backtester didn't include `expiration` or `option_type` in the trade dict. `replay_2021_trades.py` tried to use `trade.get("expiration", "")` and got empty string, then `datetime.strptime("", "%Y-%m-%d")` threw ValueError. The `except` block only set `contract_symbol = "UNKNOWN"`, leaving `exp_dt` undefined. Later use of `exp_dt` caused "local variable referenced before assignment".
- **Impact**: P6 spot-check was unable to verify any trade against Polygon data. All 5 spot-checked trades showed "ERROR" instead of actual verification results.
- **Root cause**: `_record_close` was written when only the essential accounting fields were needed. Downstream analysis scripts were added later without checking what `_record_close` stored.
- **Fix**: Added `expiration: pos.get('expiration')` and `option_type: 'C' if pos_type == 'bear_call_spread' else 'P'` to the trade dict. Added a guard in `replay_2021_trades.py` to skip Polygon check if contract_symbol == "UNKNOWN".
- **Rule**: `_record_close` is the source of truth for all closed trade data. When writing any analysis tool that reads `self.trades`, first check what fields `_record_close` actually stores. If a field is needed, add it to `_record_close`, not as a workaround in the consumer.

## 📐 Template for New Lessons

```markdown
### Lesson NNN: [Short title]
- **Date**: YYYY-MM-DD
- **What happened**: [Specific incident or observation]
- **Impact**: [What went wrong or what risk exists]
- **Root cause**: [Why it happened]
- **Fix**: [What was done or needs to be done]
- **Rule**: [The permanent rule to prevent recurrence]
```

---

## Summary Stats
- Total lessons: 20
- Backtester accuracy: 4
- System architecture: 3
- Optimization process: 5 (+1: IC bug)
- Process & management: 3
- Backtester data integrity: 2 (+1: _record_close)
- Last review: 2026-02-27

## COMPASS Integration Insights (2026-03-07)

### Critical Findings from 323-Week Analysis

1. **Complacency multiplier was backwards**: score >70 → 0.8× would cut sizes during 2021's trending bull year, costing -25.68pp. Credit spreads thrive in calm trending markets — don't reduce there.

2. **RRG breadth filter was a coin flip**: 50% threshold with 7 sectors → blocks ~49% of weeks by construction. Not a signal. Fix: use XLI + XLF both in Lagging/Weakening (~15-20% block rate).

3. **Only risk_appetite dimension has predictive power**: Overall composite r=-0.106 (weak). Risk appetite alone r=-0.250 vs forward 4w SPY returns (strong contrarian signal).

4. **Fear = opportunity for credit spreads**: score <45 weeks → avg +3.66% forward 4w SPY return. Sell premium when IV is richest and bounce probability highest.

5. **Event gate is highest-conviction signal** but macro_events table lacks 2020-2024 FOMC/CPI/NFP data. Requires one-time backfill before backtesting.

### Recalibrated Thresholds (exp_102)
- Risk appetite < 30 → 1.2× (extreme fear, sell more premium)
- Risk appetite < 45 → 1.1× (elevated fear)
- Risk appetite 45-65 → 1.0× (neutral)
- Risk appetite > 65 → 0.95× (mild complacency)
- Risk appetite > 75 → 0.85× (high complacency, contrarian caution)
- RRG: Block bull puts ONLY when XLI AND XLF both Lagging/Weakening

### Expected exp_102 Outcome
- +27 to +32% avg return (vs 26.85% baseline exp_090)
- Major improvement in 2020 (fear sizing up) and 2022 (RRG blocking bad entries)
- 2021 no longer penalized (risk_appetite ~60, not >70)
