import { NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'

export async function GET() {
  const checks: Record<string, string> = {}
  let healthy = true
  try {
    await fs.access(path.join(process.cwd(), '..', 'config.yaml'), fs.constants.R_OK)
    checks.config = 'ok'
  } catch {
    checks.config = 'unavailable'
    healthy = false
  }
  return NextResponse.json({
    status: healthy ? 'ok' : 'degraded',
    timestamp: new Date().toISOString(),
    version: process.env.npm_package_version || '1.0.0',
    checks,
  }, { status: healthy ? 200 : 503 })
}
