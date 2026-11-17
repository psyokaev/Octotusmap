import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api, type Page } from '../lib/api'
import { fmtDateTime, fmtNum, vnLocalToIso } from '../lib/format'
import { useAuth } from '../auth/AuthContext'
import { Chart, Confirm, DemoBadge, Empty, ErrorState, Loading, Modal, PageHeader, Pager, SortTh } from '../components/ui'
import { AreaSelect, Field, FormActions } from '../features/ops/Field'
import { num, optNum, reqNum, useAction, vnDateToIso, type Area } from '../features/ops/lib'
import { CAUSE_VI } from '../lib/risk'

interface FloodEvent {
  id: number; location_name: string; latitude: number; longitude: number; started_at: string; ended_at: string | null
  max_depth_cm: number | null; cause: string; description: string; is_simulated: boolean; area: Area | null
}
interface FloodStats { by_time: { bucket: string; count: number; max_depth_cm: number | null }[]; total: number }

// shortcut: thống kê mặc định 10 năm gần nhất khi không chọn "Từ ngày" (backend giới hạn 3700 ngày)
const TEN_YEARS_AGO = new Date(Date.now() - 3650 * 86_400_000).toISOString() // cố định để queryKey ổn định

export default function HistoryPage() {
  const { isStaff } = useAuth()
  const act = useAction()
  const [f, setF] = useState({ q: '', area_id: '', from: '', to: '', min_depth: '' })
  const [sort, setSort] = useState('started_at')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<FloodEvent | null>(null)
  const closeCreate = useCallback(() => setCreating(false), [])
  const closeDelete = useCallback(() => setDeleting(null), [])
  const update = (p: Partial<typeof f>) => { setF((x) => ({ ...x, ...p })); setPage(1) }
  const onSort = (c: string) => { if (c === sort) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(c); setDir('desc') } }

  const dates = { date_from: vnDateToIso(f.from), date_to: vnDateToIso(f.to, true) }
  const minDepth = f.min_depth === '' || Number.isNaN(Number(f.min_depth)) ? undefined : Number(f.min_depth)
  const params = { q: f.q, area_id: f.area_id, ...dates, min_depth: minDepth, sort, direction: dir, page, size: 20 }
  const list = useQuery({ queryKey: ['flood-events', params], queryFn: () => api.get<Page<FloodEvent>>('/history/events', params) })

  const statParams = { group: 'month', area_id: f.area_id, date_from: dates.date_from ?? TEN_YEARS_AGO, date_to: dates.date_to }
  const stats = useQuery({
    queryKey: ['flood-events', 'stats', statParams], enabled: isStaff,
    queryFn: () => api.get<FloodStats>('/statistics/flood-events', statParams),
  })
  const option = useMemo(() => ({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 40, top: 30, bottom: 30 },
    legend: { data: ['Số trận ngập', 'Độ sâu lớn nhất (cm)'] },
    xAxis: { type: 'category', data: stats.data?.by_time.map((b) => b.bucket) ?? [] },
    yAxis: [{ type: 'value', name: 'trận', minInterval: 1 }, { type: 'value', name: 'cm' }],
    series: [
      { name: 'Số trận ngập', type: 'bar', itemStyle: { color: '#1C7CB5' }, data: stats.data?.by_time.map((b) => b.count) ?? [] },
      { name: 'Độ sâu lớn nhất (cm)', type: 'line', yAxisIndex: 1, itemStyle: { color: '#C62828' }, data: stats.data?.by_time.map((b) => b.max_depth_cm) ?? [] },
    ],
  }), [stats.data])

  return (
    <div>
      <PageHeader title="Lịch sử ngập">
        {isStaff && <button className="btn-primary" onClick={() => setCreating(true)}>Thêm sự kiện ngập</button>}
      </PageHeader>

      <div className="panel mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
        <Field id="h-q" label="Tìm kiếm"><input id="h-q" className="input" placeholder="Địa điểm, mô tả" value={f.q} onChange={(e) => update({ q: e.target.value })} /></Field>
        <Field id="h-area" label="Khu vực"><AreaSelect id="h-area" value={f.area_id} onChange={(v) => update({ area_id: v })} /></Field>
        <Field id="h-from" label="Từ ngày"><input id="h-from" type="date" className="input" value={f.from} onChange={(e) => update({ from: e.target.value })} /></Field>
        <Field id="h-to" label="Đến ngày"><input id="h-to" type="date" className="input" value={f.to} onChange={(e) => update({ to: e.target.value })} /></Field>
        <Field id="h-depth" label="Độ sâu tối thiểu (cm)"><input id="h-depth" type="number" min={0} className="input" value={f.min_depth} onChange={(e) => update({ min_depth: e.target.value })} /></Field>
      </div>

      {isStaff && (
        <section className="panel mb-4 p-4" aria-label="Thống kê theo tháng">
          <h2 className="mb-2 font-semibold">Số trận ngập theo tháng{stats.data ? ` · tổng ${stats.data.total}` : ''}</h2>
          {stats.isLoading ? <Loading rows={3} /> : stats.isError ? <ErrorState error={stats.error} retry={() => stats.refetch()} />
            : !stats.data?.by_time.length ? <Empty text="Không có sự kiện trong khoảng thời gian này." />
            : <Chart option={option} height={260} ariaLabel="Biểu đồ số trận ngập và độ sâu lớn nhất theo tháng" />}
        </section>
      )}

      <div className="panel overflow-x-auto">
        {list.isLoading ? <Loading rows={6} /> : list.isError ? <ErrorState error={list.error} retry={() => list.refetch()} />
          : !list.data?.items.length ? <Empty text="Không có sự kiện ngập phù hợp bộ lọc." />
          : (
            <table className="table min-w-[860px]">
              <thead>
                <tr>
                  <SortTh label="Địa điểm" col="location_name" sort={sort} dir={dir} onSort={onSort} />
                  <th>Khu vực</th>
                  <SortTh label="Bắt đầu" col="started_at" sort={sort} dir={dir} onSort={onSort} />
                  <th>Kết thúc</th>
                  <SortTh label="Độ sâu lớn nhất" col="max_depth_cm" sort={sort} dir={dir} onSort={onSort} />
                  <th>Nguyên nhân</th><th>Mô tả</th>{isStaff && <th><span className="sr-only">Thao tác</span></th>}
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="font-medium">{e.location_name} {e.is_simulated && <DemoBadge />}</td>
                    <td>{e.area?.name ?? '—'}</td>
                    <td className="num">{fmtDateTime(e.started_at)}</td>
                    <td className="num">{fmtDateTime(e.ended_at)}</td>
                    <td className="num">{fmtNum(e.max_depth_cm, ' cm')}</td>
                    <td>{CAUSE_VI[e.cause] ?? e.cause}</td>
                    <td className="max-w-xs">{e.description || '—'}</td>
                    {isStaff && <td><button className="btn-ghost text-risk-high" onClick={() => setDeleting(e)}>Xoá</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
      </div>

      {creating && <EventForm onClose={closeCreate} />}
      {deleting && (
        <Confirm title="Xoá sự kiện ngập" danger confirmLabel="Xoá vĩnh viễn" onClose={closeDelete}
          text={`Xoá sự kiện "${deleting.location_name}" (${fmtDateTime(deleting.started_at)})? Thao tác không thể hoàn tác.`}
          onConfirm={async () => { await act(() => api.del(`/history/events/${deleting.id}`), 'Đã xoá sự kiện', ['flood-events']) }} />
      )}
    </div>
  )
}

const eventSchema = z.object({
  location_name: z.string().trim().min(2, 'Tối thiểu 2 ký tự').max(200),
  latitude: reqNum(num().min(-90, 'Vĩ độ từ -90 đến 90').max(90, 'Vĩ độ từ -90 đến 90')),
  longitude: reqNum(num().min(-180, 'Kinh độ từ -180 đến 180').max(180, 'Kinh độ từ -180 đến 180')),
  started_at: z.string().min(1, 'Chọn thời điểm bắt đầu'),
  ended_at: z.string(),
  max_depth_cm: optNum(num().min(0, 'Từ 0 đến 500 cm').max(500, 'Từ 0 đến 500 cm')),
  cause: z.enum(['RAIN', 'TIDE', 'RAIN_TIDE', 'OTHER']),
  description: z.string().max(2000, 'Tối đa 2000 ký tự'),
}).refine((v) => !v.ended_at || v.ended_at > v.started_at, { message: 'Kết thúc phải sau thời điểm bắt đầu', path: ['ended_at'] })

function EventForm({ onClose }: { onClose: () => void }) {
  const act = useAction()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof eventSchema>>({
    resolver: zodResolver(eventSchema), defaultValues: { location_name: '', started_at: '', ended_at: '', cause: 'RAIN', description: '' },
  })
  const submit = handleSubmit(async (v) => {
    const body = { ...v, started_at: vnLocalToIso(v.started_at), ended_at: v.ended_at ? vnLocalToIso(v.ended_at) : null }
    if (await act(() => api.post('/history/events', body), 'Đã thêm sự kiện ngập', ['flood-events'])) onClose()
  })
  const input = (k: 'location_name' | 'latitude' | 'longitude' | 'started_at' | 'ended_at' | 'max_depth_cm', label: string, type = 'text') => (
    <Field id={`ev-${k}`} label={label} error={errors[k]?.message}>
      <input id={`ev-${k}`} className="input" type={type} step="any" {...register(k)} />
    </Field>
  )
  return (
    <Modal title="Thêm sự kiện ngập" onClose={onClose} wide>
      <form noValidate onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">{input('location_name', 'Địa điểm')}</div>
        {input('latitude', 'Vĩ độ (trong TP.HCM)', 'number')}
        {input('longitude', 'Kinh độ (trong TP.HCM)', 'number')}
        {input('started_at', 'Bắt đầu (giờ Việt Nam)', 'datetime-local')}
        {input('ended_at', 'Kết thúc (tuỳ chọn)', 'datetime-local')}
        {input('max_depth_cm', 'Độ sâu lớn nhất (cm, 0–500)', 'number')}
        <Field id="ev-cause" label="Nguyên nhân" error={errors.cause?.message}>
          <select id="ev-cause" className="input" {...register('cause')}>
            {Object.entries(CAUSE_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field id="ev-desc" label="Mô tả" error={errors.description?.message} className="sm:col-span-2">
          <textarea id="ev-desc" rows={3} className="input" {...register('description')} />
        </Field>
        <div className="sm:col-span-2"><FormActions busy={isSubmitting} onCancel={onClose} /></div>
      </form>
    </Modal>
  )
}
