import { NextResponse } from 'next/server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import { promises as fs } from 'fs'

const execPromise = promisify(exec)

export async function POST() {
  try {
    const systemPath = path.join(process.cwd(), '..')
    
    // Run the backtest command
    const { stdout, stderr } = await execPromise('python3 main.py backtest', {
      cwd: systemPath,
      timeout: 300000, // 5 minute timeout
    })
    
    if (stderr) {
      console.error('Backtest stderr:', stderr)
    }
    
    // Try to read the results
    const backtestPath = path.join(systemPath, 'output/backtest_results.json')
    
    try {
      const data = await fs.readFile(backtestPath, 'utf-8')
      return NextResponse.json({
        success: true,
        ...JSON.parse(data),
        stdout,
      })
    } catch {
      // If no JSON results, return stdout
      return NextResponse.json({
        success: true,
        message: 'Backtest completed',
        stdout,
      })
    }
  } catch (error: any) {
    console.error('Backtest failed:', error)
    return NextResponse.json(
      { success: false, error: error.message },
      { status: 500 }
    )
  }
}
