import { describe, it, expect } from 'vitest'
import { generateTradeId, shouldAutoClose, calculatePortfolioStats } from '@/lib/paper-trades'
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
    profit_target: 75,
    stop_loss: 175,
    ...overrides,
  }
}

describe('generateTradeId', () => {
  it('starts with PT-', () => {
    expect(generateTradeId()).toMatch(/^PT-/)
  })

  it('generates unique IDs', () => {
    const ids = new Set(Array.from({ length: 20 }, () => generateTradeId()))
    expect(ids.size).toBe(20)
  })
})

describe('shouldAutoClose', () => {
  it('does not close normal open trade', () => {
    const result = shouldAutoClose(makeTrade())
    expect(result.close).toBe(false)
  })

  it('closes expired trade', () => {
    const past = new Date()
    past.setDate(past.getDate() - 1)
    // Use high profit_target so it won't trigger before expiry check
    const result = shouldAutoClose(makeTrade({
      expiration: past.toISOString().split('T')[0],
      profit_target: 999999,
      stop_loss: 999999,
    }))
    expect(result.close).toBe(true)
    expect(result.reason).toContain('Expired')
  })
})

describe('calculatePortfolioStats', () => {
  it('returns zeros for empty array', () => {
    const stats = calculatePortfolioStats([])
    expect(stats.totalTrades).toBe(0)
    expect(stats.winRate).toBe(0)
    expect(stats.totalRealizedPnL).toBe(0)
  })

  it('counts open and closed correctly', () => {
    const trades = [
      makeTrade({ status: 'open' }),
      makeTrade({ status: 'closed_profit', realized_pnl: 100 }),
      makeTrade({ status: 'closed_loss', realized_pnl: -50 }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.totalTrades).toBe(3)
    expect(stats.openTrades).toBe(1)
    expect(stats.closedTrades).toBe(2)
    expect(stats.winners).toBe(1)
    expect(stats.losers).toBe(1)
  })

  it('calculates win rate', () => {
    const trades = [
      makeTrade({ status: 'closed_profit', realized_pnl: 100 }),
      makeTrade({ status: 'closed_profit', realized_pnl: 50 }),
      makeTrade({ status: 'closed_loss', realized_pnl: -30 }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.winRate).toBeCloseTo(66.67, 1)
  })

  it('calculates avgWin and avgLoss', () => {
    const trades = [
      makeTrade({ status: 'closed_profit', realized_pnl: 100 }),
      makeTrade({ status: 'closed_profit', realized_pnl: 200 }),
      makeTrade({ status: 'closed_loss', realized_pnl: -50 }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.avgWin).toBe(150)
    expect(stats.avgLoss).toBe(50)
  })

  it('calculates profitFactor', () => {
    const trades = [
      makeTrade({ status: 'closed_profit', realized_pnl: 300 }),
      makeTrade({ status: 'closed_loss', realized_pnl: -100 }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.profitFactor).toBe(3)
  })

  it('profitFactor is Infinity when no losses', () => {
    const trades = [makeTrade({ status: 'closed_profit', realized_pnl: 100 })]
    const stats = calculatePortfolioStats(trades)
    expect(stats.profitFactor).toBe(Infinity)
  })

  it('calculates openRisk', () => {
    const trades = [
      makeTrade({ status: 'open', max_loss: 350 }),
      makeTrade({ status: 'open', max_loss: 200 }),
    ]
    const stats = calculatePortfolioStats(trades)
    expect(stats.openRisk).toBe(550)
  })
})
