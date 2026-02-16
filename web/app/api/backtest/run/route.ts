import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server';
import { apiError } from "@/lib/api-error";
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { promises as fs } from 'fs';

const execFilePromise = promisify(execFile);

const BACKTEST_RATE_LIMIT = 3;
const BACKTEST_RATE_WINDOW = 3600_000; // 1 hour in ms
const backtestTimestamps: number[] = [];

let backtestInProgress = false;

export async function POST() {
  // Rate limit check
  const now = Date.now();
  while (backtestTimestamps.length > 0 && backtestTimestamps[0] <= now - BACKTEST_RATE_WINDOW) {
    backtestTimestamps.shift();
  }
  if (backtestTimestamps.length >= BACKTEST_RATE_LIMIT) {
    return apiError("Rate limit exceeded: max 3 backtests per hour", 429);
  }

  if (backtestInProgress) {
    return apiError("A backtest is already running", 409);
  }

  backtestInProgress = true;
  backtestTimestamps.push(now);
  try {
    const systemPath = path.join(process.cwd(), '..');

    await execFilePromise('python3', ['main.py', 'backtest'], {
      cwd: systemPath,
      timeout: 300000,
    });

    const backtestPath = path.join(systemPath, 'output/backtest_results.json');

    try {
      const data = await fs.readFile(backtestPath, 'utf-8');
      return NextResponse.json({
        success: true,
        ...JSON.parse(data),
      });
    } catch {
      return NextResponse.json({
        success: true,
        message: 'Backtest completed',
      });
    }
  } catch (error: unknown) {
    const err = error as { message?: string; stderr?: string; code?: number };
    logger.error('Backtest failed', {
      error: err.message || String(error),
      stderr: err.stderr?.slice(-500),
      exitCode: err.code,
    });
    return apiError("Backtest failed", 500);
  } finally {
    backtestInProgress = false;
  }
}
