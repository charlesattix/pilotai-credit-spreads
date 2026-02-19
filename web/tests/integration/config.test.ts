/**
 * @vitest-environment node
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock fs to avoid needing real config.yaml
vi.mock('fs', async () => {
  const actual = await vi.importActual('fs')
  return {
    ...actual,
    promises: {
      ...(actual as any).promises,
      readFile: vi.fn().mockResolvedValue(`
tickers:
  - SPY
  - QQQ
strategy:
  min_dte: 20
  max_dte: 45
alpaca:
  api_key: real-secret-key
  api_secret: another-secret
alerts:
  telegram:
    bot_token: my-bot-token
    chat_id: my-chat-id
`),
      writeFile: vi.fn().mockResolvedValue(undefined),
    },
  }
})

import { GET, POST } from '@/app/api/config/route'

const fakeRequest = new Request('http://localhost/api/config')

describe('GET /api/config (integration)', () => {
  it('returns 200', async () => {
    const response = await GET(fakeRequest)
    expect(response.status).toBe(200)
  })

  it('strips api_key secrets', async () => {
    const data = await (await GET(fakeRequest)).json()
    expect(data.alpaca.api_key).toBe('***REDACTED***')
    expect(data.alpaca.api_secret).toBe('***REDACTED***')
  })

  it('strips telegram secrets', async () => {
    const data = await (await GET(fakeRequest)).json()
    expect(data.alerts.telegram.bot_token).toBe('***REDACTED***')
    expect(data.alerts.telegram.chat_id).toBe('***REDACTED***')
  })

  it('preserves non-secret fields', async () => {
    const data = await (await GET(fakeRequest)).json()
    expect(data.tickers).toEqual(['SPY', 'QQQ'])
    expect(data.strategy.min_dte).toBe(20)
  })
})

describe('POST /api/config (integration)', () => {
  it('rejects invalid config', async () => {
    const request = new Request('http://localhost/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy: { min_dte: 'invalid' } }),
    })
    const response = await POST(request)
    expect(response.status).toBe(400)
    const data = await response.json()
    expect(data.error).toBe('Validation failed')
  })

  it('accepts valid config', async () => {
    const request = new Request('http://localhost/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers: ['SPY'], strategy: { min_dte: 20 } }),
    })
    const response = await POST(request)
    expect(response.status).toBe(200)
    const data = await response.json()
    expect(data.success).toBe(true)
  })
})
