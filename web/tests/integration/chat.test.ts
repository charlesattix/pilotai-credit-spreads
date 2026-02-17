/**
 * @vitest-environment node
 */
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/database', () => ({
  checkRateLimit: () => true,
}))

import { POST } from '@/app/api/chat/route'

function makeRequest(body: any): Request {
  return new Request('http://localhost/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-forwarded-for': '127.0.0.1' },
    body: JSON.stringify(body),
  })
}

describe('POST /api/chat (integration)', () => {
  it('rejects empty messages', async () => {
    const response = await POST(makeRequest({ messages: [] }))
    expect(response.status).toBe(400)
  })

  it('rejects missing messages', async () => {
    const response = await POST(makeRequest({}))
    expect(response.status).toBe(400)
  })

  it('returns fallback reply without API key', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'hello' }],
    }))
    expect(response.status).toBe(200)
    const data = await response.json()
    expect(data.reply).toBeDefined()
    expect(data.fallback).toBe(true)
  })

  it('fallback handles credit spread question', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'what is a credit spread?' }],
    }))
    const data = await response.json()
    expect(data.reply).toContain('Credit spread')
  })

  it('fallback handles delta question', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'explain delta' }],
    }))
    const data = await response.json()
    expect(data.reply).toContain('Delta')
  })

  it('fallback handles risk question', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'how much risk per trade' }],
    }))
    const data = await response.json()
    expect(data.reply).toContain('Risk')
  })

  it('fallback handles paper trading question', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'how do i get started' }],
    }))
    const data = await response.json()
    expect(data.reply).toContain('paper trading')
  })

  it('fallback handles market question with alerts', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'what about spy?' }],
      alerts: [{ ticker: 'SPY', type: 'bull_put', pop: 75, score: 8 }],
    }))
    const data = await response.json()
    expect(data.reply).toContain('1 active alert')
  })

  it('fallback handles pop question', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'what is probability of profit' }],
    }))
    const data = await response.json()
    expect(data.reply).toContain('Probability of Profit')
  })

  it('returns generic reply for unknown question', async () => {
    const response = await POST(makeRequest({
      messages: [{ role: 'user', content: 'random gibberish xyz123' }],
    }))
    const data = await response.json()
    expect(data.reply).toBeDefined()
    expect(typeof data.reply).toBe('string')
  })
})
