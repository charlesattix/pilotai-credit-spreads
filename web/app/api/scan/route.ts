import { logger } from "@/lib/logger";
import { NextResponse } from "next/server";
import { execFile } from "child_process";
import { promisify } from "util";
import { join } from "path";
import { apiError } from "@/lib/api-error";

const execFilePromise = promisify(execFile);

const SCAN_RATE_LIMIT = 5;
const SCAN_RATE_WINDOW = 3600_000; // 1 hour in ms
const scanTimestamps: number[] = [];

let scanInProgress = false;

export async function POST() {
  // Rate limit check
  const now = Date.now();
  while (scanTimestamps.length > 0 && scanTimestamps[0] <= now - SCAN_RATE_WINDOW) {
    scanTimestamps.shift();
  }
  if (scanTimestamps.length >= SCAN_RATE_LIMIT) {
    return apiError("Rate limit exceeded: max 5 scans per hour", 429);
  }

  if (scanInProgress) {
    return apiError("A scan is already in progress", 409);
  }

  scanInProgress = true;
  scanTimestamps.push(now);
  try {
    const pythonDir = join(process.cwd(), "..");

    await execFilePromise("python3", ["main.py", "scan"], {
      cwd: pythonDir,
      timeout: 120000,
    });

    return NextResponse.json({ success: true, message: "Scan completed" });
  } catch (error: unknown) {
    const err = error as { message?: string; stderr?: string; code?: number };
    logger.error("Scan failed", {
      error: err.message || String(error),
      stderr: err.stderr?.slice(-500),
      exitCode: err.code,
    });
    return apiError("Scan failed", 500);
  } finally {
    scanInProgress = false;
  }
}
