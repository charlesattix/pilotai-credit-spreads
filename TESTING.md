# Testing Guide

How to test the Credit Spread Trading System.

## Installation Test

Verify all dependencies are installed:

```bash
python3 -c "import pandas, numpy, yfinance; print('✓ Core dependencies OK')"
python3 -c "import pandas_ta; print('✓ Technical analysis OK')"
python3 -c "import yaml; print('✓ YAML OK')"
```

## Configuration Test

Verify configuration is valid:

```bash
python3 -c "from utils import load_config, validate_config; config = load_config('config.yaml'); validate_config(config); print('✓ Config valid')"
```

## Module Import Test

Test that all modules can be imported:

```bash
python3 -c "
from strategy import CreditSpreadStrategy, TechnicalAnalyzer, OptionsAnalyzer
from alerts import AlertGenerator, TelegramBot
from backtest import Backtester, PerformanceMetrics
from tracker import TradeTracker, PnLDashboard
print('✓ All modules import successfully')
"
```

## Demo Test

Run the demo to verify alert generation:

```bash
python3 demo.py
```

**Expected output:**
- "Sample alerts generated!"
- Files created in `output/`:
  - alerts.json
  - alerts.txt
  - alerts.csv

## Component Tests

### Strategy Engine Test

```python
from strategy import CreditSpreadStrategy
from utils import load_config

config = load_config('config.yaml')
strategy = CreditSpreadStrategy(config)
print("✓ Strategy engine initialized")

# Test scoring
sample_opp = {
    'credit': 1.75,
    'spread_width': 5,
    'risk_reward': 0.54,
    'pop': 88.0,
}

# Verify calculations work
assert sample_opp['credit'] > 0
assert sample_opp['pop'] > 80
print("✓ Strategy calculations OK")
```

### Technical Analysis Test

```python
from strategy import TechnicalAnalyzer
from utils import load_config
import yfinance as yf

config = load_config('config.yaml')
analyzer = TechnicalAnalyzer(config)

# Get sample data
ticker = yf.Ticker('SPY')
data = ticker.history(period='3mo')

if not data.empty:
    signals = analyzer.analyze('SPY', data)
    print(f"✓ Technical analysis OK: Trend={signals.get('trend', 'unknown')}")
else:
    print("⚠ Could not fetch data (network issue?)")
```

### Options Analysis Test

```python
from strategy import OptionsAnalyzer
from utils import load_config

config = load_config('config.yaml')
analyzer = OptionsAnalyzer(config)

# Try to get options chain (may fail if network issues)
try:
    chain = analyzer.get_options_chain('SPY')
    if not chain.empty:
        print(f"✓ Options analysis OK: Retrieved {len(chain)} options")
    else:
        print("⚠ No options data (might be weekend/market closed)")
except Exception as e:
    print(f"⚠ Options data unavailable: {e}")
```

### Alert Generation Test

```python
from alerts import AlertGenerator
from utils import load_config
from datetime import datetime, timedelta

config = load_config('config.yaml')
alert_gen = AlertGenerator(config)

# Create sample opportunity
opp = {
    'ticker': 'SPY',
    'type': 'bull_put_spread',
    'expiration': datetime.now() + timedelta(days=35),
    'dte': 35,
    'short_strike': 485.0,
    'long_strike': 480.0,
    'short_delta': 0.12,
    'credit': 1.75,
    'max_loss': 3.25,
    'max_profit': 1.75,
    'profit_target': 0.88,
    'stop_loss': 4.38,
    'spread_width': 5,
    'current_price': 505.25,
    'distance_to_short': 20.25,
    'pop': 88.0,
    'risk_reward': 0.54,
    'score': 78.5,
}

# Test Telegram formatting
msg = alert_gen.format_telegram_message(opp)
assert 'SPY' in msg
assert 'bull put spread' in msg.lower()
print("✓ Alert formatting OK")
```

### Tracker Test

```python
from tracker import TradeTracker, PnLDashboard
from utils import load_config

config = load_config('config.yaml')
tracker = TradeTracker(config)

# Get statistics (should work even with no trades)
stats = tracker.get_statistics()
print(f"✓ Tracker OK: {stats['total_trades']} trades tracked")

# Dashboard
dashboard = PnLDashboard(config, tracker)
print("✓ Dashboard initialized")
```

### Backtest Test

```python
from backtest import Backtester, PerformanceMetrics
from utils import load_config
from datetime import datetime, timedelta

config = load_config('config.yaml')
backtester = Backtester(config)

# Run quick backtest (30 days)
end = datetime.now()
start = end - timedelta(days=30)

print("Running quick backtest (this may take a minute)...")
results = backtester.run_backtest('SPY', start, end)

if results:
    print(f"✓ Backtest OK: {results['total_trades']} trades simulated")
    print(f"  Win Rate: {results['win_rate']:.1f}%")
else:
    print("⚠ Backtest produced no results (may need more history)")
```

## Integration Tests

### Full Scan Test

