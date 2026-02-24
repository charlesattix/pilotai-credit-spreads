/**
 * POST /api/sync-alpaca
 *
 * One-shot sync: fetches all filled MLEG orders from Alpaca, pairs each
 * opening order with its corresponding closing order, computes realised P&L
 * and writes the completed spreads into the SQLite trades table.
 *
 * Safe to run multiple times — trades are upserted by Alpaca order ID so
 * no duplicates are created.
 *
 * Entry vs exit detection uses leg structure (no reliance on client_order_id):
 *   Bull put spread entry:  sell higher-strike put  + buy lower-strike put
 *   Bear call spread entry: sell lower-strike call  + buy higher-strike call
 *   → Exit is the reverse in each case.
 *
 * Matching: entry and exit for the same spread share an identical set of
 * OCC symbols (just with sides swapped), so we index exits by sorted symbol
 * set and FIFO-match against entries.
 */

import { NextResponse } from 'next/server'
import { logger } from '@/lib/logger'
import { verifyAuth } from '@/lib/auth'
import { upsertUserTrade } from '@/lib/database'
import { fetchAlpacaOrders, parseOCC, AlpacaOrder, AlpacaOrderLeg } from '@/lib/alpaca'

export const dynamic = 'force-dynamic'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function legSymbolKey(legs: AlpacaOrderLeg[]): string {
  return legs.map(l => l.symbol).sort().join('|')
}

/**
 * Determine whether a 2-leg filled MLEG order is a credit-spread ENTRY.
 * Returns false if it's an exit (closing order), or if legs can't be parsed.
 */
function isEntry(legs: AlpacaOrderLeg[]): boolean {
  const sellLeg = legs.find(l => l.side === 'sell')
  const buyLeg  = legs.find(l => l.side === 'buy')
  if (!sellLeg || !buyLeg) return false

  const sellP = parseOCC(sellLeg.symbol)
  const buyP  = parseOCC(buyLeg.symbol)
  if (!sellP || !buyP || sellP.optionType !== buyP.optionType) return false

  if (sellP.optionType === 'P') {
    // Bull put spread: sell the higher strike put
    return sellP.strike > buyP.strike
  } else {
    // Bear call spread: sell the lower strike call
    return sellP.strike < buyP.strike
  }
}

// ---------------------------------------------------------------------------
// Route handler
// ---------------------------------------------------------------------------

export async function POST(request: Request) {
  const authErr = await verifyAuth(request)
  if (authErr) return authErr

  // 1. Fetch all orders from Alpaca
  const allOrders = await fetchAlpacaOrders(500)
  if (!allOrders) {
    return NextResponse.json({ error: 'Alpaca unavailable or credentials missing' }, { status: 503 })
  }

  // 2. Keep only filled 2-leg MLEG orders
  const mlegFilled: AlpacaOrder[] = allOrders.filter(
    o => o.status === 'filled' && o.order_class === 'mleg' && (o.legs?.length ?? 0) === 2
  )

  // 3. Split into entries and exits
  const entries: AlpacaOrder[] = []
  const exits: AlpacaOrder[] = []
  for (const o of mlegFilled) {
    if (isEntry(o.legs)) entries.push(o)
    else exits.push(o)
  }

  // 4. Index exits by sorted symbol set, sorted oldest-first for FIFO matching
  const exitIndex = new Map<string, AlpacaOrder[]>()
  for (const ex of exits) {
    const key = legSymbolKey(ex.legs)
    if (!exitIndex.has(key)) exitIndex.set(key, [])
    exitIndex.get(key)!.push(ex)
  }
  for (const queue of exitIndex.values()) {
    queue.sort((a, b) => (a.filled_at ?? a.submitted_at).localeCompare(b.filled_at ?? b.submitted_at))
  }

  // 5. Match entries with exits and write to SQLite
  let synced = 0
  let skipped = 0
  const warnings: string[] = []

  // Sort entries oldest-first so FIFO matching is chronologically correct
  entries.sort((a, b) => (a.filled_at ?? a.submitted_at).localeCompare(b.filled_at ?? b.submitted_at))

  for (const entry of entries) {
    const key = legSymbolKey(entry.legs)
    const exitQueue = exitIndex.get(key) ?? []
    const exit = exitQueue.shift()   // FIFO — consume first matching exit

    if (!exit) {
      // No matching exit = position is still open; handled by /api/positions
      skipped++
      continue
    }

    // Identify legs
    const sellLeg = entry.legs.find(l => l.side === 'sell')!
    const buyLeg  = entry.legs.find(l => l.side === 'buy')!

    const shortP = parseOCC(sellLeg.symbol)
    const longP  = parseOCC(buyLeg.symbol)
    if (!shortP || !longP) {
      warnings.push(`Could not parse OCC symbols for order ${entry.id}`)
      skipped++
      continue
    }

    const spreadType = shortP.optionType === 'P' ? 'bull_put_spread' : 'bear_call_spread'
    const qty = parseInt(entry.filled_qty ?? entry.qty ?? '1')

    // Net fill prices — both positive; entry received credit, exit paid debit
    const entryCredit = Math.abs(parseFloat(entry.filled_avg_price ?? '0'))
    const exitDebit   = Math.abs(parseFloat(exit.filled_avg_price  ?? '0'))
    const pnl = Math.round((entryCredit - exitDebit) * qty * 100 * 100) / 100

    const status =
      pnl > 0 ? 'closed_profit' :
      pnl < 0 ? 'closed_loss'   :
      'closed_expiry'

    try {
      upsertUserTrade({
        id:            `alpaca-${entry.id}`,
        ticker:        shortP.ticker,
        strategy_type: spreadType,
        status,
        short_strike:  shortP.strike,
        long_strike:   longP.strike,
        expiration:    shortP.expiration,
        credit:        entryCredit,
        contracts:     qty,
        entry_date:    entry.filled_at ?? entry.submitted_at,
        exit_date:     exit.filled_at  ?? exit.submitted_at,
        exit_reason:   'alpaca_sync',
        pnl,
        metadata: {
          alpaca_order_id:       entry.id,
          alpaca_close_order_id: exit.id,
          entry_fill_price:      entryCredit,
          exit_fill_price:       exitDebit,
          short_symbol:          sellLeg.symbol,
          long_symbol:           buyLeg.symbol,
        },
      })
      synced++
    } catch (err) {
      warnings.push(`DB write failed for ${entry.id}: ${String(err)}`)
      skipped++
    }
  }

  logger.info(`[sync-alpaca] synced=${synced} skipped=${skipped} total_orders=${allOrders.length}`)

  return NextResponse.json({
    ok: true,
    total_orders: allOrders.length,
    mleg_filled: mlegFilled.length,
    entries_found: entries.length,
    exits_found:   exits.length,
    synced,
    skipped,
    warnings,
  })
}
