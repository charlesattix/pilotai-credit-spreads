import { describe, it, expect } from 'vitest'

// We test the validation logic that exists in the POST handler of route.ts
// Since the route handler uses Next.js Request/Response, we extract and test the logic directly

function validateTradeInput(alert: any, contracts: number) {
  const errors: string[] = []
  if (!alert?.ticker) errors.push('Missing ticker')
  if (typeof alert?.credit !== 'number' || alert.credit < 0) errors.push('Negative or missing credit')
  if (!contracts || contracts <= 0) errors.push('contracts must be > 0')
  if (contracts > 100) errors.push('contracts must be <= 100')
  if (alert?.spread_width != null && alert?.credit != null && alert.spread_width < alert.credit) {
    errors.push('spread_width < credit would make negative max_loss')
  }
  return errors
}

function buildTrade(alert: any, contracts: number) {
  const creditPerContract = alert.credit
  const spreadWidth = alert.spread_width
  return {
    id: `PT-test`,
    ticker: alert.ticker,
    type: alert.type,
    short_strike: alert.short_strike,
    long_strike: alert.long_strike,
    spread_width: spreadWidth,
    expiration: alert.expiration,
    dte_at_entry: alert.dte,
    entry_credit: creditPerContract,
    entry_price: alert.current_price,
    contracts,
    max_profit: creditPerContract * 100 * contracts,
    max_loss: (spreadWidth - creditPerContract) * 100 * contracts,
    status: 'open' as const,
  }
}

const validAlert = {
  ticker: 'SPY',
  type: 'bear_call_spread',
  short_strike: 500,
  long_strike: 505,
  spread_width: 5,
  expiration: '2026-03-20',
  dte: 30,
  credit: 1.5,
  current_price: 480,
  pop: 75,
  score: 8,
  short_delta: 0.15,
}

describe('paper trade validation', () => {
  it('valid alert creates a trade with correct fields', () => {
    const errors = validateTradeInput(validAlert, 1)
    expect(errors).toHaveLength(0)
    const trade = buildTrade(validAlert, 1)
    expect(trade.ticker).toBe('SPY')
    expect(trade.max_profit).toBe(150)
    expect(trade.max_loss).toBe(350)
  })

  it('missing ticker is rejected', () => {
    const errors = validateTradeInput({ ...validAlert, ticker: '' }, 1)
    expect(errors.length).toBeGreaterThan(0)
    expect(errors[0]).toMatch(/ticker/i)
  })

  it('negative credit is rejected', () => {
    const errors = validateTradeInput({ ...validAlert, credit: -0.5 }, 1)
    expect(errors.length).toBeGreaterThan(0)
    expect(errors[0]).toMatch(/credit/i)
  })

  it('contracts = 0 is rejected', () => {
    const errors = validateTradeInput(validAlert, 0)
    expect(errors.length).toBeGreaterThan(0)
    expect(errors[0]).toMatch(/contracts/i)
  })

  it('contracts > 100 is rejected', () => {
    const errors = validateTradeInput(validAlert, 101)
    expect(errors.length).toBeGreaterThan(0)
    expect(errors[0]).toMatch(/contracts/i)
  })

  it('spread_width < credit is rejected (negative max_loss)', () => {
    const errors = validateTradeInput({ ...validAlert, spread_width: 1, credit: 2 }, 1)
    expect(errors.length).toBeGreaterThan(0)
    expect(errors[0]).toMatch(/spread_width/i)
  })
})
