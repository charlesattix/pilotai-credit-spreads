import { NextRequest, NextResponse } from 'next/server'
import { writeFile, rename } from 'fs/promises'
import { existsSync } from 'fs'
import { timingSafeEqual } from 'crypto'
import path from 'path'
import { DATA_DIR } from '@/lib/paths'
import { resetDb } from '@/lib/database'

const DB_PATH = path.join(DATA_DIR, 'pilotai.db')

// SQLite files start with this 16-byte header string
const SQLITE_MAGIC = Buffer.from('SQLite format 3\0')
const MAX_UPLOAD_SIZE = 100 * 1024 * 1024 // 100 MB

function timingSafeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) {
    // Compare against self to burn constant time, then return false
    const buf = Buffer.from(a)
    timingSafeEqual(buf, buf)
    return false
  }
  return timingSafeEqual(Buffer.from(a), Buffer.from(b))
}

export async function POST(request: NextRequest) {
  // Verify auth token using timing-safe comparison
  const authHeader = request.headers.get('authorization')
  const expectedToken = process.env.API_AUTH_TOKEN || process.env.RAILWAY_ADMIN_TOKEN

  if (!expectedToken) {
    return NextResponse.json({ error: 'Admin endpoint not configured' }, { status: 500 })
  }

  const providedToken = authHeader?.replace('Bearer ', '') || ''
  if (!providedToken || !timingSafeCompare(providedToken, expectedToken)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  try {
    // Get the uploaded file
    const formData = await request.formData()
    const file = formData.get('database') as File

    if (!file) {
      return NextResponse.json({ error: 'No database file provided' }, { status: 400 })
    }

    // Enforce file size limit
    if (file.size > MAX_UPLOAD_SIZE) {
      return NextResponse.json(
        { error: `File too large. Maximum size is ${MAX_UPLOAD_SIZE / 1024 / 1024} MB` },
        { status: 413 }
      )
    }

    // Read file content
    const bytes = await file.arrayBuffer()
    const buffer = Buffer.from(bytes)

    // Validate SQLite file header
    if (buffer.length < 16 || !buffer.subarray(0, 16).equals(SQLITE_MAGIC)) {
      return NextResponse.json(
        { error: 'Invalid file: not a valid SQLite database' },
        { status: 400 }
      )
    }

    // Backup existing database if it exists
    if (existsSync(DB_PATH)) {
      const backupPath = `${DB_PATH}.backup.${Date.now()}`
      await rename(DB_PATH, backupPath)
      console.log(`[upload-db] Backed up existing database to ${backupPath}`)
    }

    // Invalidate cached DB connection before replacing the file
    resetDb()

    // Write new database
    await writeFile(DB_PATH, buffer)
    console.log(`[upload-db] Successfully wrote database (${buffer.length} bytes)`)

    return NextResponse.json({
      success: true,
      message: 'Database uploaded successfully',
      size: buffer.length,
    })

  } catch (error: unknown) {
    console.error('[upload-db] Upload failed:', error)
    return NextResponse.json({
      error: 'Upload failed',
    }, { status: 500 })
  }
}

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
