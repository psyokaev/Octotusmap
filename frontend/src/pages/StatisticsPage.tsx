import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useCameraEnabled } from '../lib/health'
import { api, download, type Page } from '../lib/api'
import { fmtNum, fmtPct } from '../lib/format'
import { RISK, STATUS_VI } from '../lib/risk'
import { Chart, DemoBadge, Kpi, Loading, ErrorState, PageHeader, Pager, useToast } from '../components/ui'
import {
  C, axisOption, errMsg, fmtDec, fmtUtc, isVision, metric, useFilters,
  type AlertStats, type CameraStat, type FloodEventStats, type Group, type HandlingRow, type ModelPerf, type ObsRow,
  type ObsStats, type QualityRow, type RiskStats, type StatParams, type StationStat,
} from '../features/analytics/analytics'
import { DataTable, FilterBar, ModelMetrics, QueryState, Section, type Col } from '../features/analytics/components'

const TABS = [
  { id: 'rainfall', label: 'Lượng mưa', report: 'rainfall' },
  { id: 'water', label: 'Mực nước', report: 'water_level' },
  { id: 'risk', label: 'Nguy cơ ngập', report: 'full' },
  { id: 'alerts', label: 'Lịch sử cảnh báo', report: 'alerts' },
  { id: 'events', label: 'Sự kiện ngập lịch sử', report: 'history' },
  { id: 'perf', label: 'Hiệu quả dự báo', report: 'forecasts' },
  { id: 'cameras', label: 'Camera', report: 'cameras' },
  { id: 'stations', label: 'Trạm quan trắc', report: 'stations' },
  { id: 'quality', label: 'Dữ liệu thiếu/lỗi', report: 'stations' },
  { id: 'handling', label: 'Hoạt động xử lý cảnh báo', report: 'alerts' },
] as const
type TabId = (typeof TABS)[number]['id']

const REPORTS: { id: string; label: string }[] = [
  { id: 'full', label: 'Báo cáo tổng hợp' }, { id: 'rainfall', label: 'Lượng mưa' }, { id: 'water_level', label: 'Mực nước' },
  { id: 'alerts', label: 'Cảnh báo ngập' }, { id: 'history', label: 'Sự kiện ngập lịch sử' }, { id: 'forecasts', label: 'Dự báo AI' },
  { id: 'models', label: 'Đánh giá mô hình' }, { id: 'stations', label: 'Trạm quan trắc' }, { id: 'cameras', label: 'Camera' },
]
const ACTION_VI: Record<string, string> = {
  CREATED: 'Tạo cảnh báo', ESCALATED: 'Nâng mức', STATUS: 'Đổi trạng thái', ASSIGN: 'Phân công', NOTE: 'Ghi chú', VERIFY: 'Xác minh',
}
const CONN_VI: Record<string, string> = { ONLINE: 'Đang kết nối', OFFLINE: 'Mất kết nối', NO_DATA: 'Chưa có dữ liệu' }
const LEVELS = ['LOW', 'MEDIUM', 'HIGH'] as const

