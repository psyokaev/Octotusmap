import clsx from 'clsx'
import { ErrorState, Loading, useToast } from '../../components/ui'
import { PlaceSearch } from './PlaceSearch'
import { floodBadge, fmtDistance, fmtDuration, STATUS, type FloodStatus, type RouteSummary } from './routeStyle'

export interface Place { label: string; lon: number; lat: number }
export interface RouteSegment { geometry: GeoJSON.LineString; status: FloodStatus; probability: number; length_m: number; reasons: string[] }
export interface RouteOption {
  index: number; distance_m: number; duration_s: number; geometry: GeoJSON.LineString
  segments: RouteSegment[]; summary: RouteSummary
  steps: { instruction: string; name: string; distance_m: number; duration_s: number; location: [number, number] }[]
}
export interface RouteResult {
  routes: RouteOption[]; recommended_index: number; data_time: string | null
  active_reports: number; disclaimer: string; attribution: string; elevation_missing_ratio: number
}

export function DirectionsPanel({ start, end, setStart, setEnd, horizon, setHorizon, result, loading, error, retry, selected, setSelected, flyTo, onClose }: {
  start: Place | null; end: Place | null; setStart: (p: Place | null) => void; setEnd: (p: Place | null) => void
  horizon: number; setHorizon: (h: number) => void; result?: RouteResult; loading: boolean; error: unknown; retry: () => void
  selected: number; setSelected: (i: number) => void; flyTo: (c: number[]) => void; onClose: () => void
}) {
  const toast = useToast()
  const myLocation = () => navigator.geolocation.getCurrentPosition(
    (p) => setStart({ label: 'Vị trí của tôi', lon: p.coords.longitude, lat: p.coords.latitude }),
    () => toast('error', 'Không lấy được vị trí. Hãy cấp quyền vị trí hoặc chọn điểm trên bản đồ.'),
  )
  const route = result?.routes.find((r) => r.index === selected)
  const risky = route?.segments.filter((s) => s.status !== 'DRY') ?? []
  return (
    <div className="text-sm">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-base font-semibold">Chỉ đường</h2>
        <button className="btn-ghost px-2" onClick={onClose} aria-label="Đóng chỉ đường">✕</button>
      </div>
      <div className="flex gap-2">
        <div className="min-w-0 flex-1 space-y-2">
          <PlaceSearch label="Điểm đi" placeholder="Chọn điểm đi hoặc bấm trên bản đồ" value={start?.label}
            onPick={(r) => setStart({ label: r.label, lon: r.lon, lat: r.lat })} />
          <PlaceSearch label="Điểm đến" placeholder="Chọn điểm đến hoặc bấm trên bản đồ" value={end?.label}
            onPick={(r) => setEnd({ label: r.label, lon: r.lon, lat: r.lat })} />
        </div>
        <button className="btn-ghost self-center px-2" aria-label="Đổi chiều điểm đi và điểm đến"
          onClick={() => { setStart(end); setEnd(start) }}>⇅</button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {navigator.geolocation && <button className="btn-ghost" onClick={myLocation}>Vị trí của tôi</button>}
        <label className="flex items-center gap-1">
          <span>Khởi hành</span>
          <select className="input w-auto" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            <option value={0}>Bây giờ</option>
            {[1, 2, 3, 4, 5, 6].map((h) => <option key={h} value={h}>Sau {h} giờ</option>)}
          </select>
        </label>
      </div>

      {!start || !end ? (
        <p className="muted mt-3">Chọn đủ điểm đi và điểm đến để xem tuyến đường và các đoạn có thể ngập.</p>
      ) : loading ? <Loading rows={3} /> : error ? <ErrorState error={error} retry={retry} /> : result && (
        <>
          {result.elevation_missing_ratio > 0 && (
            <p role="alert" className="mt-3 rounded-lg border border-[#F29900] p-2 text-xs">
              Thiếu dữ liệu độ cao ở {Math.round(result.elevation_missing_ratio * 100)}% đoạn đường nên đánh giá ngập kém tin cậy. Thử lại sau ít phút.
            </p>
          )}
          <ul className="mt-3 space-y-2">
            {result.routes.map((r) => {
              const b = floodBadge(r.summary)
              return (
                <li key={r.index}>
                  <button aria-pressed={r.index === selected} onClick={() => setSelected(r.index)}
                    className={clsx('w-full rounded-lg border p-2.5 text-left', r.index === selected ? 'border-[#1A73E8] bg-[#1A73E8]/5' : 'border-[var(--line)]')}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-base font-semibold">{fmtDuration(r.duration_s)}</span>
                      <span className="muted">{fmtDistance(r.distance_m)}</span>
                    </div>
                    <div className="mt-0.5 font-medium" style={{ color: b.color }}>{b.text}</div>
                    {r.index === result.recommended_index && <div className="muted text-xs">Tuyến đề xuất</div>}
                  </button>
                </li>
              )
            })}
          </ul>

          <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {(Object.keys(STATUS) as FloodStatus[]).map((k) => (
              <span key={k} className="inline-flex items-center gap-1">
                <svg width="22" height="6" aria-hidden><line x1="0" y1="3" x2="22" y2="3" stroke={STATUS[k].color} strokeWidth="4" strokeDasharray={k === 'DRY' ? undefined : '6 3'} /></svg>
                {STATUS[k].label}
              </span>
            ))}
          </div>

          {risky.length > 0 && (
            <div className="mt-3">
              <h3 className="mb-1 font-semibold">Đoạn cần chú ý</h3>
              <ul className="space-y-1">
                {risky.map((s, i) => (
                  <li key={i}>
                    <button className="w-full rounded-md px-1 py-1 text-left hover:bg-black/5 dark:hover:bg-white/5"
                      onClick={() => flyTo(s.geometry.coordinates[Math.floor(s.geometry.coordinates.length / 2)])}>
                      <span className="font-medium" style={{ color: STATUS[s.status].color }}>{STATUS[s.status].label}</span>
                      <span className="muted"> · {fmtDistance(s.length_m)}</span>
                      {s.reasons.length > 0 && <div className="muted text-xs">{s.reasons.join('; ')}</div>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {route && (
            <div className="mt-3">
              <h3 className="mb-1 font-semibold">Hướng dẫn từng bước</h3>
              <ol className="divide-y divide-[var(--line)]">
                {route.steps.map((s, i) => (
                  <li key={i}>
                    <button className="flex w-full justify-between gap-3 py-1.5 text-left" onClick={() => flyTo(s.location)}>
                      <span>{s.instruction}</span>
                      {s.distance_m > 0 && <span className="muted num shrink-0">{fmtDistance(s.distance_m)}</span>}
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  )
}
