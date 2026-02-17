import { logger } from "@/lib/logger"
import { NextResponse } from "next/server";
import { apiError } from "@/lib/api-error";
import { randomUUID } from "crypto";
import { z } from "zod";
import { PaperTrade } from "@/lib/types";
import { calcUnrealizedPnL } from "@/lib/pnl";
import { calculatePortfolioStats } from "@/lib/paper-trades";
import { getUserTrades, upsertUserTrade, closeUserTrade, TradeRow } from "@/lib/database";

const AlertSchema = z.object({
  ticker: z.string().min(1).max(10),
  credit: z.number().positive(),
  spread_width: z.number().positive(),
  dte: z.number().positive(),
  expiration: z.string().min(1),
  type: z.string().min(1),
  current_price: z.number().optional(),
  short_strike: z.number().optional(),
  long_strike: z.number().optional(),
  pop: z.number().optional(),
  score: z.number().optional(),
  short_delta: z.number().optional(),
}).refine(d => d.spread_width > d.credit, {
  message: "spread_width must be greater than credit",
});

const PostTradeSchema = z.object({
  alert: AlertSchema,
  contracts: z.number().int().min(1).max(100).default(1),
});

function extractUserId(request: Request): string {
  return request.headers.get('x-user-id') || 'default';
}

const STARTING_BALANCE = 100000;
const MAX_OPEN_POSITIONS = 10;
const PAPER_TRADING_ENABLED = process.env.PAPER_TRADING_ENABLED !== 'false';

function tradeRowToPaperTrade(row: TradeRow): PaperTrade {
  const meta = row.metadata ? JSON.parse(row.metadata) : {};
  return {
    id: row.id,
    ticker: row.ticker,
    type: row.strategy_type || meta.type || '',
    short_strike: row.short_strike || 0,
    long_strike: row.long_strike || 0,
    spread_width: meta.spread_width || Math.abs((row.short_strike || 0) - (row.long_strike || 0)),
    expiration: row.expiration || '',
    dte_at_entry: meta.dte_at_entry || 0,
    entry_credit: row.credit || 0,
    entry_price: meta.entry_price || meta.current_price || 0,
    current_price: meta.current_price || meta.entry_price || 0,
    contracts: row.contracts || 1,
    max_profit: meta.max_profit || (row.credit || 0) * 100 * (row.contracts || 1),
    max_loss: meta.max_loss || ((Math.abs((row.short_strike || 0) - (row.long_strike || 0)) - (row.credit || 0)) * 100 * (row.contracts || 1)),
    status: (row.status || 'open') as PaperTrade['status'],
    entry_date: row.entry_date || row.created_at,
    exit_date: row.exit_date || undefined,
    realized_pnl: row.pnl || undefined,
    profit_target: meta.profit_target,
    stop_loss: meta.stop_loss,
    pop: meta.pop,
    score: meta.score,
    short_delta: meta.short_delta,
  };
}

// GET — fetch user's paper trades
export async function GET(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return NextResponse.json({ trades: [], stats: { disabled: true }, message: "Paper trading is temporarily disabled" });
  }

  const userId = extractUserId(request);

  try {
    const dbTrades = getUserTrades(userId);
    const trades: PaperTrade[] = dbTrades.map(tradeRowToPaperTrade).map((trade) => {
      if (trade.status === 'open') {
        const { unrealized_pnl, days_remaining } = calcUnrealizedPnL(trade);
        return { ...trade, unrealized_pnl, days_remaining };
      }
      return trade;
    });

    const ps = calculatePortfolioStats(trades);

    return NextResponse.json({
      trades,
      stats: {
        total_trades: ps.totalTrades,
        open_trades: ps.openTrades,
        closed_trades: ps.closedTrades,
        winners: ps.winners,
        losers: ps.losers,
        win_rate: ps.winRate,
        total_realized_pnl: ps.totalRealizedPnL,
        total_unrealized_pnl: ps.totalUnrealizedPnL,
        total_pnl: ps.totalPnL,
        balance: STARTING_BALANCE + ps.totalRealizedPnL,
        starting_balance: STARTING_BALANCE,
      },
    });
  } catch (error) {
    logger.error("Failed to fetch paper trades", { error: String(error) });
    return NextResponse.json({ trades: [], stats: {} });
  }
}

