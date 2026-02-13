'use client'

import { useEffect, useState } from 'react'
import { RefreshCw, TrendingUp, TrendingDown, DollarSign, Target, BarChart3, Clock } from 'lucide-react'

interface Position {
  id: number
  status: string
  ticker: string
  type: string
  short_strike: number
  long_strike: number
  expiration: string
  dte_at_entry: number
  contracts: number
  credit_per_spread: number
  total_credit: number
  max_loss_per_spread: number
  total_max_loss: number
  profit_target: number
  stop_loss_amount: number
  entry_price: number
  entry_date: string
  entry_score: number
  entry_pop: number
  entry_delta: number
  current_pnl: number
  unrealized_pnl?: number
  exit_date: string | null
  exit_reason: string | null
  exit_pnl: number | null
}

interface PortfolioData {
  account_size: number
  starting_balance: number
  current_balance: number
  total_pnl: number
  total_trades: number
  open_count: number
  closed_count: number
  win_rate: number
  total_credit: number
  total_max_loss: number
  open_positions: Position[]
  closed_trades: Position[]
}

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
  const [data, setData] = useState<PortfolioData | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    try {
      const res = await fetch('/api/positions')
      const json = await res.json()
      setData(json)
    } catch (e) {
      console.error('Failed to fetch positions:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  if (loading) return (
    <div className="min-h-screen bg-[#FAF9FB] flex items-center justify-center">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#9B6DFF]" />
    </div>
  )

  if (!data) return (
    <div className="min-h-screen bg-[#FAF9FB] flex items-center justify-center text-gray-500">
      Failed to load data
    </div>
  )

  return (
    <div className="min-h-screen bg-[#FAF9FB]">
      {/* Header */}
      <header className="bg-white border-b border-gray-100 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-sm"
              style={{ background: 'linear-gradient(135deg, #9B6DFF, #E84FAD, #F59E42)' }}>P</div>
            <div>
              <h1 className="text-lg font-bold text-gray-900">Paper Trading</h1>
              <p className="text-xs text-gray-500">Alerts by PilotAI</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <a href="/" className="text-sm text-gray-500 hover:text-gray-700 transition">← Alerts</a>
            <button onClick={fetchData}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-white transition"
              style={{ background: 'linear-gradient(135deg, #9B6DFF, #E84FAD)' }}>
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard icon={<DollarSign className="w-5 h-5" />} label="Balance" 
            value={`$${data.current_balance.toLocaleString()}`} color="#9B6DFF" />
          <StatCard icon={<TrendingUp className="w-5 h-5" />} label="Total P&L" 
            value={formatMoney(data.total_pnl)} 
            color={data.total_pnl >= 0 ? '#22c55e' : '#ef4444'} />
          <StatCard icon={<Target className="w-5 h-5" />} label="Credit Collected" 
            value={`$${data.total_credit.toLocaleString()}`} color="#E84FAD" />
          <StatCard icon={<BarChart3 className="w-5 h-5" />} label="Win Rate" 
            value={data.closed_count > 0 ? `${data.win_rate.toFixed(0)}%` : 'N/A'} color="#F59E42" />
        </div>

        {/* Portfolio Risk Bar */}
        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Portfolio Risk</span>
            <span className="text-sm text-gray-500">
              {data.open_count} open · Max loss: ${data.total_max_loss.toLocaleString()}
            </span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-3">
            <div className="h-3 rounded-full transition-all" 
              style={{ 
                width: `${Math.min(100, (data.total_max_loss / data.account_size) * 100)}%`,
                background: 'linear-gradient(90deg, #9B6DFF, #E84FAD, #F59E42)' 
              }} />
          </div>
          <p className="text-xs text-gray-400 mt-1">
            {((data.total_max_loss / data.account_size) * 100).toFixed(1)}% of account at risk
          </p>
        </div>

        {/* Open Positions */}
        <div>
          <h2 className="text-base font-semibold text-gray-800 mb-3">Open Positions ({data.open_count})</h2>
          <div className="space-y-3">
            {data.open_positions.map((pos) => (
              <PositionCard key={pos.id} position={pos} />
            ))}
            {data.open_positions.length === 0 && (
              <div className="bg-white rounded-xl border border-gray-100 p-8 text-center text-gray-400">
                No open positions
              </div>
            )}
          </div>
        </div>

        {/* Closed Trades */}
        {data.closed_trades.length > 0 && (
          <div>
            <h2 className="text-base font-semibold text-gray-800 mb-3">Trade History ({data.closed_count})</h2>
            <div className="space-y-3">
              {data.closed_trades.map((pos) => (
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

function PositionCard({ position: p, closed }: { position: Position; closed?: boolean }) {
  const dte = daysUntil(p.expiration)
  const pnl = closed ? (p.exit_pnl || 0) : (p.unrealized_pnl ?? p.current_pnl ?? 0)
  const isWin = pnl >= 0

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4 hover:shadow-sm transition">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-gray-900">{p.ticker}</span>
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
            p.type.includes('bear') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
          }`}>
            {p.type.includes('bear') ? '🐻 Bear Call' : '🐂 Bull Put'}
          </span>
          {closed && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
              isWin ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'
            }`}>
              {p.exit_reason}
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
          <p className="font-medium text-gray-700">×{p.contracts}</p>
        </div>
        <div>
          <span className="text-gray-400 text-xs">Credit</span>
          <p className="font-medium text-gray-700">${p.total_credit.toLocaleString()}</p>
        </div>
        <div>
          <span className="text-gray-400 text-xs">{closed ? 'Closed' : 'DTE'}</span>
          <p className="font-medium text-gray-700">
            {closed ? new Date(p.exit_date!).toLocaleDateString() : `${dte}d`}
          </p>
        </div>
      </div>

      {!closed && (
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-gray-50 text-xs text-gray-400">
          <span>PoP: {(p.entry_pop).toFixed(0)}%</span>
          <span>Delta: {p.entry_delta.toFixed(3)}</span>
          <span>Score: {p.entry_score.toFixed(1)}</span>
          <span>Target: ${p.profit_target.toLocaleString()}</span>
          <span>Stop: ${p.stop_loss_amount.toLocaleString()}</span>
        </div>
      )}
    </div>
  )
}
