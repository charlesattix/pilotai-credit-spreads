/**
 * GET /api/experiments
 *
 * Serves the dashboard_export.json written by the Mac sync script
 * (scripts/sync_dashboard_data.py --push) from the Railway volume.
 *
 * Returns the export payload directly, with a staleness warning if the
 * data is older than 30 minutes.
 *
 * No auth required — read-only, no sensitive data beyond what's already
 * shown on the dashboard. Protect with verifyAuth() if needed in future.
 */
import { NextResponse } from 'next/server'
import { readFile } from 'fs/promises'
import { existsSync } from 'fs'
import path from 'path'
import { DATA_DIR } from '@/lib/paths'

const EXPORT_PATH    = path.join(DATA_DIR, 'dashboard_export.json')
const STALE_MINUTES  = 30

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET() {
  // ── Check file exists ──────────────────────────────────────────────────
  if (!existsSync(EXPORT_PATH)) {
    return NextResponse.json(
      {
        error:      'No data available yet',
        detail:     'dashboard_export.json not found. Run sync_dashboard_data.py --push on the Mac.',
        export_path: EXPORT_PATH,
      },
      { status: 404 }
    )
  }

  // ── Read and parse ─────────────────────────────────────────────────────
  let payload: Record<string, unknown>
  try {
    const raw = await readFile(EXPORT_PATH, 'utf-8')
    payload = JSON.parse(raw)
  } catch (err) {
    console.error('[experiments] Failed to read export file:', err)
    return NextResponse.json({ error: 'Failed to read export file' }, { status: 500 })
  }

  // ── Staleness check ────────────────────────────────────────────────────
  let stale = false
  let stale_minutes: number | null = null
  try {
    const generatedEpoch = payload.generated_epoch as number
    if (generatedEpoch) {
      stale_minutes = Math.floor((Date.now() / 1000 - generatedEpoch) / 60)
      stale         = stale_minutes > STALE_MINUTES
    }
  } catch {
    // ignore
  }

  // ── Response ───────────────────────────────────────────────────────────
  const response = NextResponse.json({
    ...payload,
    _meta: {
      served_at:     new Date().toISOString(),
      stale,
      stale_minutes,
      stale_threshold_minutes: STALE_MINUTES,
    },
  })

  // Short cache — allow CDN/browser to cache for 60s, but always revalidate
  response.headers.set('Cache-Control', 'public, max-age=60, must-revalidate')
  if (stale) {
    response.headers.set('X-Data-Stale', 'true')
    response.headers.set('X-Stale-Minutes', String(stale_minutes))
  }

  return response
}
