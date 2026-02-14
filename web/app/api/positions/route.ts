import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server';
import { promises as fs } from 'fs';
import path from 'path';
import { PaperTrade, PositionsSummary } from '@/lib/types';
import { calcUnrealizedPnL } from '@/lib/pnl';
import { calculatePortfolioStats } from '@/lib/paper-trades';

async function tryRead(...paths: string[]): Promise<string | null> {
  for (const p of paths) {
    try { return await fs.readFile(p, 'utf-8'); } catch { /* ignore */ }
  }
  return null;
}

const EMPTY_RESPONSE: PositionsSummary = {
  account_size: 100000, starting_balance: 100000, current_balance: 100000,
  total_pnl: 0, total_realized_pnl: 0, total_unrealized_pnl: 0,
  total_trades: 0, open_count: 0, closed_count: 0, win_rate: 0,
  total_credit: 0, total_max_loss: 0,
  open_positions: [], closed_trades: [],
};

export async function GET() {
  try {
    const cwd = process.cwd();
    const content = await tryRead(
      path.join(cwd, 'data', 'paper_trades.json'),
      path.join(cwd, 'public', 'data', 'paper_trades.json'),
      path.join(cwd, '..', 'data', 'paper_trades.json'),
    );

    if (!content) {
      return NextResponse.json(EMPTY_RESPONSE);
    }

    const paper = JSON.parse(content);
    const allTrades: PaperTrade[] = paper.trades || [];

    const openPositions = allTrades
      .filter((t) => t.status === 'open')
      .map((t) => {
        const pnl = calcUnrealizedPnL(t);
        return { ...t, unrealized_pnl: pnl.unrealized_pnl, days_remaining: pnl.days_remaining };
      });

    // Match all closed statuses, not just 'closed'
    const closedTrades = allTrades.filter((t) =>
      t.status === 'closed_profit' || t.status === 'closed_loss' ||
      t.status === 'closed_expiry' || t.status === 'closed_manual' ||
      (t.status as string) === 'closed' // backward compat
    );

    const ps = calculatePortfolioStats(allTrades);

    const response: PositionsSummary = {
      account_size: paper.account_size || 100000,
      starting_balance: paper.starting_balance || 100000,
      current_balance: (paper.starting_balance || 100000) + ps.totalRealizedPnL,
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
  } catch (error) {
    logger.error('Failed to read positions', { error: String(error) });
    return NextResponse.json(EMPTY_RESPONSE);
  }
}
