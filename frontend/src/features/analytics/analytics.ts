// Kiểu dữ liệu, hook bộ lọc và tiện ích dùng chung cho Dashboard / Thống kê / Dự báo / Mô hình
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '../../lib/api'
import { fmtDateTime, presetRange } from '../../lib/format'

/* ------------------------------------------------------------------ bộ lọc */
export type Preset = 'today' | '7d' | '30d' | 'month' | 'year' | 'custom'
export type Group = 'hour' | 'day' | 'month' | 'year'

export const PRESETS: { id: Preset; label: string }[] = [
  { id: 'today', label: 'Hôm nay' }, { id: '7d', label: '7 ngày' }, { id: '30d', label: '30 ngày' },
  { id: 'month', label: 'Tháng này' }, { id: 'year', label: 'Năm nay' }, { id: 'custom', label: 'Tuỳ chọn' },
]

export interface FilterState {
  preset: Preset; from: string; to: string // from/to: yyyy-mm-dd (giờ VN) khi preset = custom
  area_id: string; station_id: string; risk_level: string; data_type: string
}
export const INITIAL_FILTERS: FilterState = { preset: '7d', from: '', to: '', area_id: '', station_id: '', risk_level: '', data_type: '' }

// type (không phải interface) để gán được vào Params có index signature của api.ts
export type StatParams = {
  date_from: string; date_to: string; area_id: string; station_id: string; risk_level: string; data_type: string
}

const DAY = 86_400_000
/** Nhóm thời gian hợp lý theo độ dài khoảng: hôm nay -> giờ, 7/30 ngày -> ngày, năm -> tháng. */
export function groupFor(preset: Preset, r: { from: string; to: string }): Group {
  if (preset === 'today') return 'hour'
  if (preset === 'year') return 'month'
  const days = (Date.parse(r.to) - Date.parse(r.from)) / DAY
  return days <= 2 ? 'hour' : days <= 92 ? 'day' : 'month'
}

export function useFilters(initial: FilterState = INITIAL_FILTERS) {
  const [state, setState] = useState(initial)
  // presetRange dùng "now": chỉ tính lại khi bộ lọc đổi để query key ổn định
  const derived = useMemo(() => {
    const r = presetRange(state.preset, { from: state.from, to: state.to })
    const params: StatParams = { date_from: r.from, date_to: r.to, area_id: state.area_id, station_id: state.station_id,
      risk_level: state.risk_level, data_type: state.data_type }
    return { params, group: groupFor(state.preset, r) }
  }, [state])
  return { state, setState, ...derived }
}

export interface AreaOpt { id: number; code: string; name: string }
export interface StationOpt { id: number; code: string; name: string; area: { id: number } | null }

export const useAreas = () =>
  useQuery({ queryKey: ['gis-areas'], queryFn: () => api.get<AreaOpt[]>('/gis/areas'), staleTime: 10 * 60_000 })
export const useStationOptions = (areaId: string) =>
  useQuery({ queryKey: ['station-options', areaId], staleTime: 5 * 60_000,
    queryFn: () => api.get<Page<StationOpt>>('/stations', { size: 200, area_id: areaId }) })

/* ------------------------------------------------------------------ định dạng */
/** Một số endpoint thống kê trả datetime UTC không kèm 'Z' -> bổ sung trước khi định dạng. */
export const asUtc = (s?: string | null) => (s && !/(Z|[+-]\d\d:?\d\d)$/i.test(s) ? `${s}Z` : s)
export const fmtUtc = (s?: string | null) => fmtDateTime(asUtc(s))
export const fmtDec = (v?: number | null, digits = 3) =>
  v === null || v === undefined ? '—' : v.toLocaleString('vi-VN', { maximumFractionDigits: digits })
export const errMsg = (e: unknown) => (e instanceof Error ? e.message : 'Đã xảy ra lỗi')

/* ------------------------------------------------------------------ API shapes */
export interface Overview {
  stations_total: number; stations_online: number; stations_offline: number; cameras_total: number; areas_total: number
  areas_low: number; areas_medium: number; areas_high: number; areas_insufficient: number
  alerts_active: number; alerts_in_range: number; alerts_handled: number
  rainfall_avg_mm: number | null; water_level_max_cm: number | null; latest_forecast_at: string | null
  valid_data_ratio: number | null; generated_at: string
}
export interface SeriesRow { bucket: string; sum: number | null; avg: number | null; max: number | null; count: number }
export interface ByStationRow { station_id: number; code: string; name: string; sum: number | null; avg: number | null; max: number | null; count: number }
export interface ObsStats { series: SeriesRow[]; by_station: ByStationRow[]; unit: string }
export interface ObsRow { observed_at: string; station_code: string; station_name: string; area: string | null; value: number | null; quality: string; is_simulated: boolean }
export interface AlertStats {
  total: number; by_time: { bucket: string; LOW: number; MEDIUM: number; HIGH: number; total: number }[]
  by_area: { area: string; count: number }[]; by_level: Record<string, number>; by_status: Record<string, number>
  verification: Record<string, number>; precision_verified: number | null
  avg_minutes_to_ack: number | null; avg_minutes_to_resolve: number | null
}
export interface RiskTrendRow { bucket: string; LOW: number; MEDIUM: number; HIGH: number; INSUFFICIENT_DATA: number; avg_score: number | null }
export interface RiskStats { trend: RiskTrendRow[]; current: Record<string, number> }
export interface FloodEventStats { by_time: { bucket: string; count: number; max_depth_cm: number | null }[]; by_area: { area: string; count: number }[]; total: number }
export interface SkillRow { horizon_h: number; mae: number | null; rmse: number | null; n: number }
export interface PerfModel { id: number; name: string; type: string; version: string; active: boolean; trained_on_simulated: boolean; metrics: Metrics | null }
export interface ModelPerf { models: PerfModel[]; online_rainfall_skill: SkillRow[]; alert_verification: Record<string, number> }
export interface StationStat {
  id: number; code: string; name: string; type: string; status: string; connection: string; area: string | null; area_id: number | null
  last_observation_at: string | null; source: string; is_simulated: boolean; managing_unit: string; interval_minutes: number; flood_threshold_cm: number
}
export interface CameraStat {
  id: number; code: string; name: string; status: string; area: string | null; is_public: boolean; is_simulated: boolean
  detections: number; max_flood_ratio: number | null; avg_flood_ratio: number | null; last_detection_at: string | null
}
export type QualityRow = { kind: string; code: string; name: string; total: number; valid_ratio: number | null } & Record<string, unknown>
export interface HandlingRow { action: string; to_status: string | null; count: number }

