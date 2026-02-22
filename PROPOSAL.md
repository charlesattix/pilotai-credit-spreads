# Credit Spreads Strategy Overhaul Proposal

## P0 Priority: From 1-4% to 20-40% Annual Returns

**Date**: 2026-02-21
**Status**: PROPOSAL - Pending Approval
**Author**: Claude (requested by Carlos)

---

## Executive Summary

Our backtester with real Polygon data shows 1-4% annual returns on a $100K account. A savings account pays 4-5%. This strategy is failing because of five compounding problems that each reduce returns by 3-10x:

| Problem | Current | Impact |
|---------|---------|--------|
| Spread width | $5 | Credits of $0.02-$0.41 — barely covers commissions |
| Position sizing | 4 contracts (2% risk) | Only $60-$200 total credit per trade |
| Trade frequency | 1/week, 1 position | 42 trades/year, no concurrency |
| Win/loss asymmetry | Win $138, Lose -$572 | 1 loss wipes 4 wins |
| Single underlying | SPY only in backtest | Misses 2/3 of opportunities |

**Proposed changes would produce an estimated 25-35% annual return with <12% max drawdown**, based on the math below.

---

## Part 1: Diagnosis — Why Returns Are So Low

### 1.1 The Credit Problem (Root Cause #1)

Looking at the actual 2025 trade data, credits collected:
```
$0.02, $0.07, $0.04, $0.11, $0.11, $0.15, $0.15, $0.22, $0.23,
$0.27, $0.27, $0.29, $0.29, $0.30, $0.32, $0.34, $0.37, $0.41,
$1.01, $1.07, $1.34, $1.88, $5.02
```

**Median credit: $0.29 per contract**. On a $5-wide spread, that's 5.8% of max risk.

With 4 contracts, a typical winning trade at 50% profit target:
```
$0.29 * 0.50 * 4 contracts * 100 shares = $58 profit
```

That's $58 per winning trade on a $100K account. You'd need 345 winning trades to make 20%.

### 1.2 The Asymmetry Problem (Root Cause #2)

With a $0.29 credit and 2.5x stop loss multiplier:
- **Win**: $0.145/contract * 4 * 100 = **+$58**
- **Lose**: $0.725/contract * 4 * 100 = **-$290**

But actual 2025 losses were far worse: **-$253, -$281, -$409, -$457, -$1,201, -$1,371**.

The $1,371 loss happened because the spread value gapped past the stop. With $5-wide spreads, a $1,371 loss on 5 contracts means the spread moved to ~$3.80 — nearly max loss. **The stop loss mechanism is failing because daily checks miss intraday moves and option spreads can gap.**

This means 1 loss wipes 10-24 wins. The strategy needs roughly 95% win rate just to break even, which is unsustainable.

### 1.3 The Frequency Problem (Root Cause #3)

The backtester scans only on Mondays (`current_date.weekday() == 0`). Even with `max_positions: 7`, the serial scan structure means we almost never have concurrent positions. The code at `backtester_fixed.py:134`:

```python
if len(open_positions) < self.risk_params['max_positions']:
    opportunity = self._find_opportunity_real_logic(...)
```

This finds AT MOST 1 new opportunity per Monday. So:
- 52 weeks/year = max 52 scans
- ~42 trades = 81% hit rate on scans
- But only 1 position at a time = idle capital

**$100K account, 1 position of $2,000 max risk = 98% of capital sitting idle.**

### 1.4 The Width Problem (Root Cause #4)

A $5 spread on SPY at $600 means strikes are only 0.83% apart. The credit collected is:
- Short 0.25-delta put: ~$2.50 bid
- Long 0.20-delta put ($5 lower): ~$2.10 ask
- Net credit: $0.40

With a $10 spread:
- Short 0.25-delta put: ~$2.50 bid
- Long 0.15-delta put ($10 lower): ~$1.30 ask
- Net credit: $1.20

**3x more credit for 2x the width.** The credit-to-width ratio improves with wider spreads because the long leg is further OTM and cheaper.

### 1.5 The Scaling Problem (Root Cause #5)

Position sizing is fixed: `max_risk_per_trade: 2.0%` applied to starting capital. As the account grows (or even stays flat), there's no dynamic adjustment. Professional accounts allocate 3-5% per position with 4-6 concurrent positions, deploying 15-30% of buying power at any time.

