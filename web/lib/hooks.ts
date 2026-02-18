import useSWR from 'swr'
import { apiFetch } from '@/lib/api'
import type { AlertsResponse, PaperTrade, PositionsSummary } from '@/lib/types'

function fetcher<T>(url: string): Promise<T> {
  return apiFetch<T>(url)
}

export function useAlerts() {
  return useSWR<AlertsResponse>('/api/alerts', fetcher<AlertsResponse>, {
    refreshInterval: 300000,
    dedupingInterval: 60000,
    revalidateOnFocus: true,
  })
}

export function usePositions() {
  return useSWR<PositionsSummary>('/api/positions', fetcher<PositionsSummary>, {
    refreshInterval: 60000,
    dedupingInterval: 15000,
    revalidateOnFocus: true,
  })
}

interface PaperTradesResponse {
  trades: PaperTrade[]
  stats: {
    total_trades: number
    open_trades: number
    closed_trades: number
    winners: number
    losers: number
    win_rate: number
    total_realized_pnl: number
    total_unrealized_pnl: number
    total_pnl: number
    balance: number
    starting_balance: number
    disabled?: boolean
  }
  message?: string
}

export function usePaperTrades(userId: string = 'default') {
  return useSWR<PaperTradesResponse>(`/api/paper-trades?userId=${userId}`, fetcher<PaperTradesResponse>, {
    refreshInterval: 120000,
    dedupingInterval: 30000,
    revalidateOnFocus: true,
  })
}
