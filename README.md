# Credit Spread Trading System

A comprehensive Python-based trading system for high-probability credit spreads (bull put spreads and bear call spreads) on SPY, QQQ, and IWM, targeting a 90%+ win rate with profitable P&L.

## Features

### 1. Strategy Engine
- **Bull Put Spreads** and **Bear Call Spreads**
- High probability OTM spreads (delta-based selection: 0.10-0.15 delta short strikes)
- IV rank/percentile filters (enter when IV is elevated)
- Technical filters:
  - Trend analysis (moving averages)
  - Support/resistance levels
  - RSI indicators
- DTE targeting: 30-45 DTE, manage at 21 DTE or 50% profit

### 2. Risk Management
- Max loss per trade capped (configurable % of account)
- Position sizing based on account size
- Max concurrent positions limit
- Early exit rules:
  - Close at 50% profit target
  - Exit if delta of short strike exceeds threshold
- Stop loss at 2x-3x credit received

### 3. Signal Scanner
- Scans options chains using yfinance (free data)
- Scores each opportunity based on multiple factors:
  - Credit as % of spread width
  - Risk/reward ratio
  - Probability of profit (POP)
  - Technical alignment
  - IV rank/percentile
- Returns ranked opportunities

### 4. Alert System
- Generates actionable alerts with:
  - Exact strikes and expiration
  - Credit target, max loss, profit target, stop loss
  - Probability of profit
  - Score/ranking
- Output formats:
  - JSON (machine-readable)
  - Text (human-readable)
  - CSV (spreadsheet import)
- **Telegram bot integration** (optional)

### 5. Backtesting Module
- Backtest strategies against historical data
- Track performance metrics:
  - Win rate
  - Average P&L
  - Max drawdown
  - Sharpe ratio
  - Profit factor
- Generate comprehensive performance reports

### 6. P&L Tracker
- Track all trades (open and closed)
- Running P&L dashboard
- Win rate tracking
- Position management
- Export to CSV

## Installation

### Requirements
- Python 3.8 or higher
- pip package manager

### Setup

1. **Clone/navigate to the project directory:**
```bash
cd credit-spread-system
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

**Note:** If you have issues installing `ta-lib`, see the [TA-Lib installation guide](https://github.com/mrjbq7/ta-lib#installation). Alternatively, the system will work without it using `pandas-ta` as a fallback.

3. **Configure the system:**

Edit `config.yaml` to customize:
- Tickers to monitor
- Strategy parameters (DTE, delta targets, IV filters)
- Risk management settings (account size, position limits)
- Alert settings
- Telegram credentials (if using)

## Usage

### Scan for Opportunities

Scan the configured tickers for credit spread setups:

```bash
python main.py scan
```

This will:
- Analyze each ticker
- Find high-probability spread opportunities
- Generate alerts in multiple formats
- Send Telegram notifications (if configured)

### Run Backtest

Test the strategy against historical data:

```bash
# Backtest SPY for the last year
python main.py backtest

# Backtest QQQ for 180 days
python main.py backtest --ticker QQQ --days 180
```

This will:
- Simulate trading the strategy
- Generate performance metrics
- Create a detailed report
- Display win rate, P&L, max drawdown, Sharpe ratio

### View Dashboard

Display your current P&L and trading statistics:

```bash
python main.py dashboard
```

Shows:
- Overall statistics (win rate, total P&L)
- Recent performance (last 30 days)
- Open positions
- Best/worst trades

### Generate Alerts Only

Generate alerts from the most recent scan:

```bash
python main.py alerts
```

## Configuration

### Key Configuration Parameters

Edit `config.yaml` to adjust:

#### Strategy Parameters
```yaml
strategy:
  min_dte: 30          # Minimum days to expiration
  max_dte: 45          # Maximum days to expiration
  manage_dte: 21       # Close at this DTE if not at profit target
  min_delta: 0.10      # Minimum delta for short strike
  max_delta: 0.15      # Maximum delta for short strike
  spread_width: 5      # Width of spreads in dollars
  min_iv_rank: 30      # Enter only when IV rank >= 30
```

#### Risk Management
```yaml
risk:
  account_size: 100000           # Your account size
  max_risk_per_trade: 2.0        # Max 2% risk per trade
  max_positions: 5               # Max concurrent positions
  profit_target: 50              # Close at 50% profit
  stop_loss_multiplier: 2.5      # Stop loss at 2.5x credit
```

#### Tickers
```yaml
tickers:
  - SPY
  - QQQ
  - IWM
```

### Telegram Setup (Optional)

To receive alerts via Telegram:

1. **Create a Telegram bot:**
   - Open Telegram, search for `@BotFather`
   - Send `/newbot` and follow the prompts
   - Save the API token

2. **Get your chat ID:**
   - Search for `@userinfobot` on Telegram
   - Start a chat to get your chat ID

3. **Configure:**
```yaml
alerts:
  telegram:
    enabled: true
    bot_token: "YOUR_BOT_TOKEN_HERE"
    chat_id: "YOUR_CHAT_ID_HERE"
