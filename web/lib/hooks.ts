import useSWR from 'swr'
import { useEffect, useRef } from 'react'
import { apiFetch } from '@/lib/api'
import type { AlertsResponse, Config, PaperTrade, PositionsSummary } from '@/lib/types'

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
  const encodedUserId = encodeURIComponent(userId)
  const result = useSWR<PaperTradesResponse>(`/api/paper-trades?userId=${encodedUserId}`, fetcher<PaperTradesResponse>, {
    refreshInterval: 120000,
    dedupingInterval: 30000,
    revalidateOnFocus: true,
  })

  // Trigger auto-close of expired/target-hit trades on each fetch, then re-fetch
  const hasRunAutoClose = useRef(false)
  useEffect(() => {
    if (!result.data || hasRunAutoClose.current) return
    const hasOpenTrades = result.data.trades?.some(t => t.status === 'open')
    if (!hasOpenTrades) return
    hasRunAutoClose.current = true
    apiFetch<{ closed: number }>(`/api/paper-trades?userId=${encodedUserId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-user-id': userId },
      body: JSON.stringify({ action: 'auto-close' }),
    }).then(res => {
      if (res.closed > 0) result.mutate()
    }).catch(() => {
      // Auto-close is best-effort
    }).finally(() => {
      // Allow re-run on next mount cycle
      setTimeout(() => { hasRunAutoClose.current = false }, 60000)
    })
  }, [result.data, encodedUserId, userId, result])

  return result
}

export function useConfig() {
  const { data, error, isLoading, mutate } = useSWR<Config>(
    '/api/config',
    fetcher<Config>,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60_000,
    }
  )
  return { config: data, error, isLoading, mutate }
}
