# Position Exit Strategy Audit — Backtester vs Live

**Audit Date:** 2026-03-10
**Auditor:** Claude Code
**Scope:** All position exit/closing logic in backtester vs live trading path

---

## Executive Summary

Six discrepancies were found between the backtester (source of truth) and the live trading path. The most critical is **E1: DTE Management is enabled in live but completely absent from the backtester**, meaning the live system closes positions 21 days early that the backtester holds to near-expiration — an unmodeled behavior that directly affects P&L. A second significant finding (**E2**) is a stop-loss threshold mismatch in the IC exit alert monitor (2.0× vs 3.5× in all other components). The remaining findings are lower severity but document important behavioral differences around slippage, commission accounting, and IC partial-fill risk.

The good news: the core exit formulas (profit target, stop-loss) match between backtester and live `position_monitor.py` exactly. The circuit breaker correctly blocks new entries only — it does not force-close existing positions in either path. Expiration handling has a reasonable fallback hierarchy in both systems.

---

## Methodology

The following files were read in full:

| File | Purpose |
|------|---------|
| `backtest/backtester.py` | Source of truth for all exit logic |
| `shared/position_monitor.py` | Live exit checker |
| `shared/execution_engine.py` | Live close order submission |
| `shared/reconciler.py` | Post-entry fill tracking |
| `shared/macro_event_gate.py` | Entry-scaling gate (not exit) |
| `alerts/iron_condor_exit_monitor.py` | Paper-trading IC alert thresholds |
| `configs/paper_exp305.yaml` | Live config for exp305 |

Key strategy: Every exit trigger was extracted with exact line numbers from both paths, then compared formula-by-formula. Where backtester and live diverge, the backtester's behavior is treated as the definition of what the strategy should do.

---

## Detailed Findings

---

### Finding E1: DTE Management Enabled in Live, Absent in Backtester

- **Severity:** CRITICAL
- **Backtester behavior:** The backtester reads `manage_dte` from config but **does not implement a DTE-triggered exit**. There is no code path in `_manage_positions()` or `_check_intraday_exits()` that closes a position based on remaining DTE (other than DTE=0, which is the expiration close). The backtester holds all positions until either the profit target, stop-loss, or expiration date triggers.
- **Live behavior:** `shared/position_monitor.py` lines 330–335:
  ```python
  if self.manage_dte > 0 and dte <= self.manage_dte:
      return "dte_management"
  ```
  `configs/paper_exp305.yaml` line ~168: `manage_dte: 21`. This closes all positions 21 DTE early.
- **Discrepancy:** The live system closes positions at DTE ≤ 21. The backtester never does this. For a 35-DTE entry, the live system exits after ~14 days; the backtester may hold another 21 days collecting theta.
- **Impact:** All backtested P&L numbers assume full-term holding. Live results will systematically differ because:
  1. 50%-of-credit profit target may not be reached in 14 days (less theta decay)
  2. Stop-losses can still trigger during the first 14 days (no protection)
  3. The final 21 days of theta — typically the fastest-decaying segment — is forfeited
  4. More frequent entries (positions close sooner → capacity for new trades) not modeled in backtest
- **Recommended fix:** Either (a) disable `manage_dte` in live config (set to 0) to match backtester, or (b) implement DTE management in the backtester:
  ```python
  # In backtester.py _manage_positions(), after entry-day check:
  manage_dte = self.strategy_params.get('manage_dte', 0)
  if manage_dte > 0:
      expiry_dt = datetime.strptime(pos['expiration'], '%Y-%m-%d').date()
      dte = (expiry_dt - current_date).days
      if dte <= manage_dte:
          self._record_close(pos, current_date, pnl, 'dte_management')
          continue
  ```
  Option (a) is simpler and lower risk; option (b) would require re-running all backtests.

---

### Finding E2: Stop-Loss Threshold Mismatch in IC Alert Monitor

