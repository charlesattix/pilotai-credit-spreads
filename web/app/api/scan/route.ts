import { NextResponse } from "next/server";
import { exec } from "child_process";
import { promisify } from "util";
import { join } from "path";

const execPromise = promisify(exec);

// Concurrency guard
let scanInProgress = false;

export async function POST() {
  if (scanInProgress) {
    return NextResponse.json({ success: false, error: "A scan is already in progress" }, { status: 409 });
  }

  scanInProgress = true;
  try {
    const pythonDir = join(process.cwd(), "..");
    const command = "python3 main.py scan";

    const { stdout, stderr } = await execPromise(command, {
      cwd: pythonDir,
      timeout: 120000,
    });

    return NextResponse.json({
      success: true,
      output: stdout,
      errors: stderr || null,
    });
  } catch (error: unknown) {
    const err = error as { message: string; stdout?: string; stderr?: string };
    return NextResponse.json(
      {
        success: false,
        error: err.message,
        output: err.stdout || null,
        errors: err.stderr || null,
      },
      { status: 500 }
    );
  } finally {
    scanInProgress = false;
  }
}
