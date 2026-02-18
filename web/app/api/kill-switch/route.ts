import { NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'
import { apiError } from '@/lib/api-error'
import { logger } from '@/lib/logger'
import { DATA_DIR } from '@/lib/paths'
import { verifyAuth } from '@/lib/auth'

const KILL_SWITCH_PATH = path.join(DATA_DIR, 'kill_switch.json')

export async function GET(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    await fs.access(KILL_SWITCH_PATH)
    const content = await fs.readFile(KILL_SWITCH_PATH, 'utf-8')
    const data = JSON.parse(content)
    return NextResponse.json({ active: true, ...data })
  } catch {
    return NextResponse.json({ active: false })
  }
}

export async function POST(request: Request) {
  const authErr = await verifyAuth(request); if (authErr) return authErr;
  try {
    const body = await request.json()
    const { action, reason } = body

    if (action !== 'activate' && action !== 'deactivate') {
      return apiError('action must be "activate" or "deactivate"', 400)
    }

    if (action === 'activate') {
      const data = {
        activated_at: new Date().toISOString(),
        reason: reason || 'Manual activation',
      }
      await fs.mkdir(path.dirname(KILL_SWITCH_PATH), { recursive: true })
      await fs.writeFile(KILL_SWITCH_PATH, JSON.stringify(data, null, 2))
      logger.warn('Kill switch ACTIVATED', { reason: data.reason })
      return NextResponse.json({ active: true, ...data })
    } else {
      try {
        await fs.unlink(KILL_SWITCH_PATH)
      } catch {
        // File didn't exist — already deactivated
      }
      logger.info('Kill switch deactivated')
      return NextResponse.json({ active: false })
    }
  } catch (error) {
    logger.error('Kill switch error', { error: String(error) })
    return apiError('Kill switch operation failed', 500)
  }
}
