# PROPOSAL: Fix DTE Bug in Backtester

## Root Cause

`strategy/spread_strategy.py` → `_filter_by_dte()` (line ~118) uses `datetime.now(timezone.utc)` to calculate Days To Expiration. During backtesting, this means historical option expirations (e.g., Feb 2024) are compared against TODAY (Feb 2026), resulting in -741 DTE instead of the correct 35 DTE. All expirations are rejected → 0 trades.

## Proposed Fix

**Add an optional `as_of_date` parameter** to `evaluate_spread_opportunity()` and `_filter_by_dte()`.

### Changes Required:

**1. `strategy/spread_strategy.py`**

```python
# _filter_by_dte() - Add as_of_date parameter
def _filter_by_dte(self, option_chain, as_of_date=None):
    today = as_of_date or datetime.now(timezone.utc)
    # ... rest stays the same

# evaluate_spread_opportunity() - Add as_of_date parameter  
def evaluate_spread_opportunity(self, ticker, option_chain, technical_signals, 
                                 iv_data, current_price, as_of_date=None):
    valid_expirations = self._filter_by_dte(option_chain, as_of_date=as_of_date)
    # ... rest stays the same

# find_iron_condors() - Also uses _filter_by_dte, needs as_of_date too
def find_iron_condors(self, ticker, option_chain, current_price, 
                       technical_signals, iv_data, as_of_date=None):
    # Pass as_of_date to _filter_by_dte
```

**2. `backtest/backtester_fixed.py`**

```python
# In _find_opportunity_real_logic(), pass the backtest date:
opportunities = self.strategy.evaluate_spread_opportunity(
    ticker=ticker,
    option_chain=options_chain,
    technical_signals=technical_signals,
    iv_data=iv_data,
    current_price=current_price,
    as_of_date=date  # ← Pass the simulated backtest date
)
```

### Why This Approach:
- **Backwards compatible** — `as_of_date=None` defaults to `datetime.now()`, so live scanning is unaffected
- **Minimal changes** — Only 3 method signatures + 3 lines of logic change
- **No side effects** — Doesn't touch any other part of the pipeline
- **Easy to test** — Run backtest, should now find opportunities

### Expected Outcome:
- Backtester will correctly calculate DTE from the simulated date
- Expirations will pass the 21-45 DTE filter
- Bull puts, bear calls, and iron condors will be evaluated
- Scoring pipeline will run (ML + rules)
- **Trades will appear in backtest results**

### Tests:
- All existing 347 tests should still pass (no behavior change for live scanning)
- New test: backtest with as_of_date should find opportunities
- Verify DTE calculation with known dates

## Risk Assessment
- **Risk: LOW** — Change is isolated to adding an optional parameter
- **Impact: HIGH** — Unblocks the entire P0 critical priority
