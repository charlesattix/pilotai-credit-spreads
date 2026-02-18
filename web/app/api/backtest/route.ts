import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server'
import { apiError } from "@/lib/api-error"
import { promises as fs } from 'fs'
import path from 'path'
import { OUTPUT_DIR } from "@/lib/paths"
import { verifyAuth } from "@/lib/auth"

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    // Try to read backtest results from a JSON file if it exists
    const backtestPath = path.join(OUTPUT_DIR, 'backtest_results.json')
    
    try {
      const data = await fs.readFile(backtestPath, 'utf-8')
      return NextResponse.json(JSON.parse(data))
    } catch {
      // Return mock data if no backtest results exist yet
      return NextResponse.json({
        total_trades: 0,
        winning_trades: 0,
        losing_trades: 0,
        win_rate: 0,
        total_pnl: 0,
        avg_win: 0,
        avg_loss: 0,
        profit_factor: 0,
        sharpe_ratio: 0,
        max_drawdown: 0,
        max_drawdown_pct: 0,
        equity_curve: [],
        trade_distribution: [],
      })
    }
  } catch (error) {
    logger.error('Failed to read backtest results', { error: String(error) })
    return apiError('Failed to read backtest results', 500)
  }
}
