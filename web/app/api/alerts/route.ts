import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import path from "path";
import { logger } from "@/lib/logger";

async function tryRead(...paths: string[]): Promise<string | null> {
  for (const p of paths) {
    try { return await readFile(p, "utf-8"); } catch {}
  }
  return null;
}

export async function GET() {
  try {
    const cwd = process.cwd();
    const content = await tryRead(
      path.join(cwd, "data", "alerts.json"),
      path.join(cwd, "public", "data", "alerts.json"),
      path.join(cwd, "..", "output", "alerts.json"),
    );
    if (!content) return NextResponse.json({ alerts: [], opportunities: [], count: 0 });

    const data = JSON.parse(content);
    const opportunities = data.opportunities || [];

    return NextResponse.json({
      alerts: opportunities,
      opportunities,
      timestamp: data.timestamp,
      count: opportunities.length,
    });
  } catch (error) {
    logger.error("Failed to read alerts", { error: String(error) });
    return NextResponse.json({ alerts: [], opportunities: [], count: 0 });
  }
}
