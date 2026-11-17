import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import maplibregl, { type GeoJSONSource, type LngLatBoundsLike, type MapMouseEvent } from 'maplibre-gl'
import { useQuery } from '@tanstack/react-query'
import { Link, useOutletContext } from 'react-router-dom'
import clsx from 'clsx'
import { api } from '../lib/api'
import { fmtDateTime, fmtNum, fmtPct, fmtTime } from '../lib/format'
import { RISK, floodCause, riskOf } from '../lib/risk'
import { Chart, DemoBadge, ErrorState, Loading, RiskBadge } from '../components/ui'
import { DirectionsPanel, type Place, type RouteResult } from '../features/map/DirectionsPanel'
import { PlaceSearch } from '../features/map/PlaceSearch'
import { HotspotDetail, ReportDetail, ReportForm, TrafficCamera, type FloodReport, type Hotspot } from '../features/map/Reports'
import { circlePolygon, SimulationPanel, useSimulations } from '../features/map/SimulationPanel'
import { useAuth } from '../auth/AuthContext'
import { STATUS, type FloodStatus } from '../features/map/routeStyle'

type FC = GeoJSON.FeatureCollection
interface Features { stations: FC; alerts: FC; forecast_issued_at: string | null }
interface StationFc { station_code: string; is_simulated: boolean; points: { horizon_h: number; flood_probability: number; rainfall_mm: number }[] }
type Selection =
  | { kind: 'point'; lat: number; lon: number; label?: string }
  | { kind: 'station'; id: number }
  | { kind: 'report'; report: FloodReport }
  | { kind: 'hotspot'; hotspot: Hotspot }
  | { kind: 'camera'; id: number; name: string }
  | null

const STYLE = {
  light: 'https://tiles.openfreemap.org/styles/liberty',
  dark: 'https://tiles.openfreemap.org/styles/dark',
}
const HORIZONS = [0, 1, 2, 3, 4, 5, 6]
const CHIPS = [
  { id: 'risk', label: 'Nguy cơ ngập', layers: ['ward-fill'] },
  { id: 'rain', label: 'Mưa', layers: ['st-rain', 'st-water'] },
  { id: 'hotspots', label: 'Điểm ngập thường xuyên', layers: ['hotspot-circle'] },
  { id: 'reports', label: 'Báo cáo ngập', layers: ['report-circle'] },
  { id: 'cameras', label: 'Camera', layers: ['cam-circle'] },
  { id: 'boundary', label: 'Ranh giới', layers: ['area-line', 'ward-line', 'ward-label'] },
] as const
type ChipId = (typeof CHIPS)[number]['id']
const riskExpr = ['match', ['get', 'risk_level'], 'LOW', RISK.LOW.color, 'MEDIUM', RISK.MEDIUM.color, 'HIGH', RISK.HIGH.color, RISK.NO_DATA.color]
const statusExpr = ['match', ['get', 'status'], ...(Object.keys(STATUS) as FloodStatus[]).flatMap((k) => [k, STATUS[k].color]), '#1A73E8']
const CLICKABLE = ['route-seg', 'report-circle', 'hotspot-circle', 'cam-circle', 'st-rain', 'st-water']
const WARD_ZOOM = 12

const empty: FC = { type: 'FeatureCollection', features: [] }
const RANK: Record<string, number> = { HIGH: 3, MEDIUM: 2, LOW: 1, INSUFFICIENT_DATA: 0, NO_DATA: -1 }
interface AreaProps { id: number; name: string; level: string; parent_id: number | null; risk_level: string; score: number | null; cause?: string | null; depth_cm?: number | null }
const pointsFC = <T extends { longitude: number; latitude: number; id: number }>(rows: T[] = []): FC => ({
  type: 'FeatureCollection',
  features: rows.map((r) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.longitude, r.latitude] }, properties: { id: r.id } })),
})