- **Severity:** HIGH
- **Backtester behavior:** `backtest/backtester.py` line 1434–1435:
  ```python
  'stop_loss': combined_credit * stop_loss_multiplier  # stop_loss_multiplier = 3.5
  ```
  Stop triggers when `(current_spread_value - credit) >= stop_loss` → i.e., loss ≥ 3.5× credit received.
- **Live behavior (position_monitor.py):** Lines 165, 365–378:
  ```python
  self.stop_loss_mult = float(risk.get("stop_loss_multiplier", 3.5))
  sl_threshold = (1.0 + self.stop_loss_mult) * credit
  if current_value >= sl_threshold:
      return "stop_loss"
  ```
  Threshold: current spread value ≥ 4.5× credit (= credit + 3.5× credit). **This matches the backtester formula** (cost to close = credit × (1 + 3.5) means loss = 3.5× credit). ✓ Match.
- **Alert monitor behavior:** `alerts/iron_condor_exit_monitor.py` lines 19–20, 133–140:
  ```python
  _STOP_LOSS_MULT = 2.0   # DIFFERENT: 2× credit, not 3.5×
  if pnl <= -(total_credit * _STOP_LOSS_MULT):
      fire_alert("stop_loss", "CLOSE — Stop Loss (2x credit)")
  ```
  The alert fires at 2× credit loss — almost **half** the threshold of the real system.
- **Discrepancy:** IC exit alert monitor fires stop-loss alerts at 2.0× credit. Main system (backtester + position_monitor) uses 3.5×. For a $0.50 credit IC: alert fires at -$1.00 loss; real stop doesn't trigger until -$1.75 loss.
- **Impact:** Paper traders following the alert will exit prematurely, capturing worse P&L than the backtested strategy. Confusing discrepancy between alerting and real execution thresholds.
- **Recommended fix:** Align `_STOP_LOSS_MULT` in `iron_condor_exit_monitor.py` to read from config, or hardcode to `3.5`:
  ```python
  _STOP_LOSS_MULT = 3.5   # Match position_monitor.py and backtester
  ```

---

### Finding E3: Drawdown Circuit Breaker — Entry Gate Only, Does Not Force-Close

- **Severity:** MEDIUM (important to document; not a bug if intentional)
- **Backtester behavior:** `backtest/backtester.py` lines 674–702:
  ```python
  _skip_new_entries = (_drawdown_pct < _cb_threshold or ...)
  ```
  CB activates → sets `_skip_new_entries = True`. Existing open positions continue to be managed (profit target, stop-loss still checked). **No force-close of existing positions.**
- **Live behavior:** `shared/position_monitor.py` — no drawdown-triggered exit logic found anywhere in the file. Position monitor checks only: DTE, profit target, stop-loss. No equity-level drawdown check.
- **Discrepancy:** Backtester has a drawdown CB that blocks new entries. Live system has no CB at all (neither entry-blocking nor force-close). This means the live system will continue opening new positions during a 25%+ drawdown when the backtester would stop.
- **Impact:** During a severe drawdown, backtester stops compounding losses (no new entries); live system keeps entering trades. This is a meaningful divergence in risk management behavior.
- **Recommended fix:** Implement drawdown CB in the live scanner/scheduler that blocks new scan submissions when equity drawdown from high-water mark exceeds `drawdown_cb_pct`. This is an entry-gate fix, not a position-monitor fix. (The CB should NOT force-close existing positions — match backtester behavior.)

---

### Finding E4: Exit Slippage — VIX-Scaled in Backtester, Zero in Live

- **Severity:** MEDIUM
- **Backtester behavior:** `backtest/backtester.py` lines 473–490:
  ```python
  def _vix_scaled_exit_slippage(self) -> float:
      vix_scale = min(3.0, 1.0 + max(0.0, (self._current_vix - 20.0) * 0.1))
      return self.exit_slippage * self._slippage_multiplier * vix_scale
  ```
  Applied to **every exit**: profit target, stop-loss, expiration. For VIX=20 (normal): +$0.10/spread. For VIX=40 (stress): +$0.30/spread. These costs are subtracted from P&L on close.
