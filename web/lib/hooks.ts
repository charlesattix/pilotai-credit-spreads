import useSWR from 'swr'

const AUTH_TOKEN = typeof window !== 'undefined'
  ? process.env.NEXT_PUBLIC_API_AUTH_TOKEN
  : undefined

const fetcher = async (url: string) => {
  const headers: Record<string, string> = {}
  if (AUTH_TOKEN) {
    headers['Authorization'] = `Bearer ${AUTH_TOKEN}`
  }
  const res = await fetch(url, { headers })
  if (!res.ok) throw new Error(`API ${url} returned ${res.status}`)
  return res.json()
}

export function useAlerts() {
  return useSWR('/api/alerts', fetcher, {
    refreshInterval: 300000,
    dedupingInterval: 60000,
    revalidateOnFocus: true,
  })
}

export function usePositions() {
  return useSWR('/api/positions', fetcher, {
    refreshInterval: 300000,
    dedupingInterval: 60000,
    revalidateOnFocus: true,
  })
}

export function usePaperTrades(userId: string = 'default') {
  return useSWR(`/api/paper-trades?userId=${userId}`, fetcher, {
    refreshInterval: 120000,
    dedupingInterval: 30000,
    revalidateOnFocus: true,
  })
}
