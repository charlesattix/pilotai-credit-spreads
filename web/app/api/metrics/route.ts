import { NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'
import { apiError } from '@/lib/api-error'
import { logger } from '@/lib/logger'
import { DATA_DIR } from '@/lib/paths'
import { verifyAuth } from '@/lib/auth'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    const metricsPath = path.join(DATA_DIR, 'metrics.json')
    const data = await fs.readFile(metricsPath, 'utf-8')
    return NextResponse.json(JSON.parse(data))
  } catch {
    return NextResponse.json({ counters: {}, gauges: {}, timestamp: null })
  }
}
