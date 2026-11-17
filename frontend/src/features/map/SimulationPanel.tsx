import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useToast } from '../../components/ui'
import { api } from '../../lib/api'

export interface FloodSimulation { id: number; latitude: number; longitude: number; radius_m: number; depth_cm: number }

export const useSimulations = (enabled: boolean) =>
  useQuery({ queryKey: ['simulations'], enabled, queryFn: () => api.get<FloodSimulation[]>('/admin/simulations') })

/** Đa giác xấp xỉ vòng tròn (lon, lat) để vẽ vùng ngập mô phỏng. */
export function circlePolygon(lon: number, lat: number, radiusM: number, steps = 64): GeoJSON.Polygon {
  const dLat = radiusM / 111_320
  const dLon = dLat / Math.cos((lat * Math.PI) / 180)
  const ring = Array.from({ length: steps + 1 }, (_, i) => {
    const a = (i / steps) * 2 * Math.PI
    return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]
  })
  return { type: 'Polygon', coordinates: [ring] }
}

/** Admin bấm bản đồ để chọn tâm; chỉ tài khoản admin thấy và tuyến của admin mới bị ảnh hưởng. */
export function SimulationPanel({ point, radius, setRadius, onClose }: {
  point: { lon: number; lat: number } | null; radius: number; setRadius: (r: number) => void; onClose: () => void
}) {
  const toast = useToast()
  const qc = useQueryClient()
  const list = useSimulations(true)
  const [depth, setDepth] = useState(40)
  const [busy, setBusy] = useState(false)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['simulations'] }); qc.invalidateQueries({ queryKey: ['route'] }) }
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try { await fn(); refresh() } catch (e) { toast('error', (e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Mô phỏng ngập</h2>
        <button className="btn-ghost px-2" onClick={onClose} aria-label="Đóng mô phỏng">✕</button>
      </div>
      <p className="muted">{point ? `Tâm: ${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}` : 'Bấm lên bản đồ để chọn tâm vùng ngập.'}</p>
      <label className="block">
        <span className="label">Bán kính: {radius} m</span>
        <input type="range" className="w-full" min={100} max={2000} step={50} value={radius} onChange={(e) => setRadius(Number(e.target.value))} />
      </label>
      <label className="block">
        <span className="label">Độ sâu (cm)</span>
        <input type="number" className="input" min={1} max={300} value={depth} onChange={(e) => setDepth(Number(e.target.value))} />
      </label>
      <button className="btn-primary w-full" disabled={!point || busy || depth < 1 || depth > 300} onClick={() => run(() =>
        api.post('/admin/simulations', { latitude: point!.lat, longitude: point!.lon, radius_m: radius, depth_cm: depth }))}>
        Tạo vùng ngập
      </button>
      {!!list.data?.length && (
        <div>
          <div className="mb-1 flex items-center justify-between font-medium">
            <span>Đang mô phỏng ({list.data.length})</span>
            <button className="text-sm text-risk-high" disabled={busy} onClick={() => run(() => api.del('/admin/simulations'))}>Xoá tất cả</button>
          </div>
          <ul className="divide-y divide-[var(--line)]">
            {list.data.map((s) => (
              <li key={s.id} className="flex items-center justify-between py-1.5">
                <span className="num">{s.radius_m} m, sâu {s.depth_cm} cm</span>
                <button className="btn-ghost px-2" disabled={busy} aria-label={`Xoá vùng ${s.radius_m} m`} onClick={() => run(() => api.del(`/admin/simulations/${s.id}`))}>Xoá</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
