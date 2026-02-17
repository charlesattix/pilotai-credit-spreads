import { logger } from "@/lib/logger";
import { NextResponse } from "next/server";
import { execFile } from "child_process";
import { promisify } from "util";
import { apiError } from "@/lib/api-error";
import { PROJECT_ROOT } from "@/lib/paths";
import { checkRateLimit, acquireProcessLock, releaseProcessLock } from "@/lib/database";

const execFilePromise = promisify(execFile);

const SCAN_RATE_LIMIT = 5;
const SCAN_RATE_WINDOW = 3600_000; // 1 hour in ms
const SCAN_LOCK_TIMEOUT = 150_000; // 2.5 min (scan timeout is 2 min)

export async function POST() {
  if (!checkRateLimit("scan", SCAN_RATE_LIMIT, SCAN_RATE_WINDOW)) {
    return apiError("Rate limit exceeded: max 5 scans per hour", 429);
  }

  if (!acquireProcessLock("scan", SCAN_LOCK_TIMEOUT)) {
    return apiError("A scan is already in progress", 409);
  }

  try {
    await execFilePromise("python3", ["main.py", "scan"], {
      cwd: PROJECT_ROOT,
      timeout: 120000,
      env: { ...process.env },
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
    releaseProcessLock("scan");
  }
}
