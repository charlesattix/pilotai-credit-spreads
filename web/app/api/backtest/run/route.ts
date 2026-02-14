import { logger } from "@/lib/logger"
import { NextResponse } from 'next/server';
import { apiError } from "@/lib/api-error";
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { promises as fs } from 'fs';

const execFilePromise = promisify(execFile);

let backtestInProgress = false;

export async function POST() {
  if (backtestInProgress) {
    return apiError("A backtest is already running", 409);
  }

  backtestInProgress = true;
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
    const err = error as { message: string };
    logger.error('Backtest failed', { error: String(err) });
    return apiError("Backtest failed", 500);
  } finally {
    backtestInProgress = false;
  }
}
