'use client'

import { RefreshCw, TrendingUp, DollarSign, Target, BarChart3 } from 'lucide-react'
import { usePositions } from '@/lib/hooks'
import { PaperTrade, PositionsSummary } from '@/lib/types'

function formatMoney(n: number) {
  const sign = n >= 0 ? '+' : ''
  return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

function daysUntil(dateStr: string) {
  const exp = new Date(dateStr)
  const now = new Date()
  return Math.max(0, Math.ceil((exp.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)))
}

export default function PaperTradingPage() {
  const { data, isLoading, mutate } = usePositions()

  if (isLoading || !data) return (
    <div className="min-h-screen bg-[#FAF9FB] flex items-center justify-center">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#9B6DFF]" />
    </div>
  )

  const portfolioData = {
    account_size: data.account_size ?? 10000,
    starting_balance: data.starting_balance ?? 10000,
    current_balance: data.current_balance ?? 0,
    total_pnl: data.total_pnl ?? 0,
    total_realized_pnl: data.total_realized_pnl ?? 0,
    total_unrealized_pnl: data.total_unrealized_pnl ?? 0,
    total_trades: data.total_trades ?? 0,
    total_credit: data.total_credit ?? 0,
    total_max_loss: data.total_max_loss ?? 0,
    open_count: data.open_count ?? 0,
    closed_count: data.closed_count ?? 0,
    win_rate: data.win_rate ?? 0,
    open_positions: data.open_positions ?? [],
    closed_trades: data.closed_trades ?? [],
  }

  return (
    <div className="min-h-screen bg-[#FAF9FB]">
      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* Page title + refresh (header is provided by root layout Navbar) */}
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold text-gray-900">Paper Trading</h1>
          <button onClick={() => mutate()}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-white transition"
            style={{ background: 'linear-gradient(135deg, #9B6DFF, #E84FAD)' }}>
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>
        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard icon={<DollarSign className="w-5 h-5" />} label="Balance"
            value={`$${(portfolioData.current_balance || 0).toLocaleString()}`} color="#9B6DFF" />
          <StatCard icon={<TrendingUp className="w-5 h-5" />} label="Total P&L"
            value={formatMoney(portfolioData.total_pnl)}
            color={portfolioData.total_pnl >= 0 ? '#22c55e' : '#ef4444'} />
          <StatCard icon={<Target className="w-5 h-5" />} label="Credit Collected"
            value={`$${(portfolioData.total_credit || 0).toLocaleString()}`} color="#E84FAD" />
          <StatCard icon={<BarChart3 className="w-5 h-5" />} label="Win Rate"
            value={portfolioData.closed_count > 0 ? `${portfolioData.win_rate.toFixed(0)}%` : 'N/A'} color="#F59E42" />
        </div>

        {/* Portfolio Risk Bar */}
        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Portfolio Risk</span>
            <span className="text-sm text-gray-500">
              {portfolioData.open_count} open · Max loss: ${(portfolioData.total_max_loss || 0).toLocaleString()}
            </span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-3">
            <div className="h-3 rounded-full transition-all"
              style={{
                width: `${Math.min(100, (portfolioData.total_max_loss / portfolioData.account_size) * 100)}%`,
                background: 'linear-gradient(90deg, #9B6DFF, #E84FAD, #F59E42)'
              }} />
          </div>
          <p className="text-xs text-gray-400 mt-1">
            {((portfolioData.total_max_loss / portfolioData.account_size) * 100).toFixed(1)}% of account at risk
          </p>
        </div>

        {/* Open Positions */}
        <div>
          <h2 className="text-base font-semibold text-gray-800 mb-3">Open Positions ({portfolioData.open_count})</h2>
          <div className="space-y-3">
            {portfolioData.open_positions.map((pos) => (
              <PositionCard key={pos.id} position={pos} />
            ))}
            {portfolioData.open_positions.length === 0 && (
              <div className="bg-white rounded-xl border border-gray-100 p-8 text-center text-gray-400">
                No open positions
              </div>
            )}
          </div>
        </div>

        {/* Closed Trades */}
        {portfolioData.closed_trades.length > 0 && (
          <div>
            <h2 className="text-base font-semibold text-gray-800 mb-3">Trade History ({portfolioData.closed_count})</h2>
            <div className="space-y-3">
              {portfolioData.closed_trades.map((pos) => (
                <PositionCard key={pos.id} position={pos} closed />
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function StatCard({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: string; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4">
      <div className="flex items-center gap-2 mb-1">
        <div style={{ color }}>{icon}</div>
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      <p className="text-xl font-bold" style={{ color }}>{value}</p>
    </div>
  )
}

function PositionCard({ position: p, closed }: { position: PaperTrade; closed?: boolean }) {
  const dte = daysUntil(p.expiration)
  const pnl = closed ? (p.realized_pnl || 0) : (p.unrealized_pnl ?? 0)
  const isWin = pnl >= 0
  const totalCredit = (p.entry_credit || 0) * 100 * (p.contracts || 1)

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4 hover:shadow-sm transition">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-gray-900">{p.ticker}</span>
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
            p.type.includes('bear') || p.type.includes('call') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
          }`}>
            {p.type.includes('bear') || p.type.includes('call') ? 'Bear Call' : 'Bull Put'}
          </span>
          {p.alpaca_status && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              p.alpaca_status === 'filled' ? 'bg-green-50 text-green-600' :
              p.alpaca_status === 'submitted' ? 'bg-yellow-50 text-yellow-600' :
              'bg-gray-50 text-gray-500'
            }`}>
              Alpaca: {p.alpaca_status}
            </span>
          )}
          {closed && p.status !== 'open' && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              isWin ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'
            }`}>
              {p.status.replace('closed_', '')}
            </span>
          )}
        </div>
        <span className={`text-lg font-bold ${isWin ? 'text-green-600' : 'text-red-500'}`}>
          {formatMoney(pnl)}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <div>
          <span className="text-gray-400 text-xs">Strikes</span>
          <p className="font-medium text-gray-700">${p.short_strike} / ${p.long_strike}</p>
        </div>
        <div>
          <span className="text-gray-400 text-xs">Contracts</span>
          <p className="font-medium text-gray-700">x{p.contracts}</p>
        </div>
        <div>
          <span className="text-gray-400 text-xs">Credit</span>
          <p className="font-medium text-gray-700">${(totalCredit || 0).toLocaleString()}</p>
        </div>
        <div>
          <span className="text-gray-400 text-xs">{closed ? 'Closed' : 'DTE'}</span>
          <p className="font-medium text-gray-700">
            {closed && p.exit_date ? new Date(p.exit_date).toLocaleDateString() : `${dte}d`}
          </p>
        </div>
      </div>

      {!closed && (
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-gray-50 text-xs text-gray-400">
          <span>PoP: {(p.pop || 0).toFixed(0)}%</span>
          <span>Delta: {(p.short_delta || 0).toFixed(3)}</span>
          <span>Score: {(p.score || 0).toFixed(1)}</span>
          <span>Target: ${(p.profit_target || 0).toLocaleString()}</span>
          <span>Stop: ${(p.stop_loss || 0).toLocaleString()}</span>
        </div>
      )}
    </div>
  )
}
