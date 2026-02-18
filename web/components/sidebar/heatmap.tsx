'use client'

import { usePositions } from '@/lib/hooks'

export function Heatmap() {
  const { data } = usePositions()

  const closedTrades = data?.closed_trades || []

  // Build a map of date -> win/loss from real closed trades
  const tradeMap: Record<string, string> = {}
  closedTrades.forEach(t => {
    if (t.exit_date) {
      const dateKey = t.exit_date.split('T')[0]
      tradeMap[dateKey] = (t.realized_pnl || 0) > 0 ? 'win' : 'loss'
    }
  })

  // Generate last 28 days
  const days: { date: string; status: string }[] = []
  for (let i = 27; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateKey = d.toISOString().split('T')[0]
    days.push({ date: dateKey, status: tradeMap[dateKey] || 'none' })
  }

  return (
    <div className="bg-white rounded-lg border border-border p-4">
      <h3 className="font-semibold mb-4">Recent 28 Days</h3>
      <div className="grid grid-cols-7 gap-1">
        {days.map((day) => (
          <div
            key={day.date}
            className={`aspect-square rounded-sm ${
              day.status === 'win'
                ? 'bg-profit'
                : day.status === 'loss'
                ? 'bg-loss'
                : 'bg-secondary'
            }`}
            title={day.status === 'win' ? 'Win' : day.status === 'loss' ? 'Loss' : 'No trade'}
            aria-label={`${day.date}: ${day.status === 'win' ? 'Win' : day.status === 'loss' ? 'Loss' : 'No trade'}`}
          />
        ))}
      </div>
      <div className="flex items-center justify-between mt-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-profit rounded-sm"></div>
          <span>Win</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-loss rounded-sm"></div>
          <span>Loss</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-secondary rounded-sm"></div>
          <span>None</span>
        </div>
      </div>
    </div>
  )
}
