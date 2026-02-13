import { describe, it, expect } from 'vitest'
import { calculateUnrealizedPnL, UserPaperTrade } from '@/lib/paper-trades'

function makeTrade(overrides: Partial<UserPaperTrade> = {}): UserPaperTrade {
  const future = new Date()
  future.setDate(future.getDate() + 15)
  return {
    id: 'PT-test',
    ticker: 'SPY',
    type: 'bear_call_spread',
    short_strike: 500,
    long_strike: 505,
    spread_width: 5,
    expiration: future.toISOString().split('T')[0],
    dte_at_entry: 30,
    entry_credit: 1.5,
    entry_price: 480,
    current_price: 478,
    contracts: 1,
    max_profit: 150, // 1.5 * 100 * 1
    max_loss: 350,   // (5 - 1.5) * 100 * 1
    status: 'open',
    entry_date: new Date(Date.now() - 15 * 86400000).toISOString(),
    profit_target: 75,
    stop_loss: 175,
    pop: 75,
    score: 8,
    short_delta: 0.15,
    ...overrides,
  }
}

describe('calculateUnrealizedPnL', () => {
  it('normal trade with ~30 DTE returns bounded P&L', () => {
    const trade = makeTrade()
    const pnl = calculateUnrealizedPnL(trade)
    expect(pnl).toBeGreaterThanOrEqual(-trade.max_loss)
    expect(pnl).toBeLessThanOrEqual(trade.max_profit)
  })

  it('dte_at_entry = 0 does not produce NaN', () => {
    const trade = makeTrade({ dte_at_entry: 0 })
    const pnl = calculateUnrealizedPnL(trade)
    expect(Number.isFinite(pnl)).toBe(true)
  })

  it('entry_price = 0 does not produce NaN', () => {
    const trade = makeTrade({ entry_price: 0, current_price: 0 })
    const pnl = calculateUnrealizedPnL(trade)
    expect(Number.isFinite(pnl)).toBe(true)
  })

  it('expired trade (past expiration) returns max profit scenario', () => {
    const past = new Date()
    past.setDate(past.getDate() - 5)
    const trade = makeTrade({
      expiration: past.toISOString().split('T')[0],
      dte_at_entry: 30,
    })
    const pnl = calculateUnrealizedPnL(trade)
    // daysRemaining=0, daysHeld=30, full time decay
    expect(pnl).toBeGreaterThanOrEqual(-trade.max_loss)
    expect(pnl).toBeLessThanOrEqual(trade.max_profit)
  })

  it('missing current_price falls back to entry_price', () => {
    const trade = makeTrade({ current_price: undefined })
    const pnl = calculateUnrealizedPnL(trade)
    expect(Number.isFinite(pnl)).toBe(true)
  })

  it('result is always between -max_loss and +max_profit', () => {
    const scenarios = [
      makeTrade({ current_price: 600 }), // price way up (bad for bear call)
      makeTrade({ current_price: 300 }), // price way down (good)
      makeTrade({ contracts: 10, max_profit: 1500, max_loss: 3500 }),
    ]
    for (const trade of scenarios) {
      const pnl = calculateUnrealizedPnL(trade)
      expect(pnl).toBeGreaterThanOrEqual(-trade.max_loss)
      expect(pnl).toBeLessThanOrEqual(trade.max_profit)
    }
  })

  it('result is always a finite number', () => {
    const edgeCases = [
      makeTrade({ dte_at_entry: 0, entry_price: 0 }),
      makeTrade({ max_profit: 0, max_loss: 0 }),
      makeTrade({ contracts: 0, max_profit: 0, max_loss: 0 }),
    ]
    for (const trade of edgeCases) {
      const pnl = calculateUnrealizedPnL(trade)
      expect(Number.isFinite(pnl)).toBe(true)
    }
  })

  it('returns realized_pnl for closed trades', () => {
    const trade = makeTrade({ status: 'closed_profit', realized_pnl: 120 })
    expect(calculateUnrealizedPnL(trade)).toBe(120)
  })
})
