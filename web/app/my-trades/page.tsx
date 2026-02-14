'use client'

import { useState } from 'react'
import { TrendingUp, TrendingDown, DollarSign, Target, Clock, XCircle, BarChart3, ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import Link from 'next/link'
import { getUserId, PAPER_TRADING_ENABLED } from '@/lib/user-id'
import { usePaperTrades } from '@/lib/hooks'
import { PaperTrade } from '@/lib/types'

interface Stats {
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
}

function formatCurrency(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function MyTradesPage() {
  const { data: tradesData, isLoading: loading, mutate } = usePaperTrades(getUserId())
  const trades: PaperTrade[] = tradesData?.trades || []
  const stats: Stats | null = tradesData?.stats || null
  const [tab, setTab] = useState<'open' | 'closed' | 'all'>('open')

  const closeTrade = async (tradeId: string, reason: string = 'manual') => {
    try {
      const res = await fetch(`/api/paper-trades?id=${tradeId}&reason=${reason}&userId=${getUserId()}`, { method: 'DELETE' })
      const data = await res.json()
      
      if (res.ok) {
        const pnl = data.trade?.realized_pnl || 0
        toast.success(`Trade closed: ${pnl >= 0 ? 'Profit' : 'Loss'} ${formatCurrency(pnl)} — moved to Closed tab`)
        mutate()
        setTab('closed')
      } else {
        toast.error(data.error || 'Failed to close trade')
      }
    } catch {
      toast.error('Failed to close trade')
    }
  }

  const filteredTrades = trades.filter(t => {
    if (tab === 'open') return t.status === 'open'
    if (tab === 'closed') return t.status !== 'open'
    return true
  })

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-brand-purple border-t-transparent"></div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="p-2 hover:bg-secondary rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold">My Paper Trades</h1>
            <p className="text-sm text-muted-foreground">Track your paper trading performance</p>
          </div>
        </div>
        <Link
          href="/"
          className="px-4 py-2 text-sm font-medium text-white rounded-lg transition-colors"
          style={{ background: 'linear-gradient(135deg, #9B6DFF, #E84FAD)' }}
        >
          Browse Alerts
        </Link>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
          <StatCard
            label="Balance"
            value={`$${stats.balance.toLocaleString()}`}
            icon={<DollarSign className="w-4 h-4" />}
            color="text-foreground"
          />
          <StatCard
            label="Total P&L"
            value={formatCurrency(stats.total_pnl)}
            icon={stats.total_pnl >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            color={stats.total_pnl >= 0 ? 'text-profit' : 'text-loss'}
          />
          <StatCard
            label="Win Rate"
            value={stats.closed_trades > 0 ? `${stats.win_rate.toFixed(0)}%` : 'N/A'}
            icon={<Target className="w-4 h-4" />}
            color={stats.win_rate >= 50 ? 'text-profit' : 'text-loss'}
          />
          <StatCard
            label="Open Trades"
            value={stats.open_trades.toString()}
            icon={<Clock className="w-4 h-4" />}
            color="text-brand-purple"
          />
          <StatCard
            label="Realized P&L"
            value={formatCurrency(stats.total_realized_pnl)}
            icon={<BarChart3 className="w-4 h-4" />}
            color={stats.total_realized_pnl >= 0 ? 'text-profit' : 'text-loss'}
          />
          <StatCard
            label="Unrealized P&L"
            value={formatCurrency(stats.total_unrealized_pnl)}
            icon={<BarChart3 className="w-4 h-4" />}
            color={stats.total_unrealized_pnl >= 0 ? 'text-profit' : 'text-loss'}
          />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-4">
        {(['open', 'closed', 'all'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
              tab === t
                ? 'bg-brand-purple text-white shadow-md'
                : 'bg-white text-muted-foreground border border-border hover:border-brand-purple/30'
            }`}
          >
            {t === 'open' ? `Open (${trades.filter(tr => tr.status === 'open').length})` : 
             t === 'closed' ? `Closed (${trades.filter(tr => tr.status !== 'open').length})` : 
             `All (${trades.length})`}
          </button>
        ))}
      </div>

      {/* Trades List */}
      {filteredTrades.length === 0 ? (
        <div className="bg-white rounded-lg border border-border p-12 text-center">
          <div className="text-4xl mb-3">📊</div>
          <h3 className="text-lg font-semibold mb-1">
            {tab === 'open' ? 'No open trades' : tab === 'closed' ? 'No closed trades yet' : 'No trades yet'}
          </h3>
          <p className="text-muted-foreground text-sm mb-4">
            {tab === 'open' 
              ? 'Click "Paper Trade" on any alert to start tracking it.' 
              : 'Your closed trade history will appear here.'}
          </p>
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-lg"
            style={{ background: 'linear-gradient(135deg, #9B6DFF, #E84FAD)' }}
          >
            <TrendingUp className="w-4 h-4" />
            Browse Alerts
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredTrades.map(trade => (
            <TradeRow key={trade.id} trade={trade} onClose={closeTrade} />
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, icon, color }: { label: string; value: string; icon: React.ReactNode; color: string }) {
  return (
    <div className="bg-white rounded-lg border border-border p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground text-xs mb-1">
        {icon}
        {label}
      </div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
    </div>
  )
}

function TradeRow({ trade, onClose }: { trade: PaperTrade; onClose: (id: string, reason: string) => void }) {
  const isOpen = trade.status === 'open'
  const pnl = isOpen ? (trade.unrealized_pnl || 0) : (trade.realized_pnl || 0)
  const pnlPct = trade.max_profit > 0 ? (pnl / trade.max_profit) * 100 : 0
  const isBullish = trade.type.includes('put')
  const typeLabel = isBullish ? 'Bull Put' : 'Bear Call'
  const typeColor = isBullish ? 'text-profit' : 'text-loss'

  const statusBadge = () => {
    switch (trade.status) {
      case 'open': return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-600 border border-blue-200">Open</span>
      case 'closed_profit': return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-profit-light text-profit border border-profit/30">Win ✓</span>
      case 'closed_loss': return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-loss-light text-loss border border-loss/30">Loss ✗</span>
      case 'closed_expiry': return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-50 text-gray-600 border border-gray-200">Expired</span>
      default: return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-50 text-gray-600 border border-gray-200">Closed</span>
    }
  }

  return (
    <div className="bg-white rounded-lg border border-border hover:border-brand-purple/20 transition-all p-4">
      <div className="flex items-center justify-between">
        {/* Left: Trade info */}
        <div className="flex items-center gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-lg font-bold">{trade.ticker}</span>
              <span className={`text-sm font-medium ${typeColor}`}>{typeLabel}</span>
              {statusBadge()}
            </div>
            <div className="text-sm text-muted-foreground">
              ${trade.short_strike}/{trade.long_strike} • {trade.contracts} contract{trade.contracts > 1 ? 's' : ''} • Credit: ${(trade.entry_credit * 100).toFixed(0)}
            </div>
          </div>
        </div>

        {/* Center: Dates & DTE */}
        <div className="hidden md:block text-center">
          <div className="text-xs text-muted-foreground">
            {formatDate(trade.entry_date)} → {trade.exit_date ? formatDate(trade.exit_date) : formatDate(trade.expiration)}
          </div>
          {isOpen && trade.days_remaining !== undefined && (
            <div className="text-xs font-medium text-brand-purple">{trade.days_remaining} days remaining</div>
          )}
        </div>

        {/* Right: P&L and actions */}
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className={`text-lg font-bold ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
              {formatCurrency(pnl)}
            </div>
            <div className={`text-xs ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(0)}% of max
            </div>
          </div>

          {/* P&L Progress Bar */}
          <div className="hidden sm:block w-20">
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              {pnl >= 0 ? (
                <div className="h-full bg-profit rounded-full" style={{ width: `${Math.min(100, pnlPct)}%` }} />
              ) : (
                <div className="h-full bg-loss rounded-full" style={{ width: `${Math.min(100, Math.abs(pnlPct))}%` }} />
              )}
            </div>
          </div>

          {/* Close button for open trades */}
          {isOpen && (
            <button
              onClick={() => onClose(trade.id, 'manual')}
              className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-loss bg-loss-light border border-loss/20 rounded-lg hover:bg-loss/10 transition-colors"
            >
              <XCircle className="w-3.5 h-3.5" />
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
