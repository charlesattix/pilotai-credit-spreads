/**
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { calcUnrealizedPnL } from '@/lib/pnl'
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

describe('calcUnrealizedPnL (canonical)', () => {
  it('returns object with unrealized_pnl and days_remaining', () => {
    const result = calcUnrealizedPnL(makeTrade())
    expect(typeof result.unrealized_pnl).toBe('number')
    expect(typeof result.days_remaining).toBe('number')
  })

  it('days_remaining is non-negative', () => {
    expect(calcUnrealizedPnL(makeTrade()).days_remaining).toBeGreaterThanOrEqual(0)
  })

  it('result is bounded by max_loss and max_profit', () => {
    const trade = makeTrade()
    const { unrealized_pnl } = calcUnrealizedPnL(trade)
    expect(unrealized_pnl).toBeGreaterThanOrEqual(-trade.max_loss)
    expect(unrealized_pnl).toBeLessThanOrEqual(trade.max_profit)
  })

  it('returns 0 when max_profit is 0', () => {
    const { unrealized_pnl } = calcUnrealizedPnL(makeTrade({ max_profit: 0 }))
    expect(unrealized_pnl).toBe(0)
  })

  it('handles expired trade', () => {
    const past = new Date()
    past.setDate(past.getDate() - 5)
    const result = calcUnrealizedPnL(makeTrade({ expiration: past.toISOString().split('T')[0] }))
    expect(result.days_remaining).toBe(0)
    expect(Number.isFinite(result.unrealized_pnl)).toBe(true)
  })

  it('handles bull put spread (bullish)', () => {
    const result = calcUnrealizedPnL(makeTrade({ type: 'bull_put_spread' }))
    expect(Number.isFinite(result.unrealized_pnl)).toBe(true)
  })

  it('handles zero entry_price', () => {
    const result = calcUnrealizedPnL(makeTrade({ entry_price: 0, current_price: 0 }))
    expect(Number.isFinite(result.unrealized_pnl)).toBe(true)
  })

  it('handles missing dte_at_entry (defaults to 35)', () => {
    const result = calcUnrealizedPnL(makeTrade({ dte_at_entry: 0 }))
    expect(Number.isFinite(result.unrealized_pnl)).toBe(true)
  })
})
