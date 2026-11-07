import { describe, expect, it } from 'vitest'
import { formatBytes, formatRate, formatUptime } from '../src/utils/format'

describe('formatBytes', () => {
  it('formats small values', () => {
    expect(formatBytes(0)).toBe('0 Б')
    expect(formatBytes(500)).toBe('500 Б')
  })

  it('formats larger units', () => {
    expect(formatBytes(1024)).toBe('1.0 КБ')
    expect(formatBytes(1536)).toBe('1.5 КБ')
    expect(formatBytes(512 * 1024 * 1024)).toBe('512 МБ')
  })

  it('handles invalid input', () => {
    expect(formatBytes(-1)).toBe('—')
    expect(formatBytes(NaN)).toBe('—')
  })
})

describe('formatRate', () => {
  it('appends per second', () => {
    expect(formatRate(1024)).toBe('1.0 КБ/с')
  })

  it('handles invalid input', () => {
    expect(formatRate(-5)).toBe('—')
  })
})

describe('formatUptime', () => {
  it('formats days, hours and minutes', () => {
    expect(formatUptime(90061)).toBe('1 д 1 ч 1 мин')
  })

  it('formats minutes only', () => {
    expect(formatUptime(59)).toBe('0 мин')
    expect(formatUptime(600)).toBe('10 мин')
  })

  it('handles invalid input', () => {
    expect(formatUptime(-1)).toBe('—')
  })
})