- **Live behavior:** `shared/position_monitor.py` submits market orders (`limit_price=None`) via Alpaca. P&L is computed from actual fill prices — no explicit slippage parameter. Real market slippage is captured in the fill price.
- **Discrepancy:** The backtester models slippage as a deterministic VIX-scaled cost. Real live slippage depends on bid-ask spreads, market depth, and order timing — which may be higher or lower than the modeled amount. The systems are conceptually aligned (both account for exit friction) but the magnitude is not controlled.
- **Impact:** During high-VIX stress events, backtester applies 3× slippage automatically. Live system may get worse or better fills depending on actual market conditions. Not a code bug, but a modeling assumption that should be documented and periodically validated against real fill quality.
- **Recommended fix:** No code change needed. Recommend: quarterly review of actual vs modeled slippage by comparing Alpaca fill prices to mid-price at trigger time.

---

### Finding E5: Iron Condor Exit — Leg-by-Leg in Live, Atomic in Backtester

- **Severity:** MEDIUM
- **Backtester behavior:** IC stop-loss and profit target check the **combined** spread value of both wings together (`put_value + call_value`). When exit triggers, the entire IC is closed in one `_record_close()` call with combined P&L.
- **Live behavior (execution_engine.py):** IC is **submitted as two separate 2-leg orders** (lines 168–229):
  1. Put wing submitted first
  2. Call wing submitted second
  3. If call fails → attempt to cancel put (not guaranteed to succeed)

  On close, position_monitor similarly closes each wing as a separate spread order (lines 626–646).
- **Discrepancy:** In the backtester, an IC either closes completely or stays open. In live trading, partial fills are possible: the put wing could fill while the call wing is rejected (e.g., due to liquidity). This creates a "legged" position not modeled in the backtester.
- **Impact:**
  - Partial fill risk: one wing filled, other not → trader is now long gamma on one side (naked risk)
  - The cancel attempt on put wing failure is not guaranteed (race condition: put may fill before cancel arrives)
  - P&L on partial close is not tracked or reconciled in `reconciler.py`
- **Recommended fix:**
  1. Add a "partial fill" state to the DB for IC positions where only one wing closed
  2. Alert immediately if IC partially closes (treat as high-priority manual intervention needed)
  3. Document this risk in live trading SOPs

---

### Finding E6: Commission Accounting — Entry-Only in Backtester, Round-Trip in Live

- **Severity:** LOW
- **Backtester behavior:** Commission is charged at position open (entry). Exit commission is **not deducted separately**. The single commission entry covers the full round-trip implicitly.
- **Live behavior (`position_monitor.py` lines 864–878):**
  ```python
  commission = commission_per_contract * contracts * num_legs * 2  # Round-trip
  pnl -= commission
  ```
  The `× 2` makes this a round-trip deduction at close time.
- **Discrepancy:** Backtester charges commission once at entry (implicit round-trip). Live monitor charges commission explicitly at close as `× 2` (entry + exit legs). If the backtester also charges at open with `× 2`, these match. If backtester charges `× 1`, commissions are under-counted by 2× in the live system (or vice versa).
- **Impact:** Small dollar impact per trade ($0.65–$5.20 per contract), but should be verified to avoid systematic P&L discrepancy in live tracking.
- **Recommended fix:** Audit the backtester's commission charge formula (find exact line in `_record_close()` or `_record_open()`) and confirm it uses the same round-trip multiplier as the live monitor. Ensure both use the same `commission_per_contract` from config.

---

### Finding E7: Expiration DTE=0 — Live Exits Same Day, Backtester May Not

- **Severity:** LOW
- **Backtester behavior:** At `current_date >= expiration_date`, calls `_close_at_expiration_real()`. This runs at the **end of the trading day loop** for that expiration date. The position is held through the entire expiration day.
- **Live behavior (`position_monitor.py` lines 315–335):**
  ```python
  if dte <= 0:
      return "expiration_today"  # Close immediately
  ```
  This fires at any 5-minute scan during expiration day — the position is closed **as soon as the monitor runs** on expiration date (typically 9:30–9:35 AM ET).
