import { describe, expect, it } from 'vitest'
import { presetRange, safeNext, vnLocalToIso } from './format'

describe('safeNext', () => {
  it('chấp nhận đường dẫn nội bộ', () => {
    expect(safeNext('/alerts?open=3')).toBe('/alerts?open=3')
  })
  it('chặn open redirect', () => {
    for (const bad of ['//evil.com', '/\\evil.com', 'https://evil.com', 'evil', '', null])
      expect(safeNext(bad)).toBeNull()
  })
})

describe('thời gian VN', () => {
  it('datetime-local giờ VN -> UTC', () => {
    expect(vnLocalToIso('2026-11-01T07:00')).toBe('2026-11-01T00:00:00.000Z')
  })
  it('preset tuỳ chọn bao gồm trọn ngày cuối', () => {
    const r = presetRange('custom', { from: '2026-10-01', to: '2026-10-31' })
    expect(r.from).toBe('2026-09-30T17:00:00.000Z')
    expect(r.to).toBe('2026-10-31T17:00:00.000Z')
  })
})
