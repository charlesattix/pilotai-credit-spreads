'use client'

import { TrendingUp, TrendingDown, Clock, DollarSign, Activity } from 'lucide-react'
import { formatCurrency } from '@/lib/utils'
import { Position } from '@/lib/types'

interface PositionsData {
  open_positions: Position[]
  total_unrealized_pnl: number
  total_credit: number
  open_count: number
  current_balance: number
  total_pnl: number
  total_max_loss: number
}

interface LivePositionsProps {
  data?: PositionsData | null
}

export default function LivePositions({ data }: LivePositionsProps) {
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
          <span className={`font-bold ${(data.total_unrealized_pnl || 0) >= 0 ? 'text-profit' : 'text-loss'}`}>
            {formatCurrency(data.total_unrealized_pnl || 0)} P&L
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
              <div className="flex items-center justify-between sm:justify-start gap-2 sm:gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs sm:text-sm font-bold">{pos.ticker}</span>
                  <span className={`text-[10px] sm:text-xs font-medium px-1.5 py-0.5 rounded ${isBullish ? 'bg-profit-light text-profit' : 'bg-loss-light text-loss'}`}>
                    {typeLabel}
                  </span>
                  {pos.alpaca_status && (
                    <span className={`text-[10px] sm:text-xs font-medium px-1.5 py-0.5 rounded ${
                      pos.alpaca_status === 'filled' ? 'bg-green-50 text-green-600' :
                      pos.alpaca_status === 'submitted' ? 'bg-yellow-50 text-yellow-600' :
                      'bg-gray-50 text-gray-500'
                    }`}>
                      Alpaca: {pos.alpaca_status}
                    </span>
                  )}
                </div>
                <span className="text-[10px] sm:text-xs text-muted-foreground">
                  ${pos.short_strike}/{pos.long_strike} × {pos.contracts}
                </span>
                <div className={`sm:hidden text-xs font-bold ml-auto ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatCurrency(pnl)}
                </div>
              </div>

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

              <div className="hidden sm:block text-right">
                <div className={`text-sm font-bold ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatCurrency(pnl)}
                </div>
                <div className="text-xs text-muted-foreground">
                  of ${(pos.max_profit ?? 0).toLocaleString()} max
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
            Credit: ${(data.total_credit || 0).toLocaleString()}
          </span>
          <span className="flex items-center gap-1">
            <Activity className="w-3 h-3" />
            Max Risk: ${(data.total_max_loss || 0).toLocaleString()}
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
