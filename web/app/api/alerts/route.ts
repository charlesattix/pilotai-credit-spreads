import { NextResponse } from "next/server";
import path from "path";
import { logger } from "@/lib/logger";
import { apiError } from "@/lib/api-error";
import { getAlerts } from "@/lib/database";
import { DATA_DIR, OUTPUT_DIR } from "@/lib/paths";
import { tryReadFile } from "@/lib/fs-utils";
import { verifyAuth } from "@/lib/auth";

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
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
    const content = await tryReadFile(
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
    return apiError("Failed to read alerts", 500);
  }
}
