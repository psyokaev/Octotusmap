import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useSearchParams } from 'react-router-dom'
import { api, download, type Page } from '../lib/api'
import { fmtDateTime, fmtNum, fmtPct } from '../lib/format'
import { RISK, STATUS_VI, floodCause } from '../lib/risk'
import { useAuth, type User } from '../auth/AuthContext'
import { Confirm, DemoBadge, Empty, ErrorState, Loading, Modal, PageHeader, Pager, RiskBadge, useToast } from '../components/ui'
import { AreaSelect, Field } from '../features/ops/Field'
import { errText, useAction, vnDateToIso, WEIGHT_VI, type Area } from '../features/ops/lib'

type Status = 'NEW' | 'ACKNOWLEDGED' | 'IN_PROGRESS' | 'RESOLVED' | 'CLOSED'
interface Explanation {
  level_reason?: string; contributions?: Record<string, number>; normalized?: Record<string, number | null>
  confidence?: number; overrides?: string[]; notes?: string[]; stations?: string[]; rule_version?: number
}
interface Alert {
  id: number; code: string; area: Area; risk_level: string; status: Status; title: string; message: string
  recommendations: string[] | null; explanation: Explanation | null; score: number; horizon_h: number
  cause: string | null; depth_cm: number | null; wards: string[]
  is_simulated: boolean; is_public: boolean; verified_outcome: string; assigned_to: number | null; assignee_name: string | null
  triggered_at: string; acknowledged_at: string | null; resolved_at: string | null; closed_at: string | null; updated_at: string
}
interface AlertDetail extends Alert {
  history: { id: number; action: string; from_status: string | null; to_status: string | null; note: string; changed_at: string; username: string | null }[]
}

/** Khớp alert_service.TRANSITIONS ở backend. */
const TRANSITIONS: Record<Status, Status[]> = {
  NEW: ['ACKNOWLEDGED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED'],
  ACKNOWLEDGED: ['IN_PROGRESS', 'RESOLVED', 'CLOSED'],
  IN_PROGRESS: ['RESOLVED', 'CLOSED'],
  RESOLVED: ['CLOSED', 'IN_PROGRESS'],
  CLOSED: [],
}
const LEVELS = ['HIGH', 'MEDIUM', 'LOW', 'INSUFFICIENT_DATA'] as const
const OUTCOME_VI: Record<string, string> = { CONFIRMED: 'Xác nhận có ngập', FALSE_ALARM: 'Báo động sai', UNVERIFIED: 'Chưa xác minh' }
const SORTS = { triggered_at: 'Thời điểm phát sinh', risk_level: 'Mức rủi ro', status: 'Trạng thái', score: 'Điểm rủi ro' }

const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])

