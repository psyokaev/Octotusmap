import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useCameraEnabled } from '../lib/health'
import { fmtNum, fmtPct } from '../lib/format'
import { RISK } from '../lib/risk'
import { Chart, DemoBadge, ErrorState, Kpi, Loading, PageHeader } from '../components/ui'
import {
  C, axisOption, fmtDec, fmtUtc, isVision, useFilters,
  type AlertStats, type ModelPerf, type ObsStats, type Overview, type RiskStats, type StationFc,
} from '../features/analytics/analytics'
import { FilterBar, ModelMetrics, QueryState, Section } from '../features/analytics/components'

const LEVELS = ['LOW', 'MEDIUM', 'HIGH'] as const

export default function DashboardPage() {
  const cameraEnabled = useCameraEnabled()
  const { state, setState, params, group } = useFilters()
  const p = { ...params, risk_level: '', data_type: '' }
  const overview = useQuery({ queryKey: ['stats', 'overview', p], queryFn: () => api.get<Overview>('/statistics/overview', p) })
  const rain = useQuery({ queryKey: ['stats', 'rainfall', p, group], queryFn: () => api.get<ObsStats>('/statistics/rainfall', { ...p, group }) })
  const water = useQuery({ queryKey: ['stats', 'water', p, group], queryFn: () => api.get<ObsStats>('/statistics/water-level', { ...p, group }) })
  const alerts = useQuery({ queryKey: ['stats', 'alerts', p, group], queryFn: () => api.get<AlertStats>('/statistics/alerts', { ...p, group }) })
  const risk = useQuery({ queryKey: ['stats', 'risk', p, group], queryFn: () => api.get<RiskStats>('/statistics/risk', { ...p, group }) })
  const perf = useQuery({ queryKey: ['stats', 'perf', p], queryFn: () => api.get<ModelPerf>('/statistics/model-performance', p) })
  const fc = useQuery({ queryKey: ['forecasts-latest', state.area_id], queryFn: () => api.get<StationFc[]>('/forecasts/latest', { area_id: state.area_id }) })

  const demo = !!fc.data?.some((s) => s.is_simulated)
  const groupLabel = { hour: 'giờ', day: 'ngày', month: 'tháng', year: 'năm' }[group]

  const rainOpt = useMemo(() => {
    const s = rain.data?.series ?? []
    return axisOption(s.map((x) => x.bucket), [
      { name: 'Tổng lượng mưa (mm)', type: 'bar', data: s.map((x) => x.sum), itemStyle: { color: C.water } },
    ], { type: 'value', name: 'mm' })
  }, [rain.data])

  const waterOpt = useMemo(() => {
    const s = water.data?.series ?? []
    return axisOption(s.map((x) => x.bucket), [
      { name: 'Cao nhất (cm)', type: 'line', data: s.map((x) => x.max), itemStyle: { color: RISK.HIGH.color }, showSymbol: false },
      { name: 'Trung bình (cm)', type: 'line', data: s.map((x) => x.avg), itemStyle: { color: C.water }, showSymbol: false },
    ], { type: 'value', name: 'cm', scale: true })
  }, [water.data])

  const fcOpt = useMemo(() => {
    const hs = [1, 2, 3, 4, 5, 6]
    const pts = (h: number) => (fc.data ?? []).flatMap((s) => s.points.filter((x) => x.horizon_h === h))
    const maxOf = (xs: number[]) => (xs.length ? Math.max(...xs) : null)
    return axisOption(hs.map((h) => `+${h}h`), [
      { name: 'Mưa lớn nhất (mm)', type: 'bar', data: hs.map((h) => maxOf(pts(h).map((x) => x.rainfall_mm))), itemStyle: { color: C.water } },
      { name: 'Xác suất ngập lớn nhất (%)', type: 'line', yAxisIndex: 1, itemStyle: { color: RISK.HIGH.color },
        data: hs.map((h) => { const v = maxOf(pts(h).map((x) => x.flood_probability)); return v === null ? null : Math.round(v * 100) }) },
    ], [{ type: 'value', name: 'mm' }, { type: 'value', name: '%', min: 0, max: 100 }])
  }, [fc.data])

  const alertTimeOpt = useMemo(() => {
    const s = alerts.data?.by_time ?? []
    return axisOption(s.map((x) => x.bucket), LEVELS.map((k) => ({
      name: RISK[k].label, type: 'bar', stack: 'lv', data: s.map((x) => x[k]), itemStyle: { color: RISK[k].color },
    })))
  }, [alerts.data])

  const alertAreaOpt = useMemo(() => {
    const s = (alerts.data?.by_area ?? []).slice(0, 15)
    return axisOption(s.map((x) => x.area), [{ name: 'Số cảnh báo', type: 'bar', data: s.map((x) => x.count), itemStyle: { color: C.amber } }],
      { type: 'value', minInterval: 1 }, true)
  }, [alerts.data])

  const pieOpt = useMemo(() => {
    const o = overview.data
    const v: Record<string, number> = o
      ? { LOW: o.areas_low, MEDIUM: o.areas_medium, HIGH: o.areas_high, INSUFFICIENT_DATA: o.areas_insufficient }
      : risk.data?.current ?? {}
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} khu vực ({d}%)' }, legend: { bottom: 0 },
      series: [{ type: 'pie', radius: ['45%', '70%'], label: { formatter: '{b}\n{d}%' },
        data: ([...LEVELS, 'INSUFFICIENT_DATA'] as const).filter((k) => v[k]).map((k) => ({ name: RISK[k].label, value: v[k], itemStyle: { color: RISK[k].color } })) }],
    }
  }, [overview.data, risk.data])

  const trendOpt = useMemo(() => {
    const s = risk.data?.trend ?? []
    return axisOption(s.map((x) => x.bucket), [
      ...LEVELS.map((k) => ({ name: RISK[k].label, type: 'bar', stack: 'r', data: s.map((x) => x[k]), itemStyle: { color: RISK[k].color } })),
      { name: 'Điểm nguy cơ TB', type: 'line', yAxisIndex: 1, data: s.map((x) => x.avg_score), itemStyle: { color: C.ink }, showSymbol: false },
    ], [{ type: 'value', name: 'lượt' }, { type: 'value', name: 'điểm', min: 0 }])
  }, [risk.data])

  const skillOpt = useMemo(() => {
    const s = perf.data?.online_rainfall_skill ?? []
    return axisOption(s.map((x) => `+${x.horizon_h}h`), [
      { name: 'MAE (mm)', type: 'bar', data: s.map((x) => x.mae), itemStyle: { color: C.water } },
      { name: 'RMSE (mm)', type: 'bar', data: s.map((x) => x.rmse), itemStyle: { color: C.ink } },
    ], { type: 'value', name: 'mm' })
  }, [perf.data])

  const o = overview.data
  const activeForecast = perf.data?.models.find((m) => m.active && !isVision(m.type) && m.type !== 'BASELINE')
  const activeVision = perf.data?.models.find((m) => m.active && isVision(m.type))

  return (
    <div>
      <PageHeader title="Tổng quan" />
      <FilterBar value={state} onChange={setState} />

      {demo && (
        <p role="note" className="panel mb-4 border-dashed p-3 text-sm">
          <DemoBadge /> Có dữ liệu mô phỏng trong kỳ này.
        </p>
      )}

      {overview.isLoading ? <Loading rows={3} /> : overview.error ? <ErrorState error={overview.error} retry={overview.refetch} /> : o && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-7">
          <Kpi label="Tổng số trạm" value={fmtNum(o.stations_total)} />
          <Kpi label="Trạm đang kết nối" value={fmtNum(o.stations_online)} tone={RISK.LOW.color} />
          <Kpi label="Trạm mất kết nối" value={fmtNum(o.stations_offline)} tone={o.stations_offline ? RISK.HIGH.color : undefined} />
          {cameraEnabled && <Kpi label="Camera" value={fmtNum(o.cameras_total)} />}
          <Kpi label="Khu vực" value={fmtNum(o.areas_total)} hint={o.areas_insufficient ? `${o.areas_insufficient} khu vực thiếu dữ liệu` : undefined} />
          <Kpi label={`${RISK.LOW.symbol} Khu vực nguy cơ thấp hiện tại`} value={fmtNum(o.areas_low)} tone={RISK.LOW.color} />
          <Kpi label={`${RISK.MEDIUM.symbol} Khu vực nguy cơ trung bình hiện tại`} value={fmtNum(o.areas_medium)} tone={RISK.MEDIUM.color} />
          <Kpi label={`${RISK.HIGH.symbol} Khu vực nguy cơ cao hiện tại`} value={fmtNum(o.areas_high)} tone={RISK.HIGH.color} />
          <Kpi label="Cảnh báo đang mở" value={fmtNum(o.alerts_active)} hint="gồm dự báo tới 6 giờ" tone={o.alerts_active ? RISK.HIGH.color : undefined} />
          <Kpi label="Cảnh báo đã xử lý" value={fmtNum(o.alerts_handled)} hint={`trên ${fmtNum(o.alerts_in_range)} cảnh báo trong kỳ`} />
          <Kpi label="Mưa trung bình" value={fmtNum(o.rainfall_avg_mm, ' mm/h')} />
          <Kpi label="Mực nước cao nhất" value={fmtNum(o.water_level_max_cm, ' cm')} />
          <Kpi label="Dữ liệu hợp lệ" value={fmtPct(o.valid_data_ratio)} />
          <Kpi label="Dự báo mới nhất" value={<span className="text-base">{fmtUtc(o.latest_forecast_at)}</span>} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title={`Lượng mưa theo ${groupLabel}`}>
          <QueryState q={rain} isEmpty={(d) => !d.series.length}>{() => <Chart option={rainOpt} ariaLabel={`Biểu đồ tổng lượng mưa theo ${groupLabel}`} />}</QueryState>
        </Section>
        <Section title={`Mực nước theo ${groupLabel}`}>
          <QueryState q={water} isEmpty={(d) => !d.series.length}>{() => <Chart option={waterOpt} ariaLabel={`Biểu đồ mực nước cao nhất và trung bình theo ${groupLabel}`} />}</QueryState>
        </Section>
        <Section title="Dự báo 1–6 giờ tới (toàn bộ trạm)">
          <QueryState q={fc} isEmpty={(d) => !d.length} emptyText="Chưa có bản dự báo">{(d) => (
            <>
              <Chart option={fcOpt} ariaLabel="Biểu đồ mưa và xác suất ngập lớn nhất theo mốc dự báo 1 đến 6 giờ" />
              <p className="muted mt-1 text-xs">Phát hành {fmtUtc(d[0]?.issued_at)}</p>
            </>
          )}</QueryState>
        </Section>
        <Section title="Tỉ lệ khu vực theo mức nguy cơ hiện tại">
          {overview.isLoading || risk.isLoading ? <Loading /> : <Chart option={pieOpt} ariaLabel="Biểu đồ tròn tỉ lệ khu vực nguy cơ thấp, trung bình, cao" />}
        </Section>
        <Section title={`Cảnh báo theo ${groupLabel}`}>
          <QueryState q={alerts} isEmpty={(d) => !d.by_time.length} emptyText="Không có cảnh báo trong khoảng thời gian đã chọn">
            {() => <Chart option={alertTimeOpt} ariaLabel={`Biểu đồ cột chồng số cảnh báo theo mức, theo ${groupLabel}`} />}
          </QueryState>
        </Section>
        <Section title="Cảnh báo theo khu vực">
          <QueryState q={alerts} isEmpty={(d) => !d.by_area.length} emptyText="Không có cảnh báo trong khoảng thời gian đã chọn">
            {() => <Chart option={alertAreaOpt} height={Math.max(220, (alerts.data?.by_area.slice(0, 15).length ?? 0) * 26 + 60)} ariaLabel="Biểu đồ số cảnh báo theo khu vực" />}
          </QueryState>
        </Section>
        <Section title="Xu hướng nguy cơ ngập" className="lg:col-span-2">
          <QueryState q={risk} isEmpty={(d) => !d.trend.length}>{() => <Chart option={trendOpt} ariaLabel={`Biểu đồ số lượt đánh giá nguy cơ theo mức và điểm trung bình theo ${groupLabel}`} />}</QueryState>
        </Section>
        <Section title="Hiệu quả mô hình" className="lg:col-span-2">
          <QueryState q={perf}>{(d) => (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-4">
                <div>
                  <h3 className="mb-2 text-sm font-medium">Dự báo: {activeForecast ? activeForecast.name : 'chưa có mô hình hoạt động'} {activeForecast?.trained_on_simulated && <DemoBadge />}</h3>
                  {activeForecast && <ModelMetrics type={activeForecast.type} metrics={activeForecast.metrics} />}
                </div>
                {cameraEnabled && (
                  <div>
                    <h3 className="mb-2 text-sm font-medium">Nhận diện ngập qua camera: {activeVision ? activeVision.name : 'chưa có mô hình hoạt động'} {activeVision?.trained_on_simulated && <DemoBadge />}</h3>
                    {activeVision && <ModelMetrics type={activeVision.type} metrics={activeVision.metrics} />}
                  </div>
                )}
              </div>
              <div>
                <h3 className="mb-2 text-sm font-medium">Sai số dự báo mưa thực tế theo mốc</h3>
                {d.online_rainfall_skill.length
                  ? <Chart option={skillOpt} height={220} ariaLabel="Biểu đồ MAE và RMSE dự báo mưa đối chiếu quan trắc theo mốc giờ" />
                  : <p className="muted text-sm">Chưa đủ cặp dự báo – quan trắc để đánh giá.</p>}
                {d.online_rainfall_skill.length > 0 && (
                  <p className="muted num text-xs">Số cặp so sánh: {d.online_rainfall_skill.map((x) => `+${x.horizon_h}h: ${fmtDec(x.n, 0)}`).join(' · ')}</p>
                )}
              </div>
            </div>
          )}</QueryState>
        </Section>
      </div>
    </div>
  )
}
