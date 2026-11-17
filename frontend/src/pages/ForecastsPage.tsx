import { useId, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { api } from '../lib/api'
import { useCameraEnabled } from '../lib/health'
import { fmtDateTime, fmtNum, fmtPct, fmtTime } from '../lib/format'
import { RISK, floodCause } from '../lib/risk'
import { Chart, DemoBadge, PageHeader, RiskBadge } from '../components/ui'
import { C, MODEL_STATUS_VI, axisOption, fmtDec, fmtUtc, type AreaRisk, type ModelStatus, type StationFc } from '../features/analytics/analytics'
import { DataTable, ModelMetrics, QueryState, Section, type Col } from '../features/analytics/components'

const HOURS = [1, 2, 3, 4, 5, 6]
const HORIZONS = [0, ...HOURS]

export default function ForecastsPage() {
  const cameraEnabled = useCameraEnabled()
  const id = useId()
  const status = useQuery({ queryKey: ['forecast-model-status'], queryFn: () => api.get<ModelStatus>('/forecasts/model-status') })
  const latest = useQuery({ queryKey: ['forecasts-latest', ''], queryFn: () => api.get<StationFc[]>('/forecasts/latest', { area_id: '' }) })
  const [horizon, setHorizon] = useState(0)
  const risk = useQuery({ queryKey: ['forecast-risk', horizon], queryFn: () => api.get<AreaRisk[]>('/forecasts/risk', { horizon }), placeholderData: (p) => p })
  const [picked, setPicked] = useState('')
  const station = latest.data?.find((s) => String(s.station_id) === picked) ?? latest.data?.[0]

  const opt = useMemo(() => {
    const pts = station?.points ?? []
    return axisOption(pts.map((p) => `+${p.horizon_h}h (${fmtTime(p.target_time)})`), [
      { name: 'Mưa dự báo (mm)', type: 'bar', data: pts.map((p) => p.rainfall_mm), itemStyle: { color: C.water } },
      { name: 'Xác suất ngập (%)', type: 'line', yAxisIndex: 1, data: pts.map((p) => Math.round(p.flood_probability * 100)), itemStyle: { color: RISK.HIGH.color } },
      ...(pts.some((p) => p.water_level_cm !== null)
        ? [{ name: 'Mực nước (cm)', type: 'line', yAxisIndex: 2, data: pts.map((p) => p.water_level_cm), itemStyle: { color: C.ink }, lineStyle: { type: 'dashed' } }] : []),
    ], [{ type: 'value', name: 'mm' }, { type: 'value', name: '%', min: 0, max: 100 }, { type: 'value', name: 'cm', show: false, scale: true }])
  }, [station])

  const riskCols: Col<AreaRisk & { rank: number }>[] = [
    { key: 'rank', label: '#', value: (r) => r.rank, num: true },
    { key: 'area', label: 'Khu vực', value: (r) => r.area_name, render: (r) => <>{r.area_name} {r.is_simulated && <DemoBadge />}</> },
    { key: 'level', label: 'Mức nguy cơ', value: (r) => ['LOW', 'MEDIUM', 'HIGH'].indexOf(r.risk_level), render: (r) => <RiskBadge level={r.risk_level} /> },
    { key: 'cause', label: 'Lý do', value: (r) => floodCause(r.explanation?.cause, r.explanation?.depth_cm) ?? '', render: (r) => floodCause(r.explanation?.cause, r.explanation?.depth_cm) ?? '—' },
    { key: 'score', label: 'Điểm', value: (r) => r.score, render: (r) => fmtDec(r.score), num: true },
    { key: 'prob', label: 'Xác suất ngập', value: (r) => r.flood_probability, render: (r) => fmtPct(r.flood_probability), num: true },
    { key: 'rain', label: 'Mưa (mm/h)', value: (r) => r.rainfall_mm, render: (r) => fmtNum(r.rainfall_mm), num: true },
  ]

  return (
    <div className="space-y-4">
      <PageHeader title="Dự báo ngập 1–6 giờ" />

      <Section title="Mô hình dự báo đang dùng">
        <QueryState q={status}>{(d) => (
          <div className="space-y-3">
            {d.warning && <p role="alert" className="rounded-lg border border-dashed border-current p-2 text-sm text-[#8a5a00] dark:text-amber-300">{d.warning}</p>}
            {d.forecast_model ? (
              <>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <b>{d.forecast_model.name}</b>
                  <span className="chip bg-black/5 dark:bg-white/10">{d.forecast_model.model_type}</span>
                  <span className="chip bg-black/5 dark:bg-white/10">{MODEL_STATUS_VI[d.forecast_model.status] ?? d.forecast_model.status}</span>
                  {d.forecast_model.trained_on_simulated && <DemoBadge />}
                </div>
                <ModelMetrics type={d.forecast_model.model_type} metrics={d.forecast_model.metrics} />
              </>
            ) : <p className="muted text-sm">Chưa có mô hình dự báo hoạt động.</p>}
            <p className="muted text-xs">Lần phát hành gần nhất: {fmtDateTime(d.latest_issued_at)}{cameraEnabled && d.vision_model && ` · mô hình camera: ${d.vision_model.name}`}</p>
          </div>
        )}</QueryState>
      </Section>

      <Section title="Dự báo theo trạm">
        <QueryState q={latest} isEmpty={(d) => !d.length} emptyText="Chưa có bản dự báo nào">{(d) => (
          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[220px]">
                <label className="label" htmlFor={`${id}-st`}>Trạm hiển thị biểu đồ</label>
                <select id={`${id}-st`} className="input" value={station ? String(station.station_id) : ''} onChange={(e) => setPicked(e.target.value)}>
                  {d.map((s) => <option key={s.station_id} value={s.station_id}>{s.station_code} · {s.station_name}</option>)}
                </select>
              </div>
              <span className="muted text-xs">Phát hành {fmtDateTime(d[0].issued_at)}</span>
            </div>
            {station && <Chart option={opt} ariaLabel={`Biểu đồ dự báo mưa và xác suất ngập 6 giờ tới tại ${station.station_name}`} />}
            <div className="overflow-x-auto">
              <table className="table">
                <caption className="sr-only">Dự báo mưa (mm) và xác suất ngập theo trạm cho 1 đến 6 giờ tới</caption>
                <thead><tr>
                  <th>Trạm</th>
                  {HOURS.map((h) => <th key={h} className="num whitespace-nowrap">+{h}h</th>)}
                  <th>Chất lượng dữ liệu</th><th>Ghi chú</th>
                </tr></thead>
                <tbody>{d.map((s) => (
                  <tr key={s.station_id} className={clsx(s.station_id === station?.station_id && 'bg-water/5')}>
                    <td>
                      <button className="text-left font-medium text-water hover:underline" onClick={() => setPicked(String(s.station_id))}
                        aria-label={`Xem biểu đồ dự báo trạm ${s.station_name}`}>{s.station_code}</button>
                      <div className="muted text-xs">{s.station_name}</div>
                    </td>
                    {HOURS.map((h) => {
                      const p = s.points.find((x) => x.horizon_h === h)
                      return (
                        <td key={h} className="num whitespace-nowrap">
                          {p ? <>{fmtNum(p.rainfall_mm)} mm<div className="text-xs" style={{ color: p.flood_probability >= 0.8 ? RISK.HIGH.color : p.flood_probability >= 0.5 ? RISK.MEDIUM.color : undefined }}>{fmtPct(p.flood_probability)}</div></> : '—'}
                        </td>
                      )
                    })}
                    <td>{s.data_quality}</td>
                    <td className="space-x-1">
                      {s.is_cold_start && <span className="chip bg-black/5 dark:bg-white/10" title="Trạm thiếu lịch sử, mượn dữ liệu trạm lân cận">Cold-start</span>}
                      {s.is_simulated && <DemoBadge />}
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <p className="muted text-xs">Mỗi ô: lượng mưa dự báo và xác suất ngập. Thời gian theo giờ Việt Nam.</p>
          </div>
        )}</QueryState>
      </Section>

      <Section title="Xếp hạng nguy cơ theo khu vực">
        <div role="radiogroup" aria-label="Chọn mốc dự báo" className="mb-3 flex flex-wrap gap-1.5">
          {HORIZONS.map((h) => (
            <button key={h} role="radio" aria-checked={horizon === h} onClick={() => setHorizon(h)}
              className={horizon === h ? 'btn-primary' : 'btn-ghost'}>{h === 0 ? 'Hiện tại' : `+${h} giờ`}</button>
          ))}
        </div>
        <QueryState q={risk} isEmpty={(d) => !d.length} emptyText="Chưa có đánh giá nguy cơ">{(d) => (
          <>
            <p className="muted mb-2 text-xs">Đánh giá phát hành {fmtUtc(d[0].issued_at)}{risk.isFetching && ' · đang cập nhật…'}</p>
            <DataTable rows={d.map((r, i) => ({ ...r, rank: i + 1 }))} cols={riskCols} rowKey={(r) => r.area_id} label="Xếp hạng nguy cơ ngập theo khu vực" />
          </>
        )}</QueryState>
      </Section>
    </div>
  )
}