export default function StatisticsPage() {
  const toast = useToast()
  const id = useId()
  const { state, setState, params, group } = useFilters()
  const [tab, setTab] = useState<TabId>('rainfall')
  const [reportPick, setReportPick] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])
  const cameraEnabled = useCameraEnabled()
  const tabs = TABS.filter((t) => t.id !== 'cameras' || cameraEnabled)
  const current = tabs.find((t) => t.id === tab) ?? tabs[0]
  const report = reportPick ?? current.report
  const csvKind = tab === 'rainfall' ? 'rainfall' : tab === 'water' ? 'water_level' : null

  const run = async (path: string, extra: Record<string, string>) => {
    setBusy(true)
    try { toast('ok', `Đã tải xuống ${await download(path, { ...params, ...extra })}`) }
    catch (e) { toast('error', errMsg(e)) }
    finally { setBusy(false) }
  }

  const select = (i: number) => { setTab(tabs[i].id); setReportPick(null); tabRefs.current[i]?.focus() }
  const onTabKey = (e: KeyboardEvent, i: number) => {
    const n = tabs.length
    const next = { ArrowRight: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key]
    if (next !== undefined) { e.preventDefault(); select(next) }
  }

  return (
    <div>
      <PageHeader title="Thống kê">
        <label htmlFor={`${id}-report`} className="sr-only">Loại báo cáo Excel</label>
        <select id={`${id}-report`} className="input w-auto" value={report} onChange={(e) => setReportPick(e.target.value)}>
          {REPORTS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
        <button className="btn-primary" disabled={busy} onClick={() => run('/exports/excel', { report })}>Xuất Excel</button>
        {csvKind && <button className="btn-ghost" disabled={busy} onClick={() => run('/exports/csv', { kind: csvKind })}>Xuất CSV</button>}
      </PageHeader>
      <FilterBar value={state} onChange={setState} extended />

      <div role="tablist" aria-label="Nhóm thống kê" className="mb-4 flex gap-1 overflow-x-auto border-b border-[var(--line)]">
        {tabs.map((t, i) => (
          <button key={t.id} ref={(el) => { tabRefs.current[i] = el }} role="tab" id={`${id}-tab-${t.id}`}
            aria-selected={tab === t.id} aria-controls={`${id}-panel`} tabIndex={tab === t.id ? 0 : -1}
            onClick={() => select(i)} onKeyDown={(e) => onTabKey(e, i)}
            className={clsx('-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium',
              tab === t.id ? 'border-water text-water' : 'muted border-transparent hover:text-[var(--text)]')}>
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${tab}`}>
        {tab === 'rainfall' && <ObsTab key="rain" kind="rainfall" params={params} group={group} />}
        {tab === 'water' && <ObsTab key="water" kind="water_level" params={params} group={group} />}
        {tab === 'risk' && <RiskTab params={params} group={group} />}
        {tab === 'alerts' && <AlertsTab params={params} group={group} />}
        {tab === 'events' && <EventsTab params={params} group={group} />}
        {tab === 'perf' && <PerfTab params={params} />}
        {tab === 'cameras' && <CamerasTab params={params} />}
        {tab === 'stations' && <StationsTab params={params} />}
        {tab === 'quality' && <QualityTab params={params} />}
        {tab === 'handling' && <HandlingTab params={params} />}
      </div>
    </div>
  )
}

type TabProps = { params: StatParams; group: Group }

/* ------------------------------------------------------------------ mưa / mực nước */
function ObsTab({ kind, params, group }: TabProps & { kind: 'rainfall' | 'water_level' }) {
  const rain = kind === 'rainfall'
  const unit = rain ? 'mm' : 'cm'
  const [page, setPage] = useState(1)
  const size = 50
  const stats = useQuery({ queryKey: ['stats', kind, params, group],
    queryFn: () => api.get<ObsStats>(rain ? '/statistics/rainfall' : '/statistics/water-level', { ...params, group }) })
  const obs = useQuery({ queryKey: ['stats', 'obs', kind, params, page], placeholderData: (prev) => prev,
    queryFn: () => api.get<Page<ObsRow>>('/statistics/observations', { ...params, kind, page, size }) })
  // đổi bộ lọc -> về trang 1
  const [lastParams, setLastParams] = useState(params)
  if (lastParams !== params) { setLastParams(params); setPage(1) }

  const opt = useMemo(() => {
    const s = stats.data?.series ?? []
    return axisOption(s.map((x) => x.bucket), rain ? [
      { name: `Tổng (${unit})`, type: 'bar', data: s.map((x) => x.sum), itemStyle: { color: C.water } },
      { name: `Cao nhất 1 lần đo (${unit})`, type: 'line', data: s.map((x) => x.max), itemStyle: { color: RISK.HIGH.color }, showSymbol: false },
    ] : [
      { name: `Cao nhất (${unit})`, type: 'line', data: s.map((x) => x.max), itemStyle: { color: RISK.HIGH.color }, showSymbol: false },
      { name: `Trung bình (${unit})`, type: 'line', data: s.map((x) => x.avg), itemStyle: { color: C.water }, showSymbol: false },
    ], { type: 'value', name: unit, scale: !rain })
  }, [stats.data, rain, unit])

  const cols: Col<ObsStats['by_station'][number]>[] = [
    { key: 'code', label: 'Mã trạm', value: (r) => r.code },
    { key: 'name', label: 'Tên trạm', value: (r) => r.name },
    ...(rain ? [{ key: 'sum', label: `Tổng (${unit})`, value: (r: ObsStats['by_station'][number]) => r.sum, render: (r: ObsStats['by_station'][number]) => fmtNum(r.sum), num: true }] : []),
    { key: 'avg', label: `Trung bình (${unit})`, value: (r) => r.avg, render: (r) => fmtNum(r.avg), num: true },
    { key: 'max', label: `Cao nhất (${unit})`, value: (r) => r.max, render: (r) => fmtNum(r.max), num: true },
    { key: 'count', label: 'Số lần đo hợp lệ', value: (r) => r.count, render: (r) => fmtNum(r.count), num: true },
  ]

  return (
    <div className="grid gap-4">
      <Section title={rain ? 'Lượng mưa theo thời gian' : 'Mực nước theo thời gian'}>
        <QueryState q={stats} isEmpty={(d) => !d.series.length}>{() => <Chart option={opt} ariaLabel={rain ? 'Biểu đồ lượng mưa theo thời gian' : 'Biểu đồ mực nước theo thời gian'} />}</QueryState>
      </Section>
      <Section title="Tổng hợp theo trạm">
        <QueryState q={stats}>{(d) => <DataTable rows={d.by_station} cols={cols} rowKey={(r) => r.station_id} label="Tổng hợp theo trạm" />}</QueryState>
      </Section>
      <Section title="Dữ liệu quan trắc chi tiết" actions={obs.isFetching && !obs.isLoading ? <span className="muted text-xs">Đang tải…</span> : undefined}>
        <QueryState q={obs} isEmpty={(d) => !d.items.length}>{(d) => (
          <>
            <div className="overflow-x-auto">
              <table className="table">
                <caption className="sr-only">Dữ liệu quan trắc chi tiết, mới nhất trước</caption>
                <thead><tr><th>Thời điểm</th><th>Trạm</th><th>Khu vực</th><th>Giá trị ({unit})</th><th>Chất lượng</th><th>Nguồn</th></tr></thead>
                <tbody>{d.items.map((r, i) => (
                  <tr key={`${r.observed_at}-${r.station_code}-${i}`}>
                    <td className="num whitespace-nowrap">{fmtUtc(r.observed_at)}</td>
                    <td>{r.station_code} · {r.station_name}</td>
                    <td>{r.area ?? '—'}</td>
                    <td className="num">{fmtNum(r.value)}</td>
                    <td><span className={clsx('chip', r.quality === 'VALID' ? 'bg-black/5 dark:bg-white/10' : 'bg-risk-medium/20')}>{r.quality}</span></td>
                    <td>{r.is_simulated ? <DemoBadge /> : 'Thật'}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <Pager page={d.page} size={d.size} total={d.total} onPage={setPage} />
          </>
        )}</QueryState>
      </Section>
    </div>
  )
}

/* ------------------------------------------------------------------ nguy cơ */
function RiskTab({ params, group }: TabProps) {
  const q = useQuery({ queryKey: ['stats', 'risk', params, group], queryFn: () => api.get<RiskStats>('/statistics/risk', { ...params, group }) })
  const opts = useMemo(() => {
    const s = q.data?.trend ?? []
    const cur = q.data?.current ?? {}
    return {
      trend: axisOption(s.map((x) => x.bucket), [
        ...([...LEVELS, 'INSUFFICIENT_DATA'] as const).map((k) => ({ name: RISK[k].label, type: 'bar', stack: 'r', data: s.map((x) => x[k]), itemStyle: { color: RISK[k].color } })),
        { name: 'Điểm TB', type: 'line', yAxisIndex: 1, data: s.map((x) => x.avg_score), itemStyle: { color: C.ink }, showSymbol: false },
      ], [{ type: 'value', name: 'lượt' }, { type: 'value', name: 'điểm', min: 0 }]),
      pie: { tooltip: { trigger: 'item' }, legend: { bottom: 0 }, series: [{ type: 'pie', radius: ['45%', '70%'],
        data: ([...LEVELS, 'INSUFFICIENT_DATA'] as const).filter((k) => cur[k]).map((k) => ({ name: RISK[k].label, value: cur[k], itemStyle: { color: RISK[k].color } })) }] },
    }
  }, [q.data])
  const cols: Col<RiskStats['trend'][number]>[] = [
    { key: 'bucket', label: 'Thời gian', value: (r) => r.bucket },
    ...LEVELS.map((k) => ({ key: k, label: RISK[k].label, value: (r: RiskStats['trend'][number]) => r[k], num: true })),
    { key: 'INSUFFICIENT_DATA', label: 'Thiếu dữ liệu', value: (r) => r.INSUFFICIENT_DATA, num: true },
    { key: 'avg_score', label: 'Điểm TB', value: (r) => r.avg_score, render: (r) => fmtDec(r.avg_score), num: true },
  ]
  return (
    <QueryState q={q}>{(d) => (
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Xu hướng đánh giá nguy cơ (hiện tại, theo khu vực)" className="lg:col-span-2">
          {d.trend.length ? <Chart option={opts.trend} ariaLabel="Biểu đồ số lượt đánh giá nguy cơ theo mức theo thời gian" /> : <p className="muted text-sm">Không có dữ liệu trong khoảng thời gian đã chọn</p>}
        </Section>
        <Section title="Phân bố mức nguy cơ mới nhất">
          {Object.keys(d.current).length ? <Chart option={opts.pie} ariaLabel="Biểu đồ tròn phân bố mức nguy cơ mới nhất" /> : <p className="muted text-sm">Chưa có đánh giá</p>}
        </Section>
        <Section title="Bảng số liệu" className="lg:col-span-3">
          <DataTable rows={d.trend} cols={cols} rowKey={(r) => r.bucket} label="Xu hướng nguy cơ" />
        </Section>
      </div>
    )}</QueryState>
  )
}

/* ------------------------------------------------------------------ cảnh báo */
function AlertsTab({ params, group }: TabProps) {
  const q = useQuery({ queryKey: ['stats', 'alerts', params, group], queryFn: () => api.get<AlertStats>('/statistics/alerts', { ...params, group }) })
  const opts = useMemo(() => {
    const s = q.data?.by_time ?? []
    const a = (q.data?.by_area ?? []).slice(0, 15)
    return {
      time: axisOption(s.map((x) => x.bucket), LEVELS.map((k) => ({ name: RISK[k].label, type: 'bar', stack: 'lv', data: s.map((x) => x[k]), itemStyle: { color: RISK[k].color } }))),
      area: axisOption(a.map((x) => x.area), [{ name: 'Số cảnh báo', type: 'bar', data: a.map((x) => x.count), itemStyle: { color: C.amber } }], { type: 'value', minInterval: 1 }, true),
    }
  }, [q.data])
  return (
    <QueryState q={q}>{(d) => (
      <div className="grid gap-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Tổng cảnh báo" value={fmtNum(d.total)} />
          <Kpi label="Tỉ lệ đúng (đã xác minh)" value={fmtPct(d.precision_verified)} hint={`Xác nhận ${d.verification.CONFIRMED ?? 0} · báo nhầm ${d.verification.FALSE_ALARM ?? 0}`} />
          <Kpi label="Thời gian tiếp nhận TB" value={fmtNum(d.avg_minutes_to_ack, ' phút')} />
          <Kpi label="Thời gian xử lý TB" value={fmtNum(d.avg_minutes_to_resolve, ' phút')} />
        </div>
        {d.total === 0 ? <Section title="Cảnh báo"><p className="muted text-sm">Không có cảnh báo trong khoảng thời gian đã chọn</p></Section> : (
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="Cảnh báo theo thời gian và mức"><Chart option={opts.time} ariaLabel="Biểu đồ cột chồng cảnh báo theo thời gian và mức" /></Section>
            <Section title="Cảnh báo theo khu vực"><Chart option={opts.area} height={Math.max(220, Math.min(15, d.by_area.length) * 26 + 60)} ariaLabel="Biểu đồ cảnh báo theo khu vực" /></Section>
            <Section title="Theo trạng thái">
              <DataTable rows={Object.entries(d.by_status).map(([k, v]) => ({ k, v }))} rowKey={(r) => r.k} label="Cảnh báo theo trạng thái"
                cols={[{ key: 'k', label: 'Trạng thái', value: (r) => STATUS_VI[r.k] ?? r.k }, { key: 'v', label: 'Số lượng', value: (r) => r.v, num: true }]} />
            </Section>
            <Section title="Theo khu vực">
              <DataTable rows={d.by_area} rowKey={(r) => r.area} label="Cảnh báo theo khu vực"
                cols={[{ key: 'area', label: 'Khu vực', value: (r) => r.area }, { key: 'count', label: 'Số cảnh báo', value: (r) => r.count, num: true }]} />
            </Section>
          </div>
        )}
      </div>
    )}</QueryState>
  )
}

/* ------------------------------------------------------------------ sự kiện ngập lịch sử */
function EventsTab({ params, group }: TabProps) {
  const q = useQuery({ queryKey: ['stats', 'events', params, group], queryFn: () => api.get<FloodEventStats>('/statistics/flood-events', { ...params, group }) })
  const opt = useMemo(() => {
    const s = q.data?.by_time ?? []
    return axisOption(s.map((x) => x.bucket), [
      { name: 'Số sự kiện', type: 'bar', data: s.map((x) => x.count), itemStyle: { color: C.purple } },
      { name: 'Độ sâu lớn nhất (cm)', type: 'line', yAxisIndex: 1, data: s.map((x) => x.max_depth_cm), itemStyle: { color: RISK.HIGH.color } },
    ], [{ type: 'value', name: 'sự kiện', minInterval: 1 }, { type: 'value', name: 'cm' }])
  }, [q.data])
  return (
    <QueryState q={q} isEmpty={(d) => !d.total} emptyText="Không có sự kiện ngập trong khoảng thời gian đã chọn">{(d) => (
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title={`Sự kiện ngập theo thời gian (${fmtNum(d.total)} sự kiện)`} className="lg:col-span-2">
          <Chart option={opt} ariaLabel="Biểu đồ số sự kiện ngập và độ sâu lớn nhất theo thời gian" />
        </Section>
        <Section title="Theo khu vực">
          <DataTable rows={d.by_area} rowKey={(r) => r.area} label="Sự kiện ngập theo khu vực" pageSize={10}
            cols={[{ key: 'area', label: 'Khu vực', value: (r) => r.area }, { key: 'count', label: 'Số sự kiện', value: (r) => r.count, num: true }]} />
        </Section>
      </div>
    )}</QueryState>
  )
}

/* ------------------------------------------------------------------ hiệu quả dự báo */
function PerfTab({ params }: { params: StatParams }) {
  const cameraEnabled = useCameraEnabled()
  const q = useQuery({ queryKey: ['stats', 'perf', params], queryFn: () => api.get<ModelPerf>('/statistics/model-performance', params) })
  const opt = useMemo(() => {
    const s = q.data?.online_rainfall_skill ?? []
    return axisOption(s.map((x) => `+${x.horizon_h}h`), [
      { name: 'MAE (mm)', type: 'bar', data: s.map((x) => x.mae), itemStyle: { color: C.water } },
      { name: 'RMSE (mm)', type: 'bar', data: s.map((x) => x.rmse), itemStyle: { color: C.ink } },
    ], { type: 'value', name: 'mm' })
  }, [q.data])
  type M = ModelPerf['models'][number]
  const cols: Col<M>[] = [
    { key: 'name', label: 'Mô hình', value: (r) => r.name, render: (r) => <>{r.name} {r.trained_on_simulated && <DemoBadge />}</> },
    { key: 'type', label: 'Loại', value: (r) => r.type },
    { key: 'version', label: 'Phiên bản', value: (r) => r.version },
    { key: 'active', label: 'Đang dùng', value: (r) => (r.active ? 'Có' : 'Không') },
    { key: 'k1', label: 'MAE mưa / mask mAP50', value: (r) => metric(r.metrics, isVision(r.type) ? 'mask_map50' : 'rainfall.mae'), render: (r) => fmtDec(metric(r.metrics, isVision(r.type) ? 'mask_map50' : 'rainfall.mae')), num: true },
    { key: 'k2', label: 'F1 ngập hoặc mưa to / recall', value: (r) => metric(r.metrics, isVision(r.type) ? 'recall' : r.metrics?.heavy_rain ? 'heavy_rain.f1' : 'flood.f1'), render: (r) => fmtPct(metric(r.metrics, isVision(r.type) ? 'recall' : r.metrics?.heavy_rain ? 'heavy_rain.f1' : 'flood.f1')), num: true },
  ]
  const models = q.data?.models.filter((m) => cameraEnabled || !isVision(m.type)) ?? []
  const active = models.filter((m) => m.active)
  return (
    <QueryState q={q}>{(d) => (
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Sai số dự báo mưa đối chiếu quan trắc">
          {d.online_rainfall_skill.length ? (
            <>
              <Chart option={opt} ariaLabel="Biểu đồ MAE và RMSE dự báo mưa theo mốc giờ" />
              <table className="table num mt-2"><caption className="sr-only">Sai số theo mốc</caption>
                <thead><tr><th>Mốc</th><th>MAE (mm)</th><th>RMSE (mm)</th><th>Số cặp</th></tr></thead>
                <tbody>{d.online_rainfall_skill.map((x) => <tr key={x.horizon_h}><td>+{x.horizon_h}h</td><td>{fmtDec(x.mae)}</td><td>{fmtDec(x.rmse)}</td><td>{fmtNum(x.n)}</td></tr>)}</tbody>
              </table>
            </>
          ) : <p className="muted text-sm">Chưa đủ cặp dự báo – quan trắc trong khoảng thời gian này.</p>}
        </Section>
        <Section title="Mô hình đang hoạt động">
          {active.length ? active.map((m) => (
            <div key={m.id} className="mb-4">
              <h3 className="mb-2 text-sm font-medium">{m.name} ({m.type}) {m.trained_on_simulated && <DemoBadge />}</h3>
              <ModelMetrics type={m.type} metrics={m.metrics} />
            </div>
          )) : <p className="muted text-sm">Chưa có mô hình hoạt động</p>}
          <p className="muted text-xs">Xác minh cảnh báo trong kỳ: {Object.entries(d.alert_verification).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'chưa có'}</p>
        </Section>
        <Section title="Tất cả phiên bản mô hình" className="lg:col-span-2">
          <DataTable rows={models} cols={cols} rowKey={(r) => r.id} label="Danh sách phiên bản mô hình" />
        </Section>
      </div>
    )}</QueryState>
  )
}

/* ------------------------------------------------------------------ camera */
function CamerasTab({ params }: { params: StatParams }) {
  const q = useQuery({ queryKey: ['stats', 'cameras', params], queryFn: () => api.get<CameraStat[]>('/statistics/cameras', params) })
  const opt = useMemo(() => {
    const s = (q.data ?? []).filter((x) => x.detections > 0)
    return axisOption(s.map((x) => x.code), [
      { name: 'Tỉ lệ ngập lớn nhất (%)', type: 'bar', data: s.map((x) => (x.max_flood_ratio === null ? null : Math.round(x.max_flood_ratio * 100))), itemStyle: { color: RISK.HIGH.color } },
      { name: 'Tỉ lệ ngập trung bình (%)', type: 'bar', data: s.map((x) => (x.avg_flood_ratio === null ? null : Math.round(x.avg_flood_ratio * 100))), itemStyle: { color: C.water } },
    ], { type: 'value', name: '%', max: 100 })
  }, [q.data])
  const cols: Col<CameraStat>[] = [
    { key: 'code', label: 'Mã', value: (r) => r.code },
    { key: 'name', label: 'Tên camera', value: (r) => r.name, render: (r) => <>{r.name} {r.is_simulated && <DemoBadge />}</> },
    { key: 'area', label: 'Khu vực', value: (r) => r.area },
    { key: 'status', label: 'Trạng thái', value: (r) => r.status },
    { key: 'detections', label: 'Lượt phân tích', value: (r) => r.detections, num: true },
    { key: 'max', label: 'Ngập lớn nhất', value: (r) => r.max_flood_ratio, render: (r) => fmtPct(r.max_flood_ratio), num: true },
    { key: 'avg', label: 'Ngập trung bình', value: (r) => r.avg_flood_ratio, render: (r) => fmtPct(r.avg_flood_ratio), num: true },
    { key: 'last', label: 'Lần cuối', value: (r) => r.last_detection_at, render: (r) => fmtUtc(r.last_detection_at), num: true },
  ]
  return (
    <QueryState q={q} isEmpty={(d) => !d.length} emptyText="Chưa có camera">{(d) => (
      <div className="grid gap-4">
        <Section title="Tỉ lệ vùng ngập phát hiện qua camera">
          {d.some((x) => x.detections > 0) ? <Chart option={opt} ariaLabel="Biểu đồ tỉ lệ ngập lớn nhất và trung bình theo camera" /> : <p className="muted text-sm">Không có lượt phân tích trong khoảng thời gian đã chọn</p>}
        </Section>
        <Section title="Danh sách camera"><DataTable rows={d} cols={cols} rowKey={(r) => r.id} label="Thống kê camera" /></Section>
      </div>
    )}</QueryState>
  )
}

/* ------------------------------------------------------------------ trạm */
function StationsTab({ params }: { params: StatParams }) {
  const q = useQuery({ queryKey: ['stats', 'stations'], queryFn: () => api.get<StationStat[]>('/statistics/stations') })
  // endpoint không nhận bộ lọc -> lọc khu vực/trạm phía client
  const rows = useMemo(() => (q.data ?? []).filter((s) =>
    (!params.area_id || String(s.area_id) === params.area_id) && (!params.station_id || String(s.id) === params.station_id)), [q.data, params])
  const opt = useMemo(() => {
    const cnt: Record<string, number> = {}
    rows.forEach((s) => { cnt[s.connection] = (cnt[s.connection] ?? 0) + 1 })
    const color: Record<string, string> = { ONLINE: RISK.LOW.color, OFFLINE: RISK.HIGH.color }
    return { tooltip: { trigger: 'item' }, legend: { bottom: 0 }, series: [{ type: 'pie', radius: ['45%', '70%'],
      data: Object.entries(cnt).map(([k, v]) => ({ name: CONN_VI[k] ?? k, value: v, itemStyle: { color: color[k] ?? RISK.NO_DATA.color } })) }] }
  }, [rows])
  const cols: Col<StationStat>[] = [
    { key: 'code', label: 'Mã', value: (r) => r.code },
    { key: 'name', label: 'Tên trạm', value: (r) => r.name, render: (r) => <>{r.name} {r.is_simulated && <DemoBadge />}</> },
    { key: 'type', label: 'Loại', value: (r) => r.type },
    { key: 'area', label: 'Khu vực', value: (r) => r.area },
    { key: 'status', label: 'Trạng thái', value: (r) => r.status },
    { key: 'connection', label: 'Kết nối', value: (r) => CONN_VI[r.connection] ?? r.connection },
    { key: 'last', label: 'Quan trắc gần nhất', value: (r) => r.last_observation_at, render: (r) => fmtUtc(r.last_observation_at), num: true },
    { key: 'threshold', label: 'Ngưỡng ngập (cm)', value: (r) => r.flood_threshold_cm, num: true },
    { key: 'source', label: 'Nguồn', value: (r) => r.source },
  ]
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Section title="Tình trạng kết nối">
        {rows.length ? <Chart option={opt} ariaLabel="Biểu đồ tròn tình trạng kết nối trạm" /> : <p className="muted text-sm">Không có trạm phù hợp bộ lọc</p>}
      </Section>
      <Section title="Danh sách trạm" className="lg:col-span-2"><DataTable rows={rows} cols={cols} rowKey={(r) => r.id} label="Danh sách trạm quan trắc" /></Section>
    </div>
  )
}

/* ------------------------------------------------------------------ chất lượng dữ liệu */
const QUALITY_BASE = ['kind', 'code', 'name', 'total', 'valid_ratio']
function QualityTab({ params }: { params: StatParams }) {
  const q = useQuery({ queryKey: ['stats', 'quality', params], queryFn: () => api.get<QualityRow[]>('/statistics/data-quality', params) })
  const flags = useMemo(() => [...new Set((q.data ?? []).flatMap((r) => Object.keys(r).filter((k) => !QUALITY_BASE.includes(k))))].sort(), [q.data])
  const opt = useMemo(() => {
    const s = q.data ?? []
    const codes = [...new Set(s.map((r) => r.code))]
    const ratio = (kind: string) => codes.map((c) => { const r = s.find((x) => x.code === c && x.kind === kind); return r?.valid_ratio == null ? null : Math.round(r.valid_ratio * 1000) / 10 })
    return axisOption(codes, [...new Set(s.map((r) => r.kind))].map((k, i) => ({ name: `${k} hợp lệ (%)`, type: 'bar', data: ratio(k), itemStyle: { color: i ? C.ink : C.water } })),
      { type: 'value', name: '%', max: 100 })
  }, [q.data])
  const cols: Col<QualityRow>[] = [
    { key: 'kind', label: 'Loại', value: (r) => r.kind },
    { key: 'code', label: 'Mã trạm', value: (r) => r.code },
    { key: 'name', label: 'Tên trạm', value: (r) => r.name },
    { key: 'total', label: 'Tổng bản ghi', value: (r) => r.total, num: true },
    ...flags.map((f) => ({ key: f, label: f, value: (r: QualityRow) => (typeof r[f] === 'number' ? (r[f] as number) : 0), num: true })),
    { key: 'valid_ratio', label: 'Tỉ lệ hợp lệ', value: (r) => r.valid_ratio, render: (r) => fmtPct(r.valid_ratio), num: true },
  ]
  return (
    <QueryState q={q} isEmpty={(d) => !d.length}>{(d) => (
      <div className="grid gap-4">
        <Section title="Tỉ lệ dữ liệu hợp lệ theo trạm"><Chart option={opt} ariaLabel="Biểu đồ tỉ lệ dữ liệu hợp lệ theo trạm" /></Section>
        <Section title="Chi tiết bản ghi theo cờ chất lượng"><DataTable rows={d} cols={cols} rowKey={(r) => `${r.kind}-${r.code}`} label="Chất lượng dữ liệu" /></Section>
      </div>
    )}</QueryState>
  )
}

/* ------------------------------------------------------------------ xử lý cảnh báo */
function HandlingTab({ params }: { params: StatParams }) {
  const q = useQuery({ queryKey: ['stats', 'handling', params], queryFn: () => api.get<HandlingRow[]>('/statistics/alert-handling', params) })
  const opt = useMemo(() => {
    const by: Record<string, number> = {}
    ;(q.data ?? []).forEach((r) => { by[r.action] = (by[r.action] ?? 0) + r.count })
    const keys = Object.keys(by)
    return axisOption(keys.map((k) => ACTION_VI[k] ?? k), [{ name: 'Số thao tác', type: 'bar', data: keys.map((k) => by[k]), itemStyle: { color: C.water } }], { type: 'value', minInterval: 1 })
  }, [q.data])
  const cols: Col<HandlingRow>[] = [
    { key: 'action', label: 'Thao tác', value: (r) => ACTION_VI[r.action] ?? r.action },
    { key: 'to', label: 'Trạng thái sau', value: (r) => (r.to_status ? STATUS_VI[r.to_status] ?? r.to_status : null), render: (r) => (r.to_status ? <span className="chip bg-black/5 dark:bg-white/10">{STATUS_VI[r.to_status] ?? r.to_status}</span> : '—') },
    { key: 'count', label: 'Số lượng', value: (r) => r.count, num: true },
  ]
  return (
    <QueryState q={q} isEmpty={(d) => !d.length} emptyText="Không có hoạt động xử lý trong khoảng thời gian đã chọn">{(d) => (
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Thao tác theo loại"><Chart option={opt} ariaLabel="Biểu đồ số thao tác xử lý cảnh báo theo loại" /></Section>
        <Section title="Chi tiết"><DataTable rows={d} cols={cols} rowKey={(r) => `${r.action}-${r.to_status}`} label="Hoạt động xử lý cảnh báo" /></Section>
      </div>
    )}</QueryState>
  )
}
