import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useNavigate } from 'react-router-dom'
import { api, type Page } from '../lib/api'
import { fmtDateTime, fmtNum, fmtPct, vnLocalToIso } from '../lib/format'
import { DATA_STATUS_VI } from '../lib/risk'
import { Chart, Confirm, DemoBadge, Empty, ErrorState, Kpi, Loading, Modal, PageHeader, Pager, SortTh } from '../components/ui'
import { AreaSelect, Field, FormActions } from '../features/ops/Field'
import { fileSchema, formData, num, optNum, reqNum, useAction, vnDateToIso, type Area, type ImportReport } from '../features/ops/lib'

interface Station {
  id: number; code: string; name: string; station_type: 'RAIN' | 'WATER_LEVEL' | 'COMBINED'; address: string; latitude: number; longitude: number
  managing_unit: string; status: 'ACTIVE' | 'INACTIVE' | 'MAINTENANCE'; interval_minutes: number; flood_threshold_cm: number; notes: string
  area: Area | null; last_observation_at: string | null; connection_status: string; data_status: string
  latest_rainfall_mm: number | null; latest_water_level_cm: number | null; updated_at: string
}
interface Obs { observed_at: string; rainfall_mm: number | null; water_level_cm: number | null }
interface Quality {
  rainfall: Record<string, number>; water_level: Record<string, number>
  expected_records: number; completeness: number | null; delay_minutes: number | null
}

const TYPE_VI: Record<string, string> = { RAIN: 'Đo mưa', WATER_LEVEL: 'Đo mực nước', COMBINED: 'Kết hợp' }
const ST_STATUS_VI: Record<string, string> = { ACTIVE: 'Hoạt động', INACTIVE: 'Ngừng', MAINTENANCE: 'Bảo trì' }
const CONN_VI: Record<string, string> = { ONLINE: 'Trực tuyến', OFFLINE: 'Mất kết nối', NO_DATA: 'Chưa có dữ liệu', UNKNOWN: 'Không rõ' }
const CONN_COLOR: Record<string, string> = { ONLINE: '#2E8B57', OFFLINE: '#C62828', NO_DATA: '#8A949C', UNKNOWN: '#8A949C' }

type Dialog =
  | { kind: 'form'; station?: Station }
  | { kind: 'detail'; station: Station }
  | { kind: 'import' }
  | { kind: 'delete'; station: Station }
  | null

