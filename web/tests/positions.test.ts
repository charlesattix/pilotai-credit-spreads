import { describe, it, expect } from 'vitest'
import { calculatePortfolioStats, calculateUnrealizedPnL } from '@/lib/paper-trades'
import { PaperTrade } from '@/lib/types'

function makeTrade(overrides: Partial<PaperTrade> = {}): PaperTrade {
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
    max_profit: 150,
    max_loss: 350,
    status: 'open',
    entry_date: new Date(Date.now() - 15 * 86400000).toISOString(),
    ...overrides,
  }
}

describe('positions / portfolio stats', () => {
  it('closed trades with status closed_profit are counted correctly', () => {
    const trades = [
      makeTrade({ status: 'closed_profit', realized_pnl: 100 }),
      makeTrade({ status: 'closed_profit', realized_pnl: 50 }),
      makeTrade({ status: 'open' }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.closedTrades).toBe(2)
    expect(stats.winners).toBe(2)
  })

  it('closed trades with status closed_loss are counted correctly', () => {
    const trades = [
      makeTrade({ status: 'closed_loss', realized_pnl: -200 }),
      makeTrade({ status: 'closed_loss', realized_pnl: -100 }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.closedTrades).toBe(2)
    expect(stats.losers).toBe(2)
    expect(stats.winners).toBe(0)
  })

  it('win rate calculation is correct', () => {
    const trades = [
      makeTrade({ status: 'closed_profit', realized_pnl: 100 }),
      makeTrade({ status: 'closed_loss', realized_pnl: -50 }),
      makeTrade({ status: 'closed_profit', realized_pnl: 75 }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.winRate).toBeCloseTo(66.67, 1)
  })

  it('empty portfolio returns zeroed stats', () => {
    const stats = calculatePortfolioStats([])
    expect(stats.totalTrades).toBe(0)
    expect(stats.openTrades).toBe(0)
    expect(stats.closedTrades).toBe(0)
    expect(stats.winRate).toBe(0)
    expect(stats.totalRealizedPnL).toBe(0)
    expect(stats.totalUnrealizedPnL).toBe(0)
  })

  it('realized_pnl field is used (not exit_pnl)', () => {
    const trade = makeTrade({ status: 'closed_profit', realized_pnl: 120 })
    const pnl = calculateUnrealizedPnL(trade)
    expect(pnl).toBe(120)
  })
})
