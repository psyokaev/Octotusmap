import { describe, expect, it } from 'vitest'
import { asUtc, groupFor, metric } from './analytics'

const r = (days: number) => ({ from: '2026-01-01T00:00:00Z', to: new Date(Date.parse('2026-01-01T00:00:00Z') + days * 86_400_000).toISOString() })

describe('analytics helpers', () => {
  it('groupFor chọn nhóm theo preset / độ dài khoảng', () => {
    expect(groupFor('today', r(1))).toBe('hour')
    expect(groupFor('7d', r(7))).toBe('day')
    expect(groupFor('30d', r(30))).toBe('day')
    expect(groupFor('year', r(300))).toBe('month')
    expect(groupFor('custom', r(2))).toBe('hour')
    expect(groupFor('custom', r(200))).toBe('month')
  })
  it('metric đọc đường dẫn lồng và trả null khi thiếu', () => {
    const m = { rainfall: { mae: 0.5 }, flood: { f1: 0 } }
    expect(metric(m, 'rainfall.mae')).toBe(0.5)
    expect(metric(m, 'flood.f1')).toBe(0)
    expect(metric(m, 'flood.roc_auc')).toBeNull()
    expect(metric(null, 'x.y')).toBeNull()
  })
  it('asUtc chỉ thêm Z khi thiếu múi giờ', () => {
    expect(asUtc('2026-01-01T10:00:00')).toBe('2026-01-01T10:00:00Z')
    expect(asUtc('2026-01-01T10:00:00Z')).toBe('2026-01-01T10:00:00Z')
    expect(asUtc('2026-01-01T10:00:00+07:00')).toBe('2026-01-01T10:00:00+07:00')
    expect(asUtc(null)).toBeNull()
  })
})
