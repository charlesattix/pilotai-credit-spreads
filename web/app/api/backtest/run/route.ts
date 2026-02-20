import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server';
import { apiError } from "@/lib/api-error";
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { promises as fs } from 'fs';
import { PROJECT_ROOT, OUTPUT_DIR } from "@/lib/paths";
import { checkRateLimit, acquireProcessLock, releaseProcessLock } from "@/lib/database";
import { verifyAuth } from "@/lib/auth";

const execFilePromise = promisify(execFile);

const BACKTEST_RATE_LIMIT = 3;
const BACKTEST_RATE_WINDOW = 3600_000; // 1 hour in ms
const BACKTEST_LOCK_TIMEOUT = 330_000; // 5.5 min (backtest timeout is 5 min)

const ALLOWED_TICKERS = ['SPY', 'QQQ', 'IWM', 'DIA', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META', 'GOOGL'];

export async function POST(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  if (!checkRateLimit("backtest", BACKTEST_RATE_LIMIT, BACKTEST_RATE_WINDOW)) {
    return apiError("Rate limit exceeded: max 3 backtests per hour", 429);
  }

  if (!acquireProcessLock("backtest", BACKTEST_LOCK_TIMEOUT)) {
    return apiError("A backtest is already running. Please wait for it to finish.", 409);
  }

  let body: { ticker?: string; days?: number; clear_cache?: boolean } = {};
  try {
    body = await request.json();
  } catch {
    // Use defaults
  }

  const ticker = (body.ticker || 'SPY').toUpperCase();
  const days = Math.min(Math.max(body.days || 365, 30), 2000);
  const clearCache = body.clear_cache || false;

  // Validate ticker
  if (!ALLOWED_TICKERS.includes(ticker)) {
    releaseProcessLock("backtest");
    return apiError(`Invalid ticker: ${ticker}`, 400);
  }

  try {
    const args = ['main.py', 'backtest', '--ticker', ticker, '--days', String(days)];
    if (clearCache) {
      args.push('--clear-cache');
    }

    logger.info(`Starting backtest: ${ticker}, ${days} days`, { ticker, days, clearCache });

    await execFilePromise('python3', args, {
      cwd: PROJECT_ROOT,
      timeout: 300000, // 5 minutes
      env: { ...process.env },
    });

    // Read the canonical results file written by Python
    const backtestPath = path.join(OUTPUT_DIR, 'backtest_results.json');

    try {
      const data = await fs.readFile(backtestPath, 'utf-8');
      const results = JSON.parse(data);
      return NextResponse.json({
        success: true,
        ticker,
        days,
        ...results,
      });
    } catch {
      return NextResponse.json({
        success: true,
        message: 'Backtest completed but results file not found',
        ticker,
        days,
      });
    }
  } catch (error: unknown) {
    const err = error as { message?: string; stderr?: string; code?: number };
    logger.error('Backtest failed', {
      error: err.message || String(error),
      stderr: err.stderr?.slice(-500),
      exitCode: err.code,
    });
    return apiError(`Backtest failed: ${err.message || 'Unknown error'}`, 500);
  } finally {
    releaseProcessLock("backtest");
  }
}
