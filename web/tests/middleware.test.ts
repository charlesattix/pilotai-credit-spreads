import { describe, it, expect, vi, beforeEach } from 'vitest'

// We test the middleware logic by importing it directly
// Need to mock NextRequest/NextResponse

const nextFn = vi.fn(() => ({ headers: new Map() }))

vi.mock('next/server', () => ({
  NextRequest: class {
    nextUrl: { pathname: string }
    headers: Map<string, string>
    cookies: { get: (name: string) => undefined }
    constructor(url: string, opts?: any) {
      this.nextUrl = { pathname: new URL(url).pathname }
      this.headers = new Map(Object.entries(opts?.headers || {}))
      this.cookies = { get: (_name: string) => undefined }
    }
  },
  NextResponse: {
    next: () => {
      const res = { headers: new Map<string, string>(), _type: 'next' } as any
      res.headers.set = (k: string, v: string) => res.headers.set ? Map.prototype.set.call(res.headers, k, v) : undefined
      return { headers: { set: vi.fn() }, _type: 'next' }
    },
    json: (body: any, init?: any) => ({ body, status: init?.status || 200, _type: 'json' }),
  },
}))

// Set env before import
const VALID_TOKEN = 'test-secret-token-123'

describe('middleware', () => {
  beforeEach(() => {
    vi.resetModules()
    process.env.API_AUTH_TOKEN = VALID_TOKEN
  })

  async function runMiddleware(pathname: string, token?: string) {
    // Re-import to get fresh module with current env
    const { middleware } = await import('@/middleware')
    const { NextRequest } = await import('next/server')
    const headers: Record<string, string> = {}
    if (token) headers['authorization'] = `Bearer ${token}`
    const req = new NextRequest(`http://localhost${pathname}`, { headers } as any)
    // NextRequest mock uses Map; patch .get
    req.headers.get = (key: string) => headers[key.toLowerCase()] || null
    return middleware(req)
  }

  it('protected route without token returns 401', async () => {
    const res = await runMiddleware('/api/config')
    expect((res as any).status).toBe(401)
  })

  it('protected route with wrong token returns 401', async () => {
    const res = await runMiddleware('/api/config', 'wrong-token')
    expect((res as any).status).toBe(401)
  })

  it('protected route with valid token passes through', async () => {
    const res = await runMiddleware('/api/config', VALID_TOKEN)
    expect((res as any)._type).toBe('next')
  })

  it('public paths bypass auth (/api/health)', async () => {
    const res = await runMiddleware('/api/health')
    expect((res as any)._type).toBe('next')
  })

  it('public paths bypass auth (/api/positions)', async () => {
    const res = await runMiddleware('/api/positions')
    expect((res as any)._type).toBe('next')
  })

  it('non-API routes bypass auth', async () => {
    const res = await runMiddleware('/dashboard')
    expect((res as any)._type).toBe('next')
  })

  it('allows all API requests when API_AUTH_TOKEN is not set', async () => {
    delete process.env.API_AUTH_TOKEN
    const res = await runMiddleware('/api/config')
    expect((res as any)._type).toBe('next')
  })
})
