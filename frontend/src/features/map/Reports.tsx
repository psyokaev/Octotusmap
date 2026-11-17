import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { SEVERITY } from './routeStyle'

export interface FloodReport {
  id: number; latitude: number; longitude: number; severity: string; note: string; status: string
  confirmations: number; reported_at: string; expires_at: string; reporter: string | null
}
export interface Hotspot { id: number; name: string; street: string; latitude: number; longitude: number; note: string; source_url: string; camera_id: number | null; camera_name: string | null }

function useRefresh() {
  const qc = useQueryClient()
  return () => { qc.invalidateQueries({ queryKey: ['reports'] }); qc.invalidateQueries({ queryKey: ['route'] }) }
}

/** Form "Báo ngập tại đây"; cần đăng nhập để hạn chế báo cáo rác. */
export function ReportForm({ lat, lon, onDone }: { lat: number; lon: number; onDone: () => void }) {
  const { user } = useAuth()
  const toast = useToast()
  const refresh = useRefresh()
  const [severity, setSeverity] = useState('ANKLE')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  if (!user) return <p className="text-sm"><Link className="text-water underline" to="/login?next=/">Đăng nhập</Link> để gửi báo cáo ngập.</p>
  return (
    <form className="space-y-2 text-sm" onSubmit={async (e) => {
      e.preventDefault()
      setBusy(true)
      try {
        await api.post('/reports', { latitude: lat, longitude: lon, severity, note })
        toast('ok', 'Đã gửi báo cáo ngập. Báo cáo có hiệu lực 3 giờ.')
        refresh()
        onDone()
      } catch (err) { toast('error', (err as Error).message) } finally { setBusy(false) }
    }}>
      <fieldset className="flex flex-wrap gap-3">
        <legend className="mb-1 font-medium">Mức ngập</legend>
        {Object.entries(SEVERITY).map(([k, v]) => (
          <label key={k} className="flex items-center gap-1">
            <input type="radio" name="severity" checked={severity === k} onChange={() => setSeverity(k)} />{v}
          </label>
        ))}
      </fieldset>
      <input className="input" aria-label="Ghi chú" placeholder="Ghi chú (không bắt buộc)" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex gap-2">
        <button className="btn-primary" disabled={busy}>Gửi báo cáo</button>
        <button type="button" className="btn-ghost" onClick={onDone}>Huỷ</button>
      </div>
    </form>
  )
}

export function ReportDetail({ report, onClose }: { report: FloodReport; onClose: () => void }) {
  const { user, isStaff } = useAuth()
  const toast = useToast()
  const refresh = useRefresh()
  const act = async (path: string, msg: string, close = false) => {
    try {
      await api.post(`/reports/${report.id}/${path}`)
      toast('ok', msg)
      refresh()
      if (close) onClose()
    } catch (e) { toast('error', (e as Error).message) }
  }
  return (
    <div className="space-y-2 text-sm">
      <h2 className="text-lg font-semibold">Người dân báo ngập</h2>
      <div className="font-medium text-[#8E24AA]">{SEVERITY[report.severity] ?? report.severity}</div>
      {report.note && <p>{report.note}</p>}
      <div className="muted text-xs">
        Báo lúc {fmtDateTime(report.reported_at)}, hiệu lực đến {fmtDateTime(report.expires_at)}. {report.confirmations} người xác nhận.
        {report.reporter && ` Người báo: ${report.reporter}.`}
      </div>
      <div className="flex gap-2">
        {user && <button className="btn-primary" onClick={() => act('confirm', 'Đã xác nhận báo cáo')}>Xác nhận vẫn ngập</button>}
        {isStaff && <button className="btn-danger" onClick={() => act('reject', 'Đã từ chối báo cáo', true)}>Từ chối</button>}
      </div>
    </div>
  )
}

/** Ảnh mới nhất của camera giao thông thành phố, qua proxy backend. */
export function TrafficCamera({ id, name }: { id: number; name: string | null }) {
  const [tick, setTick] = useState(0)
  const [failed, setFailed] = useState(false)
  return (
    <figure className="space-y-1">
      {failed ? <p className="muted">Camera hiện không có ảnh.</p> : (
        <img key={tick} src={`/api/v1/cameras/${id}/snapshot?t=${tick}`} alt={`Ảnh camera ${name ?? ''}`} className="w-full rounded-lg" loading="lazy" onError={() => setFailed(true)} />
      )}
      <figcaption className="flex items-center justify-between gap-2 text-xs">
        <span className="muted">{name}</span>
        <button className="text-water" onClick={() => { setFailed(false); setTick(Date.now()) }}>Làm mới</button>
      </figcaption>
    </figure>
  )
}

export function HotspotDetail({ h }: { h: Hotspot }) {
  return (
    <div className="space-y-2 text-sm">
      <h2 className="text-lg font-semibold">{h.name}</h2>
      {h.note && <p>{h.note}</p>}
      {h.camera_id && <TrafficCamera id={h.camera_id} name={h.camera_name} />}
      {h.source_url && <a className="text-water underline" href={h.source_url} target="_blank" rel="noopener noreferrer">Xem nguồn</a>}
    </div>
  )
}
