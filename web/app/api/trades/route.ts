import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server'
import { apiError } from "@/lib/api-error"
import { promises as fs } from 'fs'
import path from 'path'
import { getTrades } from '@/lib/database'
import { DATA_DIR } from "@/lib/paths"
import { verifyAuth } from "@/lib/auth"

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    // Primary: read from SQLite
    const dbTrades = getTrades();
    if (dbTrades.length > 0) {
      return NextResponse.json(dbTrades.map(t => ({
        id: t.id,
        ticker: t.ticker,
        type: t.strategy_type,
        entry_date: t.entry_date,
        exit_date: t.exit_date,
        short_strike: t.short_strike,
        long_strike: t.long_strike,
        credit: t.credit,
        pnl: t.pnl,
        status: t.status === 'open' ? 'open' : 'closed',
        entry_price: JSON.parse(t.metadata || '{}').entry_price || 0,
        dte_entry: JSON.parse(t.metadata || '{}').dte_at_entry || 0,
      })));
    }

    // Fallback: read from JSON file during transition
    const tradesPath = path.join(DATA_DIR, 'trades.json')
    const data = await fs.readFile(tradesPath, 'utf-8')
    return NextResponse.json(JSON.parse(data))
  } catch (error) {
    logger.error('Failed to read trades', { error: String(error) })
    return apiError('Failed to read trades', 500)
  }
}
