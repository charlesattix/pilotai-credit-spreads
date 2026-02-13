'use client'

interface StatsBarProps {
  alertsCount: number
  avgPOP: number
  winRate30d: number
  avgReturn: number
  alertsThisWeek: number
}

export function StatsBar({ alertsCount, avgPOP, winRate30d, avgReturn, alertsThisWeek }: StatsBarProps) {
  return (
    <div className="bg-white border-b border-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex overflow-x-auto scrollbar-hide gap-2 sm:gap-4 py-3 sm:py-4">
          <StatItem label="Today's Alerts" value={alertsCount.toString()} />
          <StatItem label="Avg Prob of Profit" value={avgPOP > 0 ? `${avgPOP.toFixed(1)}%` : 'N/A'} />
          <StatItem label="30-Day Win Rate" value={winRate30d > 0 ? `${winRate30d.toFixed(1)}%` : 'N/A'} />
          <StatItem label="Avg Return/Trade" value={avgReturn !== 0 ? `${avgReturn >= 0 ? '+' : ''}$${Math.abs(avgReturn).toFixed(0)}` : 'N/A'} />
          <StatItem label="Alerts This Week" value={alertsThisWeek.toString()} />
        </div>
      </div>
    </div>
  )
}

function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center shrink-0 min-w-[80px] sm:min-w-0 flex-1 px-1">
      <div className="text-lg sm:text-2xl font-bold text-foreground">{value}</div>
      <div className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 sm:mt-1 whitespace-nowrap">{label}</div>
    </div>
  )
}
