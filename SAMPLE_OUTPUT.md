# Sample Alert Output

This document shows what the system's alerts look like.

## Text Alert Format

```
================================================================================
CREDIT SPREAD TRADING ALERTS
Generated: 2024-02-12 14:30:00
Total Opportunities: 3
================================================================================

ALERT #1 - SPY BULL_PUT_SPREAD
--------------------------------------------------------------------------------
Score: 78.5/100
Expiration: 2024-03-18 (DTE: 35)

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

================================================================================

ALERT #2 - QQQ BULL_PUT_SPREAD
--------------------------------------------------------------------------------
Score: 75.2/100
Expiration: 2024-03-25 (DTE: 42)

TRADE SETUP:
  Sell $420.00 Put
  Buy  $415.00 Put
  Spread Width: $5
  Credit Target: $1.90 per spread

RISK/REWARD:
  Max Profit: $1.90 (100% of credit)
  Profit Target: $0.95 (50% of credit)
  Max Loss: $3.10
  Stop Loss: $4.75
  Risk/Reward: 1:0.61

PROBABILITIES:
  Short Strike Delta: 0.140
  Probability of Profit: 86.0%

MARKET CONTEXT:
  Current Price: $442.50
  Distance to Short Strike: $22.50

================================================================================

ALERT #3 - IWM BEAR_CALL_SPREAD
--------------------------------------------------------------------------------
Score: 72.8/100
Expiration: 2024-03-21 (DTE: 38)

TRADE SETUP:
  Sell $210.00 Call
  Buy  $215.00 Call
  Spread Width: $5
  Credit Target: $1.65 per spread

RISK/REWARD:
  Max Profit: $1.65 (100% of credit)
  Profit Target: $0.83 (50% of credit)
  Max Loss: $3.35
  Stop Loss: $4.13
  Risk/Reward: 1:0.49

PROBABILITIES:
  Short Strike Delta: 0.130
  Probability of Profit: 87.0%

MARKET CONTEXT:
  Current Price: $198.75
  Distance to Short Strike: $11.25

================================================================================
```

## JSON Alert Format

```json
{
  "timestamp": "2024-02-12T14:30:00",
  "opportunities": [
    {
      "ticker": "SPY",
      "type": "bull_put_spread",
      "expiration": "2024-03-18",
      "dte": 35,
      "short_strike": 485.0,
      "long_strike": 480.0,
      "short_delta": 0.12,
      "credit": 1.75,
      "max_loss": 3.25,
      "max_profit": 1.75,
      "profit_target": 0.88,
      "stop_loss": 4.38,
      "spread_width": 5,
      "current_price": 505.25,
      "distance_to_short": 20.25,
      "pop": 88.0,
      "risk_reward": 0.54,
      "score": 78.5
    }
  ],
  "count": 3
}
```

## CSV Format

```csv
timestamp,ticker,type,expiration,dte,short_strike,long_strike,short_delta,credit,max_profit,max_loss,profit_target,stop_loss,risk_reward,pop,score,current_price,distance_to_short
2024-02-12T14:30:00,SPY,bull_put_spread,2024-03-18,35,485.0,480.0,0.12,1.75,1.75,3.25,0.88,4.38,0.54,88.0,78.5,505.25,20.25
2024-02-12T14:30:00,QQQ,bull_put_spread,2024-03-25,42,420.0,415.0,0.14,1.90,1.90,3.10,0.95,4.75,0.61,86.0,75.2,442.50,22.50
2024-02-12T14:30:00,IWM,bear_call_spread,2024-03-21,38,210.0,215.0,0.13,1.65,1.65,3.35,0.83,4.13,0.49,87.0,72.8,198.75,11.25
```

## Telegram Message Format

```
🔵 SPY BULL PUT SPREAD
Score: 78.5/100 ⭐

📋 TRADE:
  Sell $485.00 Put
  Buy  $480.00 Put
  Exp: 2024-03-18 (35 DTE)
  Credit: $1.75

💰 RISK/REWARD:
  Max Profit: $1.75
  Target (50%): $0.88
  Max Loss: $3.25
  R/R: 1:0.54

📊 PROBABILITY:
  POP: 88.0%
  Delta: 0.120
```

## Backtest Report Sample

```
================================================================================
CREDIT SPREAD STRATEGY - BACKTEST REPORT
================================================================================

SUMMARY
--------------------------------------------------------------------------------
Total Trades: 47
Winning Trades: 43
Losing Trades: 4
Win Rate: 91.49%

RETURNS
--------------------------------------------------------------------------------
Starting Capital: $100,000.00
Ending Capital: $112,450.00
Total P&L: $12,450.00
Return: 12.45%

TRADE STATISTICS
--------------------------------------------------------------------------------
Average Win: $425.50
Average Loss: $890.25
Profit Factor: 2.85

RISK METRICS
--------------------------------------------------------------------------------
Max Drawdown: -3.25%
Sharpe Ratio: 1.85

TARGET ANALYSIS
--------------------------------------------------------------------------------
✅ WIN RATE TARGET ACHIEVED (90%+)
✅ PROFITABLE STRATEGY

================================================================================
```

## Dashboard Display Sample

```
================================================================================
CREDIT SPREAD TRADING SYSTEM - P&L DASHBOARD
================================================================================
Generated: 2024-02-12 15:45:30

OVERALL STATISTICS
--------------------------------------------------------------------------------
Total Trades: 47
Winning Trades: 43
Losing Trades: 4
Win Rate: 91.49%
  ✅ TARGET ACHIEVED (90%+)

Total P&L: $12,450.00
Average P&L per Trade: $264.89
Average Win: $425.50
Average Loss: -$890.25
Best Trade: $875.00
Worst Trade: -$1,250.00

RECENT PERFORMANCE (Last 30 Days)
--------------------------------------------------------------------------------
Trades: 12
P&L: $3,150.00
Win Rate: 91.67%

OPEN POSITIONS
--------------------------------------------------------------------------------
Total Open: 2

1. SPY - bull_put_spread
   Entry: 2024-02-10
   Strikes: $485.00 / $480.00
   Credit: $1.75
   Max Loss: $3.25
   Expiration: 2024-03-18

2. QQQ - bull_put_spread
   Entry: 2024-02-11
   Strikes: $420.00 / $415.00
   Credit: $1.90
   Max Loss: $3.10
   Expiration: 2024-03-25

TOP TRADES
--------------------------------------------------------------------------------
Best Trade: SPY - $875.00
  Date: 2024-02-05
  Type: bull_put_spread

Worst Trade: IWM - -$1,250.00
  Date: 2024-01-22
  Type: bear_call_spread

================================================================================
```

## Key Metrics Explained

### Score (0-100)
Composite score based on:
- Credit as % of spread width (0-25 points)
- Risk/reward ratio (0-25 points)
- Probability of profit (0-25 points)
- Technical alignment (0-15 points)
- IV rank/percentile (0-10 points)

Higher scores indicate better opportunities.

### Probability of Profit (POP)
Estimated as `(1 - |delta|) × 100%`

For a 0.12 delta short strike: POP ≈ 88%

### Risk/Reward
`Credit ÷ Max Loss`

A 1:0.54 ratio means you risk $1.00 to make $0.54

### Win Rate Target
System targets 90%+ by:
- Selecting high-probability setups (0.10-0.15 delta)
- Closing at 50% profit (reduces time at risk)
- Using technical filters for entry timing
- Exiting early if position goes against you
