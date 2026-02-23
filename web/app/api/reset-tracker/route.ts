import { NextResponse } from 'next/server'
import { getDb } from '@/lib/database'

export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  const { searchParams } = new URL(request.url)
  const secret = searchParams.get('secret')

  if (!secret || secret !== process.env.ALPACA_API_KEY) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const db = getDb()
  if (!db) {
    return NextResponse.json({ error: 'Database unavailable' }, { status: 503 })
  }

  // Delete all closed trades (statuses: closed_profit, closed_loss, closed_expiry, closed_manual)
  const result = db.prepare("DELETE FROM trades WHERE status LIKE 'closed%'").run()

  // Update balance table if it exists
  try {
    db.exec("UPDATE user_balances SET balance = 97695, total_pnl = -2305, realized_pnl = 0")
  } catch {
    // user_balances table may not exist; balance is derived from closed trades sum
  }

  return NextResponse.json({ ok: true, deleted: result.changes })
}
