import { NextResponse } from "next/server";
import { execFile } from "child_process";
import { promisify } from "util";
import { join } from "path";
import { apiError } from "@/lib/api-error";

const execFilePromise = promisify(execFile);

let scanInProgress = false;

export async function POST() {
  if (scanInProgress) {
    return apiError("A scan is already in progress", 409);
  }

  scanInProgress = true;
  try {
    const pythonDir = join(process.cwd(), "..");

    await execFilePromise("python3", ["main.py", "scan"], {
      cwd: pythonDir,
      timeout: 120000,
    });

    return NextResponse.json({ success: true, message: "Scan completed" });
  } catch {
    return apiError("Scan failed", 500);
  } finally {
    scanInProgress = false;
  }
}
