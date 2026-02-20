'use client'

import { useEffect, useState } from 'react'
import { formatCurrency } from '@/lib/utils'
import { TrendingUp, TrendingDown, BarChart3, Target, Activity } from 'lucide-react'
import { toast } from 'sonner'
import dynamic from 'next/dynamic'
import { logger } from '@/lib/logger'
import { apiFetch } from '@/lib/api'
import type { BacktestRunResult, BacktestResult } from '@/lib/types'
import { BacktestForm } from '@/components/backtest/backtest-form'
import { TradeTable } from '@/components/backtest/trade-table'

// Lazy load chart components to prevent SSR issues
const LazyCharts = dynamic(() => import('@/components/backtest/charts'), {
  ssr: false,
  loading: () => <div className="h-[300px] flex items-center justify-center text-muted-foreground">Loading charts...</div>
})

const LazyTvChart = dynamic(() => import('@/components/backtest/tv-chart').then(m => ({ default: m.TvChart })), {
  ssr: false,
  loading: () => <div className="h-[400px] flex items-center justify-center text-muted-foreground bg-white rounded-lg border border-border">Loading chart...</div>
})

export default function BacktestPage() {
  const [results, setResults] = useState<BacktestRunResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ticker, setTicker] = useState('SPY')
  const [days, setDays] = useState(365)

  // Load existing results on mount
  useEffect(() => {
    const fetchExisting = async () => {
      try {
        const data = await apiFetch<BacktestResult>('/api/backtest')
        if (data && data.total_trades > 0) {
          // Map old format to new (BacktestResult → BacktestRunResult)
          setResults({
            ...data,
            starting_capital: (data as unknown as BacktestRunResult).starting_capital || 100000,
            ending_capital: (data as unknown as BacktestRunResult).ending_capital || 100000 + (data.total_pnl || 0),
            return_pct: (data as unknown as BacktestRunResult).return_pct || 0,
            bull_put_trades: (data as unknown as BacktestRunResult).bull_put_trades || data.total_trades,
            bear_call_trades: (data as unknown as BacktestRunResult).bear_call_trades || 0,
            bull_put_win_rate: (data as unknown as BacktestRunResult).bull_put_win_rate || data.win_rate,
            bear_call_win_rate: (data as unknown as BacktestRunResult).bear_call_win_rate || 0,
            trades: (data as unknown as BacktestRunResult).trades || [],
          })
        }
      } catch (err) {
        // No existing results — that's fine
        logger.info('No existing backtest results', { error: String(err) })
      } finally {
        setInitialLoading(false)
      }
    }
    fetchExisting()
  }, [])

  const handleRun = async (selectedTicker: string, selectedDays: number) => {
    setTicker(selectedTicker)
    setDays(selectedDays)
    setLoading(true)
    setError(null)

    try {
      const data = await apiFetch<BacktestRunResult & { success: boolean; error?: string }>(
        '/api/backtest/run',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker: selectedTicker, days: selectedDays }),
        },
        0, // no retries — backtest takes a while
      )

      if (data.success === false) {
        throw new Error(data.error || 'Backtest failed')
      }

      setResults(data)
      toast.success(`Backtest complete: ${data.total_trades} trades over ${selectedDays} days`)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      logger.error('Backtest run failed', { error: message })
      setError(message)
      toast.error('Backtest failed: ' + message)
    } finally {
      setLoading(false)
    }
  }

  if (initialLoading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-brand-purple border-t-transparent"></div>
      </div>
    )
  }

  const hasData = results && results.total_trades > 0
  const hasTrades = hasData && results.trades && results.trades.length > 0

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold mb-1">Backtest</h1>
        <p className="text-muted-foreground">Test credit spread strategies against real historical options data</p>
      </div>

      {/* Form */}
      <BacktestForm onRun={handleRun} loading={loading} />

      {/* Error */}
      {error && !loading && (
        <div className="bg-loss/5 border border-loss/20 rounded-lg p-4">
          <p className="text-loss text-sm font-medium">Backtest failed</p>
          <p className="text-loss/70 text-xs mt-1">{error}</p>
        </div>
      )}

      {/* Results */}
      {hasData && (
        <>
          {/* Key Metrics */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
            <StatCard
              label="Win Rate"
              value={`${(results.win_rate || 0).toFixed(1)}%`}
              sub={`${results.winning_trades}W / ${results.losing_trades}L`}
              icon={<Target className="w-4 h-4 text-profit" />}
            />
            <StatCard
              label="Total Return"
              value={`${(results.return_pct || 0) >= 0 ? '+' : ''}${(results.return_pct || 0).toFixed(2)}%`}
              sub={formatCurrency(results.total_pnl || 0)}
              color={results.total_pnl >= 0 ? 'text-profit' : 'text-loss'}
            />
            <StatCard
              label="Sharpe Ratio"
              value={(results.sharpe_ratio || 0).toFixed(2)}
              sub="Risk-adjusted return"
              icon={<BarChart3 className="w-4 h-4 text-brand-purple" />}
            />
            <StatCard
              label="Max Drawdown"
              value={`${(results.max_drawdown || 0).toFixed(2)}%`}
              sub="Peak-to-trough"
              color="text-loss"
              icon={<TrendingDown className="w-4 h-4 text-loss" />}
            />
            <StatCard
              label="Profit Factor"
              value={results.profit_factor === Infinity ? '∞' : (results.profit_factor || 0).toFixed(2)}
              sub={`Avg win ${formatCurrency(results.avg_win)} / loss ${formatCurrency(results.avg_loss)}`}
              icon={<Activity className="w-4 h-4 text-brand-purple" />}
            />
          </div>

          {/* Strategy Breakdown */}
          {(results.bull_put_trades > 0 || results.bear_call_trades > 0) && (
            <div className="grid gap-4 md:grid-cols-2">
              {results.bull_put_trades > 0 && (
                <div className="bg-white rounded-lg border border-border p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-profit" />
                      <span className="font-semibold text-sm">Bull Put Spreads</span>
                    </div>
                    <span className="text-sm text-muted-foreground">{results.bull_put_trades} trades</span>
                  </div>
                  <div className="mt-2">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-gray-100 rounded-full h-2">
                        <div
                          className="bg-profit rounded-full h-2 transition-all"
                          style={{ width: `${Math.min(results.bull_put_win_rate, 100)}%` }}
                        />
                      </div>
                      <span className="text-sm font-medium">{results.bull_put_win_rate.toFixed(1)}%</span>
                    </div>
                  </div>
                </div>
              )}
              {results.bear_call_trades > 0 && (
                <div className="bg-white rounded-lg border border-border p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <TrendingDown className="w-4 h-4 text-loss" />
                      <span className="font-semibold text-sm">Bear Call Spreads</span>
                    </div>
                    <span className="text-sm text-muted-foreground">{results.bear_call_trades} trades</span>
                  </div>
                  <div className="mt-2">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-gray-100 rounded-full h-2">
                        <div
                          className="bg-profit rounded-full h-2 transition-all"
                          style={{ width: `${Math.min(results.bear_call_win_rate, 100)}%` }}
                        />
                      </div>
                      <span className="text-sm font-medium">{results.bear_call_win_rate.toFixed(1)}%</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TradingView Chart */}
          <LazyTvChart ticker={ticker} days={days} />

          {/* Equity Curve + Distribution Charts */}
          <LazyCharts results={results as unknown as import('@/lib/types').BacktestResult} />

          {/* Trade Table */}
          {hasTrades && <TradeTable trades={results.trades} />}
        </>
      )}

      {/* Empty State */}
      {!hasData && !loading && !error && (
        <div className="bg-white rounded-lg border border-border p-12 text-center">
          <div className="text-4xl mb-3">📊</div>
          <h3 className="text-lg font-semibold mb-1">No backtest results yet</h3>
          <p className="text-muted-foreground text-sm">
            Select a ticker and lookback period above, then click Run Backtest to analyze strategy performance.
          </p>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, sub, color, icon }: {
  label: string
  value: string
  sub: string
  color?: string
  icon?: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-lg border border-border p-5">
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</div>
        {icon}
      </div>
      <div className={`text-2xl font-bold ${color || ''}`}>{value}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>
    </div>
  )
}
