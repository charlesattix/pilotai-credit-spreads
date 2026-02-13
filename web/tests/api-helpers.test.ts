import { describe, it, expect } from 'vitest'

// Test the type interfaces and utility aspects of lib/api.ts
// The functions themselves are thin fetch wrappers, so we test structure and error behavior

import type { Alert, Trade, BacktestResult, Config } from '@/lib/api'

describe('API type contracts', () => {
  it('Alert interface has required fields', () => {
    const alert: Alert = {
      ticker: 'AAPL',
      type: 'bear_call_spread',
      expiration: '2026-03-20',
      dte: 30,
      short_strike: 200,
      long_strike: 205,
      short_delta: 0.15,
      credit: 1.2,
      max_loss: 380,
      max_profit: 120,
      profit_target: 60,
      stop_loss: 190,
      spread_width: 5,
      current_price: 185,
      distance_to_short: 15,
      pop: 78,
      risk_reward: 3.17,
      score: 8.5,
    }
    expect(alert.ticker).toBe('AAPL')
    expect(alert.max_loss).toBeGreaterThan(0)
    expect(alert.spread_width).toBe(alert.long_strike - alert.short_strike)
  })

  it('Trade interface supports open and closed status', () => {
    const openTrade: Trade = {
      id: '1',
      ticker: 'SPY',
      type: 'bear_call_spread',
      entry_date: '2026-01-01',
      short_strike: 500,
      long_strike: 505,
      credit: 1.5,
      status: 'open',
      entry_price: 480,
      dte_entry: 30,
    }
    expect(openTrade.status).toBe('open')
    expect(openTrade.exit_date).toBeUndefined()

    const closedTrade: Trade = { ...openTrade, status: 'closed', exit_date: '2026-01-15', pnl: 120 }
    expect(closedTrade.status).toBe('closed')
    expect(closedTrade.pnl).toBe(120)
  })

  it('BacktestResult has valid numeric fields', () => {
    const result: BacktestResult = {
      total_trades: 100,
      winning_trades: 70,
      losing_trades: 30,
      win_rate: 70,
      total_pnl: 5000,
      avg_win: 150,
      avg_loss: 200,
      profit_factor: 1.75,
      sharpe_ratio: 1.2,
      max_drawdown: 3000,
      max_drawdown_pct: 15,
      equity_curve: [{ date: '2025-01-01', equity: 100000 }],
      trade_distribution: [{ range: '0-100', count: 20 }],
    }
    expect(result.win_rate).toBe(result.winning_trades / result.total_trades * 100)
    expect(result.profit_factor).toBeGreaterThan(1)
  })
})