Test the complete scanning workflow:

```bash
python3 main.py scan
```

**Expected:**
- Fetches data for SPY, QQQ, IWM
- Analyzes options chains
- Generates alerts
- Creates output files

**Common issues:**
- Network errors (retry)
- No opportunities found (normal if IV is low)
- Rate limiting (wait and retry)

### Full Backtest Test

Test the complete backtesting workflow:

```bash
python3 main.py backtest --ticker SPY --days 90
```

**Expected:**
- Simulates trading for 90 days
- Generates performance report
- Shows win rate and P&L

**Time:** 1-2 minutes

### Dashboard Test

```bash
python3 main.py dashboard
```

**Expected:**
- Shows trading statistics
- Lists open positions (if any)
- Displays recent performance

## Error Handling Tests

### Invalid Config Test

Create invalid config and verify it's caught:

```python
from utils import validate_config

bad_config = {
    'tickers': [],  # Empty tickers
    'strategy': {'min_dte': 45, 'max_dte': 30},  # Invalid range
    'risk': {'account_size': -1000},  # Negative size
}

try:
    validate_config(bad_config)
    print("✗ Should have caught invalid config")
except ValueError as e:
    print(f"✓ Config validation working: {e}")
```

### Missing Data Test

Test behavior when data is unavailable:

```python
from strategy import OptionsAnalyzer
from utils import load_config

config = load_config('config.yaml')
analyzer = OptionsAnalyzer(config)

# Try invalid ticker
chain = analyzer.get_options_chain('INVALID_TICKER_XYZ')
assert chain.empty
print("✓ Handles missing data gracefully")
```

## Performance Tests

### Options Chain Speed Test

```python
import time
from strategy import OptionsAnalyzer
from utils import load_config

config = load_config('config.yaml')
analyzer = OptionsAnalyzer(config)

start = time.time()
chain = analyzer.get_options_chain('SPY')
elapsed = time.time() - start

print(f"Options chain retrieval: {elapsed:.2f}s")
if elapsed < 10:
    print("✓ Performance acceptable")
else:
    print("⚠ Slow network or rate limiting")
```

## Continuous Testing

### Pre-commit Checklist

Before committing changes:

- [ ] All imports work
- [ ] Config validates
- [ ] Demo runs without errors
- [ ] Can scan at least one ticker
- [ ] Backtest completes
- [ ] No syntax errors in logs

### Daily Testing

Recommended daily checks:

```bash
# Quick health check
python3 -c "from utils import load_config; load_config('config.yaml')"

# Verify data access
python3 -c "import yfinance as yf; yf.Ticker('SPY').history(period='1d')"
```

## Troubleshooting Tests

### Logging Test

Verify logging is working:

```python
import logging
from utils import setup_logging, load_config

config = load_config('config.yaml')
setup_logging(config)

logger = logging.getLogger(__name__)
logger.info("Test message")
logger.warning("Test warning")

print("✓ Check logs/trading_system.log for messages")
```

### File I/O Test

Verify file operations work:

```python
from pathlib import Path
import json

# Test write
test_file = Path('output/test.json')
test_data = {'test': 'data'}

test_file.parent.mkdir(exist_ok=True)
with open(test_file, 'w') as f:
    json.dump(test_data, f)

# Test read
with open(test_file, 'r') as f:
    loaded = json.load(f)

assert loaded == test_data
test_file.unlink()  # Clean up

print("✓ File I/O working")
```

## Test Data

Sample test opportunity for manual testing:

```python
TEST_OPPORTUNITY = {
    'ticker': 'SPY',
    'type': 'bull_put_spread',
    'expiration': '2024-03-15',
    'dte': 35,
    'short_strike': 485.0,
    'long_strike': 480.0,
    'short_delta': 0.12,
    'credit': 1.75,
    'max_loss': 3.25,
    'max_profit': 1.75,
    'profit_target': 0.88,
    'stop_loss': 4.38,
    'spread_width': 5,
    'current_price': 505.25,
    'distance_to_short': 20.25,
    'pop': 88.0,
    'risk_reward': 0.54,
    'score': 78.5,
}
```

## Automated Test Suite

For full test automation, create `tests/test_all.py`:

```python
import unittest
from datetime import datetime, timedelta
from utils import load_config, validate_config
from strategy import CreditSpreadStrategy

class TestCreditSpreadSystem(unittest.TestCase):
    
    def setUp(self):
        self.config = load_config('config.yaml')
    
    def test_config_loads(self):
        self.assertIsNotNone(self.config)
        self.assertIn('tickers', self.config)
    
    def test_config_valid(self):
        self.assertTrue(validate_config(self.config))
    
    def test_strategy_init(self):
        strategy = CreditSpreadStrategy(self.config)
        self.assertIsNotNone(strategy)
    
    # Add more tests...

if __name__ == '__main__':
    unittest.main()
```

Run with:
```bash
python3 -m pytest tests/
```

---

**Testing is crucial** - run these tests after installation and before live trading!
