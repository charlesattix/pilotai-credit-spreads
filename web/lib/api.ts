import type { AlertsResponse, Config } from '@/lib/types'

// Retry wrapper for API calls — retries on 500/503 with 1s delay, max 2 retries
// Authentication is handled via HttpOnly session cookies (set by /api/auth)
export async function apiFetch<T>(url: string, options?: RequestInit, retries = 2): Promise<T> {
  let lastError: Error | null = null
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, {
        cache: 'no-store',
        credentials: 'same-origin',
        ...options,
        headers: { ...options?.headers },
      })
      if (res.ok) return res.json()
      if ((res.status === 500 || res.status === 503) && attempt < retries) {
        await new Promise(r => setTimeout(r, 1000))
        continue
      }
      throw new Error(`API ${url} returned ${res.status}`)
    } catch (err) {
      lastError = err as Error
      if (attempt < retries) {
        await new Promise(r => setTimeout(r, 1000))
        continue
      }
    }
  }
  throw lastError || new Error(`API ${url} failed after retries`)
}

export async function fetchAlerts(): Promise<AlertsResponse> {
  return apiFetch<AlertsResponse>('/api/alerts')
}

export async function fetchConfig(): Promise<Config> {
  return apiFetch<Config>('/api/config')
}

export async function runScan(): Promise<AlertsResponse> {
  return apiFetch<AlertsResponse>('/api/scan', { method: 'POST' })
}
