import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { promises as fs } from 'fs';

const execPromise = promisify(exec);

// Concurrency guard
let backtestInProgress = false;

export async function POST() {
  if (backtestInProgress) {
    return NextResponse.json({ success: false, error: "A backtest is already running" }, { status: 409 });
  }

  backtestInProgress = true;
  try {
    const systemPath = path.join(process.cwd(), '..');

    const { stdout, stderr } = await execPromise('python3 main.py backtest', {
      cwd: systemPath,
      timeout: 300000,
    });

    if (stderr) {
      console.error('Backtest stderr:', stderr);
    }

    const backtestPath = path.join(systemPath, 'output/backtest_results.json');

    try {
      const data = await fs.readFile(backtestPath, 'utf-8');
      return NextResponse.json({
        success: true,
        ...JSON.parse(data),
        stdout,
      });
    } catch {
      return NextResponse.json({
        success: true,
        message: 'Backtest completed',
        stdout,
      });
    }
  } catch (error: unknown) {
    const err = error as { message: string };
    console.error('Backtest failed:', err);
    return NextResponse.json(
      { success: false, error: err.message },
      { status: 500 }
    );
  } finally {
    backtestInProgress = false;
  }
}
