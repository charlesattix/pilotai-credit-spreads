'use client'

interface PerformanceCardProps {
  totalAlerts: number
  winners: number
  losers: number
  winRate: number
  avgWinner: number
  avgLoser: number
  profitFactor: number
}

export function PerformanceCard({
  totalAlerts,
  winners,
  losers,
  winRate,
  avgWinner,
  avgLoser,
  profitFactor,
}: PerformanceCardProps) {
  const hasClosedTrades = (winners + losers) > 0

  return (
    <div className="bg-white rounded-lg border border-border p-4">
      <h3 className="font-semibold mb-4">30-Day Performance</h3>
      <div className="space-y-3">
        <StatRow label="Total Trades" value={totalAlerts.toString()} />
        <StatRow label="Winners" value={hasClosedTrades ? winners.toString() : 'N/A'} valueColor={hasClosedTrades ? "text-profit" : ""} />
        <StatRow label="Losers" value={hasClosedTrades ? losers.toString() : 'N/A'} valueColor={hasClosedTrades ? "text-loss" : ""} />
        <StatRow label="Win Rate" value={hasClosedTrades ? `${winRate.toFixed(1)}%` : 'N/A'} valueColor={hasClosedTrades && winRate >= 60 ? "text-profit" : ""} />
        <StatRow label="Avg Winner" value={hasClosedTrades && avgWinner > 0 ? `+$${avgWinner.toFixed(0)}` : 'N/A'} valueColor={hasClosedTrades ? "text-profit" : ""} />
        <StatRow label="Avg Loser" value={hasClosedTrades && avgLoser < 0 ? `-$${Math.abs(avgLoser).toFixed(0)}` : 'N/A'} valueColor={hasClosedTrades ? "text-loss" : ""} />
        <StatRow label="Profit Factor" value={hasClosedTrades && profitFactor > 0 ? profitFactor.toFixed(2) : 'N/A'} valueColor={hasClosedTrades && profitFactor > 1 ? "text-profit" : hasClosedTrades ? "text-loss" : ""} />
      </div>
    </div>
  )
}

function StatRow({ label, value, valueColor = "" }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-semibold ${valueColor}`}>{value}</span>
    </div>
  )
}
