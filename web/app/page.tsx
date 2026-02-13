'use client'

import { useEffect, useState } from 'react'
import { StatsBar } from '@/components/layout/stats-bar'
import { AlertCard } from '@/components/alerts/alert-card'
import { AIChat } from '@/components/sidebar/ai-chat'
import { PerformanceCard } from '@/components/sidebar/performance-card'
import { Heatmap } from '@/components/sidebar/heatmap'
import { UpsellCard } from '@/components/sidebar/upsell-card'
import { MobileChatFAB } from '@/components/sidebar/mobile-chat'
import { Alert } from '@/lib/api'
import LivePositions from '@/components/positions/live-positions'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

type FilterType = 'all' | 'bullish' | 'bearish' | 'neutral' | 'high-prob'

interface PositionsData {
  closed_count: number
  win_rate: number
  total_trades: number
  closed_trades: Array<{ exit_pnl: number | null }>
}

export default function HomePage() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('all')
  const [scanning, setScanning] = useState(false)
  const [positions, setPositions] = useState<PositionsData | null>(null)

  const fetchAlerts = async () => {
    try {
      const res = await fetch('/api/alerts')
      const data = await res.json()
      setAlerts(data.alerts || data.opportunities || [])
    } catch (error) {
      console.error('Failed to fetch alerts:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchPositions = async () => {
    try {
      const res = await fetch('/api/positions')
      const data = await res.json()
      setPositions(data)
    } catch (error) {
      console.error('Failed to fetch positions:', error)
    }
  }

  useEffect(() => {
    fetchAlerts()
    fetchPositions()
    const interval = setInterval(fetchAlerts, 60000)
    return () => clearInterval(interval)
  }, [])

  const runScan = async () => {
    setScanning(true)
    toast.info('Refreshing alerts...')
    await fetchAlerts()
    toast.success('Alerts refreshed! Scans run automatically every 30 minutes.')
    setScanning(false)
  }

  const filteredAlerts = alerts.filter(alert => {
    const t = (alert.type || '').toLowerCase()
    if (filter === 'bullish') return t.includes('put')
    if (filter === 'bearish') return t.includes('call')
    if (filter === 'neutral') return !t.includes('put') && !t.includes('call')
    if (filter === 'high-prob') return (alert.pop || 0) >= 70
    return true
  })

  const avgPOP = alerts.length > 0 ? alerts.reduce((sum, a) => sum + (a.pop || 0), 0) / alerts.length : 0

  // Compute real stats from positions data
  const closedTrades = positions?.closed_trades || []
  const winners = closedTrades.filter(t => (t.exit_pnl || 0) > 0)
  const losers = closedTrades.filter(t => (t.exit_pnl || 0) <= 0)
  const realWinRate = closedTrades.length > 0 ? (winners.length / closedTrades.length) * 100 : 0
  const avgWinnerPct = winners.length > 0 ? winners.reduce((s, t) => s + (t.exit_pnl || 0), 0) / winners.length : 0
  const avgLoserPct = losers.length > 0 ? losers.reduce((s, t) => s + (t.exit_pnl || 0), 0) / losers.length : 0
  const profitFactor = losers.length > 0 && avgLoserPct !== 0
    ? Math.abs(winners.reduce((s, t) => s + (t.exit_pnl || 0), 0) / losers.reduce((s, t) => s + (t.exit_pnl || 0), 0))
    : 0

  if (loading) {
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
        avgReturn={closedTrades.length > 0 ? (closedTrades.reduce((s, t) => s + (t.exit_pnl || 0), 0) / closedTrades.length) : 0}
        alertsThisWeek={alerts.length}
      />

      <div className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-6">
        {/* Live System Positions */}
        <LivePositions />

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
                  <AlertCard key={idx} alert={alert} isNew={idx < 2} />
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
