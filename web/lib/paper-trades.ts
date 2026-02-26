// User Paper Trading Engine
// Tracks user-selected paper trades with real market data

import { PaperTrade } from './types';
import { calcUnrealizedPnL } from './pnl';

// Re-export types for backward compatibility
export type { PaperTrade as UserPaperTrade } from './types';
export type { Portfolio as UserPortfolio } from './types';

// Generate unique trade ID
export function generateTradeId(): string {
  return `PT-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`;
}

// Calculate unrealized P&L — delegates to canonical implementation
export function calculateUnrealizedPnL(trade: PaperTrade): number {
  if (trade.status !== 'open') return trade.realized_pnl || 0;
  return calcUnrealizedPnL(trade).unrealized_pnl;
}

// Check if a trade should be auto-closed
export function shouldAutoClose(trade: PaperTrade): { close: boolean; reason: string } {
  // Check expiration first — an expired trade is always closed regardless of P&L
  // Options expire at 4:00 PM ET (21:00 UTC during EST, 20:00 UTC during EDT).
  // Use 21:00 UTC as a safe approximation to avoid premature auto-close.
  const now = new Date();
  const expiry = new Date(trade.expiration + 'T21:00:00Z');
  if (now >= expiry) {
    return { close: true, reason: 'Expired' };
  }

  const unrealizedPnL = calculateUnrealizedPnL(trade);

  if (trade.profit_target && unrealizedPnL >= trade.profit_target) {
    return { close: true, reason: 'Profit target reached' };
  }

  if (trade.stop_loss && unrealizedPnL <= -(trade.stop_loss)) {
    return { close: true, reason: 'Stop loss triggered' };
  }

  return { close: false, reason: '' };
}

// Portfolio stats
export function calculatePortfolioStats(trades: PaperTrade[]) {
  const closedTrades = trades.filter(t => t.status !== 'open');
  const openTrades = trades.filter(t => t.status === 'open');
  const winners = closedTrades.filter(t => (t.realized_pnl || 0) > 0);
  const losers = closedTrades.filter(t => (t.realized_pnl || 0) < 0);

  const totalRealizedPnL = closedTrades.reduce((sum, t) => sum + (t.realized_pnl || 0), 0);
  const totalUnrealizedPnL = openTrades.reduce((sum, t) => sum + calculateUnrealizedPnL(t), 0);
  const winRate = closedTrades.length > 0 ? (winners.length / closedTrades.length) * 100 : 0;
  const avgWin = winners.length > 0 ? winners.reduce((s, t) => s + (t.realized_pnl || 0), 0) / winners.length : 0;
  const avgLoss = losers.length > 0 ? Math.abs(losers.reduce((s, t) => s + (t.realized_pnl || 0), 0) / losers.length) : 0;
  const profitFactor = avgLoss > 0 ? Math.min(avgWin / avgLoss, 999.99) : avgWin > 0 ? 999.99 : 0;

  return {
    totalTrades: trades.length,
    openTrades: openTrades.length,
    closedTrades: closedTrades.length,
    winners: winners.length,
    losers: losers.length,
    winRate,
    totalRealizedPnL,
    totalUnrealizedPnL,
    totalPnL: totalRealizedPnL + totalUnrealizedPnL,
    avgWin,
    avgLoss,
    profitFactor,
    openRisk: openTrades.reduce((sum, t) => sum + t.max_loss, 0),
  };
}
