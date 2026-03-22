# Backtest vs Live Scanner Audit v2
**Date**: 2026-03-10
**Original items**: 27
**Status**: 14 FIXED ✅ | 4 PARTIALLY FIXED ⚠️ | 9 STILL OPEN ❌ | 6 NEW ❌

---

## Executive Summary

- **The most critical IC sizing bug (D3) is FIXED** in both the `_flat_risk_size` path and `_portfolio_risk_size` path of `alert_position_sizer.py`. The `max_loss = 2 * spread_width - combined_credit` formula now matches the backtester exactly.
- **The regime default mismatch (D8) is FIXED**: `spread_strategy.py` now defaults to `regime_mode = 'combo'` matching the backtester. The fallback on detector failure now defaults to `'BULL'` (matching backtester's optimistic prior), not `'NEUTRAL'`.
- **The score gate (D1) is FIXED**: `AlertRouter.route_opportunities()` no longer applies a score ≥ 60 threshold. All opportunities flow through unless blocked by the risk gate.
- **The dedup granularity mismatch (D13) is FIXED**: dedup key is now `(ticker, expiration, strike_type)` matching backtester `_open_keys`, not coarse `(ticker, direction)`.
- **The drawdown CB reference (D14) is FIXED**: `RiskGate` now uses `starting_capital` for flat/non-compound mode and `peak_equity` for compound mode, mirroring the backtester exactly.
- **Six new discrepancies were found**, including a CRITICAL IC min-credit denominator bug still present in `spread_strategy.find_iron_condors`, a MEDIUM slippage application mismatch in `_find_spreads`, and a HIGH COMPASS macro scaling gap in the flat sizing path.

---

## Original Discrepancies (27 items)

### D1 — Scoring / Entry Gate | FIXED ✅
**Original severity**: CRITICAL
**Backtester**: No scoring system. Entry decided by regime + credit floor + momentum filter.
**Live scanner (new)**: `alert_router.py:96-108` — score gate removed. Comment: *"Score gate removed — the backtester has no scoring system; entry is decided solely by regime + credit floor + momentum filter."*
**Status detail**: The score ≥ 60 gate at `AlertRouter` has been deleted. All opportunities that pass the risk gate are dispatched. `AlertGenerator` still filters at `min_score=28` (`alert_generator.py:58-60`) but this is for file/CSV output only — the router pipeline receives all opportunities regardless of score. FIXED.

---

### D2 — Min Credit Gate (slippage timing) | PARTIALLY FIXED ⚠️
**Original severity**: CRITICAL
**Backtester**: `backtester.py:1575-1594` — min_credit check applied AFTER slippage deduction: `credit = prices["spread_value"]; slippage = ...; credit -= slippage; if credit < min_credit: return None`
**Live scanner**: `spread_strategy.py:534-562` — slippage IS now subtracted before the min-credit check: `credit = short_leg['bid'] - long_leg['ask']; credit -= _slippage; if credit < min_credit: continue`
**Status detail**: PARTIALLY FIXED. The slippage deduction is now applied before the min-credit gate, matching the backtester's ordering. However, the live slippage value comes from `config.backtest.slippage` (a flat config value, e.g., 0.05), while the backtester uses `prices.get("slippage", self.slippage) * self._slippage_multiplier` which is bar-specific (derived from intraday high-low). The live path cannot replicate bar-specific slippage because it uses a live options chain, not historical bars. The ordering is now correct but the magnitude is still different.

---

### D3 — Iron Condor max_loss Formula | FIXED ✅
**Original severity**: CRITICAL
**Backtester**: `backtester.py:1352` — `max_loss = (2 * spread_width) - combined_credit`
**Live scanner (flat path)**: `alert_position_sizer.py:302-304` — `max_loss_per_spread = max((2 * spread_width - credit) * 100, 1.0)`
**Live scanner (portfolio path)**: `alert_position_sizer.py:176-178` — `max_loss_per_spread = max((2 * spread_width - credit) * 100, 1.0)`
**Status detail**: FIXED in both sizing paths. The formula now correctly models both wings losing simultaneously. ICs are no longer over-sized by 2×.

---

### D4 — Macro Event Gate (FOMC/CPI/NFP) | STILL OPEN ❌
**Original severity**: CRITICAL
**Backtester**: No macro event gate in entry path.
**Live scanner**: `macro_event_gate.py` writes `event_scaling_factor` to `macro_state.db`. No code in the scan path reads this key. `_augment_with_compass_state()` in `main.py:229-263` does not read `event_scaling_factor`. `AlertPositionSizer` does not read it.
**Status detail**: STILL OPEN. The macro event gate infrastructure exists but is completely disconnected from the live entry path. Both paths are now consistent (both ignore it), so the discrepancy is between documented behavior and actual behavior, not between backtest and live. No change from v1 audit. Architectural debt: D4 is consistently ignored by both paths.

---

### D5 — Stop-Loss Threshold Definition | STILL OPEN ❌
**Original severity**: CRITICAL
**Backtester**: `backtester.py:1712` — `'stop_loss': credit * self.risk_params['stop_loss_multiplier']`; triggers when `spread_value - credit >= stop_loss`. No width cap.
**Live scanner (spread_strategy.py)**: `spread_strategy.py:429` — `'stop_loss': round(combined_credit * self.risk_params['stop_loss_multiplier'], 2)`. The PositionMonitor (not in this audit's file list but referenced in original) adds `min((1+mult)×credit, spread_width × 0.90)` cap.
**Status detail**: STILL OPEN. The spread_strategy computes `stop_loss = credit × multiplier` correctly, matching the backtester. But the PositionMonitor (execution/position_monitor.py) adds a `spread_width × 0.90` backstop that the backtester does not have. This causes live exits to trigger earlier than backtested on any spread where `credit × (1 + multiplier) > spread_width × 0.90`. For thin-credit entries at 10-15% of spread width, this backstop fires before the configured stop.

---

### D6 — DTE Management Exit (live only) | STILL OPEN ❌
**Original severity**: CRITICAL
**Backtester**: No DTE-based exit. Positions held to expiration, profit target, or stop.
**Live scanner**: `PositionMonitor` closes at `manage_dte=21` DTE. The backtester never models this.
**Status detail**: STILL OPEN. The structural difference remains: backtester holds 35-DTE positions for ~35 days; live closes them at 21 DTE (after ~14 days). A 35-DTE position that would expire worthless in the backtester always collects full credit; live only collects whatever the mid is at 21 DTE (typically 60-75% of max profit). The `_validate_dte()` method in `alert_router.py:353-384` enforces DTE window at entry but does NOT add DTE-based exit to the backtester.

---

### D7 — IC Construction: Slippage in Live Path | PARTIALLY FIXED ⚠️
**Original severity**: CRITICAL
**Backtester**: `backtester.py:1591` — `slippage = prices.get("slippage", self.slippage) * self._slippage_multiplier; credit -= slippage`
**Live scanner**: `spread_strategy.py:539-542` — `_slippage = float(self.config.get('backtest', {}).get('slippage', 0.0)); credit -= _slippage`
**Status detail**: PARTIALLY FIXED. Slippage is now deducted in the live path (it was not before). The flat config value from `backtest.slippage` is used. But live cannot model bar-specific slippage (function of intraday H-L range) because it uses real-time chain data, not historical bars. The direction of the fix is correct; the magnitude remains non-identical. For the champion configs with `slippage=0.05`, this is a reasonable approximation.

---

### D8 — Regime Detection Mode Default | FIXED ✅
**Original severity**: HIGH
**Backtester**: `backtester.py:407` — `self._regime_mode: str = self.strategy_params.get('regime_mode', 'combo')`
**Live scanner**: `spread_strategy.py:60` — `self.regime_mode = self.strategy_params.get('regime_mode', 'combo')`
**Status detail**: FIXED. Both now default to `'combo'`. The fallback on detector failure was also corrected: `main.py:403` — `technical_signals['combo_regime'] = 'BULL'` (was `'NEUTRAL'` in v1), matching the backtester's optimistic prior (`combo_regime_detector.py:125`: `current_regime = 'BULL'`).

---

### D9 — Trend MA Period in Live Spread Strategy | FIXED ✅
**Original severity**: HIGH
**Backtester**: Uses `trend_ma_period` from config for MA direction filter; in combo mode, direction decided by `ComboRegimeDetector` (MA200 + RSI + VIX structure).
**Live scanner**: `spread_strategy.py:195-236` — `_check_bullish_conditions` / `_check_bearish_conditions` uses `technical_signals.get('trend')` from `TechnicalAnalyzer`. BUT: when `regime_mode='combo'`, direction is decided by `technical_signals.get('combo_regime')` injected in `main.py:372-403`. The `_check_bullish_conditions` trend filter is still executed but `ComboRegimeDetector` output in `combo_regime` takes precedence via the `evaluate_spread_opportunity` call.
**Status detail**: FIXED for combo mode. When `regime_mode='combo'` (the new default), `ComboRegimeDetector.compute_regime_series()` is run with the same 3-signal logic (MA200, RSI, VIX structure) as the backtester, producing the same `BULL/BEAR/NEUTRAL` labels. The `_check_bullish_conditions` path is only the fallback for non-combo mode.

---

### D10 — IV Rank Entry Gate | FIXED ✅
**Original severity**: HIGH
**Backtester**: `backtester.py:688-689` — `_iv_rank_min = self.strategy_params.get('iv_rank_min_entry', 0)`. Default 0 = disabled.
**Live scanner**: `spread_strategy.py:212-213` — `_min_iv_rank = self.strategy_params.get('min_iv_rank', 0); _min_iv_pct = self.strategy_params.get('min_iv_percentile', 0)`. Gate only applied when `_min_iv_rank > 0 or _min_iv_pct > 0`.
**Status detail**: FIXED. The live scanner now defaults to 0 (disabled), matching the backtester. The `config.yaml` value of `min_iv_rank: 12` can still be set for specific experiments but is not applied by default. Both paths are config-driven and use the same default of disabled.

---

### D11 — Position Sizing: IV-Scaled Path | FIXED ✅
**Original severity**: HIGH
**Backtester**: `backtester.py:1636-1640` — `iv_scaled` mode uses `calculate_dynamic_risk()` with 40% heat cap; no extra `MAX_RISK_PER_TRADE` cap.
**Live scanner**: `alert_position_sizer.py:382-385` — `_legacy_size()` (used when no config injected): `dollar_risk = calculate_dynamic_risk(account_value, iv_rank, current_portfolio_risk)`. Comment: *"Matches backtester: only the 40% portfolio heat cap inside calculate_dynamic_risk applies. The MAX_RISK_PER_TRADE extra cap layer and weekly-loss breach reduction are removed (backtester has neither)."*
**Status detail**: FIXED. The extra `MAX_RISK_PER_TRADE` hard cap that was previously applied in `_legacy_size` has been removed. The legacy path now matches the backtester's single heat-cap behavior.

---

### D12 — Options Data Source | STILL OPEN ❌
**Original severity**: HIGH
**Backtester**: Polygon historical options cache (SQLite) — real bid/ask from 5-min bars; slippage from bar H-L.
**Live scanner**: Real-time options chain from Polygon/Tradier — live bid/ask; delta available; flat config slippage.
**Status detail**: STILL OPEN. This is an inherent architectural difference that cannot be fully closed without adding slippage estimation to the live scanner. The live path now applies flat slippage (D7 fix), which partially addresses this, but bar-specific slippage cannot be replicated in real-time. Delta is available live (from chain delta field) but not in the backtester cache. Strike selection methodology remains different (OTM% in backtester vs delta range in live by default).

---

### D13 — Max Positions Per Ticker / Dedup Granularity | FIXED ✅
**Original severity**: HIGH
**Backtester**: `backtester.py:754-761` — `_open_keys` set uses `(expiration, short_strike, 'P'/'C'/'IC')` keys.
**Live scanner**: `alert_router.py:297-317` — `_dedup_key()` returns `(alert.ticker, expiration, strike_type)` where `strike_type` is `'P'`, `'C'`, or `'IC'`. Comment: *"Matches backtester _open_keys granularity: same contract blocked, different OK."* Persisted to SQLite across restarts.
**Status detail**: FIXED. The dedup key now includes expiration and option type (P/C/IC), matching the backtester's contract-level dedup. Different expirations on the same ticker are allowed (as in the backtester). The ledger is persisted to SQLite via `upsert_dedup_entry()` so restarts don't lose state.

---

### D14 — Drawdown Circuit Breaker Reference | FIXED ✅
**Original severity**: HIGH
**Backtester**: `backtester.py:679-683` — compound mode uses `peak_capital` (high-water mark); non-compound uses `starting_capital`.
**Live scanner**: `risk_gate.py:199-205` — `sizing_mode = config.risk.sizing_mode; compound = config.backtest.compound; use_flat = (sizing_mode == "flat") or (not compound)`. If `use_flat`: `cb_reference = starting_capital`; else: `cb_reference = account_state.get("peak_equity", starting_capital)`.
**Status detail**: FIXED. The RiskGate now mirrors the backtester's compound/flat distinction exactly. The comment in `risk_gate.py:196-197` explicitly references the backtester lines.

---

### D15 — Slippage: Entry vs Live | PARTIALLY FIXED ⚠️
**Original severity**: MEDIUM
**Backtester**: Bar-derived slippage: `(high - low) / 2` per leg, then `* slippage_multiplier`.
**Live scanner**: `spread_strategy.py:539-542` — flat slippage from `config.backtest.slippage`. Applied before min-credit check.
**Status detail**: PARTIALLY FIXED. Flat slippage is now applied (was not in v1). The methodology is still different (flat vs bar-derived), which is unavoidable in real-time trading. For champion configs with `slippage=0.05`, the flat value is close to average bar-derived slippage. The `slippage_multiplier` brutality factor is NOT applied in the live path — only the base slippage value.

---

### D16 — Commission Model | STILL OPEN ❌
**Original severity**: MEDIUM
**Backtester**: `backtester.py:1596` — `commission_cost = self.commission * 2` at entry; exit commission deducted from PnL in `_record_close`. Default `0.65/contract`.
**Live scanner**: Commission defaults to 0 in paper configs. `execution.commission_per_contract` not set in `paper_exp305.yaml`. PositionMonitor charges round-trip commissions when configured.
**Status detail**: STILL OPEN. No change. Default commission in paper trading is effectively 0, while backtester uses 0.65/contract. For paper trading this is acceptable, but it means paper P&L will be slightly higher than backtest P&L. Not materially impactful at typical contract sizes.

---

### D17 — Profit Target Calculation | FIXED ✅
**Original severity**: MEDIUM
**Backtester**: `backtester.py:1711` — `'profit_target': credit * self._profit_target_pct` where `_profit_target_pct = risk_params['profit_target'] / 100.0`.
**Live scanner**: `spread_strategy.py:585` — `'profit_target': round(credit * self.risk_params['profit_target'] / 100, 2)`. Same formula.
**Status detail**: FIXED (was already consistent in v1; confirmed consistent in v2). Both paths compute `credit × (profit_target / 100)`.

---

### D18 — VIX Entry Gate | FIXED ✅
**Original severity**: MEDIUM
**Backtester**: `backtester.py:694-695` — `_vix_max = strategy_params.get('vix_max_entry', 0); _vix_too_high = _vix_max > 0 and current_vix > _vix_max`. Hard block.
**Live scanner**: `risk_gate.py:219-228` — `vix_max_entry = config.strategy.get('vix_max_entry', 0); if vix_max_entry > 0 and current_vix > vix_max_entry: return (False, reason)`. Hard block. `current_vix` populated in `_build_account_state()` from VIX history.
**Status detail**: FIXED. The live scanner now has a hard VIX block matching the backtester's `vix_max_entry` gate. The `account_state['current_vix']` is populated by `main.py:573-576`.

---

### D19 — Spread Width Selection (Dynamic IV) | FIXED ✅
**Original severity**: MEDIUM
**Backtester**: `backtester.py:1173` — `spread_width = self.strategy_params['spread_width']`. Single fixed config value.
**Live scanner**: `spread_strategy.py:514` — `spread_width = self.strategy_params.get('spread_width', self.default_spread_width)`. Comment: *"Single spread_width from config — matches backtester (no IV-based switching)"*. Also `spread_strategy.py:359` — same pattern in `find_iron_condors`.
**Status detail**: FIXED. The dynamic IV-based spread width switching (`_select_spread_width()`) is still defined in `spread_strategy.py:143-151` but is NOT called in `_find_spreads()` or `find_iron_condors()`. Both now use the fixed `config.strategy.spread_width`. The `_select_spread_width` method is dead code.

---

### D20 — Strike Selection Method | STILL OPEN ❌
**Original severity**: MEDIUM
**Backtester**: `backtester.py:1508-1520` — OTM% method: `target_short = price * (1 - otm_pct)`, finds closest available strike.
**Live scanner**: `spread_strategy.py:486-511` — when `use_delta_selection=False` (default): uses delta range filter `min_delta/max_delta` from config (e.g., 0.20-0.30). When `use_delta_selection=True`: uses `select_delta_strike()` with `target_delta`.
**Status detail**: STILL OPEN. Strike selection methodology remains different. OTM% (backtester default, e.g., 5% OTM for champion configs) vs delta range filter (live default, e.g., delta 0.20-0.30) will select different strikes in practice. A 5% OTM strike on SPY at $450 = $427.50, which typically corresponds to roughly 0.10-0.15 delta — outside the live 0.20-0.30 range. Live scanner selects *closer* strikes (higher delta = higher credit but lower probability). This is a material discrepancy for strike selection.

---

### D21 — Expiration Selection / MWF Logic | FIXED ✅
**Original severity**: MEDIUM
**Backtester**: `_nearest_weekday_expiration()` or `_nearest_mwf_expiration()` — targets ONE specific date closest to target_dte with Friday preference.
**Live scanner**: `spread_strategy.py:153-193` — `_filter_by_dte()` now returns a LIST with AT MOST ONE expiration: `return [min(valid_expirations, key=_pref)]` where `_pref` prefers Friday and closest-to-target. Comment: *"Matches backtester behavior: _nearest_weekday_expiration selects ONE date closest to target_dte, preferring Fridays."*
**Status detail**: FIXED. The multi-expiration issue from v1 is resolved. Live now selects one expiration matching backtester's logic. Friday preference is explicit: `is_not_friday = 0 if exp.weekday() == 4 else 1` (lower = preferred).

---

### D22 — Weekly Loss Breach Sizing | STILL OPEN ❌
**Original severity**: MEDIUM
**Backtester**: Not implemented. No weekly loss size reduction.
**Live scanner**: `alert_position_sizer.py:290-295` — `if strategy_cfg.get("compass_enabled", False): effective_risk_pct *= self._macro_scale(macro_score)`. Note: weekly loss breach is passed into `_flat_risk_size()` as `weekly_loss_breach` parameter but is NOT used in the function body. The 50% reduction is only in `_legacy_size` path which is no longer used.
**Status detail**: STILL OPEN — but with a nuance. The `weekly_loss_breach` parameter in `_flat_risk_size` is accepted but not applied. The 50% size reduction for weekly breach that existed in the old code path is effectively dead. This means both paths now agree (neither applies weekly breach sizing in the flat path), but the INTENT was for live to be more conservative. The discrepancy is now that the RiskGate flag (rule 4 in `risk_gate.py:126-135`) notes the weekly breach but no downstream consumer actually cuts size.

---

### D23 — COMPASS Macro Scoring | PARTIALLY FIXED ⚠️
**Original severity**: MEDIUM
**Backtester**: `backtester.py:1643-1644` — `if self._compass_enabled: trade_dollar_risk *= self._current_compass_mult`. Applied in flat sizing mode when `strategy.compass_enabled=True`.
**Live scanner (flat path)**: `alert_position_sizer.py:293-295` — `if strategy_cfg.get("compass_enabled", False): effective_risk_pct *= self._macro_scale(macro_score)`. Applied in `_flat_risk_size()`.
**Live scanner (portfolio path)**: `alert_position_sizer.py:168` — `effective_risk_pct = raw_risk_pct * self._macro_scale(macro_score)`. Always applied.
**Status detail**: PARTIALLY FIXED. The flat-risk path now applies COMPASS macro scaling when `strategy.compass_enabled=True`, matching the backtester. This was the key gap in v1. However: (1) the backtester uses 5 thresholds (ra<30→1.2×, ra<45→1.1×, ra>75→0.85×, ra>65→0.95×) while the live `_macro_scale()` uses only 2 thresholds (<45→1.2×, >75→0.85×). The intermediate tiers (1.1×, 0.95×) are missing from the live path. (2) The live path reads the macro score from `macro_state.db` at sizing time; the backtester uses a pre-computed daily series with forward-fill — consistent semantics but different fetch patterns.

---

### D24 — Regime Default Starting State | FIXED ✅
**Original severity**: LOW
**Backtester**: `combo_regime_detector.py:125` — `current_regime = 'BULL'` (optimistic prior).
**Live scanner**: `main.py:403` — on ComboRegimeDetector failure: `technical_signals['combo_regime'] = 'BULL'`. (Was `'NEUTRAL'` in v1.)
**Status detail**: FIXED. Fallback on detector failure now matches the backtester's optimistic BULL prior.

---

### D25 — Friday/Expiration Week Handling | FIXED ✅
**Original severity**: LOW
**Backtester**: Explicit MWF/weekday expiration selection logic with Friday fallback tracking.
**Live scanner**: `spread_strategy.py:187-193` — `_filter_by_dte()` now explicitly prefers Friday: `is_not_friday = 0 if exp.weekday() == 4 else 1`.
**Status detail**: FIXED. Friday preference is now explicit in the live path, mirroring the backtester's preference ordering.

---

### D26 — Lookback for Regime Data | STILL OPEN ❌
**Original severity**: LOW
**Backtester**: `backtester.py:513-514` — `_MA_WARMUP_DAYS = max(30, int(trend_ma_period * 1.4) + 15)`. For MA200: ~295 calendar days.
**Live scanner**: `main.py:340-341` — `_period = '2y' if regime_mode == 'combo' else '1y'`. For combo mode: 2-year window (~504 trading days).
**Status detail**: STILL OPEN — but the live path's 2y window (for combo mode) is MORE than sufficient to warm up MA200 (which needs ~280 trading days). The risk identified in v1 (insufficient warmup) does not manifest in practice. This is a LOW risk item and the live path is actually more conservative in data fetching.

---

### D27 — Score Threshold in AlertGenerator | FIXED ✅
**Original severity**: LOW
**Backtester**: No min_score concept.
**Live scanner**: `alert_generator.py:33,57-61` — `min_alert_score = config.alerts.get('min_score', 28)`. Only affects file/CSV output, NOT the alert router pipeline. AlertRouter no longer has a score gate.
**Status detail**: FIXED. The double-threshold confusion (AlertGenerator at 28 + AlertRouter at 60) is resolved since AlertRouter's 60-point gate was removed. AlertGenerator's 28-point gate now only affects text/CSV file output, not trade execution.

---

## New Discrepancies

### N1 — IC Min Combined Credit Denominator | Severity: HIGH ❌
**Backtester**: `backtester.py:1334-1339`
```python
min_combined_credit_pct = strategy_params.get('iron_condor', {}).get('min_combined_credit_pct', 20)
min_combined_credit = (2 * spread_width) * (min_combined_credit_pct / 100)
# "Denominator is 2×spread_width (total IC risk)"
```
For a $5-wide IC with 20% threshold: requires $2.00 combined credit.

**Live scanner**: `spread_strategy.py:398`
```python
if (combined_credit / spread_width) * 100 < min_combined_credit_pct:
    continue
```
For a $5-wide IC with 20% threshold: requires only $1.00 combined credit.

**Impact**: The live scanner admits ICs with half the credit minimum required by the backtester. Live will enter ~2× more ICs than the backtest would. Each of those extra ICs has a lower risk-adjusted credit profile. This was flagged as CRITICAL in v1 and remains unfixed.
**Fix**: Change `spread_strategy.py:398` from `combined_credit / spread_width` to `combined_credit / (2 * spread_width)`.

---

### N2 — IC Synthetic Credit Cap (live only) | Severity: MEDIUM ❌
**Backtester**: `backtester.py:1329-1331` — no credit cap. Uses raw combined credit from real Polygon data.
**Live scanner**: `spread_strategy.py:386-389`
```python
if combined_credit > spread_width * 0.50:
    combined_credit = round(spread_width * 0.35, 2)
```
**Impact**: For ICs where both wings have rich credits (common in high IV), the live scanner caps the recorded credit at 35% of spread width, then computes `max_loss = spread_width - combined_credit` based on the capped value. This understates the actual credit received and results in different stop/profit levels than the backtester would produce. The cap does NOT exist in the backtester.
**Fix**: Remove the synthetic credit cap from `spread_strategy.find_iron_condors`. Real data (Polygon chain) should not need a synthetic cap. If it does fire, it indicates a real data quality issue that should be logged, not silently corrected.

---

### N3 — COMPASS Macro Scale: Missing Intermediate Tiers | Severity: MEDIUM ❌
**Backtester**: `backtester.py:607-616`
```python
if ra < 30:   mult = 1.2
elif ra < 45: mult = 1.1
elif ra > 75: mult = 0.85
elif ra > 65: mult = 0.95
else:         mult = 1.0
```
5 tiers: 1.2×, 1.1×, 1.0×, 0.95×, 0.85×

**Live scanner**: `alert_position_sizer.py:235-246`
```python
if score < 45:   return 1.2   # fear boost
if score > 75:   return 0.85  # greed reduction
return 1.0
```
3 tiers: 1.2×, 1.0×, 0.85× (missing 1.1× for 30-45 range and 0.95× for 65-75 range)

**Impact**: When `compass_enabled=True` and risk_appetite is 30-44 (mild fear), backtester sizes at 1.1× but live sizes at 1.2×. When risk_appetite is 65-74 (mild greed), backtester sizes at 0.95× but live sizes at 1.0×. These are ~5-10% sizing differences that can compound over a multi-year backtest.
**Fix**: Add the intermediate tiers to `AlertPositionSizer._macro_scale()`:
```python
if score < 30:  return 1.2
if score < 45:  return 1.1
if score > 75:  return 0.85
if score > 65:  return 0.95
return 1.0
```

---

### N4 — Weekly Loss Breach: Dead Code Path | Severity: LOW ❌
**Backtester**: No weekly loss breach logic.
**Live scanner**: `alert_position_sizer.py:253` — `_flat_risk_size(self, alert, account_value, weekly_loss_breach, ...)`. The `weekly_loss_breach` parameter is accepted but never used in the function body. `RiskGate.weekly_loss_breach()` (`risk_gate.py:356-358`) returns a bool that is passed in by `AlertRouter` (`alert_router.py:93`) and forwarded to `size()` (`alert_router.py:133`), which forwards it to `_flat_risk_size` — but `_flat_risk_size` ignores it.
**Impact**: The 50% size reduction that was intended for the weekly breach scenario is silently not applied in the flat sizing path. The RiskGate still logs the breach (rule 4), but no actual size reduction occurs. This means live sizes are NOT reduced after a bad week, which is the opposite of the intended more-conservative behavior.
**Fix**: Either implement the 50% reduction in `_flat_risk_size` (e.g., `if weekly_loss_breach: effective_risk_pct *= 0.5`) and add equivalent logic to the backtester, or document that weekly loss breach reduction is NOT implemented and remove the dead parameter.

---

### N5 — IC Spread Width in `_extract_spread_params`: Uses Max Wing Width | Severity: MEDIUM ❌
**Backtester**: `backtester.py:1352` — `max_loss = (2 * spread_width) - combined_credit` where `spread_width` is the single config value (e.g., 5). IC max_loss uses `2 × spread_width`.
**Live scanner `_extract_spread_params`**: `alert_position_sizer.py:413-423`
```python
if len(alert.legs) == 4:
    put_width = (put_strikes[-1] - put_strikes[0])
    call_width = (call_strikes[-1] - call_strikes[0])
    spread_width = max(put_width, call_width)  # uses ONLY one wing width
```
Then the calling code in `_flat_risk_size:302-304`:
```python
if is_ic:
    max_loss_per_spread = max((2 * spread_width - credit) * 100, 1.0)
```
So the formula is: `2 × max(put_width, call_width) - credit`. If both wings are the same width (as they should be), this is correct. But if wings differ (possible with dynamic width ICs), this uses the wrong width for the narrower wing.

**Impact**: LOW for symmetric ICs (standard case). Becomes MEDIUM if IC wings have different widths, which can happen when `_find_spreads` finds different widths for each wing. In that case, `max_loss_per_spread` is computed using `2 × max_wing` which overstates risk and under-sizes contracts.
**Fix**: `_extract_spread_params` for ICs should return `total_ic_width = put_width + call_width` and the calling code should use `(total_ic_width - credit) * 100` (not `2 × max_wing`). However, for symmetric configs (same spread_width for both wings), current behavior is correct.

---

### N6 — `_check_bullish_conditions` / `_check_bearish_conditions` Still Execute in Combo Mode | Severity: LOW ❌
**Backtester**: `backtester.py:715-729` — in combo mode, `_want_puts` and `_want_calls` are set exclusively from `_regime_today`. The MA-based direction filter in `_find_backtest_opportunity` is explicitly bypassed: `if self._regime_mode != 'combo' and price < trend_ma: return None`.
**Live scanner**: `spread_strategy.py:107-121` — `evaluate_spread_opportunity()` always calls `_check_bullish_conditions(technical_signals, iv_data)` and `_check_bearish_conditions(technical_signals, iv_data)` regardless of regime_mode. These checks include `technical_signals.get('trend', '') in ['bullish', 'neutral']` from TechnicalAnalyzer, which uses its own fast/slow MA logic — separate from ComboRegimeDetector.
**Impact**: In combo mode, a BULL regime from ComboRegimeDetector may still be blocked by `_check_bullish_conditions` if `TechnicalAnalyzer` returns `trend='bearish'`. This creates a second directional gate not present in the backtester. Conversely, `_check_bearish_conditions` gates bear calls using `trend in ['bearish', 'neutral']`. In combo mode, bear calls should only be allowed when `combo_regime == 'BEAR'` — but the `_check_bearish_conditions` will allow them whenever TechnicalAnalyzer says 'neutral'. This can produce bear call entries that the backtester's combo regime would block.
**Fix**: In `evaluate_spread_opportunity`, when `regime_mode='combo'`, the direction decision should be made solely from `technical_signals.get('combo_regime')`, bypassing `_check_bullish_conditions` / `_check_bearish_conditions`. One approach: early-return if `combo_regime == 'BEAR'` before calling `_check_bullish_conditions`.

---

## Remaining Risk Summary

| # | Item | Severity | Status | Impact |
|---|------|----------|--------|--------|
| D2 | Min credit gate slippage timing | MEDIUM | PARTIALLY FIXED | Methodology differs (flat vs bar-specific) |
| D4 | Macro event gate disconnected | LOW | STILL OPEN | Both paths ignore it — consistent but misleading |
| D5 | Stop-loss width backstop (PositionMonitor) | HIGH | STILL OPEN | Live exits earlier than backtested |
| D6 | DTE management exit (manage_dte=21) | CRITICAL | STILL OPEN | Fundamental P&L profile difference |
| D7 | IC construction slippage | LOW | PARTIALLY FIXED | Flat vs bar-specific magnitude difference |
| D12 | Options data source | HIGH | STILL OPEN | Live has delta; backtester has bar slippage |
| D16 | Commission model | LOW | STILL OPEN | Paper P&L slightly higher than backtest P&L |
| D20 | Strike selection (OTM% vs delta range) | HIGH | STILL OPEN | Different strikes selected; live closer to ATM |
| D22 | Weekly loss breach sizing | LOW | STILL OPEN | Dead code: parameter accepted but not used |
| D23 | COMPASS macro scaling | MEDIUM | PARTIALLY FIXED | Missing 1.1× and 0.95× intermediate tiers |
| D26 | Lookback for regime data | LOW | STILL OPEN | Risk is negligible; 2y window is sufficient |
| N1 | IC min combined credit denominator | HIGH | NEW | Live enters 2× more ICs than backtester |
| N2 | IC synthetic credit cap (live only) | MEDIUM | NEW | Affects stop/profit levels vs backtester |
| N3 | COMPASS intermediate tiers missing | MEDIUM | NEW | 5-10% sizing difference in fear/greed zones |
| N4 | Weekly loss breach dead code | LOW | NEW | 50% reduction promised but never applied |
| N5 | IC spread width extraction for asymmetric wings | LOW | NEW | Overstates risk for non-symmetric ICs |
| N6 | `_check_bullish/bearish_conditions` runs in combo mode | MEDIUM | NEW | Second directional gate not in backtester |

---

## Priority Recommended Fixes

### Immediate (CRITICAL / HIGH — affects capital at risk)

1. **Fix D6 (manage_dte=21)** — `execution/position_monitor.py`: Add `manage_dte` exit logic to backtester OR accept that live P&L will structurally differ from backtest P&L. The 21 DTE closure changes the entire P&L distribution: full-credit at expiration vs ~60-75% at 21 DTE.

2. **Fix N1 (IC min combined credit denominator)** — `strategy/spread_strategy.py:398`:
   Change `combined_credit / spread_width` → `combined_credit / (2 * spread_width)`.
   Live is entering 2× more ICs than the backtester intends.

3. **Fix D5 (stop-loss 90% width cap)** — `execution/position_monitor.py`:
   Remove the `spread_width × 0.90` backstop or add it to the backtester. Currently this causes early exits in live that never happen in backtested scenarios.

4. **Fix D20 (strike selection)** — `strategy/spread_strategy.py`:
   Either change live to OTM% method (matching backtester champion configs) or update backtester to use delta range. The current mismatch means live enters different strikes than backtested, likely with higher deltas and higher credits but lower probability.

### High Priority

5. **Fix N6 (`_check_bullish/bearish` in combo mode)** — `strategy/spread_strategy.py:107-121`:
   Bypass direction filters when `regime_mode='combo'`; use `combo_regime` exclusively.

6. **Fix N2 (IC synthetic credit cap)** — `strategy/spread_strategy.py:386-389`:
   Remove the `spread_width * 0.50` cap. It has no backtester equivalent and distorts IC entry conditions.

7. **Fix N3 (COMPASS intermediate tiers)** — `alerts/alert_position_sizer.py:_macro_scale()`:
   Add 1.1× (score 30-44) and 0.95× (score 65-74) tiers to match backtester exactly.

8. **Fix D12 (strike selection / delta discrepancy)**: Document that live delta-range selection (`min_delta=0.20, max_delta=0.30`) produces ~20-30 delta strikes vs backtester's OTM% producing ~10-15 delta strikes. This is the single largest unaddressed behavioral gap for entry positioning.

### Medium Priority

9. **Fix N4 (weekly loss breach dead code)** — `alerts/alert_position_sizer.py:_flat_risk_size()`:
   Either implement 50% reduction or remove the dead parameter.

10. **Fix D23 (COMPASS macro thresholds alignment)**: Already documented in N3.

11. **Document D6** in trading log: every position opened in live trading will close ~14 days earlier than the backtested equivalent, collecting ~65-75% of maximum profit on winning trades.

---

## Files Audited

| File | Role | Changes Since v1 |
|------|------|-----------------|
| `backtest/backtester.py` | Source of truth | IC max_loss fix, IC contract sizing fix (`spread_width * 2` passed to `get_contract_size`), COMPASS scaling applied in flat mode |
| `main.py` | Live entry point | Regime fallback changed from NEUTRAL to BULL; `current_vix` added to account_state; peak_equity persisted to DB |
| `strategy/spread_strategy.py` | Opportunity finder | `regime_mode` default changed to `'combo'`; slippage applied; single-expiration filter; spread_width no longer dynamic; IC neutral-regime gate |
| `alerts/alert_generator.py` | Alert formatting | Score gate unchanged (28 for file output only) |
| `alerts/alert_router.py` | Pipeline | Score ≥ 60 gate removed; dedup key upgraded to (ticker, exp, strike_type); dedup persisted to SQLite |
| `alerts/risk_gate.py` | Hard risk rules | Drawdown CB reference fixed (flat→starting_capital, compound→peak_equity); VIX gate added (rule 7.5); per-ticker limit added (rule 5.5) |
| `alerts/alert_position_sizer.py` | Position sizing | IC max_loss fixed to `2×width - credit`; COMPASS scaling added to flat path; legacy path cleaned up |
| `ml/combo_regime_detector.py` | Regime detection | Unchanged; v2 3-signal logic confirmed |
| `ml/position_sizer.py` | IV-scaled sizer | Unchanged |
| `shared/constants.py` | Hardcoded limits | Unchanged |
