# Backtester Capability Audit
Generated: 2026-02-26 | Phase 0.2

## Configurable Parameters

| Parameter | Source | Default | Description |
|-----------|--------|---------|-------------|
| `starting_capital` | backtest config | 100,000 | Initial account size |
| `commission_per_contract` | backtest config | 0.65 | Commission per contract |
| `slippage` | backtest config | 0.05 | Entry slippage fallback ($) |
| `exit_slippage` | backtest config | 0.10 | Extra exit friction on stop-loss |
| `spread_width` | strategy params | 5 | Spread width in dollars |
| `min_credit_pct` | strategy params | 10 | Min credit as % of width |
| `use_delta_selection` | strategy params | false | Delta-based vs OTM% strike selection |
| `target_delta` | strategy params | 0.12 | Target short-strike delta |
| `target_dte` | strategy params | 35 | **NEW** Days to expiration target (configurable as of 2026-02-26) |
| `min_dte` | strategy params | 25 | **NEW** Minimum DTE (configurable as of 2026-02-26) |
| `iron_condor.enabled` | strategy params | false | Enable iron condor mode |
| `max_risk_per_trade` | risk params | 2.0 | Max risk % of account |
| `max_contracts` | risk params | 5 | Hard cap on contracts |
| `stop_loss_multiplier` | risk params | 2.5 | Stop at credit × N |
| `profit_target` | risk params | 50 | **NOW WIRED** Close at N% of credit (was hardcoded 50%) |
| `otm_pct` | direct arg | 0.05 | OTM% for non-delta mode |

## Hardcoded Values (Remaining)

| Value | Location | Should Be Param |
|-------|----------|-----------------|
| ATR lookback = 20 | backtester.py ~line 380 | `strategy.atr_lookback` |
| RV clip [0.10, 1.00] | backtester.py ~line 388 | `strategy.rv_floor/ceiling` |
| RV fallback = 0.25 | backtester.py ~line 105 | `strategy.default_rv` |
| MA period = 20 | backtester.py ~line 419 | `strategy.ma_period` |
| Drawdown CB = -20% | backtester.py ~line 206 | `backtest.drawdown_circuit_breaker_pct` |
| VIX lookback = 300d | backtester.py ~line 321 | `backtest.iv_rank_lookback_days` |
| IV rank window = 252 | backtester.py ~line 344 | `backtest.iv_rank_window` |
| Base risk = 2% | ml/position_sizer.py | `backtest.iv_sizing.base_risk_pct` |
| Max heat = 40% | ml/position_sizer.py | `backtest.iv_sizing.max_heat_pct` |
| Expiry threshold = $0.05 | backtester.py ~line 1051 | `backtest.expiry_value_threshold` |

## Feature Inventory

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-year in one invocation | YES | Caller loops years |
| Compounding (reinvest profits) | NO | Always uses starting_capital for sizing |
| Variable sizing as % current equity | PARTIAL | IV-scaled but anchored to starting_capital |
| Profit-taking before expiration | YES | Configurable via risk.profit_target |
| Iron condors | PARTIAL | Real-data mode only; disabled by default |
| Monthly P&L breakdown | YES (NEW) | Added 2026-02-26 — `results['monthly_pnl']` |
| Per-trade log | YES | Full dict with entry/exit/reason/pnl |
| Max drawdown tracking | YES | `results['max_drawdown']` |
| Drawdown duration | NO | Needs _calculate_drawdown_duration() |
| Win/loss streaks | YES (NEW) | Added 2026-02-26 — `results['max_win/loss_streak']` |
| Structured return dict | YES | ~22 keys returned |
| Multiple tickers | NO | One ticker per call |
| Configurable DTE ranges | YES (NEW) | target_dte / min_dte in strategy params |
| Direction filtering | NO | Always tries both bull_put and bear_call |
| Intraday scan times | YES | 14 scan times in real-data mode |
| Heuristic mode | YES | Pass historical_data=None |
| Slippage modeling | YES | Bar H-L / 2 per leg |
| Full SQLite caching | YES | 0 API calls on 2nd run |

## Return Value Structure (post-2026-02-26)

```python
{
    'total_trades': int,
    'winning_trades': int,
    'losing_trades': int,
    'win_rate': float,           # percentage
    'total_pnl': float,
    'avg_win': float,
    'avg_loss': float,
    'profit_factor': float,
    'max_drawdown': float,       # percentage (negative)
    'sharpe_ratio': float,
    'starting_capital': float,
    'ending_capital': float,
    'return_pct': float,
    'bull_put_trades': int,
    'bear_call_trades': int,
    'bull_put_win_rate': float,
    'bear_call_win_rate': float,
    'iron_condor_trades': int,
    'iron_condor_win_rate': float,
    'monthly_pnl': {             # NEW
        'YYYY-MM': {'pnl': float, 'trades': int, 'wins': int, 'win_rate': float}
    },
    'max_win_streak': int,       # NEW
    'max_loss_streak': int,      # NEW
    'trades': [list of dicts],
    'equity_curve': [list of dicts],
}
```

## Gaps for Optimization Loop (Priority Order)

1. **Compounding** — position size does not grow with equity; can't hit 200% without this (Phase 2)
2. **Direction filtering** — can't test bull_put-only or bear_call-only strategies
3. **IV-scaling tiers** — base risk%, heat cap, high-IV multiplier are hardcoded in ml/position_sizer.py
4. **Multi-ticker** — must call once per ticker; harness loops externally
5. **Drawdown circuit breaker** — hardcoded at -20%; should be param for stress testing
6. **ATR lookback** — 20-day hardcoded; could explore 10/20/30 day variations

## Estimated Performance

| Scenario | Time | API Calls |
|----------|------|-----------|
| Single year, cold cache | 2-3 min | ~10,000 |
| Single year, warm cache | 15-30 sec | 0 |
| Full 6-year suite, warm cache | ~2-3 min | 0 |
| Full validation (run + 7 jitter) | ~20-25 min warm | 0 |
| Phase 1 grid (500 combos × 6yr) | ~25 hrs warm | 0 |

**Key insight**: After initial data load (~3 hrs for 2020-2025), all subsequent runs are cache-only. The optimization loop is effectively free to run.

## Recommended Changes for Phase 0.3 ✅ COMPLETED

- [x] `target_dte` and `min_dte` configurable (done 2026-02-26)
- [x] `profit_target_pct` configurable (done 2026-02-26)
- [x] Monthly P&L breakdown added (done 2026-02-26)
- [x] Win/loss streak tracking added (done 2026-02-26)
- [ ] Compounding support (Phase 2)
- [ ] Direction filtering (Phase 1.1)
- [ ] IV-scaling tier config (Phase 2)
