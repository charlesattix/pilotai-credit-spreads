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
- Total lessons: 13
- Backtester accuracy: 3
- System architecture: 3
- Optimization process: 4
- Process & management: 3
- Last review: 2026-02-26
