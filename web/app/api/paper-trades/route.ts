import { NextResponse } from "next/server";
import { readFile, writeFile, mkdir } from "fs/promises";
import path from "path";
import { PaperTrade, Portfolio } from "@/lib/types";
import { calcUnrealizedPnL } from "@/lib/pnl";

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
  await writeFile(userFile(userId), JSON.stringify(portfolio, null, 2));
}

// GET — fetch user's paper trades
export async function GET(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return NextResponse.json({ trades: [], stats: { disabled: true }, message: "Paper trading is temporarily disabled" });
  }

  const { searchParams } = new URL(request.url);
  const userId = searchParams.get('userId') || 'default';

  return withLock(userId, async () => {
    const portfolio = await readPortfolio(userId);

    const trades: PaperTrade[] = portfolio.trades.map((trade) => {
      if (trade.status === 'open') {
        const { unrealized_pnl, days_remaining } = calcUnrealizedPnL(trade);
        return { ...trade, unrealized_pnl, days_remaining };
      }
      return trade;
    });

    const closedTrades = trades.filter((t) => t.status !== 'open');
    const openTrades = trades.filter((t) => t.status === 'open');
    const winners = closedTrades.filter((t) => (t.realized_pnl || 0) > 0);
    const totalRealizedPnL = closedTrades.reduce((s, t) => s + (t.realized_pnl || 0), 0);
    const totalUnrealizedPnL = openTrades.reduce((s, t) => s + (t.unrealized_pnl || 0), 0);

    return NextResponse.json({
      trades,
      stats: {
        total_trades: trades.length,
        open_trades: openTrades.length,
        closed_trades: closedTrades.length,
        winners: winners.length,
        losers: closedTrades.length - winners.length,
        win_rate: closedTrades.length > 0 ? (winners.length / closedTrades.length) * 100 : 0,
        total_realized_pnl: totalRealizedPnL,
        total_unrealized_pnl: totalUnrealizedPnL,
        total_pnl: totalRealizedPnL + totalUnrealizedPnL,
        balance: portfolio.starting_balance + totalRealizedPnL,
        starting_balance: portfolio.starting_balance,
      },
    });
  });
}

// POST — open a new paper trade
export async function POST(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return NextResponse.json({ error: "Paper trading is temporarily disabled" }, { status: 403 });
  }

  try {
    const body = await request.json();
    const { alert, contracts = 1, userId = 'default' } = body;

    if (!alert) {
      return NextResponse.json({ error: "Alert data required" }, { status: 400 });
    }

    return withLock(userId, async () => {
      const portfolio = await readPortfolio(userId);

      const openCount = portfolio.trades.filter((t) => t.status === 'open').length;
      if (openCount >= MAX_OPEN_POSITIONS) {
        return NextResponse.json({ error: `Maximum ${MAX_OPEN_POSITIONS} open positions allowed` }, { status: 400 });
      }

      const duplicate = portfolio.trades.find((t) =>
        t.status === 'open' &&
        t.ticker === alert.ticker &&
        t.expiration === alert.expiration &&
        t.short_strike === alert.short_strike &&
        t.long_strike === alert.long_strike
      );
      if (duplicate) {
        return NextResponse.json({ error: "You already have this position open" }, { status: 400 });
      }

      const creditPerContract = alert.credit;
      const spreadWidth = alert.spread_width;

      const trade: PaperTrade = {
        id: `PT-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
        ticker: alert.ticker,
        type: alert.type,
        short_strike: alert.short_strike,
        long_strike: alert.long_strike,
        spread_width: spreadWidth,
        expiration: alert.expiration,
        dte_at_entry: alert.dte,
        entry_credit: creditPerContract,
        entry_price: alert.current_price,
        current_price: alert.current_price,
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
    console.error("Failed to create paper trade:", error);
    return NextResponse.json({ error: "Failed to create trade" }, { status: 500 });
  }
}

// DELETE — close a paper trade
export async function DELETE(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return NextResponse.json({ error: "Paper trading is temporarily disabled" }, { status: 403 });
  }

  try {
    const { searchParams } = new URL(request.url);
    const tradeId = searchParams.get('id');
    const reason = searchParams.get('reason') || 'manual';
    const userId = searchParams.get('userId') || 'default';

    if (!tradeId) {
      return NextResponse.json({ error: "Trade ID required" }, { status: 400 });
    }

    return withLock(userId, async () => {
      const portfolio = await readPortfolio(userId);
      const tradeIdx = portfolio.trades.findIndex((t) => t.id === tradeId);

      if (tradeIdx === -1) {
        return NextResponse.json({ error: "Trade not found" }, { status: 404 });
      }

      const trade = portfolio.trades[tradeIdx];
      if (trade.status !== 'open') {
        return NextResponse.json({ error: "Trade is already closed" }, { status: 400 });
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
    console.error("Failed to close paper trade:", error);
    return NextResponse.json({ error: "Failed to close trade" }, { status: 500 });
  }
}
