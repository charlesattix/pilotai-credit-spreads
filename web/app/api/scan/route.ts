import { NextResponse } from "next/server";
import { exec } from "child_process";
import { promisify } from "util";
import { join } from "path";

const execPromise = promisify(exec);

export async function POST() {
  try {
    const pythonDir = join(process.cwd(), "..");
    const command = "python3 main.py scan";

    const { stdout, stderr } = await execPromise(command, {
      cwd: pythonDir,
      timeout: 120000, // 2 minute timeout
    });

    return NextResponse.json({
      success: true,
      output: stdout,
      errors: stderr || null,
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: error.message,
        output: error.stdout || null,
        errors: error.stderr || null,
      },
      { status: 500 }
    );
  }
}
