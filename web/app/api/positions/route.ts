import { NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'

async function tryRead(...paths: string[]): Promise<string | null> {
  for (const p of paths) {
    try { return await fs.readFile(p, 'utf-8') } catch {}
  }
  return null
}

function calcUnrealizedPnL(trade: any) {
  const now = new Date()
  const expiry = new Date(trade.expiration)
  const entryDate = new Date(trade.entry_date || trade.opened_at || now)
  const totalDays = Math.max(1, trade.dte_at_entry || trade.dte || 35)
  const daysHeld = Math.max(0, Math.ceil((now.getTime() - entryDate.getTime()) / (1000 * 60 * 60 * 24)))
  const daysRemaining = Math.max(0, Math.ceil((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)))
  
  // Time decay factor (theta decay accelerates near expiry)
  const timeDecayPct = daysHeld > 0 ? Math.min(1, Math.pow(daysHeld / totalDays, 0.7)) : 0
  
  const maxProfit = trade.total_credit || (trade.credit * 100 * (trade.contracts || 1))
  const maxLoss = trade.total_max_loss || ((trade.spread_width - trade.credit) * 100 * (trade.contracts || 1))
  
  // Simplified P&L: mostly time decay for credit spreads
  const decayProfit = maxProfit * timeDecayPct * 0.65
  
  return {
    unrealized_pnl: Math.round(Math.max(-maxLoss, Math.min(maxProfit, decayProfit)) * 100) / 100,
    days_remaining: daysRemaining,
    days_held: daysHeld,
    max_profit: maxProfit,
    max_loss: maxLoss,
    pnl_pct: maxProfit > 0 ? Math.round((decayProfit / maxProfit) * 10000) / 100 : 0,
  }
}

export async function GET() {
  try {
    const cwd = process.cwd()
    const content = await tryRead(
      path.join(cwd, 'data', 'paper_trades.json'),
      path.join(cwd, 'public', 'data', 'paper_trades.json'),
      path.join(cwd, '..', 'data', 'paper_trades.json'),
    )
    
    if (!content) {
      return NextResponse.json({
        account_size: 100000, starting_balance: 100000, current_balance: 100000,
        total_pnl: 0, total_trades: 0, open_count: 0, closed_count: 0, win_rate: 0,
        total_credit: 0, total_max_loss: 0, total_unrealized_pnl: 0,
        open_positions: [], closed_trades: [],
      })
    }
    
    const paper = JSON.parse(content)
    const openPositions = (paper.trades || [])
      .filter((t: any) => t.status === 'open')
      .map((t: any) => {
        const pnl = calcUnrealizedPnL(t)
        return { ...t, ...pnl }
      })
    
    const closedTrades = (paper.trades || []).filter((t: any) => t.status === 'closed')
    const winners = closedTrades.filter((t: any) => (t.exit_pnl || 0) > 0)
    const totalUnrealizedPnL = openPositions.reduce((s: number, t: any) => s + (t.unrealized_pnl || 0), 0)
    const totalRealizedPnL = closedTrades.reduce((s: number, t: any) => s + (t.exit_pnl || 0), 0)
    
    return NextResponse.json({
      account_size: paper.account_size || 100000,
      starting_balance: paper.starting_balance || 100000,
      current_balance: (paper.starting_balance || 100000) + totalRealizedPnL,
      total_pnl: totalRealizedPnL + totalUnrealizedPnL,
      total_realized_pnl: totalRealizedPnL,
      total_unrealized_pnl: totalUnrealizedPnL,
      total_trades: (paper.trades || []).length,
      open_count: openPositions.length,
      closed_count: closedTrades.length,
      win_rate: closedTrades.length > 0 ? (winners.length / closedTrades.length * 100) : 0,
      total_credit: openPositions.reduce((s: number, t: any) => s + (t.total_credit || 0), 0),
      total_max_loss: openPositions.reduce((s: number, t: any) => s + (t.total_max_loss || t.max_loss || 0), 0),
      open_positions: openPositions,
      closed_trades: closedTrades,
    })
  } catch (error) {
    console.error('Failed to read positions:', error)
    return NextResponse.json({
      account_size: 100000, starting_balance: 100000, current_balance: 100000,
      total_pnl: 0, total_trades: 0, open_count: 0, closed_count: 0, win_rate: 0,
      total_credit: 0, total_max_loss: 0, total_unrealized_pnl: 0,
      open_positions: [], closed_trades: [],
    })
  }
}
