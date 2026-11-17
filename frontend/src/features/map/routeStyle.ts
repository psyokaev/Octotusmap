export type FloodStatus = 'DRY' | 'AT_RISK' | 'LIKELY_FLOODED' | 'REPORTED_FLOODED'

export const STATUS: Record<FloodStatus, { color: string; label: string }> = {
  DRY: { color: '#1A73E8', label: 'Không có dấu hiệu ngập' },
  AT_RISK: { color: '#F29900', label: 'Có nguy cơ ngập' },
  LIKELY_FLOODED: { color: '#D93025', label: 'Có thể đang ngập' },
  REPORTED_FLOODED: { color: '#8E24AA', label: 'Người dân báo ngập' },
}

export const SEVERITY: Record<string, string> = { ANKLE: 'Ngập mắt cá', KNEE: 'Ngập đầu gối', DEEP: 'Ngập sâu' }

export interface RouteSummary {
  km_by_status: Record<FloodStatus, number>
  flooded_km: number
  at_risk_km: number
  max_probability: number
}

/** Tóm tắt tình trạng ngập của một tuyến, dùng trên thẻ tuyến đường. */
export function floodBadge(s: RouteSummary): { text: string; color: string } {
  if (s.km_by_status.REPORTED_FLOODED > 0)
    return { text: `${s.km_by_status.REPORTED_FLOODED.toFixed(1)} km có báo cáo ngập`, color: STATUS.REPORTED_FLOODED.color }
  if (s.flooded_km > 0) return { text: `${s.flooded_km.toFixed(1)} km có thể ngập`, color: STATUS.LIKELY_FLOODED.color }
  if (s.at_risk_km > 0) return { text: `${s.at_risk_km.toFixed(1)} km có nguy cơ ngập`, color: STATUS.AT_RISK.color }
  return { text: 'Không có đoạn ngập', color: '#188038' }
}

export function fmtDuration(seconds: number): string {
  const m = Math.round(seconds / 60)
  return m < 60 ? `${m} phút` : `${Math.floor(m / 60)} giờ ${m % 60} phút`
}

export function fmtDistance(meters: number): string {
  return meters < 1000 ? `${Math.round(meters / 10) * 10} m` : `${(meters / 1000).toFixed(1)} km`
}
