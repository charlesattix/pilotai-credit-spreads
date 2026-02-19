import { NextRequest, NextResponse } from 'next/server'
import { writeFile, rename } from 'fs/promises'
import { existsSync } from 'fs'
import path from 'path'
import { DATA_DIR } from '@/lib/paths'

const DB_PATH = path.join(DATA_DIR, 'pilotai.db')

export async function POST(request: NextRequest) {
  // Verify auth token
  const authHeader = request.headers.get('authorization')
  const expectedToken = process.env.API_AUTH_TOKEN || process.env.RAILWAY_ADMIN_TOKEN
  
  if (!expectedToken) {
    return NextResponse.json({ error: 'Admin endpoint not configured' }, { status: 500 })
  }
  
  const providedToken = authHeader?.replace('Bearer ', '')
  if (providedToken !== expectedToken) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  try {
    // Get the uploaded file
    const formData = await request.formData()
    const file = formData.get('database') as File
    
    if (!file) {
      return NextResponse.json({ error: 'No database file provided' }, { status: 400 })
    }

    // Read file content
    const bytes = await file.arrayBuffer()
    const buffer = Buffer.from(bytes)

    // Backup existing database if it exists
    if (existsSync(DB_PATH)) {
      const backupPath = `${DB_PATH}.backup.${Date.now()}`
      await rename(DB_PATH, backupPath)
      console.log(`[upload-db] Backed up existing database to ${backupPath}`)
    }

    // Write new database
    await writeFile(DB_PATH, buffer)
    console.log(`[upload-db] Successfully wrote database to ${DB_PATH} (${buffer.length} bytes)`)

    return NextResponse.json({
      success: true,
      message: 'Database uploaded successfully',
      size: buffer.length,
      path: DB_PATH
    })

  } catch (error: any) {
    console.error('[upload-db] Upload failed:', error)
    return NextResponse.json({
      error: 'Upload failed',
      details: error?.message
    }, { status: 500 })
  }
}

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
