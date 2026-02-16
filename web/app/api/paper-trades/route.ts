import { logger } from "@/lib/logger"
import { NextResponse } from "next/server";
import { apiError } from "@/lib/api-error";
import { readFile, writeFile as fsWriteFile, mkdir, rename, unlink } from "fs/promises";
import path from "path";
import { randomUUID } from "crypto";
import { z } from "zod";
import { PaperTrade, Portfolio } from "@/lib/types";
import { calcUnrealizedPnL } from "@/lib/pnl";
import { calculatePortfolioStats } from "@/lib/paper-trades";

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

function getUserId(request: Request): string {
  return request.headers.get('x-user-id') || 'default';
}

const DATA_DIR = path.join(process.cwd(), "data");
const TRADES_DIR = path.join(DATA_DIR, "user_trades");
const STARTING_BALANCE = 100000;
const MAX_OPEN_POSITIONS = 10;

const PAPER_TRADING_ENABLED = process.env.PAPER_TRADING_ENABLED !== 'false';

// In-memory mutex per userId for file locking
const fileLocks = new Map<string, Promise<void>>();

function withLock<T>(userId: string, fn: () => Promise<T>): Promise<T> {
  const prev = fileLocks.get(userId) || Promise.resolve();
  const next = prev.then(fn, fn);
  // Store the void version so the chain continues
  fileLocks.set(userId, next.then(() => {}, () => {}));
  return next;
}

async function ensureDirs() {
  try { await mkdir(TRADES_DIR, { recursive: true }); } catch { /* ignore */ }
}

function userFile(userId: string): string {
  const safe = userId.replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 64);
  return path.join(TRADES_DIR, `${safe}.json`);
}

async function readPortfolio(userId: string): Promise<Portfolio> {
  try {
    const content = await readFile(userFile(userId), "utf-8");
    return JSON.parse(content) as Portfolio;
  } catch {
    return { trades: [], starting_balance: STARTING_BALANCE, created_at: new Date().toISOString(), user_id: userId };
  }
}

async function writePortfolio(userId: string, portfolio: Portfolio): Promise<void> {
  await ensureDirs();
  const target = userFile(userId);
  const tmp = path.join(path.dirname(target), `.${randomUUID()}.tmp`);
  try {
    await fsWriteFile(tmp, JSON.stringify(portfolio, null, 2));
    await rename(tmp, target);
  } catch (err) {
    try { await unlink(tmp); } catch { /* ignore cleanup failure */ }
    throw err;
  }
}

// GET — fetch user's paper trades
export async function GET(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return NextResponse.json({ trades: [], stats: { disabled: true }, message: "Paper trading is temporarily disabled" });
  }

  const userId = getUserId(request);

  return withLock(userId, async () => {
    const portfolio = await readPortfolio(userId);

    const trades: PaperTrade[] = portfolio.trades.map((trade) => {
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
        balance: portfolio.starting_balance + ps.totalRealizedPnL,
        starting_balance: portfolio.starting_balance,
      },
    });
  });
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
    const userId = getUserId(request);

    return withLock(userId, async () => {
      const portfolio = await readPortfolio(userId);

      const openCount = portfolio.trades.filter((t) => t.status === 'open').length;
      if (openCount >= MAX_OPEN_POSITIONS) {
        return apiError(`Maximum ${MAX_OPEN_POSITIONS} open positions allowed`, 400);
      }

      const duplicate = portfolio.trades.find((t) =>
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

      const trade: PaperTrade = {
        id: `PT-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
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

      portfolio.trades.push(trade);
      await writePortfolio(userId, portfolio);

      return NextResponse.json({ success: true, trade });
    });
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
    const userId = getUserId(request);

    if (!tradeId) {
      return apiError("Trade ID required", 400);
    }

    return withLock(userId, async () => {
      const portfolio = await readPortfolio(userId);
      const tradeIdx = portfolio.trades.findIndex((t) => t.id === tradeId);

      if (tradeIdx === -1) {
        return apiError("Trade not found", 404);
      }

      const trade = portfolio.trades[tradeIdx];
      if (trade.status !== 'open') {
        return apiError("Trade is already closed", 400);
      }

      const { unrealized_pnl } = calcUnrealizedPnL(trade);

      portfolio.trades[tradeIdx] = {
        ...trade,
        status: reason === 'profit' ? 'closed_profit' : reason === 'loss' ? 'closed_loss' : reason === 'expiry' ? 'closed_expiry' : 'closed_manual',
        exit_date: new Date().toISOString(),
        realized_pnl: unrealized_pnl,
      };

      await writePortfolio(userId, portfolio);

      return NextResponse.json({ success: true, trade: portfolio.trades[tradeIdx] });
    });
  } catch (error) {
    logger.error("Failed to close paper trade", { error: String(error) });
    return apiError("Failed to close trade", 500);
  }
}
