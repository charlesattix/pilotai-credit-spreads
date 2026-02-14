/**
 * @vitest-environment node
 */
import { describe, it, expect, vi } from 'vitest'

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs')
  return {
    ...actual,
    promises: {
      ...(actual as any).promises,
      readFile: vi.fn().mockRejectedValue(new Error('ENOENT')),
    },
  }
})

import { GET } from '@/app/api/backtest/route'

describe('GET /api/backtest (integration)', () => {
  it('returns 200 with default empty results when no file exists', async () => {
    const response = await GET()
    expect(response.status).toBe(200)
    const data = await response.json()
    expect(data.total_trades).toBe(0)
    expect(data.win_rate).toBe(0)
    expect(Array.isArray(data.equity_curve)).toBe(true)
    expect(Array.isArray(data.trade_distribution)).toBe(true)
  })
})