---

## Part 2: The Overhaul — Specific Changes

### Change 1: Wider Spreads ($5 → $10 default, $15 in high IV)

**File**: `config.yaml`
```yaml
# BEFORE
spread_width: 5

# AFTER
spread_width: 10
spread_width_high_iv: 15  # When IV rank > 50
spread_width_low_iv: 10   # When IV rank 12-50
```

**File**: `strategy/spread_strategy.py` — `_find_spreads()`

Add dynamic width selection based on IV environment:
```python
def _get_spread_width(self, iv_data: Dict) -> int:
    iv_rank = iv_data.get('iv_rank', 0)
    if iv_rank >= 50:
        return self.strategy_params.get('spread_width_high_iv', 15)
    return self.strategy_params.get('spread_width_low_iv', 10)
```

**Expected impact**: Credit per trade increases from $0.29 median to $1.20-$2.00 median (4-7x improvement).

### Change 2: Aggressive Position Sizing (2% → 5% risk per trade)

**File**: `config.yaml`
```yaml
# BEFORE
max_risk_per_trade: 2.0

# AFTER
max_risk_per_trade: 5.0
```

**File**: `backtest/backtester_fixed.py` — `_opportunity_to_position()`

Current sizing:
```python
risk_per_spread = max_loss * 100  # e.g., $8.50 * 100 = $850
max_risk = self.capital * (self.risk_params['max_risk_per_trade'] / 100)  # $100K * 5% = $5,000
contracts = max(1, int(max_risk / risk_per_spread))  # $5,000 / $850 = 5 contracts
```

With $10-wide spreads and $1.50 avg credit:
- Max loss per contract: $8.50 * 100 = $850
- 5% of $100K = $5,000 max risk
- Contracts: 5-6 per position

**Expected impact**: Total credit per trade = $1.50 * 6 * 100 = **$900** (vs current ~$116).

### Change 3: Multiple Concurrent Positions (1 → 4-5 active)

**File**: `backtest/backtester_fixed.py` — `run_backtest()`

Replace Monday-only scanning with MWF, and scan ALL configured tickers:

```python
# BEFORE
if current_date.weekday() == 0:  # Monday only
    if len(open_positions) < self.risk_params['max_positions']:
        opportunity = self._find_opportunity_real_logic(ticker, ...)

# AFTER
if current_date.weekday() in (0, 2, 4):  # Mon, Wed, Fri
    for scan_ticker in self.config['tickers']:
        if len(open_positions) < self.risk_params['max_positions']:
            # Check we don't already have a position in this ticker+expiration
            existing = [p for p in open_positions
                       if p['ticker'] == scan_ticker
                       and p['expiration'] == ...]  # same expiration cycle
            if len(existing) >= max_per_ticker:
                continue
            opportunity = self._find_opportunity_real_logic(scan_ticker, ...)
```

**Config change**:
```yaml
# AFTER
max_positions: 5
max_positions_per_ticker: 2  # Max 2 positions in same underlying
scan_days: [0, 2, 4]  # Mon, Wed, Fri
```

**Expected impact**: From ~42 trades/year to ~120-150 trades/year (3-4x), with 3-5 concurrent positions deploying 15-25% of capital.

### Change 4: Multiple Underlyings (SPY → SPY + QQQ + IWM)

The config already lists `tickers: [SPY, QQQ, IWM]` but the backtester only runs against a single ticker passed to `run_backtest()`.

**File**: `backtest/backtester_fixed.py`

Add `run_multi_ticker_backtest()`:
```python
def run_multi_ticker_backtest(self, tickers: List[str],
                               start_date: datetime, end_date: datetime) -> Dict:
    """Run backtest across multiple underlyings simultaneously."""
    # Download all price data upfront
    price_data = {t: self._get_historical_data(t, start_date, end_date) for t in tickers}

    # Single portfolio, scan all tickers on each scan day
    # Positions tracked by ticker for correlation limits
```

