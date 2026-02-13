import { PaperTrade } from './types';

/**
 * Canonical unrealized P&L calculation for credit spreads.
 * Combines theta decay (70% weight) and price movement (30% weight).
 * NaN-guarded throughout.
 */
export function calcUnrealizedPnL(trade: PaperTrade): { unrealized_pnl: number; days_remaining: number } {
  const now = new Date();
  const expiry = new Date(trade.expiration);
  const dteAtEntry = trade.dte_at_entry || 35;
  const daysRemaining = Math.max(0, Math.ceil((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)));
  const daysHeld = Math.max(0, dteAtEntry - daysRemaining);

  const maxProfit = trade.max_profit || 0;
  const maxLoss = trade.max_loss || 0;

  if (!maxProfit || !dteAtEntry) {
    return { unrealized_pnl: 0, days_remaining: daysRemaining };
  }

  // Time decay factor (accelerates near expiry via exponent < 1)
  const timeDecayPct = daysHeld > 0 ? Math.min(1, Math.pow(daysHeld / dteAtEntry, 0.7)) : 0;

  // Price movement factor
  const priceAtEntry = trade.entry_price || 0;
  const currentPrice = trade.current_price || priceAtEntry;
  const isBullish = trade.type.includes('put');

  let priceMovementFactor = 0;
  if (priceAtEntry > 0) {
    if (isBullish) {
      const priceDelta = (currentPrice - priceAtEntry) / priceAtEntry;
      priceMovementFactor = priceDelta > 0 ? Math.min(0.3, priceDelta * 2) : Math.max(-0.5, priceDelta * 3);
    } else {
      const priceDelta = (priceAtEntry - currentPrice) / priceAtEntry;
      priceMovementFactor = priceDelta > 0 ? Math.min(0.3, priceDelta * 2) : Math.max(-0.5, priceDelta * 3);
    }
  }

  const decayProfit = maxProfit * timeDecayPct * 0.7;
  const movementPnL = maxProfit * priceMovementFactor * 0.3;
  const raw = decayProfit + movementPnL;
  const clamped = Math.max(-maxLoss, Math.min(maxProfit, raw));
  const result = isNaN(clamped) ? 0 : Math.round(clamped * 100) / 100;

  return { unrealized_pnl: result, days_remaining: daysRemaining };
}
