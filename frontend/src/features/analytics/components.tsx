import { useId, useMemo, useState, type ReactNode } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import clsx from 'clsx'
import { Empty, ErrorState, Loading, Pager, SortTh } from '../../components/ui'
import { fmtPct } from '../../lib/format'
import { RISK } from '../../lib/risk'
import {
  FORECAST_METRICS, PRESETS, VISION_METRICS, fmtDec, isVision, metric, useAreas, useStationOptions,
  type FilterState, type Metrics, type Preset,
} from './analytics'

/* ------------------------------------------------------------------ filter bar */
export function FilterBar({ value, onChange, extended }: { value: FilterState; onChange: (v: FilterState) => void; extended?: boolean }) {
  const id = useId()
  const areas = useAreas()
  const stations = useStationOptions(value.area_id)
  const set = (patch: Partial<FilterState>) => onChange({ ...value, ...patch })
  const badRange = value.preset === 'custom' && value.from && value.to && value.from > value.to
  const field = 'min-w-[150px] flex-1'
  return (
    <div className="panel mb-4 flex flex-wrap items-start gap-3 p-3" role="search" aria-label="Bộ lọc thống kê">
      <div className={field}>
        <label className="label" htmlFor={`${id}-preset`}>Khoảng thời gian</label>
        <select id={`${id}-preset`} className="input" value={value.preset} onChange={(e) => set({ preset: e.target.value as Preset })}>
          {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      </div>
      {value.preset === 'custom' && (
        <>
          <div className={field}>
            <label className="label" htmlFor={`${id}-from`}>Từ ngày</label>
            <input id={`${id}-from`} type="date" className="input" value={value.from} max={value.to || undefined}
              onChange={(e) => set({ from: e.target.value })} aria-invalid={!!badRange} />
          </div>
          <div className={field}>
            <label className="label" htmlFor={`${id}-to`}>Đến ngày</label>
            <input id={`${id}-to`} type="date" className="input" value={value.to} min={value.from || undefined}
              onChange={(e) => set({ to: e.target.value })} aria-invalid={!!badRange} />
            {badRange && <p className="field-error" role="alert">Ngày bắt đầu phải trước ngày kết thúc</p>}
            {(!value.from || !value.to) && <p className="muted mt-1 text-xs">Chọn đủ hai ngày; tạm dùng 7 ngày gần nhất.</p>}
          </div>
        </>
      )}
      <div className={field}>
        <label className="label" htmlFor={`${id}-area`}>Khu vực</label>
        <select id={`${id}-area`} className="input" value={value.area_id} disabled={areas.isLoading}
          onChange={(e) => set({ area_id: e.target.value, station_id: '' })}>
          <option value="">Tất cả khu vực</option>
          {areas.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </div>
      <div className={field}>
        <label className="label" htmlFor={`${id}-station`}>Trạm quan trắc</label>
        <select id={`${id}-station`} className="input" value={value.station_id} disabled={stations.isLoading}
          onChange={(e) => set({ station_id: e.target.value })}>
          <option value="">Tất cả trạm</option>
          {stations.data?.items.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}
        </select>
      </div>
      {extended && (
        <>
          <div className={field}>
            <label className="label" htmlFor={`${id}-risk`}>Mức nguy cơ</label>
            <select id={`${id}-risk`} className="input" value={value.risk_level} onChange={(e) => set({ risk_level: e.target.value })}>
              <option value="">Tất cả mức</option>
              {(['LOW', 'MEDIUM', 'HIGH'] as const).map((k) => <option key={k} value={k}>{RISK[k].label}</option>)}
            </select>
          </div>
          <div className={field}>
            <label className="label" htmlFor={`${id}-dt`}>Loại dữ liệu</label>
            <select id={`${id}-dt`} className="input" value={value.data_type} onChange={(e) => set({ data_type: e.target.value })}>
              <option value="">Tất cả</option>
              <option value="REAL">Dữ liệu thật</option>
              <option value="SIMULATED">Dữ liệu mô phỏng</option>
            </select>
          </div>
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ layout / states */
export function Section({ title, actions, children, className }: { title: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={clsx('panel min-w-0 p-4', className)} aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{title}</h2>{actions}
      </div>
      {children}
    </section>
  )
}

/** Hiển thị loading / lỗi / rỗng thống nhất cho một query. */
export function QueryState<T>({ q, isEmpty, emptyText = 'Không có dữ liệu trong khoảng thời gian đã chọn', children }: {
  q: UseQueryResult<T>; isEmpty?: (d: T) => boolean; emptyText?: string; children: (d: T) => ReactNode
}) {
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />
  if (q.data === undefined || isEmpty?.(q.data)) return <Empty text={emptyText} />
  return <>{children(q.data)}</>
}

/* ------------------------------------------------------------------ table */
export interface Col<T> {
  key: string; label: string
  value: (r: T) => string | number | boolean | null | undefined
  render?: (r: T) => ReactNode
  num?: boolean
}

/** Bảng có tìm kiếm, sắp xếp và phân trang phía client. */
export function DataTable<T>({ rows, cols, rowKey, label, pageSize = 20 }: {
  rows: T[]; cols: Col<T>[]; rowKey: (r: T, i: number) => string | number; label: string; pageSize?: number
}) {
  const id = useId()
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('')
  const [dir, setDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(1)
  const view = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const out = needle ? rows.filter((r) => cols.some((c) => String(c.value(r) ?? '').toLowerCase().includes(needle))) : [...rows]
    const col = cols.find((c) => c.key === sort)
    if (col) out.sort((a, b) => {
      const x = col.value(a), y = col.value(b)
      if (x === null || x === undefined) return 1 // giá trị trống luôn ở cuối
      if (y === null || y === undefined) return -1
      const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'vi', { numeric: true })
      return dir === 'asc' ? c : -c
    })
    return out
  }, [rows, cols, q, sort, dir])
  const pages = Math.max(1, Math.ceil(view.length / pageSize))
  const cur = Math.min(page, pages)
  const onSort = (c: string) => { if (c === sort) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(c); setDir('asc') } }
  if (!rows.length) return <Empty text="Không có dữ liệu trong khoảng thời gian đã chọn" />
  return (
    <div>
      <label htmlFor={`${id}-q`} className="sr-only">Tìm trong {label}</label>
      <input id={`${id}-q`} className="input mb-2 max-w-xs" type="search" placeholder="Tìm kiếm…" value={q}
        onChange={(e) => { setQ(e.target.value); setPage(1) }} />
      <div className="overflow-x-auto">
        <table className="table">
          <caption className="sr-only">{label}</caption>
          <thead><tr>{cols.map((c) => <SortTh key={c.key} label={c.label} col={c.key} sort={sort} dir={dir} onSort={onSort} />)}</tr></thead>
          <tbody>
            {view.slice((cur - 1) * pageSize, cur * pageSize).map((r, i) => (
              <tr key={rowKey(r, i)}>
                {cols.map((c) => <td key={c.key} className={clsx(c.num && 'num whitespace-nowrap')}>{c.render ? c.render(r) : String(c.value(r) ?? '—')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {view.length ? (view.length > pageSize && <Pager page={cur} size={pageSize} total={view.length} onPage={setPage} />)
        : <Empty text="Không có kết quả phù hợp" />}
    </div>
  )
}

/* ------------------------------------------------------------------ metrics */
/** Lưới chỉ số chính của một mô hình (dự báo hoặc YOLO). */
export function ModelMetrics({ type, metrics }: { type: string; metrics: Metrics | null }) {
  const defs = isVision(type) ? VISION_METRICS : FORECAST_METRICS
  if (!metrics) return <p className="muted text-sm">Chưa có chỉ số đánh giá</p>
  return (
    <dl className="num grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
      {defs.filter((d) => metric(metrics, d.path) !== null).map((d) => {
        const v = metric(metrics, d.path)
        return (
          <div key={d.path}>
            <dt className="muted text-xs">{d.label}</dt>
            <dd className="font-semibold">{d.pct ? fmtPct(v) : fmtDec(v)}</dd>
          </div>
        )
      })}
    </dl>
  )
}