```

4. **Test:**
```bash
python main.py scan
```

## Project Structure

```
credit-spread-system/
├── main.py                 # Main entry point
├── config.yaml             # Configuration file
├── requirements.txt        # Python dependencies
├── utils.py                # Utility functions
├── strategy/               # Strategy engine
│   ├── __init__.py
│   ├── spread_strategy.py      # Credit spread logic
│   ├── technical_analysis.py   # Technical indicators
│   └── options_analyzer.py     # Options chain analysis
├── alerts/                 # Alert system
│   ├── __init__.py
│   ├── alert_generator.py      # Alert formatting
│   └── telegram_bot.py         # Telegram integration
├── backtest/               # Backtesting
│   ├── __init__.py
│   ├── backtester.py           # Backtest engine
│   └── performance_metrics.py  # Performance calculations
├── tracker/                # Trade tracking
│   ├── __init__.py
│   ├── trade_tracker.py        # Position tracking
│   └── pnl_dashboard.py        # P&L display
├── data/                   # Trade data storage
├── logs/                   # Log files
└── output/                 # Generated alerts and reports
    ├── alerts.json
    ├── alerts.txt
    ├── alerts.csv
    └── backtest_reports/
```

## Output Files

### Alert Files

After running `python main.py scan`, check the `output/` directory:

- **`alerts.json`** - Machine-readable JSON format
- **`alerts.txt`** - Human-readable text format
- **`alerts.csv`** - Spreadsheet-compatible CSV

### Backtest Reports

After running `python main.py backtest`, check `output/backtest_reports/`:

- **`backtest_report_YYYYMMDD_HHMMSS.txt`** - Performance summary
- **`backtest_results_YYYYMMDD_HHMMSS.json`** - Detailed results

### Trade Data

The system stores trade data in `data/`:

- **`trades.json`** - All closed trades
- **`positions.json`** - Currently open positions

## Sample Alert Output

```
================================================================================
CREDIT SPREAD TRADING ALERTS
Generated: 2024-02-12 14:30:00
Total Opportunities: 3
================================================================================

ALERT #1 - SPY BULL_PUT_SPREAD
--------------------------------------------------------------------------------
Score: 78.5/100
Expiration: 2024-03-15 (DTE: 35)

TRADE SETUP:
  Sell $485.00 Put
  Buy  $480.00 Put
  Spread Width: $5
  Credit Target: $1.75 per spread

RISK/REWARD:
  Max Profit: $1.75 (100% of credit)
  Profit Target: $0.88 (50% of credit)
  Max Loss: $3.25
  Stop Loss: $4.38
  Risk/Reward: 1:0.54

PROBABILITIES:
  Short Strike Delta: 0.120
  Probability of Profit: 88.0%

MARKET CONTEXT:
  Current Price: $505.25
  Distance to Short Strike: $20.25
```

## Performance Metrics

The system tracks and reports:

- **Win Rate**: Percentage of profitable trades
- **Total P&L**: Net profit/loss
- **Average Win/Loss**: Mean profit and loss per trade
- **Profit Factor**: Gross profit ÷ Gross loss
- **Max Drawdown**: Largest peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted returns
- **Return %**: Overall return on capital

## Target Performance

The system is designed to achieve:
- **Win Rate**: 90%+ (targeting high-probability OTM spreads)
- **Risk/Reward**: ~1:3 (risk $300 to make $100)
- **Profit Target**: 50% of credit received
- **Profitable P&L**: Consistent positive returns

## Logging

Logs are saved to `logs/trading_system.log` with automatic rotation:
- Max size: 10 MB per file
- Keeps 5 backup files
- Configurable log level in `config.yaml`

View logs in real-time:
```bash
tail -f logs/trading_system.log
```

## Troubleshooting

### No opportunities found
- Check that IV rank is elevated (>30)
- Verify technical filters aren't too restrictive
- Ensure options data is available for your tickers

### Can't install ta-lib
- Use `pandas-ta` as fallback (already in requirements)
- The system will work without ta-lib

### Telegram bot not sending
- Verify bot token and chat ID in `config.yaml`
- Ensure `python-telegram-bot` is installed
- Set `enabled: true` in Telegram config

### Backtest shows low win rate
- Adjust delta targets (try 0.08-0.12)
- Increase IV rank minimum
- Tighten technical filters
- Note: Backtest uses simulated options data (real historical options data would be more accurate)

## Important Notes

### Data Limitations
- Uses **yfinance** for free market data
- Options Greeks may be estimates
- Real-time data requires paid API (Interactive Brokers, TD Ameritrade, etc.)
- Backtest uses simplified options pricing (for production, use historical options data)

### Live Trading
This system generates **alerts only**. It does **not** execute trades automatically. 

To trade live:
1. Review generated alerts
2. Verify setup in your broker platform
3. Manually enter orders
4. Monitor positions
5. Update tracker when closing positions

### Risk Disclaimer
This software is for **educational and research purposes only**. Trading options involves substantial risk and is not suitable for all investors. Past performance does not guarantee future results. Always do your own research and consult with a financial advisor.

## Contributing

To extend the system:
- Add new strategy modules in `strategy/`
- Create custom alert channels in `alerts/`
- Implement new metrics in `backtest/`

## License

MIT License - See LICENSE file for details

## Support

For issues or questions:
1. Check the logs in `logs/trading_system.log`
2. Verify configuration in `config.yaml`
3. Review the code comments and docstrings
4. Check that all dependencies are installed

---

**Built with Python 3.x | Designed for high-probability credit spreads**
