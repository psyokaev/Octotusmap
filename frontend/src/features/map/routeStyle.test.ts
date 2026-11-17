import { describe, expect, it } from 'vitest'
import { floodBadge, fmtDistance, fmtDuration, STATUS, type RouteSummary } from './routeStyle'

const summary = (km: Partial<RouteSummary['km_by_status']>): RouteSummary => {
  const k = { DRY: 0, AT_RISK: 0, LIKELY_FLOODED: 0, REPORTED_FLOODED: 0, ...km }
  return { km_by_status: k, flooded_km: k.LIKELY_FLOODED + k.REPORTED_FLOODED, at_risk_km: k.AT_RISK, max_probability: 0 }
}

describe('floodBadge', () => {
  it('ưu tiên báo cáo của người dân', () => {
    const b = floodBadge(summary({ REPORTED_FLOODED: 0.2, LIKELY_FLOODED: 3 }))
    expect(b.text).toContain('báo cáo')
    expect(b.color).toBe(STATUS.REPORTED_FLOODED.color)
  })
  it('xếp mức ngập trước mức nguy cơ', () => {
    expect(floodBadge(summary({ LIKELY_FLOODED: 1.25, AT_RISK: 4 })).text).toBe('1.3 km có thể ngập')
    expect(floodBadge(summary({ AT_RISK: 4 })).text).toBe('4.0 km có nguy cơ ngập')
  })
  it('tuyến khô', () => {
    expect(floodBadge(summary({ DRY: 9 })).text).toBe('Không có đoạn ngập')
  })
})

describe('định dạng', () => {
  it('thời gian và quãng đường', () => {
    expect(fmtDuration(720)).toBe('12 phút')
    expect(fmtDuration(4500)).toBe('1 giờ 15 phút')
    expect(fmtDistance(240)).toBe('240 m')
    expect(fmtDistance(9100)).toBe('9.1 km')
  })
})
