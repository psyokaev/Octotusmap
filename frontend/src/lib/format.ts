// Backend trả thời gian UTC (ISO 'Z'); hiển thị theo Asia/Ho_Chi_Minh
const TZ = 'Asia/Ho_Chi_Minh'
const dtf = new Intl.DateTimeFormat('vi-VN', {
  timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
})
const tf = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false })
const nf = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 })

export const fmtDateTime = (iso?: string | null) => (iso ? dtf.format(new Date(iso)) : '—')
export const fmtTime = (iso?: string | null) => (iso ? tf.format(new Date(iso)) : '—')
export const fmtNum = (v?: number | null, unit = '') => (v === null || v === undefined ? '—' : `${nf.format(v)}${unit}`)
export const fmtPct = (v?: number | null) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`)

/** Chỉ nhận đường dẫn nội bộ cho redirect sau đăng nhập (chặn //host, /\host, URL tuyệt đối). */
export function safeNext(next: string | null): string | null {
  return next && /^\/(?![/\\])/.test(next) ? next : null
}

/** Chuyển giá trị input datetime-local (giờ VN) sang ISO UTC. */
export function vnLocalToIso(local: string): string {
  return new Date(`${local}:00+07:00`).toISOString()
}

/** Khoảng thời gian preset -> [from, to) ISO UTC, mốc theo giờ VN. */
export function presetRange(preset: string, custom?: { from: string; to: string }): { from: string; to: string } {
  const now = new Date()
  const vnMidnight = (d: Date) => {
    const s = new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(d)
    return new Date(`${s}T00:00:00+07:00`)
  }
  const day = 86400000
  switch (preset) {
    case 'today':
      return { from: vnMidnight(now).toISOString(), to: now.toISOString() }
    case '30d':
      return { from: new Date(now.getTime() - 30 * day).toISOString(), to: now.toISOString() }
    case 'month': {
      const m = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit' }).format(now)
      return { from: new Date(`${m}-01T00:00:00+07:00`).toISOString(), to: now.toISOString() }
    }
    case 'year': {
      const y = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric' }).format(now)
      return { from: new Date(`${y}-01-01T00:00:00+07:00`).toISOString(), to: now.toISOString() }
    }
    case 'custom':
      if (custom?.from && custom?.to)
        return { from: new Date(`${custom.from}T00:00:00+07:00`).toISOString(),
                 to: new Date(new Date(`${custom.to}T00:00:00+07:00`).getTime() + day).toISOString() }
      return presetRange('7d')
    default:
      return { from: new Date(now.getTime() - 7 * day).toISOString(), to: now.toISOString() }
  }
}
