'use client'

import { useState, useMemo, useCallback } from 'react'
import { StatsBar } from '@/components/layout/stats-bar'
import { AlertCard } from '@/components/alerts/alert-card'
import { AIChat } from '@/components/sidebar/ai-chat'
import { PerformanceCard } from '@/components/sidebar/performance-card'
import { Heatmap } from '@/components/sidebar/heatmap'
import { UpsellCard } from '@/components/sidebar/upsell-card'
import { MobileChatFAB } from '@/components/sidebar/mobile-chat'
import type { Alert } from '@/lib/types'
import LivePositions from '@/components/positions/live-positions'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { useAlerts, usePositions, usePaperTrades } from '@/lib/hooks'
import { PaperTrade } from '@/lib/types'

type FilterType = 'all' | 'bullish' | 'bearish' | 'neutral' | 'high-prob'

export default function HomePage() {
  const { data: alertsData, isLoading: alertsLoading, mutate: mutateAlerts } = useAlerts()
  const { data: positions } = usePositions()
  const { mutate: mutatePaperTrades } = usePaperTrades()

  const handlePaperTrade = () => {
    mutatePaperTrades()
  }
  const [filter, setFilter] = useState<FilterType>('all')
  const [scanning, setScanning] = useState(false)

  const alerts: Alert[] = alertsData?.alerts || alertsData?.opportunities || []

  const runScan = useCallback(async () => {
    setScanning(true)
    try {
      toast.info('Refreshing alerts...')
      await mutateAlerts()
      toast.success('Alerts refreshed! Scans run automatically every 30 minutes.')
    } catch {
      toast.error('Failed to refresh alerts. Please try again.')
    } finally {
      setScanning(false)
    }
  }, [mutateAlerts])

  const filteredAlerts = useMemo(() => alerts.filter(alert => {
    const t = (alert.type || '').toLowerCase()
    if (filter === 'bullish') return t.includes('put')
    if (filter === 'bearish') return t.includes('call')
    if (filter === 'neutral') return !t.includes('put') && !t.includes('call')
    if (filter === 'high-prob') return (alert.pop || 0) >= 70
    return true
  }), [alerts, filter])

  const avgPOP = useMemo(() =>
    alerts.length > 0 ? alerts.reduce((sum, a) => sum + (a.pop || 0), 0) / alerts.length : 0
  , [alerts])

  // Compute real stats from positions data
  const { closedTrades, winners, losers, realWinRate, avgWinnerPct, avgLoserPct, profitFactor } = useMemo(() => {
    const closedTrades: PaperTrade[] = positions?.closed_trades || []
    const winners = closedTrades.filter((t) => (t.realized_pnl || 0) > 0)
    const losers = closedTrades.filter((t) => (t.realized_pnl || 0) <= 0)
    const realWinRate = closedTrades.length > 0 ? (winners.length / closedTrades.length) * 100 : 0
    const avgWinnerPct = winners.length > 0 ? winners.reduce((s, t) => s + (t.realized_pnl || 0), 0) / winners.length : 0
    const avgLoserPct = losers.length > 0 ? losers.reduce((s, t) => s + (t.realized_pnl || 0), 0) / losers.length : 0
    const profitFactor = losers.length > 0 && avgLoserPct !== 0
      ? Math.abs(winners.reduce((s, t) => s + (t.realized_pnl || 0), 0) / losers.reduce((s, t) => s + (t.realized_pnl || 0), 0))
      : 0
    return { closedTrades, winners, losers, realWinRate, avgWinnerPct, avgLoserPct, profitFactor }
  }, [positions])

  if (alertsLoading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-brand-purple border-t-transparent"></div>
      </div>
    )
  }

  return (
    <>
      <StatsBar 
        alertsCount={alerts.length}
        avgPOP={avgPOP}
        winRate30d={closedTrades.length > 0 ? realWinRate : 0}
        avgReturn={closedTrades.length > 0 ? (closedTrades.reduce((s, t) => s + (t.realized_pnl || 0), 0) / closedTrades.length) : 0}
        alertsThisWeek={alerts.length}
      />

      <div className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-6">
        {/* Live System Positions — uses shared SWR data, no extra fetch */}
        <LivePositions data={positions?.open_positions ? {
          open_positions: positions.open_positions.map(p => ({
            ticker: p.ticker,
            type: p.type,
            short_strike: p.short_strike,
            long_strike: p.long_strike,
            contracts: p.contracts || 1,
            total_credit: (p.entry_credit || 0) * 100 * (p.contracts || 1),
            total_max_loss: p.max_loss || 0,
            unrealized_pnl: p.unrealized_pnl ?? 0,
            days_remaining: p.days_remaining ?? 0,
            days_held: 0,
            max_profit: p.max_profit || 0,
            pnl_pct: p.max_profit ? ((p.unrealized_pnl ?? 0) / p.max_profit) * 100 : 0,
            expiration: p.expiration,
            alpaca_status: p.alpaca_status,
          })),
          total_unrealized_pnl: positions.total_unrealized_pnl ?? 0,
          total_credit: positions.total_credit ?? 0,
          open_count: positions.open_count ?? 0,
          current_balance: positions.current_balance ?? 0,
          total_pnl: positions.total_pnl ?? 0,
          total_max_loss: positions.total_max_loss ?? 0,
        } : null} />

        <div className="flex gap-6">
          {/* Main Content */}
          <div className="flex-1">
            {/* Filter Tabs */}
            <div className="mb-6">
              <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-hide">
                <FilterPill 
                  active={filter === 'all'} 
                  onClick={() => setFilter('all')}
                >
                  All
                </FilterPill>
                <FilterPill 
                  active={filter === 'bullish'} 
                  onClick={() => setFilter('bullish')}
                >
                  Bullish
                </FilterPill>
                <FilterPill 
                  active={filter === 'bearish'} 
                  onClick={() => setFilter('bearish')}
                >
                  Bearish
                </FilterPill>
                <FilterPill 
                  active={filter === 'high-prob'} 
                  onClick={() => setFilter('high-prob')}
                >
                  High Prob
                </FilterPill>
                <div className="ml-auto flex items-center gap-2 shrink-0">
                  <button
                    onClick={runScan}
                    disabled={scanning}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-brand-purple hover:bg-brand-purple/5 rounded-lg transition-colors"
                  >
                    <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
                    {scanning ? 'Scanning...' : 'Refresh'}
                  </button>
                </div>
              </div>
            </div>

            {/* Alerts Feed */}
            {filteredAlerts.length === 0 ? (
              <div className="bg-white rounded-lg border border-border p-12 text-center">
                <p className="text-muted-foreground">
                  {filter === 'all' 
                    ? 'No alerts available. Scans run automatically every 30 minutes.' 
                    : `No ${filter === 'high-prob' ? 'high probability' : filter} alerts found. Try a different filter.`}
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {filteredAlerts.map((alert, idx) => (
                  <AlertCard key={`${alert.ticker}-${alert.type}-${alert.short_strike}-${alert.long_strike}`} alert={alert} isNew={idx < 2} onPaperTrade={handlePaperTrade} />
                ))}
              </div>
            )}
          </div>

          {/* Sidebar (desktop) */}
          <div className="hidden lg:block w-[340px] space-y-4">
            <AIChat />
            <PerformanceCard
              totalAlerts={positions?.total_trades || 0}
              winners={winners.length}
              losers={losers.length}
              winRate={realWinRate}
              avgWinner={avgWinnerPct}
              avgLoser={avgLoserPct}
              profitFactor={profitFactor}
            />
            <Heatmap />
            <UpsellCard />
          </div>
        </div>
      </div>

      {/* Mobile Chat FAB */}
      <MobileChatFAB />
    </>
  )
}

function FilterPill({ 
  active, 
  onClick, 
  children 
}: { 
  active: boolean
  onClick: () => void
  children: React.ReactNode 
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
        active
          ? 'bg-brand-purple text-white shadow-md'
          : 'bg-white text-muted-foreground border border-border hover:border-brand-purple/30'
      }`}
    >
      {children}
    </button>
  )
}
