import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server';
import path from 'path';
import { PaperTrade, PositionsSummary } from '@/lib/types';
import { calcUnrealizedPnL } from '@/lib/pnl';
import { calculatePortfolioStats } from '@/lib/paper-trades';
import { getTrades, TradeRow } from '@/lib/database';
import { DATA_DIR } from '@/lib/paths';
import { tryReadFile } from '@/lib/fs-utils';
import { verifyAuth } from "@/lib/auth";

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

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    // Primary: read ALL trades from SQLite (both scanner and user-initiated)
    const dbTrades = getTrades({});
    if (dbTrades.length > 0) {
      const allTrades = dbTrades.map(tradeRowToPaperTrade);
      return buildResponse(allTrades);
    }

    // Fallback: read from JSON file during transition
    const content = await tryReadFile(
      path.join(DATA_DIR, 'paper_trades.json'),
      path.join(process.cwd(), 'public', 'data', 'paper_trades.json'),
    );

    if (!content) {
      return NextResponse.json(EMPTY_RESPONSE);
    }

    const paper = JSON.parse(content);
    const allTrades: PaperTrade[] = paper.trades || [];
    return buildResponse(allTrades, paper);
  } catch (error) {
    logger.error('Failed to read positions', { error: String(error) });
    return NextResponse.json(EMPTY_RESPONSE);
  }
}

function buildResponse(allTrades: PaperTrade[], paper?: Record<string, unknown>) {
  const openPositions = allTrades
    .filter((t) => t.status === 'open')
    .map((t) => {
      const pnl = calcUnrealizedPnL(t);
      return { ...t, unrealized_pnl: pnl.unrealized_pnl, days_remaining: pnl.days_remaining };
    });

  const closedTrades = allTrades.filter((t) =>
    t.status === 'closed_profit' || t.status === 'closed_loss' ||
    t.status === 'closed_expiry' || t.status === 'closed_manual' ||
    (t.status as string) === 'closed'
  );

  const ps = calculatePortfolioStats(allTrades);

  const startingBalance = (paper?.starting_balance as number) || 100000;
  const response: PositionsSummary = {
    account_size: (paper?.account_size as number) || 100000,
    starting_balance: startingBalance,
    current_balance: startingBalance + ps.totalRealizedPnL,
    total_pnl: ps.totalPnL,
    total_realized_pnl: ps.totalRealizedPnL,
    total_unrealized_pnl: ps.totalUnrealizedPnL,
    total_trades: ps.totalTrades,
    open_count: ps.openTrades,
    closed_count: ps.closedTrades,
    win_rate: ps.winRate,
    total_credit: openPositions.reduce((s, t) => s + (t.entry_credit || 0) * 100 * (t.contracts || 1), 0),
    total_max_loss: openPositions.reduce((s, t) => s + (t.max_loss || 0), 0),
    open_positions: openPositions,
    closed_trades: closedTrades,
  };

  return NextResponse.json(response);
}
