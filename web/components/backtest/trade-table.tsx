'use client'

import { useState } from 'react'
import { formatCurrency, formatDate } from '@/lib/utils'
import { ChevronDown, ChevronUp, ArrowUpDown } from 'lucide-react'
import type { BacktestTradeRecord } from '@/lib/types'

interface TradeTableProps {
  trades: BacktestTradeRecord[]
}

type SortKey = 'entry_date' | 'pnl' | 'return_pct' | 'credit'
type SortDir = 'asc' | 'desc'

export function TradeTable({ trades }: TradeTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('entry_date')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [filter, setFilter] = useState<'all' | 'winners' | 'losers'>('all')

  const filtered = trades.filter((t) => {
    if (filter === 'winners') return t.pnl > 0
    if (filter === 'losers') return t.pnl < 0
    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    const aVal = a[sortKey] ?? 0
    const bVal = b[sortKey] ?? 0
    if (typeof aVal === 'string' && typeof bVal === 'string') {
      return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
    }
    return sortDir === 'asc' ? Number(aVal) - Number(bVal) : Number(bVal) - Number(aVal)
  })

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return <ArrowUpDown className="w-3 h-3 text-gray-300" />
    return sortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
  }

  const reasonLabel = (reason: string) => {
    switch (reason) {
      case 'profit_target': return 'Profit Target'
      case 'stop_loss': return 'Stop Loss'
      case 'expiration_profit': return 'Expired (Win)'
      case 'expiration_loss': return 'Expired (Loss)'
      case 'backtest_end': return 'End of Test'
      default: return reason
    }
  }

  const typeLabel = (type: string) => {
    if (type === 'bull_put_spread') return 'Bull Put'
    if (type === 'bear_call_spread') return 'Bear Call'
    return type
  }

  return (
    <div className="bg-white rounded-lg border border-border">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <h3 className="text-lg font-semibold">Trade History</h3>
        <div className="flex gap-1.5">
          {(['all', 'winners', 'losers'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filter === f
                  ? 'bg-brand-purple text-white'
                  : 'text-muted-foreground hover:bg-gray-50'
              }`}
            >
              {f === 'all' ? `All (${trades.length})` :
               f === 'winners' ? `Winners (${trades.filter(t => t.pnl > 0).length})` :
               `Losers (${trades.filter(t => t.pnl < 0).length})`}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-gray-50/50">
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">Type</th>
              <th
                className="px-4 py-3 text-left font-medium text-muted-foreground cursor-pointer select-none"
                onClick={() => toggleSort('entry_date')}
              >
                <span className="inline-flex items-center gap-1">Entry <SortIcon col="entry_date" /></span>
              </th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">Exit</th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">Strikes</th>
              <th
                className="px-4 py-3 text-right font-medium text-muted-foreground cursor-pointer select-none"
                onClick={() => toggleSort('credit')}
              >
                <span className="inline-flex items-center gap-1 justify-end">Credit <SortIcon col="credit" /></span>
              </th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">Reason</th>
              <th
                className="px-4 py-3 text-right font-medium text-muted-foreground cursor-pointer select-none"
                onClick={() => toggleSort('pnl')}
              >
                <span className="inline-flex items-center gap-1 justify-end">P&L <SortIcon col="pnl" /></span>
              </th>
              <th
                className="px-4 py-3 text-right font-medium text-muted-foreground cursor-pointer select-none"
                onClick={() => toggleSort('return_pct')}
              >
                <span className="inline-flex items-center gap-1 justify-end">Return <SortIcon col="return_pct" /></span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((trade, i) => (
              <tr key={i} className="border-b border-border last:border-0 hover:bg-gray-50/50 transition-colors">
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                    trade.type === 'bull_put_spread'
                      ? 'bg-profit/10 text-profit'
                      : 'bg-loss/10 text-loss'
                  }`}>
                    {typeLabel(trade.type)}
                  </span>
                </td>
                <td className="px-4 py-3 text-muted-foreground">{formatDate(trade.entry_date)}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatDate(trade.exit_date)}</td>
                <td className="px-4 py-3 font-mono text-xs">
                  {trade.short_strike.toFixed(0)}/{trade.long_strike.toFixed(0)}
                  {trade.contracts > 1 && <span className="text-muted-foreground ml-1">x{trade.contracts}</span>}
                </td>
                <td className="px-4 py-3 text-right font-mono">${trade.credit.toFixed(2)}</td>
                <td className="px-4 py-3">
                  <span className="text-xs text-muted-foreground">{reasonLabel(trade.exit_reason)}</span>
                </td>
                <td className={`px-4 py-3 text-right font-semibold ${trade.pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatCurrency(trade.pnl)}
                </td>
                <td className={`px-4 py-3 text-right text-xs ${trade.return_pct >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {trade.return_pct >= 0 ? '+' : ''}{trade.return_pct.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sorted.length === 0 && (
        <div className="p-8 text-center text-muted-foreground text-sm">
          No trades match the current filter.
        </div>
      )}
    </div>
  )
}
