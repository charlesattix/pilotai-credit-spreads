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

vi.mock('@/lib/database', () => ({
  getTrades: vi.fn().mockReturnValue([]),
  TradeRow: {},
}))

import { GET } from '@/app/api/positions/route'

describe('GET /api/positions (integration)', () => {
  it('returns 200 with empty positions when no file exists', async () => {
    const response = await GET()
    expect(response.status).toBe(200)
    const data = await response.json()
    expect(data.account_size).toBe(100000)
    expect(data.open_count).toBe(0)
    expect(data.closed_count).toBe(0)
    expect(Array.isArray(data.open_positions)).toBe(true)
    expect(Array.isArray(data.closed_trades)).toBe(true)
  })

  it('returns correct balance fields', async () => {
    const data = await (await GET()).json()
    expect(data.starting_balance).toBe(100000)
    expect(data.current_balance).toBe(100000)
    expect(data.total_pnl).toBe(0)
    expect(data.total_realized_pnl).toBe(0)
    expect(data.total_unrealized_pnl).toBe(0)
  })

  it('win_rate is 0 with no trades', async () => {
    const data = await (await GET()).json()
    expect(data.win_rate).toBe(0)
  })
})
