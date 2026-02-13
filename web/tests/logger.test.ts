import { describe, it, expect, vi } from 'vitest'
import { logger } from '@/lib/logger'

describe('structured logger', () => {
  it('logger.info outputs valid JSON', () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    logger.info('test message', { key: 'value' })
    expect(spy).toHaveBeenCalledOnce()
    const output = JSON.parse(spy.mock.calls[0][0])
    expect(output.level).toBe('info')
    expect(output.msg).toBe('test message')
    expect(output.key).toBe('value')
    expect(output.ts).toBeDefined()
    spy.mockRestore()
  })

  it('logger.error outputs valid JSON with error level', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    logger.error('bad thing', { code: 500 })
    const output = JSON.parse(spy.mock.calls[0][0])
    expect(output.level).toBe('error')
    expect(output.msg).toBe('bad thing')
    expect(output.code).toBe(500)
    spy.mockRestore()
  })

  it('logger.warn outputs valid JSON with warn level', () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    logger.warn('caution')
    const output = JSON.parse(spy.mock.calls[0][0])
    expect(output.level).toBe('warn')
    expect(output.msg).toBe('caution')
    spy.mockRestore()
  })

  it('timestamp is valid ISO string', () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    logger.info('ts test')
    const output = JSON.parse(spy.mock.calls[0][0])
    expect(() => new Date(output.ts).toISOString()).not.toThrow()
    spy.mockRestore()
  })
})
