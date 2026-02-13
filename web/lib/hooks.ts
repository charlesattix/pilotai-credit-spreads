import useSWR from 'swr'

const fetcher = (url: string) => fetch(url).then(res => res.json())

export function useAlerts() {
  return useSWR('/api/alerts', fetcher, {
    refreshInterval: 60000,
    dedupingInterval: 30000,
  })
}

export function usePositions() {
  return useSWR('/api/positions', fetcher, {
    refreshInterval: 30000,
    dedupingInterval: 15000,
  })
}

export function usePaperTrades(userId: string = 'default') {
  return useSWR(`/api/paper-trades?userId=${userId}`, fetcher, {
    refreshInterval: 30000,
    dedupingInterval: 15000,
  })
}
