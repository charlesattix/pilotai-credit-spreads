import { describe, it, expect } from 'vitest'
import { z } from 'zod'

// Recreate the ConfigSchema from the route to test validation logic
const TechnicalSchema = z.object({
  use_trend_filter: z.boolean().optional(),
  use_rsi_filter: z.boolean().optional(),
  fast_ma: z.number().int().positive().optional(),
  slow_ma: z.number().int().positive().optional(),
  rsi_period: z.number().int().positive().optional(),
  rsi_oversold: z.number().min(0).max(100).optional(),
  rsi_overbought: z.number().min(0).max(100).optional(),
}).optional()

const ConfigSchema = z.object({
  tickers: z.array(z.string().min(1).max(10)).optional(),
  strategy: z.object({
    min_dte: z.number().int().positive().optional(),
    max_dte: z.number().int().positive().optional(),
    min_delta: z.number().min(0).max(1).optional(),
    max_delta: z.number().min(0).max(1).optional(),
    spread_width: z.number().positive().optional(),
    technical: TechnicalSchema,
  }).optional(),
  risk: z.object({
    account_size: z.number().positive().optional(),
    max_risk_per_trade: z.number().min(0).max(100).optional(),
    max_positions: z.number().int().positive().optional(),
    profit_target: z.number().min(0).max(100).optional(),
    stop_loss_multiplier: z.number().positive().optional(),
  }).optional(),
}).passthrough()

describe('config validation (zod schema)', () => {
  it('valid config passes validation', () => {
    const valid = {
      tickers: ['SPY', 'QQQ'],
      strategy: { min_dte: 20, max_dte: 45, spread_width: 5 },
      risk: { account_size: 100000, max_positions: 5 },
    }
    expect(ConfigSchema.safeParse(valid).success).toBe(true)
  })

  it('empty object passes (all fields optional)', () => {
    expect(ConfigSchema.safeParse({}).success).toBe(true)
  })

  it('invalid types rejected — tickers must be array', () => {
    const result = ConfigSchema.safeParse({ tickers: 'SPY' })
    expect(result.success).toBe(false)
  })

  it('invalid types rejected — min_dte must be number', () => {
    const result = ConfigSchema.safeParse({ strategy: { min_dte: 'thirty' } })
    expect(result.success).toBe(false)
  })

  it('negative account_size rejected', () => {
    const result = ConfigSchema.safeParse({ risk: { account_size: -5000 } })
    expect(result.success).toBe(false)
  })

  it('negative spread_width rejected', () => {
    const result = ConfigSchema.safeParse({ strategy: { spread_width: -1 } })
    expect(result.success).toBe(false)
  })

  it('delta > 1 rejected', () => {
    const result = ConfigSchema.safeParse({ strategy: { max_delta: 1.5 } })
    expect(result.success).toBe(false)
  })

  it('rsi_oversold > 100 rejected', () => {
    const result = ConfigSchema.safeParse({ strategy: { technical: { rsi_oversold: 150 } } })
    expect(result.success).toBe(false)
  })
})
