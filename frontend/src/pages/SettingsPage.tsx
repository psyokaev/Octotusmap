import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import clsx from 'clsx'
import { api, type Page } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import { Confirm, DemoBadge, Empty, ErrorState, Loading, PageHeader, Pager, useToast } from '../components/ui'
import { Field } from '../features/ops/Field'
import { errDetails, fileSchema, formData, num, reqNum, useAction, WEIGHT_VI } from '../features/ops/lib'

const TABS = [
  { id: 'rules', label: 'Quy tắc cảnh báo' },
  { id: 'settings', label: 'Cấu hình hệ thống' },
  { id: 'audit', label: 'Nhật ký' },
  { id: 'sources', label: 'Nguồn dữ liệu' },
  { id: 'ops', label: 'Vận hành' },
] as const
type Tab = (typeof TABS)[number]['id']

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('rules')
  return (
    <div>
      <PageHeader title="Cấu hình" />
      <div role="tablist" aria-label="Nhóm cấu hình" className="mb-4 flex flex-wrap gap-1 border-b border-[var(--line)]">
        {TABS.map((t) => (
          <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`}
            className={clsx('-mb-px border-b-2 px-3 py-2 text-sm font-medium', tab === t.id ? 'border-water text-water' : 'muted border-transparent')}
            onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'rules' && <RulesTab />}
        {tab === 'settings' && <SettingsTab />}
        {tab === 'audit' && <AuditTab />}
        {tab === 'sources' && <SourcesTab />}
        {tab === 'ops' && <OpsTab />}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ (a) quy tắc */
interface Rule { id: number; version: number; name: string; config: Record<string, unknown>; is_active: boolean; notes: string; created_at: string }

const ratio = (msg = 'Từ 0 đến 1') => reqNum(num().min(0, msg).max(1, msg))
const ruleSchema = z.object({
  name: z.string().trim().min(2, 'Tối thiểu 2 ký tự').max(120),
  notes: z.string().max(2000, 'Tối đa 2000 ký tự'),
  config: z.object({
    weights: z.object({
      flood_probability: reqNum(num().min(0, 'Không âm')), rainfall: reqNum(num().min(0, 'Không âm')),
      water_level: reqNum(num().min(0, 'Không âm')), camera: reqNum(num().min(0, 'Không âm')), history: reqNum(num().min(0, 'Không âm')),
    }),
    rainfall_ref_mm: reqNum(num().gt(0, 'Phải lớn hơn 0')),
    thresholds: z.object({ medium: reqNum(num().gt(0, 'Lớn hơn 0').max(1, 'Tối đa 1')), high: reqNum(num().gt(0, 'Lớn hơn 0').max(1, 'Tối đa 1')) })
      .refine((t) => t.medium < t.high, { message: 'Ngưỡng trung bình phải nhỏ hơn ngưỡng cao', path: ['high'] }),
    hysteresis: reqNum(num().min(0, 'Từ 0 đến dưới 0,3').lt(0.3, 'Từ 0 đến dưới 0,3')),
    overrides: z.object({ flood_probability_high: ratio(), water_level_ratio_high: reqNum(num().gt(0, 'Phải lớn hơn 0')), camera_ratio_high: ratio() }),
    min_confidence: ratio(),
    freshness_max_minutes: reqNum(num().int('Số nguyên').min(1, 'Tối thiểu 1 phút')),
    alert_min_level: z.enum(['LOW', 'MEDIUM', 'HIGH']),
    cooldown_minutes: reqNum(num().int('Số nguyên').min(0, 'Không âm')),
  }).refine((c) => Object.values(c.weights).some((w) => w > 0), { message: 'Cần ít nhất một trọng số lớn hơn 0', path: ['weights'] }),
})
type RuleForm = z.infer<typeof ruleSchema>

function RulesTab() {
  const act = useAction()
  const rules = useQuery({ queryKey: ['rules'], queryFn: () => api.get<Rule[]>('/admin/rules') })
  const [activating, setActivating] = useState<Rule | null>(null)
  const active = rules.data?.find((r) => r.is_active)

  if (rules.isLoading) return <Loading rows={6} />
  if (rules.isError) return <ErrorState error={rules.error} retry={() => rules.refetch()} />
  return (
    <div className="space-y-4">
      <p className="rounded-lg border border-dashed border-current p-3 text-sm text-[#8a5a00] dark:text-amber-300">
        Các trọng số và ngưỡng chỉ phục vụ nghiên cứu/trình diễn, chưa phải ngưỡng vận hành chính thức của cơ quan quản lý.
        Mỗi lần lưu tạo một phiên bản quy tắc mới và kích hoạt ngay.
      </p>
      {active ? <RuleEditor key={active.id} rule={active} /> : <div className="panel"><Empty text="Chưa có quy tắc đang áp dụng." /></div>}

      <section className="panel overflow-x-auto" aria-label="Các phiên bản quy tắc">
        <h2 className="p-4 pb-2 font-semibold">Các phiên bản</h2>
        {!rules.data?.length ? <Empty text="Chưa có phiên bản nào." /> : (
          <table className="table min-w-[640px]">
            <thead><tr><th>Phiên bản</th><th>Tên</th><th>Ghi chú</th><th>Ngày tạo</th><th>Trạng thái</th></tr></thead>
            <tbody>
              {rules.data.map((r) => (
                <tr key={r.id}>
                  <td className="num">v{r.version}</td><td>{r.name}</td><td className="max-w-xs">{r.notes || '—'}</td>
                  <td className="num">{fmtDateTime(r.created_at)}</td>
                  <td>{r.is_active ? <span className="chip bg-risk-low text-white">Đang áp dụng</span>
                    : <button className="btn-ghost" onClick={() => setActivating(r)}>Kích hoạt lại</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {activating && (
        <Confirm title="Kích hoạt phiên bản quy tắc" confirmLabel="Kích hoạt" onClose={() => setActivating(null)}
          text={`Áp dụng quy tắc v${activating.version} "${activating.name}" cho các chu kỳ cảnh báo tiếp theo?`}
          onConfirm={async () => { await act(() => api.post(`/admin/rules/${activating.id}/activate`), 'Đã kích hoạt quy tắc', ['rules']) }} />
      )}
    </div>
  )
}

function RuleEditor({ rule }: { rule: Rule }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [pending, setPending] = useState<RuleForm | null>(null)
  const [serverErrs, setServerErrs] = useState<string[]>([])
  const { register, handleSubmit, formState: { errors } } = useForm<RuleForm>({
    resolver: zodResolver(ruleSchema),
    defaultValues: { name: rule.name, notes: '', config: rule.config as RuleForm['config'] },
  })
  const c = errors.config
  const n = (name: Parameters<typeof register>[0], label: string, error?: string, hint?: string) => (
    <Field id={`r-${name}`} label={label} error={error} hint={hint}>
      <input id={`r-${name}`} type="number" step="any" className="input" {...register(name)} />
    </Field>
  )
  const save = async (v: RuleForm) => {
    setServerErrs([])
    try {
      await api.post('/admin/rules', v)
      toast('ok', 'Đã lưu và kích hoạt phiên bản quy tắc mới')
      qc.invalidateQueries({ queryKey: ['rules'] })
    } catch (e) {
      toast('error', (e as Error).message)
      setServerErrs(errDetails(e))
    }
  }
  return (
    <form noValidate className="panel space-y-4 p-4" onSubmit={handleSubmit(setPending)}>
      <h2 className="font-semibold">Quy tắc đang áp dụng · v{rule.version}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="r-name" label="Tên phiên bản mới" error={errors.name?.message}><input id="r-name" className="input" {...register('name')} /></Field>
        <Field id="r-notes" label="Ghi chú thay đổi" error={errors.notes?.message}><input id="r-notes" className="input" {...register('notes')} /></Field>
      </div>
      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Trọng số thành phần</legend>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {(['flood_probability', 'rainfall', 'water_level', 'camera', 'history'] as const).map((k) =>
            <div key={k}>{n(`config.weights.${k}`, WEIGHT_VI[k], c?.weights?.[k]?.message)}</div>)}
        </div>
        {c?.weights?.message && <p className="field-error" role="alert">{c.weights.message}</p>}
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Ngưỡng mức rủi ro</legend>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {n('config.thresholds.medium', 'Ngưỡng trung bình (0–1)', c?.thresholds?.medium?.message)}
          {n('config.thresholds.high', 'Ngưỡng cao (0–1)', c?.thresholds?.high?.message)}
          {n('config.hysteresis', 'Độ trễ hạ mức (hysteresis)', c?.hysteresis?.message, 'Trong khoảng [0; 0,3)')}
          {n('config.rainfall_ref_mm', 'Lượng mưa tham chiếu (mm/giờ)', c?.rainfall_ref_mm?.message)}
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Điều kiện nâng thẳng lên mức cao</legend>
        <div className="grid gap-3 sm:grid-cols-3">
          {n('config.overrides.flood_probability_high', 'Xác suất ngập ≥ (0–1)', c?.overrides?.flood_probability_high?.message)}
          {n('config.overrides.water_level_ratio_high', 'Tỉ lệ mực nước/ngưỡng ≥', c?.overrides?.water_level_ratio_high?.message)}
          {n('config.overrides.camera_ratio_high', 'Tỉ lệ ngập camera ≥ (0–1)', c?.overrides?.camera_ratio_high?.message)}
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Điều kiện phát cảnh báo</legend>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {n('config.min_confidence', 'Độ tin cậy tối thiểu (0–1)', c?.min_confidence?.message)}
          {n('config.freshness_max_minutes', 'Tuổi dữ liệu tối đa (phút)', c?.freshness_max_minutes?.message)}
          {n('config.cooldown_minutes', 'Thời gian chờ sau khi đóng (phút)', c?.cooldown_minutes?.message)}
          <Field id="r-min-level" label="Mức tối thiểu để phát cảnh báo" error={c?.alert_min_level?.message}>
            <select id="r-min-level" className="input" {...register('config.alert_min_level')}>
              <option value="LOW">Thấp</option><option value="MEDIUM">Trung bình</option><option value="HIGH">Cao</option>
            </select>
          </Field>
        </div>
      </fieldset>
      {serverErrs.length > 0 && (
        <ul role="alert" className="list-disc rounded-lg border border-risk-high p-3 pl-7 text-sm text-risk-high">{serverErrs.map((e, i) => <li key={i}>{e}</li>)}</ul>
      )}
      <button className="btn-primary">Lưu thành phiên bản mới</button>
      {pending && (
        <Confirm title="Lưu quy tắc mới" confirmLabel="Lưu và kích hoạt" onClose={() => setPending(null)}
          text="Phiên bản mới sẽ được kích hoạt ngay và áp dụng cho chu kỳ đánh giá rủi ro tiếp theo. Tiếp tục?"
          onConfirm={() => save(pending)} />
      )}
    </form>
  )
}

/* ------------------------------------------------------------------ (b) cấu hình hệ thống */
interface Setting { key: string; value: unknown; description: string; updated_at: string }

function SettingsTab() {
  const q = useQuery({ queryKey: ['settings'], queryFn: () => api.get<Setting[]>('/admin/settings') })
  if (q.isLoading) return <Loading rows={6} />
  if (q.isError) return <ErrorState error={q.error} retry={() => q.refetch()} />
  if (!q.data?.length) return <div className="panel"><Empty text="Chưa có cấu hình nào." /></div>
  return <div className="space-y-3">{q.data.map((s) => <SettingRow key={`${s.key}-${s.updated_at}`} s={s} />)}</div>
}

const jsonSchema = z.object({
  text: z.string().min(1, 'Nhập giá trị JSON').refine((t) => { try { JSON.parse(t); return true } catch { return false } }, 'JSON không hợp lệ'),
})

function SettingRow({ s }: { s: Setting }) {
  const act = useAction()
  const [pending, setPending] = useState<unknown>(undefined)
  const { register, handleSubmit, formState: { errors, isDirty } } = useForm<z.infer<typeof jsonSchema>>({
    resolver: zodResolver(jsonSchema), defaultValues: { text: JSON.stringify(s.value, null, 2) },
  })
  const id = `set-${s.key}`
  return (
    <form noValidate className="panel p-4" onSubmit={handleSubmit((v) => setPending(JSON.parse(v.text)))}>
      <Field id={id} label={s.key} error={errors.text?.message} hint={`${s.description || 'Không có mô tả'} · cập nhật ${fmtDateTime(s.updated_at)}`}>
        <textarea id={id} rows={Math.min(10, JSON.stringify(s.value, null, 2).split('\n').length + 1)} className="input font-mono text-xs" spellCheck={false} {...register('text')} />
      </Field>
      <button className="btn-primary mt-2" disabled={!isDirty}>Lưu</button>
      {pending !== undefined && (
        <Confirm title="Lưu cấu hình" confirmLabel="Lưu" onClose={() => setPending(undefined)}
          text={`Cập nhật cấu hình "${s.key}"? Thay đổi có hiệu lực ngay và được ghi nhật ký.`}
          onConfirm={async () => { await act(() => api.put(`/admin/settings/${encodeURIComponent(s.key)}`, { value: pending }), 'Đã lưu cấu hình', ['settings']) }} />
      )}
    </form>
  )
}

/* ------------------------------------------------------------------ (c) nhật ký */
interface Audit { id: number; username: string; action: string; entity_type: string; entity_id: string; detail: unknown; ip: string; created_at: string }

function AuditTab() {
  const [q, setQ] = useState('')
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const params = { q, action: action.trim().toUpperCase(), page, size: 50 }
  const list = useQuery({ queryKey: ['audit', params], queryFn: () => api.get<Page<Audit>>('/admin/audit-logs', params) })
  return (
    <div>
      <div className="panel mb-4 grid gap-3 p-4 sm:grid-cols-2">
        <Field id="au-q" label="Người dùng hoặc đối tượng"><input id="au-q" className="input" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
        <Field id="au-action" label="Mã thao tác" hint="Ví dụ: LOGIN, ALERT_STATUS, RULE_CREATE"><input id="au-action" className="input" value={action} onChange={(e) => { setAction(e.target.value); setPage(1) }} /></Field>
      </div>
      <div className="panel overflow-x-auto">
        {list.isLoading ? <Loading rows={8} /> : list.isError ? <ErrorState error={list.error} retry={() => list.refetch()} />
          : !list.data?.items.length ? <Empty text="Không có bản ghi nhật ký phù hợp." />
          : (
            <table className="table min-w-[760px]">
              <thead><tr><th>Thời điểm</th><th>Người dùng</th><th>Thao tác</th><th>Đối tượng</th><th>IP</th><th>Chi tiết</th></tr></thead>
              <tbody>
                {list.data.items.map((a) => (
                  <tr key={a.id}>
                    <td className="num whitespace-nowrap">{fmtDateTime(a.created_at)}</td>
                    <td>{a.username || '—'}</td>
                    <td className="font-mono text-xs">{a.action}</td>
                    <td>{a.entity_type}{a.entity_id ? ` #${a.entity_id}` : ''}</td>
                    <td className="num">{a.ip || '—'}</td>
                    <td>{a.detail ? <details><summary className="cursor-pointer text-water">Xem</summary><pre className="mt-1 max-w-md overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(a.detail, null, 2)}</pre></details> : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ (d) nguồn dữ liệu */
interface Source { id: number; code: string; name: string; kind: string; is_simulated: boolean; license: string; url: string }

function SourcesTab() {
  const q = useQuery({ queryKey: ['data-sources'], queryFn: () => api.get<Source[]>('/admin/data-sources') })
  return (
    <div className="panel overflow-x-auto">
      {q.isLoading ? <Loading rows={5} /> : q.isError ? <ErrorState error={q.error} retry={() => q.refetch()} />
        : !q.data?.length ? <Empty text="Chưa có nguồn dữ liệu." />
        : (
          <table className="table min-w-[700px]">
            <thead><tr><th>Mã</th><th>Tên</th><th>Loại</th><th>Tính chất</th><th>Giấy phép</th><th>Liên kết</th></tr></thead>
            <tbody>
              {q.data.map((s) => (
                <tr key={s.id}>
                  <td className="font-mono text-xs">{s.code}</td><td>{s.name}</td><td>{s.kind}</td>
                  <td>{s.is_simulated ? <DemoBadge /> : 'Dữ liệu thật'}</td>
                  <td>{s.license || '—'}</td>
                  <td>{/^https?:\/\//.test(s.url) ? <a className="text-water underline" href={s.url} target="_blank" rel="noreferrer">Mở</a> : (s.url || '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  )
}

/* ------------------------------------------------------------------ (e) vận hành */
const geoSchema = z.object({
  file: fileSchema(['.geojson', '.json'], 30),
  level: z.enum(['WARD', 'DISTRICT']),
  name_field: z.string().trim().min(1, 'Nhập tên thuộc tính'),
  code_field: z.string().trim().min(1, 'Nhập tên thuộc tính'),
  source_name: z.string().trim().min(2, 'Tối thiểu 2 ký tự').max(200, 'Tối đa 200 ký tự'),
})

function OpsTab() {
  const act = useAction()
  const [confirmRun, setConfirmRun] = useState(false)
  const [cycle, setCycle] = useState<unknown>(null)
  const [geoResult, setGeoResult] = useState<{ inserted: number } | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof geoSchema>>({
    resolver: zodResolver(geoSchema),
    defaultValues: { level: 'WARD', name_field: 'name', code_field: 'code', source_name: 'Ranh giới do quản trị viên nhập' },
  })
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="panel p-4" aria-label="Chu kỳ xử lý">
        <h2 className="mb-1 font-semibold">Chu kỳ xử lý</h2>
        <p className="muted mb-3 text-sm">Thu thập dữ liệu, dự báo, đánh giá rủi ro và sinh cảnh báo ngay lập tức thay vì chờ lịch chạy định kỳ.</p>
        <button className="btn-primary" onClick={() => setConfirmRun(true)}>Chạy chu kỳ xử lý ngay</button>
        {cycle !== null && <pre className="mt-3 max-h-80 overflow-auto rounded-lg bg-black/5 p-3 text-xs dark:bg-white/5" role="status">{JSON.stringify(cycle, null, 2)}</pre>}
      </section>

      <section className="panel p-4" aria-label="Nhập ranh giới hành chính">
        <h2 className="mb-1 font-semibold">Nhập ranh giới hành chính (GeoJSON)</h2>
        <p className="muted mb-3 text-sm">Tệp GeoJSON hệ toạ độ WGS84, tối đa 30 MB. Khu vực mới sẽ được dùng cho bản đồ và đánh giá rủi ro.</p>
        <form noValidate className="grid gap-3 sm:grid-cols-2" onSubmit={handleSubmit(async (v) => {
          await act(async () => setGeoResult(await api.post<{ inserted: number }>('/gis/import', formData({ file: v.file[0] }),
            { level: v.level, name_field: v.name_field, code_field: v.code_field, source_name: v.source_name })),
          'Đã nhập ranh giới', ['areas'])
        })}>
          <Field id="geo-file" label="Tệp GeoJSON" error={errors.file?.message} className="sm:col-span-2">
            <input id="geo-file" type="file" accept=".geojson,.json,application/geo+json,application/json" className="input" {...register('file')} />
          </Field>
          <Field id="geo-level" label="Cấp hành chính" error={errors.level?.message}>
            <select id="geo-level" className="input" {...register('level')}><option value="WARD">Phường/xã</option><option value="DISTRICT">Quận/huyện</option></select>
          </Field>
          <Field id="geo-src" label="Tên nguồn" error={errors.source_name?.message}><input id="geo-src" className="input" {...register('source_name')} /></Field>
          <Field id="geo-name" label="Thuộc tính tên" error={errors.name_field?.message}><input id="geo-name" className="input" {...register('name_field')} /></Field>
          <Field id="geo-code" label="Thuộc tính mã" error={errors.code_field?.message}><input id="geo-code" className="input" {...register('code_field')} /></Field>
          <div className="sm:col-span-2"><button className="btn-primary" disabled={isSubmitting}>{isSubmitting ? 'Đang nhập…' : 'Nhập ranh giới'}</button></div>
        </form>
        {geoResult && <p className="mt-3 text-sm" role="status">Đã thêm <b className="num">{geoResult.inserted}</b> khu vực.</p>}
      </section>

      {confirmRun && (
        <Confirm title="Chạy chu kỳ xử lý" confirmLabel="Chạy ngay" onClose={() => setConfirmRun(false)}
          text="Chạy toàn bộ chu kỳ xử lý (có thể mất vài chục giây và sinh cảnh báo mới)?"
          onConfirm={async () => { await act(async () => setCycle(await api.post('/admin/jobs/run-cycle')), 'Đã chạy xong chu kỳ xử lý', ['alerts', 'stations', 'risk-layers', 'features']) }} />
      )}
    </div>
  )
}
