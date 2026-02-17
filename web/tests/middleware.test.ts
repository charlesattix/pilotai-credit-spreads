import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('next/server', () => ({
  NextResponse: {
    next: () => ({ headers: { set: vi.fn() }, _type: 'next' }),
  },
}))

describe('middleware', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('returns NextResponse.next() for all requests', async () => {
    const { middleware } = await import('@/middleware')
    const res = middleware()
    expect((res as any)._type).toBe('next')
  })
})
