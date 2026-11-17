export type Risk = 'LOW' | 'MEDIUM' | 'HIGH' | 'INSUFFICIENT_DATA' | 'NO_DATA'

// Màu + ký hiệu hình dạng (không chỉ dựa vào màu)
export const RISK: Record<Risk, { color: string; label: string; symbol: string }> = {
  LOW: { color: '#2E8B57', label: 'Thấp', symbol: '●' },
  MEDIUM: { color: '#D99A00', label: 'Trung bình', symbol: '▲' },
  HIGH: { color: '#C62828', label: 'Cao', symbol: '◆' },
  INSUFFICIENT_DATA: { color: '#8A949C', label: 'Không đủ dữ liệu', symbol: '○' },
  NO_DATA: { color: '#8A949C', label: 'Không có dữ liệu', symbol: '○' },
}

export const riskOf = (r?: string | null): Risk => (r && r in RISK ? (r as Risk) : 'NO_DATA')

export const STATUS_VI: Record<string, string> = {
  NEW: 'Mới', ACKNOWLEDGED: 'Đã tiếp nhận', IN_PROGRESS: 'Đang xử lý', RESOLVED: 'Đã xử lý', CLOSED: 'Đã đóng',
}

export const DATA_STATUS_VI: Record<string, string> = {
  DEMO: 'DEMO/mô phỏng', LIVE: 'Trực tiếp', STALE: 'Dữ liệu cũ', UNAVAILABLE: 'Không có dữ liệu',
}

export const CAUSE_VI: Record<string, string> = { RAIN: 'Mưa', TIDE: 'Triều cường', RAIN_TIDE: 'Mưa kết hợp triều', OTHER: 'Khác' }

const FLOOD_CAUSE: Record<string, string> = {
  TIDE: 'Ngập do triều', RAIN: 'Ngập do mưa', RAIN_TIDE: 'Ngập do mưa kết hợp triều', REPORT: 'Người dân báo ngập', CAMERA: 'Camera phát hiện ngập (mô hình thử nghiệm, tham khảo)',
}

/** Nguyên nhân ngập + độ sâu ước tính (cm); null khi không có nguyên nhân. */
export function floodCause(cause?: string | null, depthCm?: number | null): string | null {
  const phrase = cause ? FLOOD_CAUSE[cause] : undefined
  if (!phrase) return null
  return depthCm != null ? `${phrase}, khoảng ${depthCm} cm (ước tính)` : phrase
}
