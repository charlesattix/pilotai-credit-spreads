import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import path from "path";
import { logger } from "@/lib/logger";
import { getAlerts } from "@/lib/database";
import { DATA_DIR, OUTPUT_DIR } from "@/lib/paths";

async function tryReadJsonFile(...paths: string[]): Promise<string | null> {
  for (const p of paths) {
    try { return await readFile(p, "utf-8"); } catch {}
  }
  return null;
}

export async function GET() {
  try {
    // Primary: read from SQLite
    const dbAlerts = getAlerts(50);
    if (dbAlerts.length > 0) {
      return NextResponse.json({
        alerts: dbAlerts,
        opportunities: dbAlerts,
        timestamp: dbAlerts[0]?.created_at || new Date().toISOString(),
        count: dbAlerts.length,
      });
    }

    // Fallback: read from JSON file during transition
    const content = await tryReadJsonFile(
      path.join(DATA_DIR, "alerts.json"),
      path.join(process.cwd(), "public", "data", "alerts.json"),
      path.join(OUTPUT_DIR, "alerts.json"),
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
