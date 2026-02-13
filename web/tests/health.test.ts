/**
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'

describe('Health Endpoint', () => {
  it('health route file exists and exports GET handler', () => {
    const healthPath = path.resolve(__dirname, '../app/api/health/route.ts')
    expect(fs.existsSync(healthPath)).toBe(true)
    const content = fs.readFileSync(healthPath, 'utf-8')
    expect(content).toContain('export async function GET')
    expect(content).toContain('status')
    expect(content).toContain('ok')
  })
})
