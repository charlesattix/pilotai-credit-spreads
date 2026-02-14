/**
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import { GET } from '@/app/api/health/route'

describe('GET /api/health (integration)', () => {
  it('returns 200 with status ok', async () => {
    const response = await GET()
    expect(response.status).toBe(200)
    const data = await response.json()
    expect(data.status).toBe('ok')
  })

  it('includes timestamp', async () => {
    const data = await (await GET()).json()
    expect(data.timestamp).toBeDefined()
    expect(() => new Date(data.timestamp).toISOString()).not.toThrow()
  })

  it('includes version', async () => {
    const data = await (await GET()).json()
    expect(data.version).toBeDefined()
  })

  it('response has correct content-type', async () => {
    const response = await GET()
    expect(response.headers.get('content-type')).toContain('application/json')
  })
})
