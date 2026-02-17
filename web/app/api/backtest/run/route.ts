import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server';
import { apiError } from "@/lib/api-error";
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { promises as fs } from 'fs';
import { PROJECT_ROOT, OUTPUT_DIR } from "@/lib/paths";
import { checkRateLimit, acquireProcessLock, releaseProcessLock } from "@/lib/database";

const execFilePromise = promisify(execFile);

const BACKTEST_RATE_LIMIT = 3;
const BACKTEST_RATE_WINDOW = 3600_000; // 1 hour in ms
const BACKTEST_LOCK_TIMEOUT = 330_000; // 5.5 min (backtest timeout is 5 min)

export async function POST() {
  if (!checkRateLimit("backtest", BACKTEST_RATE_LIMIT, BACKTEST_RATE_WINDOW)) {
    return apiError("Rate limit exceeded: max 3 backtests per hour", 429);
  }

  if (!acquireProcessLock("backtest", BACKTEST_LOCK_TIMEOUT)) {
    return apiError("A backtest is already running", 409);
  }

  try {
    await execFilePromise('python3', ['main.py', 'backtest'], {
      cwd: PROJECT_ROOT,
      timeout: 300000,
    });

    const backtestPath = path.join(OUTPUT_DIR, 'backtest_results.json');

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
    releaseProcessLock("backtest");
  }
}
