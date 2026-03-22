/**
 * POST /api/admin/push-experiments
 *
 * Receives a dashboard_export.json payload from the local Mac sync script
 * (scripts/sync_dashboard_data.py --push) and writes it to the Railway volume.
 *
 * Auth: Bearer token matching API_AUTH_TOKEN (same key used by upload-db).
 * Size limit: 10 MB (export is typically <200 KB).
 */
import { NextRequest, NextResponse } from 'next/server'
import { writeFile } from 'fs/promises'
import { timingSafeEqual } from 'crypto'
import path from 'path'
import { DATA_DIR } from '@/lib/paths'

const EXPORT_PATH    = path.join(DATA_DIR, 'dashboard_export.json')
const MAX_BODY_BYTES = 10 * 1024 * 1024 // 10 MB

const REQUIRED_FIELDS = ['schema_version', 'generated_at', 'experiments', 'summary'] as const

function timingSafeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) {
    const buf = Buffer.from(a)
    timingSafeEqual(buf, buf) // burn constant time
    return false
  }
  return timingSafeEqual(Buffer.from(a), Buffer.from(b))
}

export async function POST(request: NextRequest) {
  // ── Auth ────────────────────────────────────────────────────────────────
  const expectedToken = process.env.API_AUTH_TOKEN || process.env.RAILWAY_ADMIN_TOKEN
  if (!expectedToken) {
    return NextResponse.json({ error: 'Admin endpoint not configured' }, { status: 500 })
  }

  const authHeader    = request.headers.get('authorization') || ''
  const providedToken = authHeader.replace('Bearer ', '').trim()
  if (!providedToken || !timingSafeCompare(providedToken, expectedToken)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  // ── Size guard ──────────────────────────────────────────────────────────
  const contentLength = parseInt(request.headers.get('content-length') || '0', 10)
  if (contentLength > MAX_BODY_BYTES) {
    return NextResponse.json({ error: 'Payload too large' }, { status: 413 })
  }

  // ── Parse + validate ────────────────────────────────────────────────────
  let payload: Record<string, unknown>
  try {
    payload = await request.json()
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  for (const field of REQUIRED_FIELDS) {
    if (!(field in payload)) {
      return NextResponse.json(
        { error: `Missing required field: ${field}` },
        { status: 400 }
      )
    }
  }

  if (!Array.isArray(payload.experiments)) {
    return NextResponse.json({ error: 'experiments must be an array' }, { status: 400 })
  }

  // ── Write to volume ─────────────────────────────────────────────────────
  try {
    const json = JSON.stringify(payload, null, 2)
    await writeFile(EXPORT_PATH, json, 'utf-8')

    const expCount = (payload.experiments as unknown[]).length
    const summary  = payload.summary as Record<string, unknown>

    console.log(
      `[push-experiments] Wrote ${json.length} bytes — ` +
      `${expCount} experiments, ` +
      `${summary?.total_closed ?? '?'} closed trades, ` +
      `generated_at=${payload.generated_at}`
    )

    return NextResponse.json({
      success:       true,
      experiments:   expCount,
      generated_at:  payload.generated_at,
      bytes_written: json.length,
    })
  } catch (err) {
    console.error('[push-experiments] Write failed:', err)
    return NextResponse.json({ error: 'Failed to write export file' }, { status: 500 })
  }
}

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
