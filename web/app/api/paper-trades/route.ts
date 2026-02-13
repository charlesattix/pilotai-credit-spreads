import { NextResponse } from "next/server";
import { readFile, writeFile, mkdir } from "fs/promises";
import path from "path";

const DATA_DIR = path.join(process.cwd(), "data");
const TRADES_DIR = path.join(DATA_DIR, "user_trades");
const STARTING_BALANCE = 100000;
const MAX_OPEN_POSITIONS = 10;

// Feature flag — disable to block all paper trading
const PAPER_TRADING_ENABLED = process.env.PAPER_TRADING_ENABLED !== 'false';

async function ensureDirs() {
  try { await mkdir(TRADES_DIR, { recursive: true }); } catch {}
}

function userFile(userId: string): string {
  // Sanitize userId to prevent path traversal
  const safe = userId.replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 64);
  return path.join(TRADES_DIR, `${safe}.json`);
}

async function readPortfolio(userId: string) {
  try {
    const content = await readFile(userFile(userId), "utf-8");
    return JSON.parse(content);
  } catch {
    return { trades: [], starting_balance: STARTING_BALANCE, created_at: new Date().toISOString(), user_id: userId };
  }
}

async function writePortfolio(userId: string, portfolio: any) {
  await ensureDirs();
  await writeFile(userFile(userId), JSON.stringify(portfolio, null, 2));
}

function calcUnrealizedPnL(trade: any) {
  const now = new Date();
  const expiry = new Date(trade.expiration);
  const daysRemaining = Math.max(0, Math.ceil((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)));
  const daysHeld = trade.dte_at_entry - daysRemaining;
  const timeDecayPct = daysHeld > 0 ? Math.min(1, Math.pow(daysHeld / trade.dte_at_entry, 0.7)) : 0;
  
  const priceAtEntry = trade.entry_price;
  const currentPrice = trade.current_price || priceAtEntry;
  const isBullish = trade.type.includes('put');
  
  let priceMovementFactor = 0;
  if (isBullish) {
    const priceDelta = (currentPrice - priceAtEntry) / priceAtEntry;
    priceMovementFactor = priceDelta > 0 ? Math.min(0.3, priceDelta * 2) : Math.max(-0.5, priceDelta * 3);
  } else {
    const priceDelta = (priceAtEntry - currentPrice) / priceAtEntry;
    priceMovementFactor = priceDelta > 0 ? Math.min(0.3, priceDelta * 2) : Math.max(-0.5, priceDelta * 3);
  }
  
  const decayProfit = trade.max_profit * timeDecayPct * 0.7;
  const movementPnL = trade.max_profit * priceMovementFactor * 0.3;
  return {
    unrealized_pnl: Math.max(-trade.max_loss, Math.min(trade.max_profit, decayProfit + movementPnL)),
    days_remaining: daysRemaining,
  };
}

// GET — fetch user's paper trades
export async function GET(request: Request) {
  if (!PAPER_TRADING_ENABLED) {
    return NextResponse.json({ trades: [], stats: { disabled: true }, message: "Paper trading is temporarily disabled" });
  }

  const { searchParams } = new URL(request.url);
  const userId = searchParams.get('userId') || 'default';
  const portfolio = await readPortfolio(userId);
  
  const trades = portfolio.trades.map((trade: any) => {
    if (trade.status === 'open') {
      const { unrealized_pnl, days_remaining } = calcUnrealizedPnL(trade);
      return { ...trade, unrealized_pnl, days_remaining };
    }
    return trade;
  });
  
  const closedTrades = trades.filter((t: any) => t.status !== 'open');
  const openTrades = trades.filter((t: any) => t.status === 'open');
  const winners = closedTrades.filter((t: any) => (t.realized_pnl || 0) > 0);
  const totalRealizedPnL = closedTrades.reduce((s: number, t: any) => s + (t.realized_pnl || 0), 0);
  const totalUnrealizedPnL = openTrades.reduce((s: number, t: any) => s + (t.unrealized_pnl || 0), 0);
  
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
    
    const portfolio = await readPortfolio(userId);
    
    const openCount = portfolio.trades.filter((t: any) => t.status === 'open').length;
    if (openCount >= MAX_OPEN_POSITIONS) {
      return NextResponse.json({ error: `Maximum ${MAX_OPEN_POSITIONS} open positions allowed` }, { status: 400 });
    }
    
    const duplicate = portfolio.trades.find((t: any) => 
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
    
    const trade = {
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
    
    const portfolio = await readPortfolio(userId);
    const tradeIdx = portfolio.trades.findIndex((t: any) => t.id === tradeId);
    
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
  } catch (error) {
    console.error("Failed to close paper trade:", error);
    return NextResponse.json({ error: "Failed to close trade" }, { status: 500 });
  }
}