export interface FcPoint { horizon_h: number; target_time: string; rainfall_mm: number; water_level_cm: number | null; flood_probability: number }
export interface StationFc {
  station_id: number; station_code: string; station_name: string; area_id: number | null; issued_at: string
  model_version: string | null; data_quality: string; is_cold_start: boolean; is_simulated: boolean; points: FcPoint[]
}
export interface AreaRisk {
  area_id: number; area_name: string; horizon_h: number; issued_at: string; risk_level: string; score: number
  flood_probability: number | null; rainfall_mm: number | null; water_level_ratio: number | null; camera_flood_ratio: number | null; is_simulated: boolean
  explanation?: { cause?: string | null; depth_cm?: number | null } | null
}
export type Metrics = Record<string, unknown>
export interface ModelVersion {
  id: number; name: string; model_type: string; version: string; status: string; is_active: boolean; trained_on_simulated: boolean
  dataset_description: string; metrics: Metrics | null; params: Metrics | null; trained_at: string | null
  training_seconds: number | null; created_at: string
}
export interface ModelStatus {
  forecast_model: ModelVersion | null; vision_model: ModelVersion | null; latest_issued_at: string | null
  last_cycle: Record<string, unknown>; warning: string | null
}
export interface TrainingRun {
  id: number; task: string; status: string; started_at: string; finished_at: string | null
  params: Metrics | null; model_version_id: number | null; log: string
}

/* ------------------------------------------------------------------ chỉ số mô hình */
/** Đọc số theo đường dẫn 'a.b.c' trong JSON metrics (an toàn khi thiếu khoá). */
export function metric(m: Metrics | null | undefined, path: string): number | null {
  let x: unknown = m
  for (const k of path.split('.')) x = x && typeof x === 'object' ? (x as Record<string, unknown>)[k] : undefined
  return typeof x === 'number' ? x : null
}
export const isVision = (type: string) => type === 'YOLOV8_SEG'

export const FORECAST_METRICS: { path: string; label: string; pct?: boolean }[] = [
  { path: 'rainfall.mae', label: 'MAE mưa (mm)' }, { path: 'rainfall.rmse', label: 'RMSE mưa (mm)' },
  { path: 'water_level.mae', label: 'MAE mực nước (cm)' }, { path: 'flood.precision', label: 'Precision ngập', pct: true },
  { path: 'flood.recall', label: 'Recall ngập', pct: true }, { path: 'flood.f1', label: 'F1 ngập', pct: true },
  { path: 'flood.brier', label: 'Brier' }, { path: 'flood.roc_auc', label: 'ROC AUC' },
  { path: 'heavy_rain.precision', label: 'Precision mưa to (≥5 mm/h)', pct: true },
  { path: 'heavy_rain.recall', label: 'Recall mưa to', pct: true }, { path: 'heavy_rain.f1', label: 'F1 mưa to', pct: true },
]
export const VISION_METRICS: { path: string; label: string; pct?: boolean }[] = [
  { path: 'box_map50', label: 'Box mAP50', pct: true }, { path: 'mask_map50', label: 'Mask mAP50', pct: true },
  { path: 'mask_map50_95', label: 'Mask mAP50-95', pct: true }, { path: 'precision', label: 'Precision', pct: true },
  { path: 'recall', label: 'Recall', pct: true },
]
export const MODEL_STATUS_VI: Record<string, string> = {
  TRAINED: 'Đã huấn luyện', DEPLOYED: 'Đang triển khai', ARCHIVED: 'Lưu trữ', FAILED: 'Lỗi',
}
export const RUN_STATUS_VI: Record<string, string> = { RUNNING: 'Đang chạy', SUCCESS: 'Hoàn tất', FAILED: 'Lỗi' }

/* ------------------------------------------------------------------ echarts */
export const C = { water: '#1C7CB5', ink: '#4F6B7D', amber: '#D99A00', purple: '#6B4E9B' }

/** Biểu đồ trục danh mục (cột/đường) với cấu hình chung. */
export function axisOption(categories: (string | number)[], series: object[], yAxis: object | object[] = { type: 'value' }, horizontal = false) {
  const cat = { type: 'category', data: categories, axisLabel: { hideOverlap: true } }
  return {
    tooltip: { trigger: 'axis' }, legend: { bottom: 0, type: 'scroll' },
    grid: { left: 12, right: 12, top: 28, bottom: 40, containLabel: true },
    xAxis: horizontal ? yAxis : cat, yAxis: horizontal ? { ...cat, inverse: true } : yAxis, series,
  }
}
