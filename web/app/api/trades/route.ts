import { NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'

export async function GET() {
  try {
    const tradesPath = path.join(process.cwd(), '../data/trades.json')
    const data = await fs.readFile(tradesPath, 'utf-8')
    return NextResponse.json(JSON.parse(data))
  } catch (error) {
    console.error('Failed to read trades:', error)
    return NextResponse.json([], { status: 200 })
  }
}
