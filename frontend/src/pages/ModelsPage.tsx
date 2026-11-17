import { useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDateTime, fmtNum } from '../lib/format'
import { RISK } from '../lib/risk'
import { Confirm, DemoBadge, Empty, ErrorState, Loading, Modal, PageHeader, useToast } from '../components/ui'
import {
  MODEL_STATUS_VI, RUN_STATUS_VI, errMsg, fmtDec, isVision, metric, type Metrics, type ModelVersion, type TrainingRun,
} from '../features/analytics/analytics'
import { ModelMetrics, Section } from '../features/analytics/components'

type Task = 'forecast' | 'vision'
const TASK_VI: Record<string, string> = { forecast: 'mô hình dự báo (LSTM/GRU)', vision: 'mô hình camera (YOLOv8-seg)', FORECAST: 'Dự báo', VISION: 'Camera' }
const POLL_MS = 10_000

export default function ModelsPage() {
  const id = useId()
  const toast = useToast()
  const qc = useQueryClient()
  // Run mới được tạo trong luồng nền sau khi POST trả về -> theo dõi thêm 1 phút kể cả khi chưa thấy RUNNING
  const [watchUntil, setWatchUntil] = useState(0)
  const runs = useQuery({
    queryKey: ['training-runs'], queryFn: () => api.get<TrainingRun[]>('/admin/training-runs'),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'RUNNING') || Date.now() < watchUntil ? POLL_MS : false),
  })
  const running = !!runs.data?.some((r) => r.status === 'RUNNING')
  const models = useQuery({ queryKey: ['admin-models'], queryFn: () => api.get<ModelVersion[]>('/admin/models'),
    refetchInterval: running ? POLL_MS : false })

  const [detail, setDetail] = useState<ModelVersion | null>(null)
  const [activate, setActivate] = useState<ModelVersion | null>(null)
  const [train, setTrain] = useState<Task | null>(null)
  const [epochs, setEpochs] = useState<Record<Task, number>>({ forecast: 8, vision: 15 })

  const activateMut = useMutation({
    mutationFn: (m: ModelVersion) => api.post<ModelVersion>(`/admin/models/${m.id}/activate`),
    onSuccess: (m) => { toast('ok', `Đã kích hoạt ${m.name} ${m.version}`); qc.invalidateQueries({ queryKey: ['admin-models'] }); qc.invalidateQueries({ queryKey: ['forecast-model-status'] }) },
    onError: (e) => toast('error', errMsg(e)),
  })
  const trainMut = useMutation({
    mutationFn: (t: Task) => api.post<{ message: string }>('/admin/models/train', undefined, { task: t, epochs: epochs[t] }),
    onSuccess: (r) => { toast('ok', r.message); setWatchUntil(Date.now() + 60_000); qc.invalidateQueries({ queryKey: ['training-runs'] }) },
    onError: (e) => toast('error', errMsg(e)),
  })

  const epochsOk = (t: Task) => Number.isInteger(epochs[t]) && epochs[t] >= 1 && epochs[t] <= 100

  return (
    <div className="space-y-4">
      <PageHeader title="Mô hình AI" />

      <Section title="Huấn luyện lại">
        <div className="flex flex-wrap items-end gap-4">
          {(['forecast', 'vision'] as const).map((t) => (
            <div key={t} className="flex items-end gap-2">
              <div className="w-28">
                <label className="label" htmlFor={`${id}-ep-${t}`}>Số epoch</label>
                <input id={`${id}-ep-${t}`} type="number" min={1} max={100} className="input num" value={epochs[t]}
                  aria-invalid={!epochsOk(t)} aria-describedby={`${id}-ep-${t}-err`}
                  onChange={(e) => setEpochs({ ...epochs, [t]: e.target.valueAsNumber })} />
              </div>
              <button className="btn-primary" disabled={running || trainMut.isPending || !epochsOk(t)} onClick={() => setTrain(t)}>
                Huấn luyện lại {t === 'forecast' ? 'dự báo' : 'camera'}
              </button>
              {!epochsOk(t) && <p id={`${id}-ep-${t}-err`} className="field-error">Từ 1 đến 100</p>}
            </div>
          ))}
        </div>
        <p className="muted mt-2 text-xs">
          {running ? 'Đang có phiên huấn luyện chạy; danh sách tự cập nhật mỗi 10 giây.' : 'Huấn luyện chạy nền trên máy chủ và có thể mất vài phút.'}
        </p>
      </Section>

      <Section title="Phiên bản mô hình">
        {models.isLoading ? <Loading /> : models.error ? <ErrorState error={models.error} retry={models.refetch} /> : !models.data?.length ? <Empty text="Chưa có mô hình nào" /> : (
          <div className="overflow-x-auto">
            <table className="table">
              <caption className="sr-only">Danh sách phiên bản mô hình</caption>
              <thead><tr><th>Mô hình</th><th>Trạng thái</th><th>Huấn luyện</th><th>Chỉ số chính</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
              <tbody>{models.data.map((m) => (
                <tr key={m.id}>
                  <td>
                    <div className="font-medium">{m.name}</div>
                    <div className="muted num text-xs">{m.model_type} · {m.version}</div>
                    {m.trained_on_simulated && <DemoBadge />}
                  </td>
                  <td>
                    <span className="chip text-white" style={{ background: m.is_active ? RISK.LOW.color : RISK.NO_DATA.color }}>
                      {m.is_active ? 'Đang dùng' : MODEL_STATUS_VI[m.status] ?? m.status}
                    </span>
                  </td>
                  <td className="num whitespace-nowrap text-xs">{fmtDateTime(m.trained_at)}<div className="muted">{fmtNum(m.training_seconds, ' giây')}</div></td>
                  <td className="num text-xs"><KeyMetrics m={m} /></td>
                  <td className="whitespace-nowrap text-right">
                    <button className="btn-ghost" onClick={() => setDetail(m)}>Chi tiết</button>{' '}
                    {m.model_type !== 'BASELINE' && !m.is_active && (
                      <button className="btn-primary" disabled={activateMut.isPending} onClick={() => setActivate(m)}>Kích hoạt</button>
                    )}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Lịch sử huấn luyện" actions={runs.isFetching ? <span className="muted text-xs">Đang cập nhật…</span> : undefined}>
        {runs.isLoading ? <Loading /> : runs.error ? <ErrorState error={runs.error} retry={runs.refetch} /> : !runs.data?.length ? <Empty text="Chưa có phiên huấn luyện" /> : (
          <div className="overflow-x-auto">
            <table className="table">
              <caption className="sr-only">Lịch sử huấn luyện</caption>
              <thead><tr><th>#</th><th>Tác vụ</th><th>Trạng thái</th><th>Bắt đầu</th><th>Kết thúc</th><th>Tham số</th><th>Nhật ký</th></tr></thead>
              <tbody>{runs.data.map((r) => (
                <tr key={r.id}>
                  <td className="num">{r.id}</td>
                  <td>{TASK_VI[r.task] ?? r.task}</td>
                  <td>
                    <span className="chip text-white" style={{ background: r.status === 'SUCCESS' ? RISK.LOW.color : r.status === 'FAILED' ? RISK.HIGH.color : RISK.MEDIUM.color }}>
                      {RUN_STATUS_VI[r.status] ?? r.status}
                    </span>
                    {r.model_version_id && <div className="muted text-xs">Mô hình #{r.model_version_id}</div>}
                  </td>
                  <td className="num whitespace-nowrap">{fmtDateTime(r.started_at)}</td>
                  <td className="num whitespace-nowrap">{fmtDateTime(r.finished_at)}</td>
                  <td className="num text-xs">{r.params ? Object.entries(r.params).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ') : '—'}</td>
                  <td className="min-w-[200px]">
                    {r.log ? (
                      <details>
                        <summary className="cursor-pointer text-sm">Xem nhật ký</summary>
                        <pre className="mt-1 max-h-60 max-w-[480px] overflow-auto whitespace-pre-wrap rounded bg-black/5 p-2 text-xs dark:bg-white/5">{r.log}</pre>
                      </details>
                    ) : '—'}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Section>

      {detail && <DetailModal m={detail} onClose={() => setDetail(null)} />}
      {activate && (
        <Confirm title="Kích hoạt mô hình" confirmLabel="Kích hoạt" onClose={() => setActivate(null)}
          text={`Kích hoạt ${activate.name} ${activate.version}? Mô hình cùng nhóm đang dùng sẽ chuyển sang lưu trữ và các lần dự báo tiếp theo sẽ dùng mô hình này.`}
          onConfirm={async () => { await activateMut.mutateAsync(activate).catch(() => undefined) }} />
      )}
      {train && (
        <Confirm title="Huấn luyện lại" confirmLabel="Bắt đầu huấn luyện" onClose={() => setTrain(null)}
          text={`Bắt đầu huấn luyện lại ${TASK_VI[train]} với ${epochs[train]} epoch? Quá trình chạy nền và tốn tài nguyên máy chủ.`}
          onConfirm={async () => { await trainMut.mutateAsync(train).catch(() => undefined) }} />
      )}
    </div>
  )
}

function KeyMetrics({ m }: { m: ModelVersion }) {
  const x = m.metrics
  if (!x) return <span className="muted">—</span>
  if (isVision(m.model_type))
    return <>mask mAP50 {fmtDec(metric(x, 'mask_map50'))} · mAP50-95 {fmtDec(metric(x, 'mask_map50_95'))} · box mAP50 {fmtDec(metric(x, 'box_map50'))}<br />P {fmtDec(metric(x, 'precision'))} · R {fmtDec(metric(x, 'recall'))}</>
  if (x.heavy_rain)
    return <>Mưa MAE {fmtDec(metric(x, 'rainfall.mae'))} · RMSE {fmtDec(metric(x, 'rainfall.rmse'))}<br />Mưa to ≥5 mm/h: P {fmtDec(metric(x, 'heavy_rain.precision'))} · R {fmtDec(metric(x, 'heavy_rain.recall'))} · F1 {fmtDec(metric(x, 'heavy_rain.f1'))}</>
  return <>Mưa MAE {fmtDec(metric(x, 'rainfall.mae'))} · RMSE {fmtDec(metric(x, 'rainfall.rmse'))} · mực nước MAE {fmtDec(metric(x, 'water_level.mae'))}<br />
    P {fmtDec(metric(x, 'flood.precision'))} · R {fmtDec(metric(x, 'flood.recall'))} · F1 {fmtDec(metric(x, 'flood.f1'))} · Brier {fmtDec(metric(x, 'flood.brier'))} · AUC {fmtDec(metric(x, 'flood.roc_auc'))}</>
}

function DetailModal({ m, onClose }: { m: ModelVersion; onClose: () => void }) {
  const cm = (m.metrics?.flood as Metrics | undefined)?.confusion_matrix as Record<string, number> | undefined
  const perH = (k: string) => (m.metrics?.[k] as Metrics | undefined)?.per_horizon as Record<string, Metrics> | undefined
  const rainH = perH('rainfall')
  const wlH = perH('water_level')
  const hs = Object.keys(rainH ?? wlH ?? {}).sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)))
  return (
    <Modal title={`${m.name} ${m.version}`} onClose={onClose} wide>
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip bg-black/5 dark:bg-white/10">{m.model_type}</span>
          <span className="chip bg-black/5 dark:bg-white/10">{m.is_active ? 'Đang dùng' : MODEL_STATUS_VI[m.status] ?? m.status}</span>
          {m.trained_on_simulated && <DemoBadge />}
        </div>
        <dl className="num grid grid-cols-1 gap-2 sm:grid-cols-3">
          <div><dt className="muted text-xs">Huấn luyện lúc</dt><dd>{fmtDateTime(m.trained_at)}</dd></div>
          <div><dt className="muted text-xs">Thời gian huấn luyện</dt><dd>{fmtNum(m.training_seconds, ' giây')}</dd></div>
          <div><dt className="muted text-xs">Tạo lúc</dt><dd>{fmtDateTime(m.created_at)}</dd></div>
        </dl>
        {m.dataset_description && <p><span className="muted">Dữ liệu: </span>{m.dataset_description}</p>}
        <ModelMetrics type={m.model_type} metrics={m.metrics} />

        {hs.length > 0 && (
          <div className="overflow-x-auto">
            <h3 className="mb-1 font-medium">Sai số theo mốc dự báo</h3>
            <table className="table num">
              <thead><tr><th>Mốc</th><th>MAE mưa (mm)</th><th>RMSE mưa (mm)</th><th>MAE mực nước (cm)</th><th>RMSE mực nước (cm)</th></tr></thead>
              <tbody>{hs.map((h) => (
                <tr key={h}>
                  <td>+{h.slice(1)}h</td>
                  <td>{fmtDec(metric(rainH?.[h], 'mae'))}</td><td>{fmtDec(metric(rainH?.[h], 'rmse'))}</td>
                  <td>{fmtDec(metric(wlH?.[h], 'mae'))}</td><td>{fmtDec(metric(wlH?.[h], 'rmse'))}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}

        {cm && (
          <div>
            <h3 className="mb-1 font-medium">Ma trận nhầm lẫn (ngưỡng {fmtDec(metric(m.metrics, 'flood.threshold'), 2)})</h3>
            <table className="table num max-w-sm">
              <thead><tr><th><span className="sr-only">Thực tế</span></th><th>Dự báo ngập</th><th>Dự báo không ngập</th></tr></thead>
              <tbody>
                <tr><th scope="row">Thực tế ngập</th><td>{fmtNum(cm.tp)} (TP)</td><td>{fmtNum(cm.fn)} (FN)</td></tr>
                <tr><th scope="row">Thực tế không ngập</th><td>{fmtNum(cm.fp)} (FP)</td><td>{fmtNum(cm.tn)} (TN)</td></tr>
              </tbody>
            </table>
          </div>
        )}

        <details>
          <summary className="cursor-pointer font-medium">Toàn bộ chỉ số và tham số (JSON)</summary>
          <pre className="mt-2 max-h-80 overflow-auto rounded bg-black/5 p-3 text-xs dark:bg-white/5">
            {JSON.stringify({ metrics: m.metrics, params: m.params }, null, 2)}
          </pre>
        </details>
      </div>
    </Modal>
  )
}