export default function AlertsPage() {
  const { isStaff } = useAuth()
  const toast = useToast()
  const [sp, setSp] = useSearchParams()
  const [f, setF] = useState({ status: [] as Status[], level: [] as string[], area_id: '', q: '', from: '', to: '' })
  const [sort, setSort] = useState<keyof typeof SORTS>('triggered_at')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)
  const update = (p: Partial<typeof f>) => { setF((x) => ({ ...x, ...p })); setPage(1) }

  const dates = { date_from: vnDateToIso(f.from), date_to: vnDateToIso(f.to, true) }
  const params = { status: f.status, level: f.level, area_id: f.area_id, q: f.q, ...dates, sort, direction: dir, page, size: 20 }
  const list = useQuery({ queryKey: ['alerts', params], queryFn: () => api.get<Page<Alert>>('/alerts', params) })
  const openId = Number(sp.get('open')) || null
  const setOpen = useCallback((id: number | null) => setSp((p) => { if (id) p.set('open', String(id)); else p.delete('open'); return p }, { replace: true }), [setSp])
  const closeModal = useCallback(() => setOpen(null), [setOpen])

  const counts = LEVELS.map((l) => [l, list.data?.items.filter((a) => a.risk_level === l).length ?? 0] as const)

  const exportExcel = async () => {
    setExporting(true)
    try {
      const lv = f.level.length === 1 && f.level[0] !== 'INSUFFICIENT_DATA' ? f.level[0] : undefined
      const name = await download('/exports/excel', { report: 'alerts', ...dates, area_id: f.area_id, risk_level: lv })
      toast('ok', `Đã tải ${name}`)
    } catch (e) { toast('error', errText(e)) } finally { setExporting(false) }
  }

  return (
    <div>
      <PageHeader title="Cảnh báo ngập">
        {isStaff && <button className="btn-ghost" onClick={exportExcel} disabled={exporting}>{exporting ? 'Đang xuất…' : 'Xuất Excel'}</button>}
      </PageHeader>

      <div className="panel mb-4 space-y-3 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field id="al-q" label="Tìm kiếm">
            <input id="al-q" className="input" placeholder="Mã, tiêu đề, nội dung" value={f.q} onChange={(e) => update({ q: e.target.value })} />
          </Field>
          <Field id="al-area" label="Khu vực"><AreaSelect id="al-area" value={f.area_id} onChange={(v) => update({ area_id: v })} /></Field>
          <Field id="al-from" label="Từ ngày"><input id="al-from" type="date" className="input" value={f.from} onChange={(e) => update({ from: e.target.value })} /></Field>
          <Field id="al-to" label="Đến ngày"><input id="al-to" type="date" className="input" value={f.to} onChange={(e) => update({ to: e.target.value })} /></Field>
          <Field id="al-sort" label="Sắp xếp">
            <div className="flex gap-1">
              <select id="al-sort" className="input" value={sort} onChange={(e) => setSort(e.target.value as keyof typeof SORTS)}>
                {Object.entries(SORTS).filter(([k]) => isStaff || k !== 'status').map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <button className="btn-ghost" onClick={() => setDir(dir === 'asc' ? 'desc' : 'asc')} aria-label={dir === 'asc' ? 'Tăng dần, bấm để đổi' : 'Giảm dần, bấm để đổi'}>{dir === 'asc' ? '↑' : '↓'}</button>
            </div>
          </Field>
        </div>
        <fieldset className="flex flex-wrap items-center gap-2 text-sm">
          <legend className="sr-only">Mức rủi ro</legend>
          <span className="font-medium">Mức:</span>
          {LEVELS.map((l) => (
            <label key={l} className="flex items-center gap-1"><input type="checkbox" checked={f.level.includes(l)} onChange={() => update({ level: toggle(f.level, l) })} />{RISK[l].label}</label>
          ))}
        </fieldset>
        {isStaff && (
          <fieldset className="flex flex-wrap items-center gap-2 text-sm">
            <legend className="sr-only">Trạng thái</legend>
            <span className="font-medium">Trạng thái:</span>
            {(Object.keys(TRANSITIONS) as Status[]).map((s) => (
              <label key={s} className="flex items-center gap-1"><input type="checkbox" checked={f.status.includes(s)} onChange={() => update({ status: toggle(f.status, s) })} />{STATUS_VI[s]}</label>
            ))}
          </fieldset>
        )}
      </div>

      {list.data && list.data.items.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
          <span className="muted">Trên trang này:</span>
          {counts.filter(([, n]) => n).map(([l, n]) => <span key={l} className="flex items-center gap-1"><RiskBadge level={l} /> <span className="num">{n}</span></span>)}
        </div>
      )}

      <div className="panel overflow-x-auto">
        {list.isLoading ? <Loading rows={6} /> : list.isError ? <ErrorState error={list.error} retry={() => list.refetch()} />
          : !list.data?.items.length ? <Empty text={isStaff ? 'Không có cảnh báo phù hợp bộ lọc.' : 'Hiện không có cảnh báo công khai nào đang hoạt động.'} />
          : (
            <table className="table min-w-[900px]">
              <thead><tr><th>Mã</th><th>Tiêu đề</th><th>Khu vực</th><th>Mức</th>{isStaff && <th>Trạng thái</th>}<th className="text-right">Điểm</th><th>Phát sinh</th><th>Phụ trách</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
              <tbody>
                {list.data.items.map((a) => (
                  <tr key={a.id}>
                    <td className="font-medium">{a.code}</td>
                    <td>{a.title} {a.is_simulated && <DemoBadge />}<CauseLines a={a} /></td>
                    <td>{a.area.name}</td>
                    <td><RiskBadge level={a.risk_level} /></td>
                    {isStaff && <td>{STATUS_VI[a.status] ?? a.status}</td>}
                    <td className="num text-right">{fmtNum(a.score)}</td>
                    <td className="num">{fmtDateTime(a.triggered_at)}</td>
                    <td>{a.assignee_name ?? '—'}</td>
                    <td><button className="btn-ghost" onClick={() => setOpen(a.id)}>Chi tiết</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
      </div>

      {openId && <AlertModal id={openId} staff={isStaff} onClose={closeModal} />}
    </div>
  )
}

/* ------------------------------------------------------------------ chi tiết */
function AlertModal({ id, staff, onClose }: { id: number; staff: boolean; onClose: () => void }) {
  const q = useQuery({ queryKey: ['alert', id], queryFn: () => api.get<AlertDetail>(`/alerts/${id}`) })
  const a = q.data
  const ex = a?.explanation
  return (
    <Modal title={a ? `${a.code} · ${a.title}` : 'Chi tiết cảnh báo'} onClose={onClose} wide>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={() => q.refetch()} /> : a && (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge level={a.risk_level} />
            {staff && <span className="chip border border-current">{STATUS_VI[a.status] ?? a.status}</span>}
            {a.is_simulated && <DemoBadge />}
            <span className="muted">{a.area.name} · điểm <span className="num">{fmtNum(a.score)}</span> · tầm dự báo {a.horizon_h} giờ</span>
          </div>
          <p>{a.message}</p>
          <div className="text-sm"><CauseLines a={a} /></div>

          {!!a.recommendations?.length && (
            <section><h3 className="mb-1 font-semibold">Khuyến nghị</h3>
              <ul className="list-disc space-y-0.5 pl-5">{a.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </section>
          )}

          {ex && (
            <section><h3 className="mb-1 font-semibold">Giải thích mức cảnh báo</h3>
              {ex.level_reason && <p>{ex.level_reason}</p>}
              {ex.confidence !== undefined && <p className="muted">Độ tin cậy dữ liệu: {fmtPct(ex.confidence)}{ex.rule_version ? ` · quy tắc phiên bản ${ex.rule_version}` : ''}</p>}
              {ex.contributions && Object.keys(ex.contributions).length > 0 && (
                <table className="table mt-2">
                  <thead><tr><th>Thành phần</th><th className="text-right">Giá trị chuẩn hoá</th><th className="text-right">Đóng góp</th></tr></thead>
                  <tbody>{Object.entries(ex.contributions).map(([k, v]) => (
                    <tr key={k}><td>{WEIGHT_VI[k] ?? k}</td><td className="num text-right">{fmtNum(ex.normalized?.[k])}</td><td className="num text-right">{fmtNum(v)}</td></tr>
                  ))}</tbody>
                </table>
              )}
              {!!ex.overrides?.length && <div className="mt-2"><b>Điều kiện nâng mức:</b><ul className="list-disc pl-5">{ex.overrides.map((o, i) => <li key={i}>{o}</li>)}</ul></div>}
              {!!ex.notes?.length && <div className="mt-2"><b>Ghi chú:</b><ul className="list-disc pl-5">{ex.notes.map((o, i) => <li key={i}>{o}</li>)}</ul></div>}
              {!!ex.stations?.length && <p className="mt-2">Trạm liên quan: {ex.stations.join(', ')}</p>}
            </section>
          )}

          <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 sm:grid-cols-4">
            <dt className="muted">Phát sinh</dt><dd className="num">{fmtDateTime(a.triggered_at)}</dd>
            {staff && <>
              <dt className="muted">Tiếp nhận</dt><dd className="num">{fmtDateTime(a.acknowledged_at)}</dd>
              <dt className="muted">Xử lý xong</dt><dd className="num">{fmtDateTime(a.resolved_at)}</dd>
              <dt className="muted">Đóng</dt><dd className="num">{fmtDateTime(a.closed_at)}</dd>
            </>}
            {staff && <><dt className="muted">Phụ trách</dt><dd>{a.assignee_name ?? '—'}</dd><dt className="muted">Xác minh</dt><dd>{OUTCOME_VI[a.verified_outcome] ?? a.verified_outcome}</dd></>}
          </dl>

          {staff && <StaffActions a={a} />}

          {staff && (
            <section><h3 className="mb-1 font-semibold">Lịch sử xử lý</h3>
              {!a.history.length ? <p className="muted">Chưa có thao tác.</p> : (
                <ol className="space-y-2 border-l-2 border-[var(--line)] pl-4">
                  {a.history.map((h) => (
                    <li key={h.id}>
                      <div className="num muted text-xs">{fmtDateTime(h.changed_at)} · {h.username ?? 'hệ thống'}</div>
                      <div>{h.action}{h.to_status ? `: ${STATUS_VI[h.from_status ?? ''] ?? h.from_status ?? '—'} → ${STATUS_VI[h.to_status] ?? h.to_status}` : ''}</div>
                      {h.note && <div className="muted">{h.note}</div>}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}
        </div>
      )}
    </Modal>
  )
}

/* ------------------------------------------------------------------ thao tác cán bộ */
const statusSchema = z.object({ status: z.string().min(1, 'Chọn trạng thái mới'), note: z.string().max(2000, 'Tối đa 2000 ký tự') })
const assignSchema = z.object({ user_id: z.string(), note: z.string().max(2000, 'Tối đa 2000 ký tự') })
const noteSchema = z.object({ note: z.string().trim().min(1, 'Nhập nội dung ghi chú').max(2000, 'Tối đa 2000 ký tự') })
const verifySchema = z.object({ outcome: z.enum(['CONFIRMED', 'FALSE_ALARM', 'UNVERIFIED']), note: z.string().max(2000, 'Tối đa 2000 ký tự') })

function StaffActions({ a }: { a: AlertDetail }) {
  const act = useAction()
  const keys = ['alerts', 'alert']
  const [pending, setPending] = useState<z.infer<typeof statusSchema> | null>(null)
  const assignees = useQuery({ queryKey: ['assignees'], queryFn: () => api.get<User[]>('/alerts/assignees'), staleTime: 60_000 })
  const sf = useForm<z.infer<typeof statusSchema>>({ resolver: zodResolver(statusSchema), defaultValues: { status: '', note: '' } })
  const af = useForm<z.infer<typeof assignSchema>>({ resolver: zodResolver(assignSchema), defaultValues: { user_id: a.assigned_to ? String(a.assigned_to) : '', note: '' } })
  const nf = useForm<z.infer<typeof noteSchema>>({ resolver: zodResolver(noteSchema), defaultValues: { note: '' } })
  const vf = useForm<z.infer<typeof verifySchema>>({ resolver: zodResolver(verifySchema), defaultValues: { outcome: 'CONFIRMED', note: '' } })
  const next = TRANSITIONS[a.status] ?? []

  return (
    <section className="rounded-lg border border-[var(--line)] p-3" aria-label="Thao tác xử lý">
      <h3 className="mb-2 font-semibold">Xử lý cảnh báo</h3>
      {a.status === 'NEW' && (
        <button className="btn-primary mb-3" onClick={() => act(() => api.post(`/alerts/${a.id}/acknowledge`), 'Đã tiếp nhận cảnh báo', keys)}>Tiếp nhận</button>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {next.length > 0 ? (
          <form noValidate className="space-y-2" onSubmit={sf.handleSubmit((v) => setPending(v))}>
            <Field id="as-status" label="Chuyển trạng thái" error={sf.formState.errors.status?.message}>
              <select id="as-status" className="input" {...sf.register('status')}>
                <option value="">Chọn trạng thái…</option>
                {next.map((s) => <option key={s} value={s}>{STATUS_VI[s]}</option>)}
              </select>
            </Field>
            <Field id="as-note" label="Ghi chú (tuỳ chọn)" error={sf.formState.errors.note?.message}><input id="as-note" className="input" {...sf.register('note')} /></Field>
            <button className="btn-primary">Cập nhật trạng thái</button>
          </form>
        ) : <p className="muted">Cảnh báo đã đóng, không thể chuyển trạng thái.</p>}

        <form noValidate className="space-y-2" onSubmit={af.handleSubmit((v) =>
          act(() => api.post(`/alerts/${a.id}/assign`, { user_id: v.user_id ? Number(v.user_id) : null, note: v.note }), 'Đã cập nhật phân công', keys))}>
          <Field id="as-user" label="Phân công cán bộ" error={assignees.isError ? errText(assignees.error) : undefined}>
            <select id="as-user" className="input" {...af.register('user_id')}>
              <option value="">Không phân công</option>
              {assignees.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
            </select>
          </Field>
          <Field id="as-anote" label="Ghi chú (tuỳ chọn)" error={af.formState.errors.note?.message}><input id="as-anote" className="input" {...af.register('note')} /></Field>
          <button className="btn-primary" disabled={af.formState.isSubmitting}>Phân công</button>
        </form>

        <form noValidate className="space-y-2" onSubmit={nf.handleSubmit(async (v) => {
          if (await act(() => api.post(`/alerts/${a.id}/notes`, v), 'Đã thêm ghi chú', keys)) nf.reset()
        })}>
          <Field id="as-n" label="Thêm ghi chú" error={nf.formState.errors.note?.message}><textarea id="as-n" rows={2} className="input" {...nf.register('note')} /></Field>
          <button className="btn-primary" disabled={nf.formState.isSubmitting}>Thêm ghi chú</button>
        </form>

        <form noValidate className="space-y-2" onSubmit={vf.handleSubmit((v) => act(() => api.post(`/alerts/${a.id}/verify`, v), 'Đã ghi nhận kết quả xác minh', keys))}>
          <Field id="as-out" label="Xác minh thực địa" error={vf.formState.errors.outcome?.message}>
            <select id="as-out" className="input" {...vf.register('outcome')}>
              {Object.entries(OUTCOME_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field id="as-vnote" label="Ghi chú (tuỳ chọn)" error={vf.formState.errors.note?.message}><input id="as-vnote" className="input" {...vf.register('note')} /></Field>
          <button className="btn-primary" disabled={vf.formState.isSubmitting}>Lưu xác minh</button>
        </form>
      </div>

      {pending && (
        <Confirm title="Xác nhận chuyển trạng thái" confirmLabel="Chuyển trạng thái" danger={pending.status === 'CLOSED'}
          text={`Chuyển cảnh báo ${a.code} từ "${STATUS_VI[a.status]}" sang "${STATUS_VI[pending.status]}"?`}
          onClose={() => setPending(null)}
          onConfirm={async () => { if (await act(() => api.post(`/alerts/${a.id}/status`, pending), 'Đã cập nhật trạng thái', keys)) sf.reset() }} />
      )}
    </section>
  )
}


function CauseLines({ a }: { a: Pick<Alert, 'cause' | 'depth_cm' | 'wards'> }) {
  const cause = floodCause(a.cause, a.depth_cm)
  return (
    <>
      {cause && <div className="muted text-xs">{cause}</div>}
      {!!a.wards?.length && <div className="muted text-xs">Phường: {a.wards.join(', ')}</div>}
    </>
  )
}
