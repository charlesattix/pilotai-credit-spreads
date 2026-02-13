/**
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'

describe('Error Boundaries', () => {
  it('app/error.tsx exports a default component', () => {
    const errorPath = path.resolve(__dirname, '../app/error.tsx')
    expect(fs.existsSync(errorPath)).toBe(true)
    const content = fs.readFileSync(errorPath, 'utf-8')
    expect(content).toContain("'use client'")
    expect(content).toContain('export default')
    expect(content).toContain('reset')
  })

  it('app/global-error.tsx exports a default component', () => {
    const errorPath = path.resolve(__dirname, '../app/global-error.tsx')
    expect(fs.existsSync(errorPath)).toBe(true)
    const content = fs.readFileSync(errorPath, 'utf-8')
    expect(content).toContain("'use client'")
    expect(content).toContain('export default')
  })
})