export default function StationsPage() {
  const act = useAction()
  const [f, setF] = useState({ q: '', station_type: '', status: '', area_id: '', connection: '' })
  const [sort, setSort] = useState('code')
  const [dir, setDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)
  const [dlg, setDlg] = useState<Dialog>(null)
  const close = useCallback(() => setDlg(null), []) // ổn định để Modal không lấy lại focus mỗi lần render
  const params = { ...f, sort, direction: dir, page, size: 20 }
  const list = useQuery({ queryKey: ['stations', params], queryFn: () => api.get<Page<Station>>('/stations', params) })

  const setFilter = (k: keyof typeof f, v: string) => { setF((x) => ({ ...x, [k]: v })); setPage(1) }
  const onSort = (c: string) => { if (c === sort) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(c); setDir('asc') } }

  return (
    <div>
      <PageHeader title="Trạm quan trắc">
        <button className="btn-ghost" onClick={() => setDlg({ kind: 'import' })}>Nhập dữ liệu từ tệp</button>
        <button className="btn-primary" onClick={() => setDlg({ kind: 'form' })}>Thêm trạm</button>
      </PageHeader>

      <div className="panel mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
        <Field id="st-q" label="Tìm kiếm">
          <input id="st-q" className="input" placeholder="Mã hoặc tên trạm" value={f.q} onChange={(e) => setFilter('q', e.target.value)} />
        </Field>
        <Field id="st-type" label="Loại trạm">
          <select id="st-type" className="input" value={f.station_type} onChange={(e) => setFilter('station_type', e.target.value)}>
            <option value="">Tất cả</option>
            {Object.entries(TYPE_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field id="st-status" label="Trạng thái">
          <select id="st-status" className="input" value={f.status} onChange={(e) => setFilter('status', e.target.value)}>
            <option value="">Tất cả</option>
            {Object.entries(ST_STATUS_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field id="st-area" label="Khu vực">
          <AreaSelect id="st-area" value={f.area_id} onChange={(v) => setFilter('area_id', v)} />
        </Field>
        <Field id="st-conn" label="Kết nối">
          <select id="st-conn" className="input" value={f.connection} onChange={(e) => setFilter('connection', e.target.value)}>
            <option value="">Tất cả</option>
            {['ONLINE', 'OFFLINE', 'NO_DATA'].map((k) => <option key={k} value={k}>{CONN_VI[k]}</option>)}
          </select>
        </Field>
      </div>

      <div className="panel overflow-x-auto">
        {list.isLoading ? <Loading rows={6} /> : list.isError ? <ErrorState error={list.error} retry={() => list.refetch()} />
          : !list.data?.items.length ? <Empty text="Không có trạm nào phù hợp bộ lọc." />
          : (
            <table className="table min-w-[1000px]">
              <thead>
                <tr>
                  <SortTh label="Mã" col="code" sort={sort} dir={dir} onSort={onSort} />
                  <SortTh label="Tên trạm" col="name" sort={sort} dir={dir} onSort={onSort} />
                  <th>Loại</th><th>Khu vực</th><th>Trạng thái</th><th>Kết nối</th>
                  <th className="text-right">Mưa (mm)</th><th className="text-right">Mực nước (cm)</th>
                  <SortTh label="Quan trắc gần nhất" col="last_observation_at" sort={sort} dir={dir} onSort={onSort} />
                  <SortTh label="Cập nhật" col="updated_at" sort={sort} dir={dir} onSort={onSort} />
                  <th>Dữ liệu</th><th><span className="sr-only">Thao tác</span></th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((s) => (
                  <tr key={s.id}>
                    <td className="font-medium">{s.code}</td>
                    <td>{s.name}</td>
                    <td>{TYPE_VI[s.station_type] ?? s.station_type}</td>
                    <td>{s.area?.name ?? '—'}</td>
                    <td>{ST_STATUS_VI[s.status] ?? s.status}</td>
                    <td><span className="chip text-white" style={{ background: CONN_COLOR[s.connection_status] ?? '#8A949C' }}>{CONN_VI[s.connection_status] ?? s.connection_status}</span></td>
                    <td className="num text-right">{fmtNum(s.latest_rainfall_mm)}</td>
                    <td className="num text-right">{fmtNum(s.latest_water_level_cm)}</td>
                    <td className="num">{fmtDateTime(s.last_observation_at)}</td>
                    <td className="num">{fmtDateTime(s.updated_at)}</td>
                    <td>{s.data_status === 'DEMO' ? <DemoBadge /> : <span className="chip border border-current">{DATA_STATUS_VI[s.data_status] ?? s.data_status}</span>}</td>
                    <td className="whitespace-nowrap">
                      <div className="flex gap-1">
                        <button className="btn-ghost" onClick={() => setDlg({ kind: 'detail', station: s })}>Chi tiết</button>
                        <button className="btn-ghost" onClick={() => setDlg({ kind: 'form', station: s })}>Sửa</button>
                        <button className="btn-ghost text-risk-high" onClick={() => setDlg({ kind: 'delete', station: s })}>Xoá</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
      </div>

      {dlg?.kind === 'form' && <StationForm station={dlg.station} onClose={close} />}
      {dlg?.kind === 'detail' && <StationDetail station={dlg.station} onClose={close} />}
      {dlg?.kind === 'import' && (
        <Modal title="Nhập dữ liệu quan trắc (nhiều trạm)" onClose={close} wide>
          <p className="muted mb-3 text-sm">Tệp CSV/XLSX gồm các cột station_code, observed_at, rainfall_mm, water_level_cm (hoặc water_level_m).</p>
          <ImportForm path="/stations/import" />
        </Modal>
      )}
      {dlg?.kind === 'delete' && (
        <Confirm title="Xoá trạm" danger confirmLabel="Xoá trạm" onClose={close}
          text={`Ngừng theo dõi trạm ${dlg.station.code} – ${dlg.station.name}? Trạm sẽ bị ẩn (xoá mềm), dữ liệu quan trắc vẫn được giữ lại.`}
          onConfirm={async () => { await act(() => api.del(`/stations/${dlg.station.id}`), 'Đã xoá trạm', ['stations']) }} />
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ form tạo/sửa */
const stationSchema = z.object({
  code: z.string().min(2, 'Tối thiểu 2 ký tự').max(30).regex(/^[A-Za-z0-9_-]+$/, 'Chỉ gồm chữ, số, "_" và "-"'),
  name: z.string().trim().min(2, 'Tối thiểu 2 ký tự').max(150),
  station_type: z.enum(['RAIN', 'WATER_LEVEL', 'COMBINED']),
  address: z.string().max(255),
  latitude: reqNum(num().min(-90, 'Vĩ độ từ -90 đến 90').max(90, 'Vĩ độ từ -90 đến 90')),
  longitude: reqNum(num().min(-180, 'Kinh độ từ -180 đến 180').max(180, 'Kinh độ từ -180 đến 180')),
  managing_unit: z.string().max(150),
  status: z.enum(['ACTIVE', 'INACTIVE', 'MAINTENANCE']),
  interval_minutes: reqNum(num().int('Phải là số nguyên').min(1, 'Từ 1 đến 1440 phút').max(1440, 'Từ 1 đến 1440 phút')),
  flood_threshold_cm: reqNum(num().gt(0, 'Phải lớn hơn 0').max(1000, 'Tối đa 1000 cm')),
  notes: z.string().max(2000),
})
type StationIn = z.infer<typeof stationSchema>

function StationForm({ station, onClose }: { station?: Station; onClose: () => void }) {
  const act = useAction()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<StationIn>({
    resolver: zodResolver(stationSchema),
    defaultValues: station ?? { code: '', name: '', station_type: 'COMBINED', address: '', managing_unit: '', status: 'ACTIVE',
      interval_minutes: 60, flood_threshold_cm: 60, notes: '' },
  })
  const submit = handleSubmit(async (v) => {
    const ok = station
      ? await act(() => api.patch(`/stations/${station.id}`, { ...v, code: undefined }), 'Đã cập nhật trạm', ['stations'])
      : await act(() => api.post('/stations', v), 'Đã thêm trạm', ['stations'])
    if (ok) onClose()
  })
  const text = (k: keyof StationIn, label: string, type = 'text', extra?: object) => (
    <Field id={`sf-${k}`} label={label} error={errors[k]?.message}>
      <input id={`sf-${k}`} className="input" type={type} step="any" aria-invalid={!!errors[k]} {...extra} {...register(k)} />
    </Field>
  )
  return (
    <Modal title={station ? `Sửa trạm ${station.code}` : 'Thêm trạm quan trắc'} onClose={onClose} wide>
      <form noValidate onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        {text('code', 'Mã trạm', 'text', { readOnly: !!station })}
        {text('name', 'Tên trạm')}
        <Field id="sf-type" label="Loại trạm" error={errors.station_type?.message}>
          <select id="sf-type" className="input" {...register('station_type')}>
            {Object.entries(TYPE_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field id="sf-status" label="Trạng thái" error={errors.status?.message}>
          <select id="sf-status" className="input" {...register('status')}>
            {Object.entries(ST_STATUS_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        {text('latitude', 'Vĩ độ', 'number')}
        {text('longitude', 'Kinh độ', 'number')}
        {text('interval_minutes', 'Chu kỳ gửi dữ liệu (phút)', 'number')}
        {text('flood_threshold_cm', 'Ngưỡng ngập (cm)', 'number')}
        {text('address', 'Địa chỉ')}
        {text('managing_unit', 'Đơn vị quản lý')}
        <Field id="sf-notes" label="Ghi chú" error={errors.notes?.message} className="sm:col-span-2">
          <textarea id="sf-notes" className="input" rows={2} {...register('notes')} />
        </Field>
        <div className="sm:col-span-2"><FormActions busy={isSubmitting} onCancel={onClose} /></div>
      </form>
    </Modal>
  )
}

/* ------------------------------------------------------------------ chi tiết trạm */
function StationDetail({ station: s, onClose }: { station: Station; onClose: () => void }) {
  const nav = useNavigate()
  const [range, setRange] = useState({ from: '', to: '' })
  const rangeParams = { date_from: vnDateToIso(range.from), date_to: vnDateToIso(range.to, true) }
  const obs = useQuery({ queryKey: ['observations', s.id, rangeParams], queryFn: () => api.get<Obs[]>(`/stations/${s.id}/observations`, rangeParams) })
  const quality = useQuery({ queryKey: ['station-quality', s.id], queryFn: () => api.get<Quality>(`/stations/${s.id}/quality`, { days: 7 }) })

  const option = useMemo(() => ({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Lượng mưa (mm)', 'Mực nước (cm)'] },
    grid: { left: 48, right: 48, top: 36, bottom: 32 },
    xAxis: { type: 'time' },
    yAxis: [{ type: 'value', name: 'mm' }, { type: 'value', name: 'cm' }],
    series: [
      { name: 'Lượng mưa (mm)', type: 'bar', itemStyle: { color: '#1C7CB5' },
        data: (obs.data ?? []).map((o) => [o.observed_at, o.rainfall_mm]) },
      { name: 'Mực nước (cm)', type: 'line', yAxisIndex: 1, showSymbol: false, itemStyle: { color: '#D99A00' },
        data: (obs.data ?? []).map((o) => [o.observed_at, o.water_level_cm]),
        markLine: { symbol: 'none', lineStyle: { color: '#C62828', type: 'dashed' },
          label: { formatter: `Ngưỡng ngập ${s.flood_threshold_cm} cm` }, data: [{ yAxis: s.flood_threshold_cm }] } },
    ],
  }), [obs.data, s.flood_threshold_cm])

  const flags = (r: Record<string, number> | undefined) => ['VALID', 'SUSPECT', 'MISSING'].map((k) => r?.[k] ?? 0)

  return (
    <Modal title={`${s.code} – ${s.name}`} onClose={onClose} wide>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        {s.data_status === 'DEMO' && <DemoBadge />}
        <span className="muted">{TYPE_VI[s.station_type]} · {s.area?.name ?? 'Chưa gán khu vực'} · ngưỡng ngập {fmtNum(s.flood_threshold_cm, ' cm')}</span>
        <button className="btn-ghost ml-auto" onClick={() => nav('/')}>Xem trên bản đồ</button>
      </div>

      <section aria-label="Chuỗi quan trắc" className="mb-4">
        <div className="mb-2 flex flex-wrap items-end gap-2">
          <Field id="obs-from" label="Từ ngày"><input id="obs-from" type="date" className="input" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} /></Field>
          <Field id="obs-to" label="Đến ngày"><input id="obs-to" type="date" className="input" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} /></Field>
          <span className="muted pb-2 text-xs">Để trống: 48 giờ gần nhất (tối đa 93 ngày)</span>
        </div>
        {obs.isLoading ? <Loading /> : obs.isError ? <ErrorState error={obs.error} retry={() => obs.refetch()} />
          : !obs.data?.length ? <Empty text="Không có quan trắc trong khoảng thời gian này." />
          : <Chart option={option} ariaLabel={`Biểu đồ lượng mưa và mực nước trạm ${s.code}`} />}
      </section>

      <section aria-label="Chất lượng dữ liệu" className="mb-4">
        <h3 className="mb-2 font-semibold">Chất lượng dữ liệu 7 ngày · phát hiện dữ liệu bất thường</h3>
        {quality.isLoading ? <Loading rows={2} /> : quality.isError ? <ErrorState error={quality.error} retry={() => quality.refetch()} /> : quality.data && (
          <>
            <div className="mb-2 grid gap-2 sm:grid-cols-3">
              <Kpi label="Độ đầy đủ" value={fmtPct(quality.data.completeness)} hint={`Kỳ vọng ${fmtNum(quality.data.expected_records)} bản ghi`} />
              <Kpi label="Độ trễ dữ liệu" value={fmtNum(quality.data.delay_minutes, ' phút')} hint={`Chu kỳ ${s.interval_minutes} phút`}
                tone={quality.data.delay_minutes !== null && quality.data.delay_minutes > 3 * s.interval_minutes ? '#C62828' : undefined} />
              <Kpi label="Bản ghi nghi ngờ / thiếu" value={`${flags(quality.data.rainfall)[1] + flags(quality.data.water_level)[1]} / ${flags(quality.data.rainfall)[2] + flags(quality.data.water_level)[2]}`} />
            </div>
            <table className="table">
              <thead><tr><th>Chuỗi</th><th className="text-right">Hợp lệ</th><th className="text-right">Nghi ngờ</th><th className="text-right">Thiếu</th></tr></thead>
              <tbody>
                {([['Lượng mưa', quality.data.rainfall], ['Mực nước', quality.data.water_level]] as const).map(([n, r]) => (
                  <tr key={n}><td>{n}</td>{flags(r).map((c, i) => <td key={i} className="num text-right">{fmtNum(c)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section aria-label="Nhập quan trắc thủ công"><h3 className="mb-2 font-semibold">Nhập quan trắc thủ công</h3><ManualObs stationId={s.id} /></section>
        <section aria-label="Nhập tệp cho trạm"><h3 className="mb-2 font-semibold">Nhập tệp CSV/XLSX cho trạm này</h3><ImportForm path={`/stations/${s.id}/observations/import`} /></section>
      </div>
    </Modal>
  )
}

const obsSchema = z.object({
  observed_at: z.string().min(1, 'Chọn thời điểm quan trắc'),
  rainfall_mm: optNum(num().min(0, 'Từ 0 đến 500 mm').max(500, 'Từ 0 đến 500 mm')),
  water_level_cm: optNum(num().min(-500, 'Từ -500 đến 2000 cm').max(2000, 'Từ -500 đến 2000 cm')),
}).refine((v) => v.rainfall_mm !== undefined || v.water_level_cm !== undefined, { message: 'Nhập ít nhất lượng mưa hoặc mực nước', path: ['rainfall_mm'] })

function ManualObs({ stationId }: { stationId: number }) {
  const [report, setReport] = useState<ImportReport | null>(null)
  const act = useAction()
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<z.infer<typeof obsSchema>>({ resolver: zodResolver(obsSchema) })
  return (
    <form noValidate className="space-y-3" onSubmit={handleSubmit(async (v) => {
      const ok = await act(async () => setReport(await api.post<ImportReport>(`/stations/${stationId}/observations`,
        { ...v, observed_at: vnLocalToIso(v.observed_at) })), 'Đã gửi quan trắc', ['observations', 'station-quality', 'stations'])
      if (ok) reset()
    })}>
      <Field id="mo-at" label="Thời điểm (giờ Việt Nam)" error={errors.observed_at?.message}>
        <input id="mo-at" type="datetime-local" className="input" {...register('observed_at')} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field id="mo-rain" label="Lượng mưa (mm)" error={errors.rainfall_mm?.message}>
          <input id="mo-rain" type="number" step="any" className="input" {...register('rainfall_mm')} />
        </Field>
        <Field id="mo-wl" label="Mực nước (cm)" error={errors.water_level_cm?.message}>
          <input id="mo-wl" type="number" step="any" className="input" {...register('water_level_cm')} />
        </Field>
      </div>
      <button className="btn-primary" disabled={isSubmitting}>{isSubmitting ? 'Đang gửi…' : 'Gửi quan trắc'}</button>
      {report && <ReportView r={report} />}
    </form>
  )
}

const fileForm = z.object({ file: fileSchema(['.csv', '.xlsx'], 10) })

function ImportForm({ path }: { path: string }) {
  const [report, setReport] = useState<ImportReport | null>(null)
  const act = useAction()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof fileForm>>({ resolver: zodResolver(fileForm) })
  const id = `imp-${path.replace(/\W/g, '')}`
  return (
    <form noValidate className="space-y-3" onSubmit={handleSubmit(async (v) => {
      await act(async () => setReport(await api.post<ImportReport>(path, formData({ file: v.file[0] }))),
        'Đã xử lý tệp', ['observations', 'station-quality', 'stations'])
    })}>
      <Field id={id} label="Tệp dữ liệu (.csv, .xlsx, tối đa 10 MB)" error={errors.file?.message}>
        <input id={id} type="file" accept=".csv,.xlsx" className="input" {...register('file')} />
      </Field>
      <button className="btn-primary" disabled={isSubmitting}>{isSubmitting ? 'Đang nhập…' : 'Nhập dữ liệu'}</button>
      {report && <ReportView r={report} />}
    </form>
  )
}

function ReportView({ r }: { r: ImportReport }) {
  return (
    <div className="rounded-lg border border-[var(--line)] p-3 text-sm" role="status">
      <p className="num">Tổng {r.total_rows} dòng · thêm mới <b>{r.inserted}</b> · trùng lặp {r.duplicates} · bị từ chối <b className={r.rejected ? 'text-risk-high' : ''}>{r.rejected}</b></p>
      {r.errors.length > 0 && (
        <ul className="mt-2 max-h-40 list-disc overflow-auto pl-5 text-xs text-risk-high">
          {r.errors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
    </div>
  )
}
