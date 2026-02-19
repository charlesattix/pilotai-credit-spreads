/**
 * Bulk trade import/clear endpoint.
 * POST: Accepts {trades: [...], clear_existing?: true} and upserts all trades.
 * DELETE: Wipes all trades from the database.
 *
 * Uses the same auth as other routes (verifyAuth), so it works in
 * single-user mode without API_AUTH_TOKEN configured.
 */
import { NextResponse } from 'next/server'
import { logger } from '@/lib/logger'
import { apiError } from '@/lib/api-error'
import { verifyAuth } from '@/lib/auth'
import { upsertUserTrade, getTrades } from '@/lib/database'

interface ImportTrade {
  id: string
  ticker: string
  strategy_type: string
  status: string
  short_strike: number
  long_strike: number
  expiration: string
  credit: number
  contracts: number
  entry_date: string
  exit_date?: string | null
  exit_reason?: string | null
  pnl?: number | null
  metadata?: Record<string, unknown>
}

export async function POST(request: Request) {
  const authErr = await verifyAuth(request)
  if (authErr) return authErr

  try {
    const body = await request.json()
    const { trades, clear_existing } = body as {
      trades: ImportTrade[]
      clear_existing?: boolean
    }

    if (!Array.isArray(trades)) {
      return apiError('trades must be an array', 400)
    }

    if (clear_existing) {
      try {
        const DatabaseConstructor = require('better-sqlite3')
        const { DB_PATH } = require('@/lib/paths')
        const fs = require('fs')
        const pathMod = require('path')

        let dbPath = pathMod.join(process.cwd(), 'data', 'pilotai.db')
        if (fs.existsSync(DB_PATH)) dbPath = DB_PATH

        const db = new DatabaseConstructor(dbPath)
        db.prepare('DELETE FROM trades').run()
        db.close()
        logger.info('[import-trades] Cleared existing trades')
      } catch (err) {
        logger.error('[import-trades] Failed to clear trades', { error: String(err) })
      }
    }

    let imported = 0
    for (const trade of trades) {
      if (!trade.id || !trade.ticker) continue
      upsertUserTrade({
        id: trade.id,
        ticker: trade.ticker,
        strategy_type: trade.strategy_type || '',
        status: trade.status || 'open',
        short_strike: trade.short_strike || 0,
        long_strike: trade.long_strike || 0,
        expiration: trade.expiration || '',
        credit: trade.credit || 0,
        contracts: trade.contracts || 1,
        entry_date: trade.entry_date || new Date().toISOString(),
        exit_date: trade.exit_date || null,
        exit_reason: trade.exit_reason || null,
        pnl: trade.pnl ?? null,
        metadata: trade.metadata || {},
      })
      imported++
    }

    const total = getTrades()
    return NextResponse.json({ success: true, imported, total: total.length })
  } catch (error) {
    logger.error('[import-trades] Failed', { error: String(error) })
    return apiError('Import failed: ' + String(error), 500)
  }
}

export async function DELETE(request: Request) {
  const authErr = await verifyAuth(request)
  if (authErr) return authErr

  try {
    const DatabaseConstructor = require('better-sqlite3')
    const { DB_PATH } = require('@/lib/paths')
    const fs = require('fs')
    const pathMod = require('path')

    let dbPath = pathMod.join(process.cwd(), 'data', 'pilotai.db')
    if (fs.existsSync(DB_PATH)) dbPath = DB_PATH

    const db = new DatabaseConstructor(dbPath)
    const result = db.prepare('DELETE FROM trades').run()
    db.close()

    return NextResponse.json({ success: true, deleted: result.changes })
  } catch (error) {
    logger.error('[import-trades] Delete failed', { error: String(error) })
    return apiError('Failed: ' + String(error), 500)
  }
}
