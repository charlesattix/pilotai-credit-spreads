import { NextResponse } from 'next/server'

export function apiError(message: string, status: number, details?: unknown) {
  return NextResponse.json({ error: message, details, success: false }, { status })
}
