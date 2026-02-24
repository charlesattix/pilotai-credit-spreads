import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server';
import { PaperTrade, PositionsSummary } from '@/lib/types';
import { getTrades, TradeRow } from '@/lib/database';
import { verifyAuth } from "@/lib/auth";
import { fetchAlpacaAccount, fetchAlpacaPositions, AlpacaPosition, parseOCC } from '@/lib/alpaca';

export const dynamic = 'force-dynamic'

const EMPTY_RESPONSE: PositionsSummary = {
  account_size: 100000, starting_balance: 100000, current_balance: 100000,
  total_pnl: 0, total_realized_pnl: 0, total_unrealized_pnl: 0,
  total_trades: 0, open_count: 0, closed_count: 0, win_rate: 0,
  total_credit: 0, total_max_loss: 0,
  open_positions: [], closed_trades: [],
};

function tradeRowToPaperTrade(row: TradeRow): PaperTrade {
  const meta = row.metadata ? JSON.parse(row.metadata) : {};
  return {
    id: row.id,
    ticker: row.ticker,
    type: row.strategy_type || meta.type || '',
    short_strike: row.short_strike || 0,
    long_strike: row.long_strike || 0,
    spread_width: Math.abs((row.short_strike || 0) - (row.long_strike || 0)),
    expiration: row.expiration || '',
    dte_at_entry: meta.dte_at_entry || 0,
    entry_credit: row.credit || meta.credit_per_spread || 0,
    entry_price: meta.entry_price || 0,
    current_price: meta.entry_price || 0,
    contracts: row.contracts || 1,
    max_profit: (row.credit || 0) * 100 * (row.contracts || 1),
    max_loss: meta.total_max_loss || ((Math.abs((row.short_strike || 0) - (row.long_strike || 0)) - (row.credit || 0)) * 100 * (row.contracts || 1)),
    status: (row.status || 'open') as PaperTrade['status'],
    entry_date: row.entry_date || row.created_at,
    exit_date: row.exit_date || undefined,
    realized_pnl: row.pnl || undefined,
    profit_target: meta.profit_target,
    stop_loss: meta.stop_loss_amount,
    pop: meta.entry_pop,
    score: meta.entry_score,
    short_delta: meta.entry_delta,
    alpaca_order_id: meta.alpaca_order_id || undefined,
    alpaca_status: meta.alpaca_status || undefined,
    alpaca_filled_price: meta.alpaca_filled_price ? Number(meta.alpaca_filled_price) : undefined,
  };
}

// OCC parsing delegated to shared alpaca helper (handles O: prefix and padded tickers)

function daysUntil(dateStr: string): number {
  return Math.max(0, Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000))
}

/**
 * Convert raw Alpaca option positions (individual legs) into PaperTrade spread objects.
 * Legs are grouped by ticker + expiration + option type; short+long pairs become spreads.
 */