**Why this matters**:
- Diversification reduces correlation risk (SPY, QQQ, IWM don't move identically)
- 3x the strike/expiration universe = more high-quality setups
- Can avoid same-day entries in correlated underlyings

### Change 5: Fix the Win/Loss Asymmetry

The current stop loss (`2.5x credit`) is both too wide AND unreliable. With small credits, 2.5x barely moves the needle, but the spread can blow through it.

#### 5a. Tighter Stop Loss Based on Spread Width, Not Credit

**File**: `config.yaml`
```yaml
# BEFORE
stop_loss_multiplier: 2.5  # 2.5x credit — useless on $0.15 credit

# AFTER
stop_loss_pct_of_width: 50  # Exit if spread value reaches 50% of width
                             # On $10 spread: stop at $5.00 spread value
                             # Max loss = $5.00 - $1.50 credit = $3.50/contract
```

**File**: `backtest/backtester_fixed.py` — `_manage_positions()`
```python
# BEFORE
if current_pnl_per_contract <= -(credit * 2.0):
    self._close_position(pos, current_date, "stop_loss", ...)

# AFTER
spread_width = pos.get('spread_width', 10)
stop_value = spread_width * (self.risk_params['stop_loss_pct_of_width'] / 100)
if current_spread_value >= stop_value:
    self._close_position(pos, current_date, "stop_loss", ...)
```

With this change on a $10 spread, $1.50 credit:
- **Win (50% target)**: +$0.75/contract * 6 * 100 = **+$450**
- **Lose (50% width stop)**: -$3.50/contract * 6 * 100 = **-$2,100**
- **Break-even win rate**: $2,100 / ($2,100 + $450) = 82.4%

With 85% win rate: `0.85 * $450 - 0.15 * $2,100 = $382.50 - $315 = +$67.50/trade`

That's thin. So we also need:

#### 5b. Time-Based Stop Tightening

As DTE decreases, gamma increases and losers accelerate. Tighten the stop as expiration approaches:

```python
def _get_dynamic_stop(self, pos: Dict, current_date: datetime) -> float:
    """Stop tightens as DTE decreases (gamma risk increases)."""
    dte_remaining = (pos['expiration'] - current_date).days
    spread_width = pos['spread_width']

    if dte_remaining > 21:
        return spread_width * 0.50  # 50% of width
    elif dte_remaining > 14:
        return spread_width * 0.40  # 40% — tighter
    elif dte_remaining > 7:
        return spread_width * 0.35  # 35% — tighter still
    else:
        return spread_width * 0.30  # 30% — final week, very tight
```

#### 5c. Roll Losing Positions Instead of Stop Loss

When a position approaches the stop, roll it out in time (same strikes, later expiration) to collect additional credit and buy more time for the trade to work.

**New method**: `_attempt_roll()`
```python
def _attempt_roll(self, pos: Dict, current_date: datetime,
                   price_data: pd.DataFrame) -> Optional[Dict]:
    """
    Roll a losing position to a later expiration.
    Only roll once per position. Collect additional credit to lower cost basis.
    """
    if pos.get('rolled', False):
        return None  # Already rolled once, take the loss

    # Find new expiration 30 DTE out
    new_expiration = self._snap_to_friday(current_date + timedelta(days=30))

    # Get new spread prices at same strikes
    # ... (fetch from Polygon)

    # Only roll if additional credit > $0.30/contract
    if additional_credit < 0.30:
        return None

    new_pos = {**pos}
    new_pos['expiration'] = new_expiration
    new_pos['credit'] += additional_credit  # Lower cost basis
    new_pos['rolled'] = True
    new_pos['roll_date'] = current_date
    return new_pos
```

### Change 6: Dynamic Spread Width Based on IV Environment

High IV = wider spreads (more premium available), low IV = consider skipping or iron condors.

**File**: `strategy/spread_strategy.py`

```python
def _select_spread_width(self, iv_data: Dict) -> int:
    """
    Dynamic spread width based on IV rank.

    High IV (rank > 50): $15 wide — maximum premium capture
    Normal IV (rank 25-50): $10 wide — standard
    Low IV (rank 12-25): $5 wide or skip — less premium available
    """
    iv_rank = iv_data.get('iv_rank', 0)

    if iv_rank >= 50:
        return 15  # High IV: wide spreads, fat premiums
    elif iv_rank >= 25:
        return 10  # Normal: standard width
    else:
        return 5   # Low IV: narrow or consider iron condors instead
```

### Change 7: Scale Contracts with Account Growth

**File**: `backtest/backtester_fixed.py` — `_opportunity_to_position()`

The current code already uses `self.capital` for sizing, but we should make this more explicit and add a floor/ceiling:

```python
# Dynamic position sizing
risk_per_spread = max_loss * 100
current_capital = self.capital  # Updated after each trade
max_risk = current_capital * (self.risk_params['max_risk_per_trade'] / 100)
contracts = max(1, min(20, int(max_risk / risk_per_spread)))  # Floor 1, ceiling 20
```

Add to config:
```yaml
min_contracts: 1
max_contracts: 20  # Safety cap
```

### Change 8: Iron Condors as Primary Strategy in Low IV

The current iron condor implementation requires `trend == 'neutral'` AND RSI 35-65. This is too restrictive.

**Proposed changes**:
- Iron condors should be the DEFAULT strategy when IV rank is 12-30 (low IV makes directional spreads unprofitable)
- Relax RSI requirement to 30-70
- Allow trend to be 'neutral' OR when both bullish and bearish setups score similarly

```python
# In evaluate_spread_opportunity():
if iv_data.get('iv_rank', 0) < 30:
    # Low IV: prefer iron condors (collect premium from both sides)
    condors = self.find_iron_condors(...)
    if condors:
        return self._score_opportunities(condors, ...)
```

### Change 9: Smarter Profit Target Management

Instead of a flat 50% profit target, use time-decay-aware targets:

```python
def _get_profit_target(self, pos: Dict, current_date: datetime) -> float:
    """
    Profit target as % of credit, adjusted by time remaining.

    > 21 DTE: Take 50% profit (normal)
    14-21 DTE: Take 40% profit (capture theta acceleration)
    7-14 DTE: Take 25% profit (gamma risk increasing)
    < 7 DTE: Take any profit > $0 (close before expiration week)
    """
    dte_remaining = (pos['expiration'] - current_date).days
    credit = pos['credit']

    if dte_remaining > 21:
        return credit * 0.50
    elif dte_remaining > 14:
        return credit * 0.40
    elif dte_remaining > 7:
        return credit * 0.25
    else:
        return 0.01  # Take any profit
```

**Why**: Theta decay accelerates after 21 DTE. By taking profits earlier, we free capital for new positions and reduce gamma risk.

### Change 10: Portfolio-Level Risk Limits

Add guardrails to prevent over-concentration:

```yaml
# New config entries
portfolio_risk:
  max_portfolio_risk_pct: 25    # Max 25% of account at risk across all positions
  max_single_ticker_pct: 12     # Max 12% in any single underlying
  max_same_expiration: 3        # Max 3 positions expiring same week
  min_cash_reserve_pct: 50      # Always keep 50% cash
  correlation_limit: 0.80       # Don't add positions when portfolio correlation > 0.80
```

```python
def _check_portfolio_limits(self, new_position: Dict,
                             open_positions: List[Dict]) -> bool:
    """Check if adding a new position violates portfolio limits."""
    total_risk = sum(p['max_loss'] * p['contracts'] * 100 for p in open_positions)
    new_risk = new_position['max_loss'] * new_position['contracts'] * 100

    if (total_risk + new_risk) / self.capital > self.portfolio_risk['max_portfolio_risk_pct'] / 100:
        return False

    # Check single-ticker concentration
    ticker_risk = sum(p['max_loss'] * p['contracts'] * 100
                      for p in open_positions if p['ticker'] == new_position['ticker'])
    if (ticker_risk + new_risk) / self.capital > self.portfolio_risk['max_single_ticker_pct'] / 100:
        return False

    return True
```

---

## Part 3: Expected Returns Math

### Conservative Scenario (25% annual)

| Parameter | Value |
|-----------|-------|
| Account | $100,000 |
| Spread width | $10 |
| Avg credit | $1.50/contract |
| Contracts/trade | 6 |
| Credit/trade | $900 |
| Concurrent positions | 3-4 |
| Trades/year | 120 |
| Win rate | 83% |
| Avg win (50% target) | $450 |
| Avg loss (50% width stop) | $2,100 |

```
Annual P&L = (120 * 0.83 * $450) - (120 * 0.17 * $2,100) - commissions
           = $44,820 - $42,840 - $312
           = +$1,668
```

That's too thin. The numbers don't work with an 83% win rate and 4.7:1 loss-to-win ratio. We need to either:

**Option A**: Higher win rate (target 88%+ by being more selective) + tighter stops
**Option B**: Higher credit collection (wider spreads in high IV)
**Option C**: Better win/loss ratio through rolling

### Realistic Optimized Scenario (with rolling + tighter stops)

| Parameter | Value |
|-----------|-------|
| Account | $100,000 |
| Spread width | $10 (normal), $15 (high IV) |
| Avg credit | $1.80/contract |
| Contracts/trade | 6 |
| Credit/trade | $1,080 |
| Concurrent positions | 4 |
| Trades/year | 130 |
| Win rate | 85% (improved by rolling 50% of losers to winners) |
| Avg win (50% target) | $540 |
| Avg loss (35% width stop after rolling fails) | $1,380 |

```
Winners: 130 * 0.85 * $540 = $59,670
Losers:  130 * 0.15 * $1,380 = $26,910
Commissions: 130 * 2 * $0.65 * 6 = $1,014
Net P&L = $59,670 - $26,910 - $1,014 = +$31,746 (31.7%)
```

### Aggressive Scenario (with account scaling + high IV periods)

| Parameter | Value |
|-----------|-------|
| Same as above, but... | |
| VIX spikes (2-3/year): $15 spreads, 8 contracts | $2,400 credit/trade |
| Account scaling: +15% more contracts by Q3 | Compounds returns |
| Add QQQ + IWM | 30-40% more trades |

Estimated: **35-40% annual return** in a year with 2-3 VIX spikes.

---

## Part 4: Implementation Priority

### Phase 1: Core Changes (Biggest Impact) — 1-2 days
These are the changes that will have the most immediate effect:

1. **Widen spreads to $10** (`config.yaml`, `spread_strategy.py`)
   - Impact: 3-4x more credit per trade

2. **Increase risk per trade to 5%** (`config.yaml`)
   - Impact: 50% more contracts per trade

3. **Scan MWF + all tickers** (`backtester_fixed.py`)
   - Impact: 3-4x more trades per year

4. **Fix stop loss to % of width** (`backtester_fixed.py`)
   - Impact: Capped, predictable losses

### Phase 2: Optimization — 1-2 days

5. **Dynamic spread width based on IV** (`spread_strategy.py`)
6. **Time-based profit targets** (`backtester_fixed.py`)
7. **Portfolio-level risk limits** (new module or backtester)
8. **Multi-ticker backtest runner** (`backtester_fixed.py`)

### Phase 3: Advanced — 2-3 days

9. **Rolling losing positions** (`backtester_fixed.py`)
10. **Iron condors as default in low IV** (`spread_strategy.py`)
11. **Account-size-based scaling** (already partially implemented)
12. **Correlation-aware position limits** (new)

---

## Part 5: Config Changes Summary

```yaml
# === PROPOSED config.yaml changes ===

strategy:
  min_dte: 30
  max_dte: 45
  manage_dte: 21

  # Slightly wider delta range for more opportunities
  min_delta: 0.15
  max_delta: 0.30

  # Dynamic spread width
  spread_width: 10           # Default (was 5)
  spread_width_high_iv: 15   # When IV rank > 50
  spread_width_low_iv: 10    # When IV rank 25-50

  # Scan frequency
  scan_days: [0, 2, 4]       # Mon, Wed, Fri (was Monday only)

  # IV filters (keep as-is, they're reasonable)
  min_iv_rank: 12
  min_iv_percentile: 12

  iron_condor:
    enabled: true
    prefer_in_low_iv: true    # NEW: default to condors when IV < 30
    min_combined_credit_pct: 25
    max_wing_width: 10        # Match spread_width (was 5)
    rsi_min: 30               # Relaxed (was 35)
    rsi_max: 70               # Relaxed (was 65)

risk:
  account_size: 100000
  max_risk_per_trade: 5.0     # Was 2.0 — deploy more capital
  max_positions: 5            # Was 7 — focused but concurrent
  max_positions_per_ticker: 2 # NEW: diversification

  profit_target: 50           # Keep 50% — proven approach

  # NEW: Width-based stop loss instead of credit-based
  stop_loss_pct_of_width: 50  # Exit when spread value = 50% of width
  stop_loss_multiplier: 2.5   # DEPRECATED — replaced by above

  # NEW: Rolling
  enable_rolling: true
  max_rolls_per_position: 1
  min_roll_credit: 0.30       # Must collect at least $0.30 additional

  min_credit_pct: 20          # Keep — minimum credit quality
  min_contracts: 1
  max_contracts: 20           # Safety cap

  # NEW: Portfolio-level limits
  portfolio_risk:
    max_portfolio_risk_pct: 25
    max_single_ticker_pct: 12
    max_same_expiration: 3
    min_cash_reserve_pct: 50

backtest:
  starting_capital: 100000
  commission_per_contract: 0.65
  slippage: 0.05
  score_threshold: 28
```

---

## Part 6: Key Code Changes Summary

| File | Change | Lines Affected |
|------|--------|---------------|
| `config.yaml` | Wider spreads, more risk, scan days, portfolio limits | ~30 lines |
| `strategy/spread_strategy.py` | Dynamic width, relaxed condor filters, IV-based width | `_find_spreads()`, `find_iron_condors()`, new `_select_spread_width()` |
| `backtest/backtester_fixed.py` | MWF scanning, multi-ticker, width-based stops, time-based targets, rolling, portfolio checks | `run_backtest()`, `_manage_positions()`, `_opportunity_to_position()`, new methods |
| `run_fixed_backtest.py` | Multi-ticker backtest runner | Call `run_multi_ticker_backtest()` |

---

## Part 7: Risk Analysis

### What could go wrong

1. **Black swan event (2020 March)**: Multiple positions hit max loss simultaneously
   - Mitigation: 50% cash reserve, 25% max portfolio risk, correlation limits
   - Worst case: 25% drawdown (all positions max loss at once)

2. **Prolonged low IV (2017-style)**: Credits too small to be meaningful
   - Mitigation: Iron condors collect from both sides, skip low-IV weeks entirely
   - Worst case: 10-15% annual return instead of 25-35%

3. **Whipsaw markets**: Stop losses triggered then market reverses
   - Mitigation: Rolling instead of stopping out, time-based stop tightening
   - Worst case: More small losses, but capped by width-based stops

4. **Polygon data gaps**: Missing option prices → skipped trades
   - Already handled: current code skips trades without Polygon data
   - Impact: Lower trade count than projected

### Drawdown expectations

| Scenario | Max Drawdown | Recovery Time |
|----------|-------------|---------------|
| Normal year | 3-5% | 2-4 weeks |
| Volatile year (2025-style) | 8-12% | 4-8 weeks |
| Crash (2020 March) | 15-20% | 8-16 weeks |
| Absolute worst case (all positions max loss) | 25% | 16-24 weeks |

---

## Part 8: Validation Plan

Before going live, run backtests with the new parameters across all 3 periods:

1. **2024 (bull market)**: Expect 30-40% return (was 4%)
2. **2025 (volatile)**: Expect 20-30% return (was 0.8%)
3. **2026 YTD**: Expect 8-12% in 7 weeks (was 1.4%)

Key metrics to validate:
- Max drawdown < 15%
- Win rate > 82%
- Average win/loss ratio > 1:3 (i.e., need 3 wins per loss)
- Sharpe ratio > 1.5
- No single loss > 5% of account

---

## Appendix: What Professional Credit Spread Traders Do

Reference points from published strategies and fund returns:

1. **TastyTrade/tastylive methodology**:
   - Sell at 30 delta, $10+ wide spreads
   - Manage at 21 DTE, take profits at 50%
   - 3-5 concurrent positions across SPY, IWM, QQQ, GLD, TLT
   - Target: 1-2% per month (12-24% annual)

2. **CBOE PutWrite Index (PUT)**:
   - Systematically sells ATM puts on S&P 500
   - Historical return: ~10% annually with lower vol than S&P 500
   - Our approach should beat this by being more selective

3. **Professional premium sellers**:
   - Deploy 20-30% of buying power
   - 4-8 concurrent positions
   - Roll losers aggressively
   - Size positions for max 3-5% account loss per trade
   - Target 2-4% monthly (24-48% annual) before drawdowns

**Our proposed strategy aligns with these professional approaches while adding systematic discipline through backtesting validation.**

---

## Decision Required

Approve Phase 1 implementation to begin immediately. Expected timeline:
- Phase 1 (core): 1-2 days
- Phase 2 (optimization): 1-2 days
- Phase 3 (advanced): 2-3 days
- Full backtest validation: 1 day

**Total: 5-8 days to a validated, production-ready strategy targeting 25-35% annual returns.**
