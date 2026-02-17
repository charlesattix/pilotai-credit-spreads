'use client'

import { useState } from 'react'
import { ChevronDown, ChevronUp, Sparkles, TrendingUp, Loader2 } from 'lucide-react'
import { Alert } from '@/lib/types'
import { apiFetch } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import { toast } from 'sonner'
import { getUserId, PAPER_TRADING_ENABLED } from '@/lib/user-id'

interface AlertCardProps {
  alert: Alert
  isNew?: boolean
  onPaperTrade?: (alert: Alert) => void
}

export function AlertCard({ alert, isNew = false, onPaperTrade }: AlertCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [trading, setTrading] = useState(false)
  const [traded, setTraded] = useState(false)

  const isBullish = alert.type.includes('put')
  const isBearish = alert.type.includes('call')

  const typeLabel = isBullish ? 'Bullish' : isBearish ? 'Bearish' : 'Neutral'
  const typeIcon = isBullish ? '▲' : isBearish ? '▼' : '◆'
  const typeColor = isBullish ? 'bg-profit-light text-profit border-profit/30' : 
                    isBearish ? 'bg-loss-light text-loss border-loss/30' : 
                    'bg-neutral-light text-neutral border-neutral/30'

  const confidenceLevel = alert.score >= 70 ? 'High' : alert.score >= 60 ? 'Medium' : 'Low'
  const confidenceColor = alert.score >= 70 ? 'text-profit' : alert.score >= 60 ? 'text-neutral' : 'text-loss'

  const handlePaperTrade = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (traded || trading) return
    
    setTrading(true)
    try {
      const data = await apiFetch<{ success: boolean; trade?: unknown; error?: string }>('/api/paper-trades', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alert, contracts: 1, userId: getUserId() }),
      })

      if (data.success) {
        setTraded(true)
        toast.success(`Paper trade opened: ${alert.ticker} ${typeLabel} spread`, {
          description: `Credit: ${formatCurrency(alert.credit * 100)} • Track it on My Trades →`,
          action: { label: 'View', onClick: () => window.location.href = '/my-trades' },
        })
        onPaperTrade?.(alert)
      } else {
        toast.error('Failed to open trade')
      }
    } catch {
      toast.error('Failed to open paper trade')
    } finally {
      setTrading(false)
    }
  }

  return (
    <div 
      className={`bg-white rounded-lg border border-border hover:border-brand-purple/30 hover:shadow-lg transition-all cursor-pointer ${
        isNew ? 'border-l-4 border-l-brand-purple' : ''
      }`}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Header */}
      <div className="p-3 sm:p-4 border-b border-border">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-1.5 sm:gap-2">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 sm:py-1 rounded-full text-[10px] sm:text-xs font-medium border ${typeColor}`}>
              {typeIcon} {typeLabel}
            </span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 sm:py-1 rounded-full text-[10px] sm:text-xs font-medium bg-brand-purple/10 text-brand-purple border border-brand-purple/30">
              <Sparkles className="w-3 h-3" />
              AI-Powered
            </span>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <span className="text-[10px] sm:text-xs text-muted-foreground">{formatDate(alert.expiration)}</span>
            <span className={`text-[10px] sm:text-xs font-medium ${confidenceColor}`}>
              {confidenceLevel} Confidence
            </span>
          </div>
        </div>

        {/* Main Content */}
        <div className="mb-3">
          <div className="flex items-baseline gap-2 mb-1">
            <h3 className="text-xl sm:text-2xl font-bold">{alert.ticker}</h3>
            <span className="text-base sm:text-lg text-muted-foreground">${alert.current_price.toFixed(2)}</span>
          </div>
          <p className="text-xs sm:text-sm text-muted-foreground">
            {alert.type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())} • {alert.dte} days to expiration
          </p>
        </div>

        {/* Stats Bar + Paper Trade Button */}
        <div className="flex flex-col sm:flex-row sm:items-end gap-3 sm:gap-4">
          <div className="grid grid-cols-3 gap-3 sm:gap-4 flex-1">
            <div>
              <div className="text-[10px] sm:text-xs text-muted-foreground mb-0.5 sm:mb-1">Max Profit</div>
              <div className="text-base sm:text-lg font-bold text-profit">{formatCurrency(alert.max_profit)}</div>
            </div>
            <div>
              <div className="text-[10px] sm:text-xs text-muted-foreground mb-0.5 sm:mb-1">Max Loss</div>
              <div className="text-base sm:text-lg font-bold text-loss">{formatCurrency(alert.max_loss)}</div>
            </div>
            <div>
              <div className="text-[10px] sm:text-xs text-muted-foreground mb-0.5 sm:mb-1">Prob of Profit</div>
              <div className="flex items-center gap-1.5 sm:gap-2">
                <div className="flex-1 h-2 bg-secondary rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-profit rounded-full transition-all"
                    style={{ width: `${alert.pop}%` }}
                  ></div>
                </div>
                <span className="text-base sm:text-lg font-bold">{alert.pop.toFixed(0)}%</span>
              </div>
            </div>
          </div>

          {/* Paper Trade Button */}
          {PAPER_TRADING_ENABLED && <button
            onClick={handlePaperTrade}
            disabled={trading || traded}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-all whitespace-nowrap ${
              traded 
                ? 'bg-profit/10 text-profit border border-profit/30 cursor-default'
                : trading
                ? 'bg-gray-100 text-gray-400 cursor-wait'
                : 'text-white shadow-md hover:shadow-lg hover:scale-[1.02] active:scale-[0.98]'
            }`}
            style={!traded && !trading ? { background: 'linear-gradient(135deg, #9B6DFF, #E84FAD)' } : undefined}
          >
            {trading ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Opening...</>
            ) : traded ? (
              <><TrendingUp className="w-4 h-4" /> Traded ✓</>
            ) : (
              <><TrendingUp className="w-4 h-4" /> Paper Trade</>
            )}
          </button>}
        </div>
      </div>

      {/* Expandable Section */}
      {expanded && (
        <div className="p-4 bg-secondary/30">
          <div className="space-y-4">
            {/* Trade Legs */}
            <div>
              <h4 className="text-sm font-semibold mb-2">Trade Legs</h4>
              <div className="space-y-2">
                <div className="flex items-center justify-between p-2 bg-white rounded-lg">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-loss-light text-loss text-xs font-medium rounded">Sell</span>
                    <span className="text-sm font-medium">${alert.short_strike} Strike</span>
                  </div>
                  <span className="text-sm text-muted-foreground">Delta: {alert.short_delta.toFixed(3)}</span>
                </div>
                <div className="flex items-center justify-between p-2 bg-white rounded-lg">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 bg-profit-light text-profit text-xs font-medium rounded">Buy</span>
                    <span className="text-sm font-medium">${alert.long_strike} Strike</span>
                  </div>
                  <span className="text-sm text-muted-foreground">Width: ${alert.spread_width}</span>
                </div>
              </div>
            </div>

            {/* Details Grid */}
            <div className="grid grid-cols-2 gap-3">
              <div className="p-2 bg-white rounded-lg">
                <div className="text-xs text-muted-foreground">Net Premium</div>
                <div className="text-sm font-semibold text-profit">{formatCurrency(alert.credit)}</div>
              </div>
              <div className="p-2 bg-white rounded-lg">
                <div className="text-xs text-muted-foreground">Profit Target</div>
                <div className="text-sm font-semibold">{formatCurrency(alert.profit_target)}</div>
              </div>
              <div className="p-2 bg-white rounded-lg">
                <div className="text-xs text-muted-foreground">Stop Loss</div>
                <div className="text-sm font-semibold">{formatCurrency(alert.stop_loss)}</div>
              </div>
              <div className="p-2 bg-white rounded-lg">
                <div className="text-xs text-muted-foreground">Risk/Reward</div>
                <div className="text-sm font-semibold">{alert.risk_reward.toFixed(2)}</div>
              </div>
            </div>

            {/* Why This Trade */}
            <div>
              <h4 className="text-sm font-semibold mb-2">Why This Trade?</h4>
              <ul className="space-y-1 text-sm text-muted-foreground">
                <li>• High probability of profit ({alert.pop.toFixed(1)}%)</li>
                <li>• Optimal delta positioning at {alert.short_delta.toFixed(3)}</li>
                <li>• {alert.dte} days provides adequate time decay</li>
                <li>• Risk/reward ratio of {alert.risk_reward.toFixed(2)}</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Expand/Collapse Hint */}
      <div className="px-4 py-2 border-t border-border bg-secondary/10 flex items-center justify-center gap-2 text-xs text-muted-foreground">
        {expanded ? (
          <>
            <ChevronUp className="w-4 h-4" />
            Click to collapse
          </>
        ) : (
          <>
            <ChevronDown className="w-4 h-4" />
            Click for details
          </>
        )}
      </div>
    </div>
  )
}
