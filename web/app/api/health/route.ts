import { NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import { CONFIG_PATH } from '@/lib/paths'

// Prevent Next.js from caching this route — health checks must be fresh
export const dynamic = 'force-dynamic'

export async function GET() {
  const checks: Record<string, string> = {}
  try {
    await fs.access(CONFIG_PATH, fs.constants.R_OK)
    checks.config = 'ok'
  } catch {
    checks.config = 'unavailable'
  }

  // ALWAYS return 200 — Railway healthcheck rolls back deployment on non-200.
  // Use response body "status" field to indicate degraded components.
  return NextResponse.json({
    status: checks.config === 'ok' ? 'ok' : 'degraded',
    timestamp: new Date().toISOString(),
    version: process.env.npm_package_version || '1.0.0',
    build: process.env.RAILWAY_GIT_COMMIT_SHA?.substring(0, 7) || 'dev',
    checks,
  })
}
