/**
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { GET } from '@/app/api/alerts/route'

const fakeRequest = new Request('http://localhost/api/alerts')

describe('GET /api/alerts (integration)', () => {
  it('returns 200', async () => {
    const response = await GET(fakeRequest)
    expect(response.status).toBe(200)
  })

  it('returns alerts array', async () => {
    const data = await (await GET(fakeRequest)).json()
    expect(Array.isArray(data.alerts)).toBe(true)
    expect(Array.isArray(data.opportunities)).toBe(true)
  })

  it('returns count field', async () => {
    const data = await (await GET(fakeRequest)).json()
    expect(typeof data.count).toBe('number')
  })

  it('count matches opportunities length', async () => {
    const data = await (await GET(fakeRequest)).json()
    expect(data.count).toBe(data.opportunities.length)
  })

  it('alerts and opportunities are the same array', async () => {
    const data = await (await GET(fakeRequest)).json()
    expect(data.alerts).toEqual(data.opportunities)
  })
})
