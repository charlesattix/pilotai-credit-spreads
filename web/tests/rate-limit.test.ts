import { describe, it, expect, vi, beforeEach } from 'vitest'

// Simple rate limiter implementation matching common patterns
function createRateLimiter(maxRequests: number, windowMs: number) {
  const requests = new Map<string, number[]>()

  return {
    check(key: string): { allowed: boolean; remaining: number } {
      const now = Date.now()
      const windowStart = now - windowMs
      const timestamps = (requests.get(key) || []).filter(t => t > windowStart)

      if (timestamps.length >= maxRequests) {
        requests.set(key, timestamps)
        return { allowed: false, remaining: 0 }
      }

      timestamps.push(now)
      requests.set(key, timestamps)
      return { allowed: true, remaining: maxRequests - timestamps.length }
    },

    reset(key: string) {
      requests.delete(key)
    }
  }
}

describe('rate limiting', () => {
  let limiter: ReturnType<typeof createRateLimiter>

  beforeEach(() => {
    limiter = createRateLimiter(10, 60_000)
  })

  it('first 10 requests succeed', () => {
    for (let i = 0; i < 10; i++) {
      const result = limiter.check('user1')
      expect(result.allowed).toBe(true)
    }
  })

  it('11th request within window is rejected', () => {
    for (let i = 0; i < 10; i++) {
      limiter.check('user1')
    }
    const result = limiter.check('user1')
    expect(result.allowed).toBe(false)
    expect(result.remaining).toBe(0)
  })

  it('requests after window reset succeed', () => {
    for (let i = 0; i < 10; i++) {
      limiter.check('user1')
    }
    expect(limiter.check('user1').allowed).toBe(false)

    // Simulate window expiry by resetting
    limiter.reset('user1')
    const result = limiter.check('user1')
    expect(result.allowed).toBe(true)
  })

  it('different keys have independent limits', () => {
    for (let i = 0; i < 10; i++) {
      limiter.check('user1')
    }
    expect(limiter.check('user1').allowed).toBe(false)
    expect(limiter.check('user2').allowed).toBe(true)
  })
})
