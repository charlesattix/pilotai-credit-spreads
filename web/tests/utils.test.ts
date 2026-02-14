import { describe, it, expect } from 'vitest'
import { formatCurrency, formatPercent, formatDate, formatDateTime, getScoreColor, getScoreBgColor } from '@/lib/utils'

describe('formatCurrency', () => {
  it('formats positive amount', () => {
    expect(formatCurrency(1234.56)).toBe('$1,234.56')
  })

  it('formats negative amount', () => {
    expect(formatCurrency(-500)).toBe('-$500.00')
  })

  it('formats zero', () => {
    expect(formatCurrency(0)).toBe('$0.00')
  })
})

describe('formatPercent', () => {
  it('formats positive with + prefix', () => {
    expect(formatPercent(12.5)).toBe('+12.50%')
  })

  it('formats negative without + prefix', () => {
    expect(formatPercent(-3.2)).toBe('-3.20%')
  })

  it('formats zero with + prefix', () => {
    expect(formatPercent(0)).toBe('+0.00%')
  })
})

describe('formatDate', () => {
  it('formats a date string', () => {
    const result = formatDate('2026-01-15')
    expect(result).toContain('Jan')
    expect(result).toContain('15')
    expect(result).toContain('2026')
  })
})

describe('formatDateTime', () => {
  it('formats a datetime string', () => {
    const result = formatDateTime('2026-01-15T14:30:00Z')
    expect(result).toContain('Jan')
    expect(result).toContain('15')
  })
})

describe('getScoreColor', () => {
  it('returns profit for score >= 70', () => {
    expect(getScoreColor(80)).toBe('text-profit')
  })

  it('returns yellow for score >= 60', () => {
    expect(getScoreColor(65)).toBe('text-yellow-500')
  })

  it('returns orange for score >= 50', () => {
    expect(getScoreColor(55)).toBe('text-orange-500')
  })

  it('returns loss for score < 50', () => {
    expect(getScoreColor(30)).toBe('text-loss')
  })
})

describe('getScoreBgColor', () => {
  it('returns profit bg for score >= 70', () => {
    expect(getScoreBgColor(75)).toContain('profit')
  })

  it('returns loss bg for score < 50', () => {
    expect(getScoreBgColor(40)).toContain('loss')
  })
})
