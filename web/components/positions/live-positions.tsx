'use client'

import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, Clock, DollarSign, Activity } from 'lucide-react'

interface Position {
  ticker: string
  type: string
  short_strike: number
  long_strike: number
  contracts: number
  total_credit: number
  total_max_loss: number
  unrealized_pnl: number
  days_remaining: number
  days_held: number
  max_profit: number
  pnl_pct: number
  expiration: string
}

interface PositionsData {
  open_positions: Position[]
  total_unrealized_pnl: number
  total_credit: number
  open_count: number
  current_balance: number
  total_pnl: number
  total_max_loss: number
}

function formatCurrency(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

export default function LivePositions() {
  const [data, setData] = useState<PositionsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchPositions = async () => {
      try {
        const res = await fetch('/api/positions')
        const json = await res.json()
        setData(json)
      } catch (err) {
        console.error('Failed to fetch positions:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchPositions()
    const interval = setInterval(fetchPositions, 15000) // refresh every 15s
    return () => clearInterval(interval)
  }, [])

  if (loading) return null
  if (!data || data.open_count === 0) return null

  return (
    <div className="bg-white rounded-xl border border-border p-3 sm:p-4 mb-4 sm:mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <h3 className="font-bold text-xs sm:text-sm uppercase tracking-wide text-muted-foreground">Live System Positions</h3>
        </div>
        <div className="flex items-center gap-2 sm:gap-4 text-xs sm:text-sm">
          <span className="text-muted-foreground">{data.open_count} open</span>
          <span className={`font-bold ${data.total_unrealized_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
            {formatCurrency(data.total_unrealized_pnl)} P&L
          </span>
        </div>
      </div>

      {/* Positions Grid */}
      <div className="space-y-2">
        {data.open_positions.map((pos, idx) => {
          const isBullish = pos.type.includes('put')
          const typeLabel = isBullish ? 'Bull Put' : 'Bear Call'
          const pnl = pos.unrealized_pnl || 0
          const pnlPct = pos.pnl_pct || 0
          const progressWidth = Math.min(100, Math.abs(pnlPct))

          return (
            <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between py-2 px-2 sm:px-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors gap-1 sm:gap-0">
              {/* Top row on mobile / Left on desktop */}
              <div className="flex items-center justify-between sm:justify-start gap-2 sm:gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs sm:text-sm font-bold">{pos.ticker}</span>
                  <span className={`text-[10px] sm:text-xs font-medium px-1.5 py-0.5 rounded ${isBullish ? 'bg-profit-light text-profit' : 'bg-loss-light text-loss'}`}>
                    {typeLabel}
                  </span>
                </div>
                <span className="text-[10px] sm:text-xs text-muted-foreground">
                  ${pos.short_strike}/{pos.long_strike} × {pos.contracts}
                </span>
                {/* Mobile P&L inline */}
                <div className={`sm:hidden text-xs font-bold ml-auto ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatCurrency(pnl)}
                </div>
              </div>

              {/* Progress bar row */}
              <div className="flex items-center gap-2 flex-1 sm:mx-4 max-w-full sm:max-w-[200px]">
                <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${pnl >= 0 ? 'bg-profit' : 'bg-loss'}`}
                    style={{ width: `${progressWidth}%` }}
                  />
                </div>
                <span className="text-[10px] sm:text-xs text-muted-foreground whitespace-nowrap">
                  {pos.days_remaining}d left
                </span>
              </div>

              {/* Right: P&L (desktop only) */}
              <div className="hidden sm:block text-right">
                <div className={`text-sm font-bold ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatCurrency(pnl)}
                </div>
                <div className="text-xs text-muted-foreground">
                  of ${pos.max_profit.toLocaleString()} max
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer Summary */}
      <div className="flex flex-wrap items-center justify-between mt-3 pt-3 border-t border-border gap-2">
        <div className="flex items-center gap-3 sm:gap-4 text-[10px] sm:text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <DollarSign className="w-3 h-3" />
            Credit: ${data.total_credit.toLocaleString()}
          </span>
          <span className="flex items-center gap-1">
            <Activity className="w-3 h-3" />
            Max Risk: ${data.total_max_loss?.toLocaleString() || '0'}
          </span>
        </div>
        <a
          href="/paper-trading"
          className="text-xs font-medium text-brand-purple hover:underline"
        >
          View Full Results →
        </a>
      </div>
    </div>
  )
}