function alpacaPositionsToPaperTrades(positions: AlpacaPosition[]): PaperTrade[] {
  type ParsedLeg = {
    ticker: string; expiration: string; optionType: 'P' | 'C'; strike: number
    qty: number; side: 'long' | 'short'
    avg_entry_price: number; current_price: number; unrealized_pl: number; symbol: string
  }

  const legs: ParsedLeg[] = []
  for (const pos of positions) {
    const parsed = parseOCC(pos.symbol)
    if (!parsed) continue
    legs.push({
      ...parsed,
      qty: parseInt(pos.qty),
      side: pos.side,
      avg_entry_price: parseFloat(pos.avg_entry_price),
      current_price: parseFloat(pos.current_price),
      unrealized_pl: parseFloat(pos.unrealized_pl),
      symbol: pos.symbol,
    })
  }

  // Group by ticker:expiration:optionType
  const groups = new Map<string, ParsedLeg[]>()
  for (const leg of legs) {
    const key = `${leg.ticker}:${leg.expiration}:${leg.optionType}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(leg)
  }

  const today = new Date().toISOString().split('T')[0]
  const trades: PaperTrade[] = []

  for (const [key, groupLegs] of groups) {
    const [ticker, expiration] = key.split(':')
    const shortLegs = groupLegs.filter(l => l.side === 'short').sort((a, b) => a.strike - b.strike)
    const longLegs = groupLegs.filter(l => l.side === 'long').sort((a, b) => a.strike - b.strike)

    // Pair short+long legs into spreads by closest strike proximity
    const usedLong = new Set<number>()
    const paired: Array<{ short: ParsedLeg; long: ParsedLeg }> = []

    for (const sl of shortLegs) {
      let bestIdx = -1
      let bestDist = Infinity
      for (let i = 0; i < longLegs.length; i++) {
        if (usedLong.has(i)) continue
        const dist = Math.abs(sl.strike - longLegs[i].strike)
        if (dist < bestDist) { bestDist = dist; bestIdx = i }
      }
      if (bestIdx >= 0) {
        usedLong.add(bestIdx)
        paired.push({ short: sl, long: longLegs[bestIdx] })
      }
    }

    if (paired.length > 0) {
      for (const { short: shortLeg, long: longLeg } of paired) {
        const type = shortLeg.optionType === 'P' ? 'bull_put_spread' : 'bear_call_spread'
        const contracts = Math.min(shortLeg.qty, longLeg.qty)
        const entry_credit = shortLeg.avg_entry_price - longLeg.avg_entry_price
        const spread_width = Math.abs(shortLeg.strike - longLeg.strike)
        const unrealized_pnl = shortLeg.unrealized_pl + longLeg.unrealized_pl
        trades.push({
          id: `alpaca:${shortLeg.symbol}`,
          ticker,
          type,
          short_strike: shortLeg.strike,
          long_strike: longLeg.strike,
          spread_width,
          expiration,
          dte_at_entry: daysUntil(expiration),
          entry_credit,
          entry_price: shortLeg.avg_entry_price,
          current_price: shortLeg.current_price,
          contracts,
          max_profit: entry_credit * 100 * contracts,
          max_loss: (spread_width - entry_credit) * 100 * contracts,
          status: 'open',
          entry_date: today,
          unrealized_pnl,
          days_remaining: daysUntil(expiration),
        })
      }

      // Any unpaired legs
      const unpairedShorts = shortLegs.filter((_, i) => !paired.some(p => p.short === shortLegs[i]))
      const unpairedLongs = longLegs.filter((_, i) => !usedLong.has(i))
      const unpaired = [...unpairedShorts, ...unpairedLongs]
      for (const leg of unpaired) {
        trades.push({
          id: `alpaca:${leg.symbol}`,
          ticker,
          type: leg.side === 'short'
            ? (leg.optionType === 'P' ? 'short_put' : 'short_call')
            : (leg.optionType === 'P' ? 'long_put' : 'long_call'),
          short_strike: leg.side === 'short' ? leg.strike : 0,
          long_strike: leg.side === 'long' ? leg.strike : 0,
          spread_width: 0,
          expiration,
          dte_at_entry: daysUntil(expiration),
          entry_credit: leg.side === 'short' ? leg.avg_entry_price : 0,
          entry_price: leg.avg_entry_price,
          current_price: leg.current_price,
          contracts: leg.qty,
          max_profit: leg.side === 'short' ? leg.avg_entry_price * 100 * leg.qty : 0,
          max_loss: 0,
          status: 'open',
          entry_date: today,
          unrealized_pnl: leg.unrealized_pl,
          days_remaining: daysUntil(expiration),
        })
      }
    } else {
      // Single legs (no matching pair) — show individually
      for (const leg of groupLegs) {
        trades.push({
          id: `alpaca:${leg.symbol}`,
          ticker,
          type: leg.side === 'short'
            ? (leg.optionType === 'P' ? 'short_put' : 'short_call')
            : (leg.optionType === 'P' ? 'long_put' : 'long_call'),
          short_strike: leg.side === 'short' ? leg.strike : 0,
          long_strike: leg.side === 'long' ? leg.strike : 0,
          spread_width: 0,
          expiration,
          dte_at_entry: daysUntil(expiration),
          entry_credit: leg.side === 'short' ? leg.avg_entry_price : 0,
          entry_price: leg.avg_entry_price,
          current_price: leg.current_price,
          contracts: leg.qty,
          max_profit: leg.side === 'short' ? leg.avg_entry_price * 100 * leg.qty : 0,
          max_loss: 0,
          status: 'open',
          entry_date: today,
          unrealized_pnl: leg.unrealized_pl,
          days_remaining: daysUntil(expiration),
        })
      }
    }
  }

  return trades
}

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    // Fetch Alpaca state and SQLite closed trades in parallel
    const [alpacaAccount, alpacaPositions] = await Promise.all([
      fetchAlpacaAccount(),
      fetchAlpacaPositions(),
    ])

    // Closed trades from SQLite — audit log for realized P&L
    const closedTrades = getTrades({})
      .filter(r => r.status !== 'open')
      .map(tradeRowToPaperTrade)

    // Open positions from Alpaca (source of truth); fall back to SQLite if unavailable
    const openPositions: PaperTrade[] = alpacaPositions !== null
      ? alpacaPositionsToPaperTrades(alpacaPositions)
      : getTrades({ status: 'open' }).map(tradeRowToPaperTrade)

    const totalRealizedPnL = closedTrades.reduce((s, t) => s + (t.realized_pnl || 0), 0)
    const totalUnrealizedPnL = openPositions.reduce((s, t) => s + (t.unrealized_pnl || 0), 0)
    const closedWinners = closedTrades.filter(t => (t.realized_pnl || 0) > 0).length

    // Balance from Alpaca equity; fall back to SQLite-derived if Alpaca unavailable
    const currentBalance = alpacaAccount?.equity ?? (100000 + totalRealizedPnL)

    const response: PositionsSummary = {
      account_size: currentBalance,
      starting_balance: 100000,
      current_balance: currentBalance,
      total_pnl: totalRealizedPnL + totalUnrealizedPnL,
      total_realized_pnl: totalRealizedPnL,
      total_unrealized_pnl: totalUnrealizedPnL,
      total_trades: openPositions.length + closedTrades.length,
      open_count: openPositions.length,
      closed_count: closedTrades.length,
      win_rate: closedTrades.length > 0 ? (closedWinners / closedTrades.length) * 100 : 0,
      total_credit: openPositions.reduce((s, t) => s + (t.entry_credit || 0) * 100 * (t.contracts || 1), 0),
      total_max_loss: openPositions.reduce((s, t) => s + (t.max_loss || 0), 0),
      open_positions: openPositions,
      closed_trades: closedTrades,
    }

    return NextResponse.json(response)
  } catch (error) {
    logger.error('Failed to read positions', { error: String(error) });
    return NextResponse.json(EMPTY_RESPONSE);
  }
}
