/**
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'

describe('Production Readiness', () => {
  it('Dockerfile exists with multi-stage build', () => {
    const dockerPath = path.resolve(__dirname, '../Dockerfile')
    expect(fs.existsSync(dockerPath)).toBe(true)
    const content = fs.readFileSync(dockerPath, 'utf-8')
    expect(content).toContain('FROM')
    expect(content).toContain('npm')
    expect(content).toContain('EXPOSE')
  })

  it('.dockerignore exists', () => {
    const ignorePath = path.resolve(__dirname, '../.dockerignore')
    expect(fs.existsSync(ignorePath)).toBe(true)
    const content = fs.readFileSync(ignorePath, 'utf-8')
    expect(content).toContain('node_modules')
    expect(content).toContain('.next')
  })

  it('next.config.js has standalone output', () => {
    const configPath = path.resolve(__dirname, '../next.config.js')
    const content = fs.readFileSync(configPath, 'utf-8')
    expect(content).toContain('standalone')
  })

  it('.env.example exists with required vars documented', () => {
    const envPath = path.resolve(__dirname, '../../.env.example')
    expect(fs.existsSync(envPath)).toBe(true)
    const content = fs.readFileSync(envPath, 'utf-8')
    expect(content).toContain('ALPACA_API_KEY')
    expect(content).toContain('POLYGON_API_KEY')
  })

  it('middleware.ts exists with auth protection', () => {
    const mwPath = path.resolve(__dirname, '../middleware.ts')
    expect(fs.existsSync(mwPath)).toBe(true)
    const content = fs.readFileSync(mwPath, 'utf-8')
    expect(content).toContain('API_AUTH_TOKEN')
    expect(content).toContain('/api/health')
    expect(content).toContain('401')
  })
})