export default function MapPage() {
  const { dark } = useOutletContext<{ dark: boolean }>()
  const { user, hasRole } = useAuth()
  const isAdmin = hasRole('ADMIN')
  const [simOpen, setSimOpen] = useState(false)
  const [simPoint, setSimPoint] = useState<{ lon: number; lat: number } | null>(null)
  const [simRadius, setSimRadius] = useState(500)
  const [expanded, setExpanded] = useState<number | null>(null)
  const sims = useSimulations(isAdmin)
  const cameras = useQuery({ queryKey: ['traffic-cameras'], enabled: false, staleTime: 3600_000, queryFn: () => api.get<FC>('/gis/traffic-cameras') })
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(0)
  const [horizon, setHorizon] = useState(0)
  const [visible, setVisible] = useState<Record<ChipId, boolean>>({ risk: true, rain: true, hotspots: true, reports: true, boundary: true, cameras: false })
  const [legend, setLegend] = useState(false)
  const [sel, setSel] = useState<Selection>(null)
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth >= 768)  // mobile: thu gọn để thấy bản đồ
  const [dirOpen, setDirOpen] = useState(false)
  const [start, setStart] = useState<Place | null>(null)
  const [end, setEnd] = useState<Place | null>(null)
  const [selected, setSelected] = useState(0)

  const risk = useQuery({ queryKey: ['risk-layers', horizon], queryFn: () => api.get<FC & { properties: { issued_at: string | null } }>('/gis/risk-layers', { horizon }) })
  const feats = useQuery({ queryKey: ['features', horizon], queryFn: () => api.get<Features>('/gis/features', { horizon }) })
  const latest = useQuery({ queryKey: ['forecasts-latest'], queryFn: () => api.get<StationFc[]>('/forecasts/latest') })
  const hotspots = useQuery({ queryKey: ['hotspots'], staleTime: 3600_000, queryFn: () => api.get<Hotspot[]>('/gis/hotspots') })
  const reports = useQuery({ queryKey: ['reports'], refetchInterval: 60_000, queryFn: () => api.get<FloodReport[]>('/reports/active') })
  const route = useQuery({
    queryKey: ['route', user?.id, start?.lon, start?.lat, end?.lon, end?.lat, horizon], enabled: dirOpen && !!start && !!end,
    queryFn: () => api.post<RouteResult>('/routing/route', { start: [start!.lon, start!.lat], end: [end!.lon, end!.lat], horizon_h: horizon }),
  })

  // ---------- khởi tạo bản đồ (theo theme)
  useEffect(() => {
    if (!box.current) return
    const m = new maplibregl.Map({
      container: box.current, style: dark ? STYLE.dark : STYLE.light, center: [106.70, 10.78], zoom: 10.6,
      attributionControl: { compact: true, customAttribution: 'Ranh giới: geoBoundaries, GADM · Mưa: Open-Meteo CC BY 4.0' },
    })
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'bottom-right')
    m.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true } }), 'bottom-right')
    m.addControl(new maplibregl.FullscreenControl({ container: box.current.parentElement! }), 'bottom-right')
    m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')
    m.on('load', () => {
      for (const s of ['stations', 'alerts', 'hotspots', 'reports', 'route-alt', 'route-sel', 'route-seg', 'traffic-cams', 'sims']) m.addSource(s, { type: 'geojson', data: empty })
      m.addSource('areas', { type: 'geojson', data: empty, promoteId: 'id' })
      // zoom xa tô theo quận, zoom gần tô theo phường
      const isDistrict = ['==', ['get', 'level'], 'DISTRICT'] as never
      const isWard = ['==', ['get', 'level'], 'WARD'] as never
      const lineColor = dark ? '#9fb6c6' : '#5F6368'
      m.addLayer({ id: 'ward-fill', type: 'fill', source: 'areas', filter: ['all', isWard, ['in', ['get', 'risk_level'], ['literal', ['MEDIUM', 'HIGH']]]] as never, paint: { 'fill-color': riskExpr as never, 'fill-opacity': 0.22 } })
      m.addLayer({ id: 'ward-line', type: 'line', source: 'areas', filter: isWard, minzoom: WARD_ZOOM, paint: { 'line-color': lineColor, 'line-width': 0.7, 'line-dasharray': [2, 2] } })
      m.addLayer({ id: 'area-line', type: 'line', source: 'areas', filter: isDistrict, paint: { 'line-color': lineColor, 'line-width': ['step', ['zoom'], 1, WARD_ZOOM, 2] as never } })
      m.addLayer({ id: 'ward-label', type: 'symbol', source: 'areas', filter: isWard, minzoom: WARD_ZOOM + 0.5, layout: { 'text-field': ['get', 'name'], 'text-size': 11, 'text-font': ['Noto Sans Regular'] }, paint: { 'text-color': dark ? '#E3ECF2' : '#3C4043', 'text-halo-color': dark ? '#13212C' : '#fff', 'text-halo-width': 1.2 } })
      m.addLayer({ id: 'sim-fill', type: 'fill', source: 'sims', paint: { 'fill-color': '#00897B', 'fill-opacity': 0.3 } })
      m.addLayer({ id: 'sim-line', type: 'line', source: 'sims', paint: { 'line-color': '#00695C', 'line-width': 2, 'line-dasharray': [2, 1] } })
      m.addLayer({ id: 'sim-label', type: 'symbol', source: 'sims', layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-font': ['Noto Sans Bold'] }, paint: { 'text-color': '#004D40', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } })
      m.addLayer({ id: 'cam-circle', type: 'circle', source: 'traffic-cams', layout: { visibility: 'none' }, paint: { 'circle-radius': 4, 'circle-color': '#0E2A3B', 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } })
      m.addLayer({ id: 'st-rain', type: 'circle', source: 'stations', filter: ['==', ['get', 'station_type'], 'RAIN'], paint: {
        'circle-radius': ['interpolate', ['linear'], ['coalesce', ['get', 'rainfall_mm'], 0], 0, 4, 20, 13],
        'circle-color': ['interpolate', ['linear'], ['coalesce', ['get', 'rainfall_mm'], 0], 0, '#9AA0A6', 1, '#4FB0E6', 5, '#1C7CB5', 20, '#0D47A1'],
        'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } })
      m.addLayer({ id: 'st-water', type: 'circle', source: 'stations', filter: ['!=', ['get', 'station_type'], 'RAIN'], paint: {
        'circle-radius': 7, 'circle-color': '#1C7CB5', 'circle-stroke-color': '#fff', 'circle-stroke-width': 3 } })
      m.addLayer({ id: 'route-alt', type: 'line', source: 'route-alt', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#9AA0A6', 'line-width': 6 } })
      m.addLayer({ id: 'route-casing', type: 'line', source: 'route-sel', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#fff', 'line-width': 11 } })
      m.addLayer({ id: 'route-line', type: 'line', source: 'route-sel', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#1A73E8', 'line-width': 7 } })
      m.addLayer({ id: 'route-seg-bg', type: 'line', source: 'route-seg', paint: { 'line-color': '#fff', 'line-width': 8 } })
      // nét đứt để đoạn ngập không chỉ phân biệt bằng màu
      m.addLayer({ id: 'route-seg', type: 'line', source: 'route-seg', paint: { 'line-color': statusExpr as never, 'line-width': 8, 'line-dasharray': [1.6, 0.6] } })
      m.addLayer({ id: 'hotspot-circle', type: 'circle', source: 'hotspots', paint: {
        'circle-radius': 5, 'circle-color': '#F29900', 'circle-stroke-color': '#5F3B00', 'circle-stroke-width': 1.5 } })
      m.addLayer({ id: 'report-circle', type: 'circle', source: 'reports', paint: {
        'circle-radius': 9, 'circle-color': '#8E24AA', 'circle-stroke-color': '#fff', 'circle-stroke-width': 3 } })
      m.addLayer({ id: 'alert-symbol', type: 'symbol', source: 'alerts', maxzoom: WARD_ZOOM, layout: {
        'text-field': ['match', ['get', 'risk_level'], 'HIGH', '◆', 'MEDIUM', '▲', '●'], 'text-size': 26, 'text-font': ['Noto Sans Regular'],
        'text-allow-overlap': true, 'text-offset': [0, -0.6] },
        paint: { 'text-color': riskExpr as never, 'text-halo-color': '#fff', 'text-halo-width': 2 } })
      for (const id of CLICKABLE) {
        m.on('mouseenter', id, () => { m.getCanvas().style.cursor = 'pointer' })
        m.on('mouseleave', id, () => { m.getCanvas().style.cursor = '' })
      }
      setReady((x) => x + 1)
    })
    map.current = m
    return () => { m.remove(); map.current = null }
  }, [dark])

  // ---------- dữ liệu -> nguồn bản đồ
  const setData = useCallback((id: string, data: FC) => {
    (map.current?.getSource(id) as GeoJSONSource | undefined)?.setData(data)
  }, [])
  useEffect(() => { if (ready && risk.data) setData('areas', risk.data) }, [ready, risk.data, setData])
  useEffect(() => {
    if (ready && feats.data) { setData('stations', feats.data.stations); setData('alerts', feats.data.alerts) }
  }, [ready, feats.data, setData])
  useEffect(() => { if (ready) setData('hotspots', pointsFC(hotspots.data)) }, [ready, hotspots.data, setData])
  useEffect(() => { if (ready) setData('reports', pointsFC(reports.data)) }, [ready, reports.data, setData])
  useEffect(() => {
    if (visible.cameras && !cameras.data) cameras.refetch()
  }, [visible.cameras, cameras])
  useEffect(() => { if (ready && cameras.data) setData('traffic-cams', cameras.data) }, [ready, cameras.data, setData])
  useEffect(() => {
    if (!ready) return
    const rows = isAdmin ? sims.data ?? [] : []
    const draft = simOpen && simPoint ? [{ longitude: simPoint.lon, latitude: simPoint.lat, radius_m: simRadius, label: 'Vùng sẽ tạo' }] : []
    setData('sims', { type: 'FeatureCollection', features: [
      ...rows.map((s) => ({ longitude: s.longitude, latitude: s.latitude, radius_m: s.radius_m, label: `MÔ PHỎNG ${s.depth_cm} cm` })), ...draft,
    ].map((s) => ({ type: 'Feature', geometry: circlePolygon(s.longitude, s.latitude, s.radius_m), properties: { label: s.label } })) })
  }, [ready, isAdmin, sims.data, simOpen, simPoint, simRadius, setData])
  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    for (const c of CHIPS) for (const id of c.layers)
      if (m.getLayer(id)) m.setLayoutProperty(id, 'visibility', visible[c.id] ? 'visible' : 'none')
  }, [ready, visible])

  // ---------- vẽ tuyến
  const result = dirOpen && start && end ? route.data : undefined
  useEffect(() => { if (result) setSelected(result.recommended_index) }, [result])
  useEffect(() => {
    if (!ready) return
    const chosen = result?.routes.find((r) => r.index === selected)
    const line = (g: GeoJSON.LineString, properties = {}): GeoJSON.Feature => ({ type: 'Feature', geometry: g, properties })
    setData('route-alt', { type: 'FeatureCollection', features: (result?.routes ?? []).filter((r) => r !== chosen).map((r) => line(r.geometry)) })
    setData('route-sel', { type: 'FeatureCollection', features: chosen ? [line(chosen.geometry)] : [] })
    setData('route-seg', { type: 'FeatureCollection', features: (chosen?.segments ?? []).filter((s) => s.status !== 'DRY').map((s) =>
      line(s.geometry, { status: s.status, probability: s.probability, reasons: s.reasons.join('; ') })) })
  }, [ready, result, selected, setData])
  // chỉ canh khung khi đổi điểm đi/đến, không canh lại khi dữ liệu tuyến làm mới
  const fitted = useRef('')
  useEffect(() => {
    const m = map.current
    const key = `${start?.lon},${start?.lat},${end?.lon},${end?.lat}`
    if (!m || !result || fitted.current === key) return
    fitted.current = key
    const c = result.routes[result.recommended_index].geometry.coordinates
    const b = c.reduce((acc, p) => acc.extend(p as [number, number]), new maplibregl.LngLatBounds(c[0] as [number, number], c[0] as [number, number]))
    const wide = window.innerWidth >= 768
    m.fitBounds(b as LngLatBoundsLike, { padding: wide ? { left: 440, right: 60, top: 60, bottom: 160 } : { left: 30, right: 30, top: 90, bottom: 380 }, maxZoom: 16 })
  }, [result, start, end])

  // ---------- marker A/B kéo thả được
  useEffect(() => {
    const m = map.current
    if (!m || !ready || !dirOpen) return
    const mk = (p: Place | null, color: string, set: (x: Place) => void, name: string) => {
      if (!p) return null
      const marker = new maplibregl.Marker({ color, draggable: true }).setLngLat([p.lon, p.lat]).addTo(m)
      marker.getElement().setAttribute('aria-label', name)
      marker.on('dragend', () => {
        const { lng, lat } = marker.getLngLat()
        set({ label: `${lat.toFixed(5)}, ${lng.toFixed(5)}`, lon: lng, lat })
      })
      return marker
    }
    const a = mk(start, '#188038', setStart, 'Điểm đi')
    const b = mk(end, '#D93025', setEnd, 'Điểm đến')
    return () => { a?.remove(); b?.remove() }
  }, [ready, dirOpen, start, end])

  // ---------- click
  const onClick = useCallback((e: MapMouseEvent) => {
    const m = map.current!
    const here: Place = { label: `${e.lngLat.lat.toFixed(5)}, ${e.lngLat.lng.toFixed(5)}`, lon: e.lngLat.lng, lat: e.lngLat.lat }
    if (simOpen) { setSimPoint({ lon: here.lon, lat: here.lat }); return }
    if (dirOpen && !start) { setStart(here); return }
    if (dirOpen && !end) { setEnd(here); return }
    const f = m.queryRenderedFeatures(e.point, { layers: CLICKABLE.filter((l) => m.getLayer(l)) })[0]
    const id = Number(f?.properties?.id)
    if (f?.layer.id === 'route-seg') {
      const p = f.properties
      new maplibregl.Popup({ closeButton: true }).setLngLat(e.lngLat)
        .setText(`${STATUS[p.status as FloodStatus].label}${p.reasons ? `: ${p.reasons}` : ''}`).addTo(m)
    } else if (f?.layer.id === 'report-circle') {
      const r = reports.data?.find((x) => x.id === id)
      if (r) setSel({ kind: 'report', report: r })
    } else if (f?.layer.id === 'hotspot-circle') {
      const h = hotspots.data?.find((x) => x.id === id)
      if (h) setSel({ kind: 'hotspot', hotspot: h })
    } else if (f?.layer.id === 'cam-circle') setSel({ kind: 'camera', id, name: String(f.properties.name) })
    else if (f) setSel({ kind: 'station', id })
    else if (!dirOpen) setSel({ kind: 'point', lat: here.lat, lon: here.lon })
  }, [simOpen, dirOpen, start, end, reports.data, hotspots.data])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    m.on('click', onClick)
    return () => { m.off('click', onClick) }
  }, [ready, onClick])

  const flyTo = (lon: number, lat: number, zoom = 14) => map.current?.flyTo({ center: [lon, lat], zoom })
  const directionsTo = (p: Place) => { setEnd(p); setSel(null); setDirOpen(true) }

  // ---------- thủy đồ thời gian: xác suất ngập lớn nhất toàn TP theo mốc
  const hydro = useMemo(() => HORIZONS.map((h) => {
    if (!latest.data?.length) return null
    const probs = latest.data.flatMap((s) => s.points.filter((p) => p.horizon_h === Math.max(h, 1)).map((p) => p.flood_probability))
    return probs.length ? Math.max(...probs) : null
  }), [latest.data])

  const issuedAt = risk.data?.properties?.issued_at
  const areasRanked = useMemo(() => (risk.data?.features ?? [])
    .map((f) => f.properties as AreaProps)
    .filter((a) => a.level === 'DISTRICT')
    .sort((a, b) => RANK[riskOf(b.risk_level)] - RANK[riskOf(a.risk_level)] || (b.score ?? -1) - (a.score ?? -1)), [risk.data])
  const anySim = (risk.data?.features ?? []).some((f) => f.properties?.is_simulated)
  const sideOpen = dirOpen || !!sel || simOpen
  const wardsOf = (id: number) => (risk.data?.features ?? []).map((f) => f.properties as AreaProps)
    .filter((a) => a.parent_id === id).sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
  const wardsHot = (id: number) => wardsOf(id).filter((w) => w.risk_level === 'MEDIUM' || w.risk_level === 'HIGH').length
  const highWards = (risk.data?.features ?? []).map((f) => f.properties as AreaProps).filter((a) => a.level === 'WARD' && a.risk_level === 'HIGH')
  const deepest = highWards.reduce<AreaProps | null>((m, w) => (!m || (w.depth_cm ?? -1) > (m.depth_cm ?? -1) ? w : m), null)
  const showArea = (id: number) => {
    const c = centroidOf(risk.data!.features.find((x) => x.properties?.id === id)!.geometry)
    flyTo(c[0], c[1], 13)
    setSel({ kind: 'point', lat: c[1], lon: c[0] })
  }

  return (
    <div className="absolute inset-0">
      <div ref={box} className="absolute inset-0" aria-label="Bản đồ nguy cơ ngập TP.HCM" role="application" />

      {/* Thanh tìm kiếm + tình hình */}
      {!dirOpen && !simOpen && (
        <div className="pointer-events-none absolute left-3 top-3 z-10 flex w-[min(400px,calc(100%-24px))] flex-col gap-2">
          <div className="pointer-events-auto flex items-center gap-1 rounded-xl bg-[var(--surface)] p-1 shadow-lg">
            <div className="min-w-0 flex-1">
              <PlaceSearch label="Tìm kiếm địa điểm" placeholder="Tìm đường, quận, điểm ngập, toạ độ…" className="h-10 border-0 text-base focus:ring-0"
                onPick={(r) => {
                  flyTo(r.lon, r.lat, r.type === 'area' ? 12.5 : 15)
                  if (r.type === 'station' && r.id) setSel({ kind: 'station', id: r.id })
                  else setSel({ kind: 'point', lat: r.lat, lon: r.lon, label: r.label })
                }} />
            </div>
            <button className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#1A73E8] text-white" aria-label="Chỉ đường" title="Chỉ đường"
              onClick={() => { setSel(null); setSimOpen(false); setDirOpen(true) }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden><path d="M21.7 11.3l-9-9a1 1 0 0 0-1.4 0l-9 9a1 1 0 0 0 0 1.4l9 9a1 1 0 0 0 1.4 0l9-9a1 1 0 0 0 0-1.4zM14 14.5V12h-4v3H8v-4a1 1 0 0 1 1-1h5V7.5l3.5 3.5-3.5 3.5z" /></svg>
            </button>
          </div>
          {!sel && (
            <div className="panel pointer-events-auto shadow-lg">
              <button className="flex w-full items-center justify-between px-3 py-2 text-sm font-semibold"
                aria-expanded={panelOpen} onClick={() => setPanelOpen(!panelOpen)}>
                <span>Tình hình {horizon === 0 ? 'hiện tại' : `sau ${horizon} giờ`}</span>
                <span aria-hidden>{panelOpen ? '−' : '+'}</span>
              </button>
              {panelOpen && (
                <div className="max-h-[45vh] overflow-auto border-t border-[var(--line)] px-3 pb-3 pt-2 text-sm">
                  <div className="muted mb-2 flex flex-wrap items-center gap-2 text-xs">
                    Cập nhật {fmtDateTime(issuedAt)} {anySim && <DemoBadge />}
                  </div>
                  {risk.isLoading ? <Loading rows={3} /> : risk.error ? <ErrorState error={risk.error} retry={risk.refetch} /> : (
                    <ul className="space-y-1">
                      {areasRanked.map((a) => (
                        <li key={a.id}>
                          <button className="flex w-full items-center justify-between gap-2 rounded-md px-1 py-1 text-left hover:bg-black/5 dark:hover:bg-white/5"
                            aria-expanded={expanded === a.id} onClick={() => setExpanded(expanded === a.id ? null : a.id)}>
                            <span><span aria-hidden className="muted mr-1">{expanded === a.id ? '▾' : '▸'}</span>{a.name}
                              {floodCause(a.cause, a.depth_cm) && <span className="muted block text-xs">{floodCause(a.cause, a.depth_cm)}</span>}
                              {wardsHot(a.id) > 0 && <span className="muted block text-xs">{wardsHot(a.id)} phường nguy cơ trung bình/cao</span>}
                            </span><RiskBadge level={a.risk_level} />
                          </button>
                          {expanded === a.id && (
                            <ul className="ml-4 border-l border-[var(--line)] pl-2">
                              {wardsOf(a.id).map((w) => (
                                <li key={w.id}>
                                  <button className="flex w-full items-center justify-between gap-2 rounded-md px-1 py-0.5 text-left text-xs hover:bg-black/5 dark:hover:bg-white/5" onClick={() => showArea(w.id)}>
                                    <span>{w.name}{floodCause(w.cause, w.depth_cm) && <span className="muted block">{floodCause(w.cause, w.depth_cm)}</span>}</span><RiskBadge level={w.risk_level} compact />
                                  </button>
                                </li>
                              ))}
                            </ul>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  <Link to="/alerts" className="btn-ghost mt-3">Danh sách cảnh báo ({feats.data?.alerts.features.length ?? 0})</Link>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Chip lớp bản đồ */}
      <div className={clsx('absolute left-2 right-2 z-10 flex gap-2 overflow-x-auto p-1 md:left-[424px] md:right-3', dirOpen ? 'top-2' : 'top-[64px] md:top-3')}>
        {CHIPS.map((c) => (
          <button key={c.id} aria-pressed={visible[c.id]} onClick={() => setVisible((v) => ({ ...v, [c.id]: !v[c.id] }))}
            className={clsx('shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium shadow',
              visible[c.id] ? 'bg-[#D2E3FC] text-[#174EA6]' : 'bg-[var(--surface)] text-[var(--text)]')}>
            {visible[c.id] ? '✓ ' : ''}{c.label}
          </button>
        ))}
        {isAdmin && (
          <button aria-pressed={simOpen} onClick={() => { setSimOpen(!simOpen); setSimPoint(null); setSel(null); setDirOpen(false) }}
            className={clsx('shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium shadow', simOpen ? 'bg-[#00897B] text-white' : 'bg-[var(--surface)] text-[var(--text)]')}>
            Mô phỏng ngập
          </button>
        )}
        <button aria-expanded={legend} aria-label="Chú giải và nguồn dữ liệu" onClick={() => setLegend(!legend)} className="shrink-0 whitespace-nowrap rounded-full bg-[var(--surface)] px-3 py-1.5 text-sm font-medium text-[var(--text)] shadow">ⓘ</button>
      </div>
      {legend && (
        <div className="panel absolute right-3 top-[110px] z-10 w-60 space-y-1 p-3 text-xs shadow-lg md:top-14">
          {(['MEDIUM', 'HIGH'] as const).map((k) => (
            <div key={k} className="flex items-center gap-2">
              <span className="inline-flex h-4 w-6 items-center justify-center rounded text-white" style={{ background: RISK[k].color }} aria-hidden>{RISK[k].symbol}</span>
              Phường nguy cơ {RISK[k].label.toLowerCase()} (tô màu)
            </div>
          ))}
          <p className="muted">Phường nguy cơ thấp hoặc chưa có dữ liệu không tô màu. Độ sâu ngập (cm) là ước tính.</p>
          <div className="flex items-center gap-2"><span className="inline-block h-3 w-3 rounded-full border border-[#5F3B00] bg-[#F29900]" aria-hidden />Điểm ngập thường xuyên</div>
          <div className="flex items-center gap-2"><span className="inline-block h-4 w-4 rounded-full border-2 border-white bg-[#8E24AA]" aria-hidden />Người dân báo ngập</div>
          <div className="flex items-center gap-2"><span className="inline-block h-3 w-3 rounded-full bg-[#1C7CB5]" aria-hidden />Mưa (chấm to, đậm = mưa nhiều)</div>
          <p className="muted border-t border-[var(--line)] pt-2">Mưa và triều lấy từ mô hình Open-Meteo, không phải trạm đo. Trạng thái ngập là ước tính, chưa kiểm chứng với ngập thật. Không đảm bảo đoạn đường an toàn. Camera: Cổng thông tin giao thông TP.HCM.</p>
        </div>
      )}

      {/* Panel bên: chỉ đường / chi tiết. Desktop: cột trái; mobile: bottom sheet */}
      {sideOpen && (
        <aside className={clsx('panel absolute inset-x-0 bottom-0 z-20 max-h-[60vh] overflow-auto rounded-b-none p-4 shadow-2xl md:inset-x-auto md:bottom-3 md:left-3 md:max-h-none md:w-[400px] md:rounded-b-xl',
          dirOpen || simOpen ? 'md:top-3' : 'md:top-[72px]')} aria-label={simOpen ? 'Mô phỏng ngập' : sel ? 'Chi tiết vị trí' : 'Chỉ đường'}>
          {simOpen ? (
            <SimulationPanel point={simPoint} radius={simRadius} setRadius={setSimRadius} onClose={() => { setSimOpen(false); setSimPoint(null) }} />
          ) : sel ? (
            <>
              <div className="flex justify-end">
                <button className="btn-ghost px-2" onClick={() => setSel(null)} aria-label={dirOpen ? 'Quay lại chỉ đường' : 'Đóng chi tiết'}>{dirOpen ? '← Chỉ đường' : '✕'}</button>
              </div>
              {sel.kind === 'station' && <StationDetail id={sel.id} />}
              {sel.kind === 'point' && <PointDetail lat={sel.lat} lon={sel.lon} label={sel.label} horizon={horizon} onDirections={directionsTo} />}
              {sel.kind === 'report' && <ReportDetail report={sel.report} onClose={() => setSel(null)} />}
              {sel.kind === 'hotspot' && <HotspotDetail h={sel.hotspot} />}
              {sel.kind === 'camera' && <><h2 className="mb-2 text-lg font-semibold">{sel.name}</h2><TrafficCamera id={sel.id} name={sel.name} /></>}
            </>
          ) : (
            <DirectionsPanel start={start} end={end} setStart={setStart} setEnd={setEnd} horizon={horizon} setHorizon={setHorizon}
              result={result} loading={route.isFetching && !route.data} error={route.error} retry={route.refetch}
              selected={selected} setSelected={setSelected} flyTo={(c) => flyTo(c[0], c[1], 16)}
              onClose={() => { setDirOpen(false); setStart(null); setEnd(null); fitted.current = '' }} />
          )}
        </aside>
      )}

      {/* Thủy đồ thời gian */}
      <div className={clsx('panel absolute bottom-8 left-1/2 z-10 w-[min(520px,calc(100%-24px))] -translate-x-1/2 px-2 pb-1 pt-1 shadow-lg',
        sideOpen && 'hidden md:left-[calc(50%+200px)] md:block md:w-[min(460px,calc(100%-500px))]')}>
        <div className="mb-0.5 text-xs font-semibold">Nguy cơ ngập theo giờ</div>
        {deepest && <div className="muted mb-0.5 text-xs">{highWards.length} phường nguy cơ cao{floodCause(deepest.cause, deepest.depth_cm) ? ` · ${floodCause(deepest.cause, deepest.depth_cm)}` : ''}</div>}
        <div role="radiogroup" aria-label="Chọn mốc thời gian dự báo" className="grid grid-cols-7 items-end gap-1">
          {HORIZONS.map((h) => {
            const p = hydro[h]
            const lv = p === null ? 'NO_DATA' : p >= 0.8 ? 'HIGH' : p >= 0.5 ? 'MEDIUM' : 'LOW'
            return (
              <button key={h} role="radio" aria-checked={horizon === h}
                aria-label={`${h === 0 ? 'Hiện tại' : `Sau ${h} giờ`}, xác suất ngập ước tính tối đa ${fmtPct(p)}`}
                onClick={() => setHorizon(h)}
                className={clsx('flex flex-col items-center rounded-md px-1 pb-0.5 pt-1', horizon === h ? 'bg-water/15 ring-2 ring-water' : 'hover:bg-black/5 dark:hover:bg-white/5')}>
                <div className="flex h-7 w-full items-end justify-center">
                  <div className="w-4 rounded-t" style={{ height: `${Math.max(8, (p ?? 0) * 100)}%`, background: RISK[lv as 'LOW'].color }} />
                </div>
                <span className="num text-xs font-semibold">{h === 0 ? 'Nay' : `+${h}h`}</span>
                <span className="num muted text-[10px]">{h === 0 ? fmtTime(issuedAt) : fmtTime(addHours(issuedAt, h))}</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function addHours(iso: string | null | undefined, h: number) {
  return iso ? new Date(new Date(iso).getTime() + h * 3600_000).toISOString() : null
}

function centroidOf(g: GeoJSON.Geometry): [number, number] {
  const coords: number[][] = []
  const walk = (x: unknown): void => { if (Array.isArray(x) && typeof x[0] === 'number') coords.push(x as number[]); else if (Array.isArray(x)) x.forEach(walk) }
  walk((g as GeoJSON.Polygon).coordinates)
  return [coords.reduce((s, c) => s + c[0], 0) / coords.length, coords.reduce((s, c) => s + c[1], 0) / coords.length]
}

/* ------------------------------------------------------------------ detail panels */
interface Identify {
  area: { id: number; name: string } | null
  district: string | null
  stations: { id: number; code: string; name: string; distance_m: number; rainfall_mm: number | null; water_level_cm: number | null; observed_at: string | null; data_status: string; source: string }[]
  risk: { horizon_h: number; risk_level: string; score: number; flood_probability: number | null; rainfall_mm: number | null; explanation: { notes?: string[]; overrides?: string[]; level_reason?: string; cause?: string | null; depth_cm?: number | null } | null }[]
  history: { events_within_1500m: number; last_event_at: string | null; max_depth_cm: number | null }
  issued_at: string | null
}

const RECO: Record<string, string[]> = {
  LOW: ['Tiếp tục theo dõi.'],
  MEDIUM: ['Tăng cường giám sát; kiểm tra khả năng thoát nước; chuẩn bị phương án ứng phó.'],
  HIGH: ['Ưu tiên xác minh hiện trường; hạn chế lưu thông qua khu vực trũng thấp; theo dõi thông tin chính thức.'],
}

function PointDetail({ lat, lon, label, horizon, onDirections }: { lat: number; lon: number; label?: string; horizon: number; onDirections: (p: Place) => void }) {
  const [reporting, setReporting] = useState(false)
  const q = useQuery({ queryKey: ['identify', lat.toFixed(5), lon.toFixed(5)], queryFn: () => api.get<Identify>('/gis/identify', { lat, lon }) })
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorState error={q.error} />
  const d = q.data!
  const cur = d.risk.find((r) => r.horizon_h === horizon)
  return (
    <div className="space-y-3 text-sm">
      <div>
        <h2 className="text-lg font-semibold">{label ?? d.area?.name ?? 'Ngoài ranh giới dữ liệu'}</h2>
        {(label || d.district) && <div className="muted text-sm">{[label && d.area?.name, d.district].filter(Boolean).join(', ')}</div>}
        <div className="muted num text-xs">{lat.toFixed(5)}, {lon.toFixed(5)} · cập nhật {fmtDateTime(d.issued_at)}</div>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" onClick={() => onDirections({ label: label ?? d.area?.name ?? `${lat.toFixed(5)}, ${lon.toFixed(5)}`, lon, lat })}>Chỉ đường tới đây</button>
        <button className="btn-ghost" aria-expanded={reporting} onClick={() => setReporting(!reporting)}>Báo ngập tại đây</button>
      </div>
      {reporting && <ReportForm lat={lat} lon={lon} onDone={() => setReporting(false)} />}
      {cur && (
        <div className="flex items-center gap-2">
          <RiskBadge level={cur.risk_level} />
          <span className="num">Xác suất ngập {fmtPct(cur.flood_probability)} · mưa {fmtNum(cur.rainfall_mm, ' mm/h')}</span>
        </div>
      )}
      {d.risk.length > 0 && (
        <div>
          <div className="mb-1 font-medium">Mức rủi ro 0–6 giờ</div>
          <div className="grid grid-cols-7 gap-1 text-center text-xs">
            {d.risk.map((r) => <div key={r.horizon_h}><RiskBadge level={r.risk_level} compact /><div className="num">{r.horizon_h === 0 ? 'Nay' : `+${r.horizon_h}h`}</div></div>)}
          </div>
        </div>
      )}
      {floodCause(cur?.explanation?.cause, cur?.explanation?.depth_cm) && <div className="font-medium">{floodCause(cur?.explanation?.cause, cur?.explanation?.depth_cm)}</div>}
      {!!(cur?.explanation?.overrides?.length || cur?.explanation?.notes?.length) && (
        <div className="rounded-lg bg-black/5 p-2 text-xs dark:bg-white/5">
          {cur!.explanation!.overrides?.map((o) => <div key={o}>• {o}</div>)}
          {cur!.explanation!.notes?.map((o) => <div key={o} className="muted">• {o}</div>)}
        </div>
      )}
      {cur && RECO[cur.risk_level] && (
        <div><div className="font-medium">Khuyến nghị</div><ul className="list-disc pl-5">{RECO[cur.risk_level].map((x) => <li key={x}>{x}</li>)}</ul></div>
      )}
      {d.history.events_within_1500m > 0 && (
        <div><div className="font-medium">Lịch sử ngập (bán kính 1,5 km)</div>
          <div className="num">{d.history.events_within_1500m} sự kiện · gần nhất {fmtDateTime(d.history.last_event_at)} · sâu nhất {fmtNum(d.history.max_depth_cm, ' cm')}</div>
        </div>
      )}
    </div>
  )
}

interface Obs { observed_at: string; rainfall_mm: number | null; water_level_cm: number | null; is_simulated: boolean }
interface Station { id: number; code: string; name: string; address: string; station_type: string; latitude: number; longitude: number; flood_threshold_cm: number; connection_status: string; data_status: string; latest_rainfall_mm: number | null; latest_water_level_cm: number | null; last_observation_at: string | null; area: { name: string } | null; source: { name: string; is_simulated: boolean } }
interface StationForecastResp { issued_at: string | null; points: { horizon_h: number; target_time: string; rainfall_mm: number; water_level_cm: number | null; flood_probability: number; data_quality: string; is_cold_start: boolean }[] }

function StationDetail({ id }: { id: number }) {
  const st = useQuery({ queryKey: ['station', id], queryFn: () => api.get<Station>(`/stations/${id}`) })
  const obs = useQuery({ queryKey: ['obs', id], queryFn: () => api.get<Obs[]>(`/stations/${id}/observations`) })
  const fc = useQuery({ queryKey: ['station-fc', id], queryFn: () => api.get<StationForecastResp>(`/stations/${id}/forecast`) })
  const option = useMemo(() => {
    const o = obs.data ?? []
    const f = fc.data?.points ?? []
    return {
      tooltip: { trigger: 'axis' }, legend: { top: 0, textStyle: { fontSize: 11 }, itemWidth: 14 },
      grid: { left: 40, right: 40, top: 52, bottom: 28 },
      xAxis: { type: 'time', axisLabel: { hideOverlap: true, fontSize: 10, formatter: (v: number) => fmtTime(new Date(v).toISOString()) } },
      yAxis: [{ type: 'value', name: 'mm', inverse: false }, { type: 'value', name: 'cm' }],
      series: [
        { name: 'Mưa (mm/h)', type: 'bar', data: o.map((x) => [x.observed_at, x.rainfall_mm]), itemStyle: { color: '#1C7CB5' } },
        { name: 'Mực nước (cm)', type: 'line', yAxisIndex: 1, showSymbol: false, data: o.map((x) => [x.observed_at, x.water_level_cm]), itemStyle: { color: '#0E2A3B' } },
        { name: 'Dự báo mực nước', type: 'line', yAxisIndex: 1, lineStyle: { type: 'dashed' }, data: f.map((x) => [x.target_time, x.water_level_cm]), itemStyle: { color: '#D99A00' } },
        { name: 'Ngưỡng ngập', type: 'line', yAxisIndex: 1, showSymbol: false, lineStyle: { type: 'dotted', color: '#C62828' },
          data: o.length ? [[o[0].observed_at, st.data?.flood_threshold_cm], [f.at(-1)?.target_time ?? o.at(-1)!.observed_at, st.data?.flood_threshold_cm]] : [] },
      ],
    }
  }, [obs.data, fc.data, st.data])
  if (st.isLoading) return <Loading />
  if (st.error) return <ErrorState error={st.error} />
  const s = st.data!
  return (
    <div className="space-y-3 text-sm">
      <div>
        <h2 className="text-lg font-semibold">{s.name}</h2>
        <div className="muted text-xs">{s.code} · {s.address} · {s.area?.name}</div>
        <div className="mt-1 flex flex-wrap gap-1">
          <span className="chip bg-black/5 dark:bg-white/10">{s.connection_status === 'ONLINE' ? 'Đang kết nối' : 'Mất kết nối'}</span>
          {s.source.is_simulated && <DemoBadge />}
        </div>
      </div>
      <dl className="num grid grid-cols-2 gap-2">
        <div><dt className="muted text-xs">Mưa hiện tại</dt><dd className="text-lg font-semibold">{fmtNum(s.latest_rainfall_mm, ' mm/h')}</dd></div>
        <div><dt className="muted text-xs">Mực nước / ngưỡng</dt><dd className="text-lg font-semibold">{fmtNum(s.latest_water_level_cm)} / {s.flood_threshold_cm} cm</dd></div>
      </dl>
      <div className="muted text-xs">Cập nhật {fmtDateTime(s.last_observation_at)} · nguồn {s.source.name}</div>
      {obs.isLoading ? <Loading rows={2} /> : <Chart option={option} height={220} ariaLabel={`Biểu đồ mưa và mực nước 48 giờ của ${s.name}`} />}
      {fc.data?.points.length ? (
        <table className="table num">
          <thead><tr><th>Mốc</th><th>Mưa</th><th>Mực nước</th><th>XS ngập</th></tr></thead>
          <tbody>{fc.data.points.map((p) => (
            <tr key={p.horizon_h}><td>+{p.horizon_h}h</td><td>{fmtNum(p.rainfall_mm)}</td><td>{fmtNum(p.water_level_cm)}</td><td>{fmtPct(p.flood_probability)}</td></tr>
          ))}</tbody>
        </table>
      ) : <div className="muted">Chưa có dự báo cho trạm này</div>}

    </div>
  )
}
