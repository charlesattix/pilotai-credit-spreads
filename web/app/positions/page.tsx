'use client'

import { useEffect, useState } from 'react'
import { Trade } from '@/lib/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import { logger } from '@/lib/logger'

export default function PositionsPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'open' | 'closed'>('open')

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const res = await fetch('/api/trades')
        const data = await res.json()
        setTrades(data || [])
      } catch (error) {
        logger.error('Failed to fetch trades', { error: String(error) })
      } finally {
        setLoading(false)
      }
    }

    fetchTrades()
  }, [])

  const openTrades = trades.filter(t => t.status === 'open')
  const closedTrades = trades.filter(t => t.status === 'closed')

  const totalPnL = closedTrades.reduce((sum, t) => sum + (t.pnl || 0), 0)

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-brand-purple border-t-transparent"></div>
      </div>
    )
  }

  const currentTrades = activeTab === 'open' ? openTrades : closedTrades

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-2">Trade History</h1>
        <p className="text-muted-foreground">View your open and closed positions</p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-lg border border-border p-6">
          <div className="text-sm text-muted-foreground mb-1">Total P&L</div>
          <div className={`text-3xl font-bold ${totalPnL >= 0 ? 'text-profit' : 'text-loss'}`}>
            {formatCurrency(totalPnL)}
          </div>
        </div>
        <div className="bg-white rounded-lg border border-border p-6">
          <div className="text-sm text-muted-foreground mb-1">Open Positions</div>
          <div className="text-3xl font-bold">{openTrades.length}</div>
        </div>
        <div className="bg-white rounded-lg border border-border p-6">
          <div className="text-sm text-muted-foreground mb-1">Closed Trades</div>
          <div className="text-3xl font-bold">{closedTrades.length}</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-lg border border-border">
        <div className="border-b border-border">
          <div className="flex gap-4 px-6">
            <button
              onClick={() => setActiveTab('open')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'open'
                  ? 'border-brand-purple text-brand-purple'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              Open ({openTrades.length})
            </button>
            <button
              onClick={() => setActiveTab('closed')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'closed'
                  ? 'border-brand-purple text-brand-purple'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              Closed ({closedTrades.length})
            </button>
          </div>
        </div>

        <div className="p-6">
          {currentTrades.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-muted-foreground">No {activeTab} positions</p>
            </div>
          ) : (
            <div className="space-y-4">
              {currentTrades.map((trade) => (
                <div
                  key={trade.id}
                  className="p-4 bg-secondary/30 rounded-lg hover:bg-secondary/50 transition-colors"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <h3 className="text-xl font-bold">{trade.ticker}</h3>
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        trade.type.includes('call')
                          ? 'bg-loss-light text-loss'
                          : 'bg-profit-light text-profit'
                      }`}>
                        {trade.type.replace(/_/g, ' ')}
                      </span>
                    </div>
                    {trade.pnl !== undefined && (
                      <div className={`text-xl font-bold ${trade.pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                        {formatCurrency(trade.pnl)}
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <div className="text-muted-foreground mb-1">Strikes</div>
                      <div className="font-medium">{trade.short_strike} / {trade.long_strike}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground mb-1">Entry Date</div>
                      <div className="font-medium">{formatDate(trade.entry_date)}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground mb-1">Credit</div>
                      <div className="font-medium text-profit">{formatCurrency(trade.credit)}</div>
                    </div>
                    {trade.exit_date && (
                      <div>
                        <div className="text-muted-foreground mb-1">Exit Date</div>
                        <div className="font-medium">{formatDate(trade.exit_date)}</div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
