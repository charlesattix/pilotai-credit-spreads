'use client'

import { useEffect, useState } from 'react'
import { formatCurrency } from '@/lib/utils'
import { PlayCircle, TrendingUp, TrendingDown, BarChart3 } from 'lucide-react'
import { toast } from 'sonner'
import dynamic from 'next/dynamic'
import { logger } from '@/lib/logger'
import { apiFetch } from '@/lib/api'
import { BacktestResult } from '@/lib/types'

// Lazy load recharts to prevent SSR issues
const LazyCharts = dynamic(() => import('@/components/backtest/charts'), {
  ssr: false,
  loading: () => <div className="h-[300px] flex items-center justify-center text-muted-foreground">Loading charts...</div>
})

export default function BacktestPage() {
  const [results, setResults] = useState<BacktestResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchResults = async () => {
      try {
        const data = await apiFetch<BacktestResult>('/api/backtest')
        setResults(data)
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        logger.error('Failed to fetch backtest results', { error: message })
        setError(message)
      } finally {
        setLoading(false)
      }
    }
    fetchResults()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-brand-purple border-t-transparent"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="bg-white rounded-lg border border-loss/30 p-12 text-center">
          <p className="text-loss font-medium mb-2">Failed to load backtest results</p>
          <p className="text-muted-foreground text-sm mb-4">{error}</p>
          <button
            onClick={() => { setError(null); setLoading(true); window.location.reload() }}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-brand-purple hover:opacity-90 transition-opacity"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const hasData = results && results.total_trades > 0

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold mb-2">System Performance</h1>
          <p className="text-muted-foreground">Backtesting & historical analysis</p>
        </div>
        <button
          onClick={() => toast.info('Backtests run automatically. Results appear here when available.')}
          className="flex items-center gap-2 px-6 py-3 bg-gradient-brand text-white font-medium rounded-lg hover:opacity-90 transition-opacity"
        >
          <PlayCircle className="w-5 h-5" />
          Run Backtest
        </button>
      </div>

      {!hasData ? (
        <div className="bg-white rounded-lg border border-border p-12 text-center">
          <div className="text-4xl mb-3">📊</div>
          <h3 className="text-lg font-semibold mb-1">No backtest data yet</h3>
          <p className="text-muted-foreground text-sm">
            System performance data will appear here once trades are executed and tracked. First scan starts at 9:45 AM ET.
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-6">
            <StatCard label="Win Rate" value={`${(results.win_rate || 0).toFixed(1)}%`} sub={`${results.winning_trades}W / ${results.losing_trades}L`} icon={<TrendingUp className="w-4 h-4 text-profit" />} />
            <StatCard label="Total P&L" value={formatCurrency(results.total_pnl || 0)} sub="Net profit/loss" color={results.total_pnl >= 0 ? 'text-profit' : 'text-loss'} />
            <StatCard label="Sharpe Ratio" value={(results.sharpe_ratio || 0).toFixed(2)} sub="Risk-adjusted return" icon={<BarChart3 className="w-4 h-4 text-brand-purple" />} />
            <StatCard label="Max Drawdown" value={formatCurrency(results.max_drawdown || 0)} sub={`${(results.max_drawdown_pct || 0).toFixed(1)}%`} color="text-loss" icon={<TrendingDown className="w-4 h-4 text-loss" />} />
          </div>

          <LazyCharts results={results} />
        </>
      )}
    </div>
  )
}

function StatCard({ label, value, sub, color, icon }: { label: string; value: string; sub: string; color?: string; icon?: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-border p-6">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-muted-foreground">{label}</div>
        {icon}
      </div>
      <div className={`text-3xl font-bold ${color || ''}`}>{value}</div>
      <div className="text-xs text-muted-foreground mt-1">{sub}</div>
    </div>
  )
}
