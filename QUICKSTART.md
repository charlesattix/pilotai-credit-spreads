# Quick Start Guide

Get started with the Credit Spread Trading System in 5 minutes.

## 1. Installation

```bash
# Navigate to the project directory
cd credit-spread-system

# Install dependencies
pip install -r requirements.txt
```

**Note:** If `ta-lib` fails to install, that's okay - the system will use `pandas-ta` instead.

## 2. Configuration (Optional)

Edit `config.yaml` if you want to customize:
- Account size (default: $100,000)
- Tickers (default: SPY, QQQ, IWM)
- Risk parameters
- Strategy settings

## 3. Run a Demo

See sample alerts without scanning real data:

```bash
python demo.py
```

This creates sample alerts in the `output/` directory.

## 4. Scan for Real Opportunities

Scan the market for credit spread setups:

```bash
python main.py scan
```

This will:
- Download current market data
- Analyze options chains
- Find high-probability spreads
- Generate alerts in `output/`

**Expected runtime:** 2-5 minutes depending on internet speed

## 5. Run a Backtest

Test the strategy on historical data:

```bash
python main.py backtest
```

This backtests SPY for the last 365 days and shows:
- Win rate
- Total P&L
- Max drawdown
- Sharpe ratio

**Expected runtime:** 1-2 minutes

## 6. View Your Dashboard

Once you have some trades (from backtesting or real tracking):

```bash
python main.py dashboard
```

## Common First-Time Issues

### No opportunities found
**Cause:** IV might be low or filters too restrictive  
**Fix:** Lower `min_iv_rank` in config.yaml to 20

### Module import errors
**Cause:** Missing dependencies  
**Fix:** `pip install -r requirements.txt`

### yfinance errors
**Cause:** Network issues or rate limiting  
**Fix:** Wait a minute and try again

## Next Steps

1. **Review alerts** in `output/alerts.txt`
2. **Customize settings** in `config.yaml`
3. **Set up Telegram** (see README.md) for mobile alerts
4. **Paper trade** the signals before going live
5. **Track results** using the dashboard

## Example Workflow

Daily routine:
```bash
# Morning: Scan for opportunities
python main.py scan

# Review alerts
cat output/alerts.txt

# Check your positions
python main.py dashboard
```

Weekly routine:
```bash
# Review performance
python main.py dashboard

# Re-backtest to validate strategy
python main.py backtest --days 180
```

## Getting Help

- Check `logs/trading_system.log` for detailed info
- Review `README.md` for full documentation
- Ensure all config parameters are valid

---

**You're ready to start!** Run `python demo.py` to see sample alerts now.