// POST — open a new paper trade
export async function POST(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return apiError("Paper trading is temporarily disabled", 403);
  }

  try {
    const body = await request.json();
    const parsed = PostTradeSchema.safeParse(body);
    if (!parsed.success) {
      return apiError("Validation failed", 400, parsed.error.flatten());
    }
    const { alert, contracts } = parsed.data;
    const userId = extractUserId(request);

    // Check open position count
    const existing = getUserTrades(userId);
    const openCount = existing.filter((t) => t.status === 'open').length;
    if (openCount >= MAX_OPEN_POSITIONS) {
      return apiError(`Maximum ${MAX_OPEN_POSITIONS} open positions allowed`, 400);
    }

    // Check total portfolio risk cap (50% of starting balance)
    const MAX_TOTAL_RISK = STARTING_BALANCE * 0.5;
    const openTrades = existing.filter((t) => t.status === 'open').map(tradeRowToPaperTrade);
    const currentTotalRisk = openTrades.reduce((sum, t) => sum + (t.max_loss || 0), 0);
    const newTradeMaxLoss = (alert.spread_width - alert.credit) * 100 * contracts;
    if (currentTotalRisk + newTradeMaxLoss > MAX_TOTAL_RISK) {
      return apiError("Total portfolio risk limit exceeded", 400);
    }

    // Check for duplicate
    const duplicate = existing.find((t) =>
      t.status === 'open' &&
      t.ticker === alert.ticker &&
      t.expiration === alert.expiration &&
      t.short_strike === alert.short_strike &&
      t.long_strike === alert.long_strike
    );
    if (duplicate) {
      return apiError("You already have this position open", 400);
    }

    const creditPerContract = alert.credit;
    const spreadWidth = alert.spread_width;
    const tradeId = `PT-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`;

    const trade: PaperTrade = {
      id: tradeId,
      ticker: alert.ticker,
      type: alert.type,
      short_strike: alert.short_strike ?? 0,
      long_strike: alert.long_strike ?? 0,
      spread_width: spreadWidth,
      expiration: alert.expiration,
      dte_at_entry: alert.dte,
      entry_credit: creditPerContract,
      entry_price: alert.current_price ?? 0,
      current_price: alert.current_price ?? 0,
      contracts,
      max_profit: creditPerContract * 100 * contracts,
      max_loss: (spreadWidth - creditPerContract) * 100 * contracts,
      status: 'open',
      entry_date: new Date().toISOString(),
      profit_target: creditPerContract * 100 * contracts * 0.5,
      stop_loss: (spreadWidth - creditPerContract) * 100 * contracts * 0.5,
      pop: alert.pop,
      score: alert.score,
      short_delta: alert.short_delta,
    };

    upsertUserTrade({
      id: tradeId,
      ticker: alert.ticker,
      strategy_type: alert.type,
      status: 'open',
      short_strike: alert.short_strike ?? 0,
      long_strike: alert.long_strike ?? 0,
      expiration: alert.expiration,
      credit: creditPerContract,
      contracts,
      entry_date: new Date().toISOString(),
      metadata: {
        user_id: userId,
        spread_width: spreadWidth,
        dte_at_entry: alert.dte,
        entry_price: alert.current_price ?? 0,
        current_price: alert.current_price ?? 0,
        max_profit: trade.max_profit,
        max_loss: trade.max_loss,
        profit_target: trade.profit_target,
        stop_loss: trade.stop_loss,
        pop: alert.pop,
        score: alert.score,
        short_delta: alert.short_delta,
      },
    });

    return NextResponse.json({ success: true, trade });
  } catch (error) {
    logger.error("Failed to create paper trade", { error: String(error) });
    return apiError("Failed to create trade", 500);
  }
}

// DELETE — close a paper trade
export async function DELETE(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return apiError("Paper trading is temporarily disabled", 403);
  }

  try {
    const { searchParams } = new URL(request.url);
    const tradeId = searchParams.get('id');
    const reason = searchParams.get('reason') || 'manual';

    if (!tradeId) {
      return apiError("Trade ID required", 400);
    }

    // Get current trade to calculate unrealized P&L
    const userId = extractUserId(request);
    const dbTrades = getUserTrades(userId);
    const tradeRow = dbTrades.find(t => t.id === tradeId);
    if (!tradeRow) {
      return apiError("Trade not found", 404);
    }
    if (tradeRow.status !== 'open') {
      return apiError("Trade is already closed", 400);
    }

    const paperTrade = tradeRowToPaperTrade(tradeRow);
    const { unrealized_pnl } = calcUnrealizedPnL(paperTrade);

    const closed = closeUserTrade(tradeId, unrealized_pnl, reason);

    return NextResponse.json({
      success: true,
      trade: closed ? {
        ...tradeRowToPaperTrade(closed),
        realized_pnl: unrealized_pnl,
      } : { id: tradeId, realized_pnl: unrealized_pnl },
    });
  } catch (error) {
    logger.error("Failed to close paper trade", { error: String(error) });
    return apiError("Failed to close trade", 500);
  }
}
