import { NextResponse } from "next/server";
import { logger } from "@/lib/logger";
import { apiError } from "@/lib/api-error";
import { getAlerts } from "@/lib/database";
import { verifyAuth } from "@/lib/auth";

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    const dbAlerts = getAlerts(50);
    if (dbAlerts.length > 0) {
      return NextResponse.json({
        alerts: dbAlerts,
        opportunities: dbAlerts,
        timestamp: dbAlerts[0]?.created_at || new Date().toISOString(),
        count: dbAlerts.length,
      });
    }

    return NextResponse.json({ alerts: [], opportunities: [], count: 0 });
  } catch (error) {
    logger.error("Failed to read alerts", { error: String(error) });
    return apiError("Failed to read alerts", 500);
  }
}