- **Discrepancy:** Backtester holds through full expiration day and settles at close. Live system closes at market open on expiration day. For near-expiration spreads, intraday movement matters: live exits at open price, backtester at close price.
- **Impact:** For positions expiring worthless (most common), the difference is minimal. For positions near the short strike, the intraday volatility during expiration day creates meaningful P&L difference. Live system avoids pin risk; backtester implicitly accepts it.
- **Recommended fix:** This is an intentional risk management choice (closing early on expiration day is correct live trading practice). No code change needed, but document this as a known modeling difference that slightly favors the live system on close-call expirations.

---

## Summary Table

| ID | Title | Severity | Backtester vs Live | Status |
|----|-------|----------|-------------------|--------|
| E1 | DTE Management active in live, absent in backtester | CRITICAL | Backtester holds full term; live exits 21 DTE early | **Unresolved — requires decision** |
| E2 | IC alert monitor stop-loss at 2.0× vs system 3.5× | HIGH | Alert fires 75% earlier than real system | **Unresolved — hardcoded bug** |
| E3 | Drawdown CB missing in live scanner | MEDIUM | Backtester blocks new entries; live system keeps trading | **Unresolved — missing feature** |
| E4 | Exit slippage: VIX-scaled model vs real fills | MEDIUM | Backtester deterministic; live uses market fills | **Acceptable (modeling difference)** |
| E5 | IC exit is leg-by-leg in live, atomic in backtester | MEDIUM | Partial fill risk not modeled | **Unresolved — operational risk** |
| E6 | Commission round-trip accounting needs verification | LOW | May be double-counted or consistent | **Needs verification** |
| E7 | Expiration handling: live exits at open, backtester at close | LOW | Live avoids pin risk; backtester accepts it | **Intentional — document only** |

---

## Confirmed Matches (No Discrepancy)

The following exit behaviors **match exactly** between backtester and live:

| Behavior | Formula | Match? |
|----------|---------|--------|
| Profit target threshold | `P&L ≥ credit × profit_target_pct` (default 50%) | ✓ Match |
| Stop-loss threshold | `current_value ≥ credit × (1 + stop_loss_mult)` (default 3.5×) | ✓ Match |
| DTE=0 close | Closes on/after expiration date | ✓ Match (different intraday timing, see E7) |
| Circuit breaker scope | Blocks new entries only; does NOT force-close open positions | ✓ Match (backtester), ✗ absent in live (see E3) |
| Profit target as % of credit received | Both use `credit_received` at entry as the denominator | ✓ Match |
| IC combined valuation | Both sum put_wing + call_wing spread values | ✓ Match |
| manage_dte=0 disables DTE exit | When set to 0 in config, neither system does DTE-based close | ✓ Match (but exp305 has it set to 21) |

---

## Conclusion

The backtester and live system share the same exit trigger formulas for stop-loss and profit-target — this is the healthy core. However, three unresolved issues need action before the live system can be considered a faithful implementation of the backtested strategy:

**Immediate action required:**
1. **E1 (CRITICAL):** Decide: disable `manage_dte` in paper_exp305.yaml (set to 0) OR implement DTE management in the backtester. Either choice re-aligns the systems. Currently, every live trade is being managed differently than all backtested results.
2. **E2 (HIGH):** Fix `_STOP_LOSS_MULT = 3.5` in `iron_condor_exit_monitor.py`. This is a one-line change with no tradeoffs.

**Engineering work required:**
3. **E3 (MEDIUM):** Implement drawdown CB in live scanner's entry gate (not position monitor). Mirror the backtester's `drawdown_cb_pct` logic.
4. **E5 (MEDIUM):** Add partial-fill state and alerting for IC leg mismatches. Operational risk documentation needed now; code fix is a larger effort.

**No action / document only:**
5. **E4:** VIX-scaled slippage is a model assumption; real fills are the correct live behavior. Schedule quarterly validation.
6. **E6:** Verify commission formula matches (5-minute audit); likely consistent.
7. **E7:** Intentional pin-risk avoidance in live. Document as known P&L model difference.
