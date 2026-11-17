import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api, type Page } from '../lib/api'
import { fmtDateTime, fmtPct } from '../lib/format'
import { Confirm, DemoBadge, Empty, ErrorState, Loading, Modal, PageHeader, Pager } from '../components/ui'
import { Field, FormActions } from '../features/ops/Field'
import { fileSchema, formData, num, reqNum, useAction, type Area } from '../features/ops/lib'

interface Detection {
  id: number; camera_id: number | null; detected_at: string; method: string; flood_ratio: number; confidence: number
  num_regions: number; is_simulated: boolean; image_url: string; result_image_url: string
  details?: { trained_on_simulated?: boolean } | null
}
type CamStatus = 'ACTIVE' | 'INACTIVE' | 'MAINTENANCE'
interface Camera {
  id: number; code: string; name: string; latitude: number; longitude: number; stream_url: string; status: CamStatus
  is_public: boolean; retention_days: number; area: Area | null; source: { is_simulated: boolean; name: string }
  latest_detection: Detection | null
}

const STATUS_VI: Record<CamStatus, string> = { ACTIVE: 'Hoạt động', INACTIVE: 'Ngừng', MAINTENANCE: 'Bảo trì' }
const methodVi = (m: string) => (m === 'HEURISTIC' ? 'Heuristic (ngưỡng màu – không phải YOLO)' : m === 'YOLOV8_SEG' ? 'YOLOv8-seg' : m)

type Dialog = { kind: 'form'; cam?: Camera } | { kind: 'delete' | 'detections'; cam: Camera } | { kind: 'analyze' } | null

export default function CamerasPage() {
  const act = useAction()
  const [dlg, setDlg] = useState<Dialog>(null)
  const close = useCallback(() => setDlg(null), []) // ổn định để Modal không lấy lại focus mỗi lần render
  const list = useQuery({ queryKey: ['cameras'], queryFn: () => api.get<Camera[]>('/cameras') })

  return (
    <div>
      <PageHeader title="Camera giám sát">
        <button className="btn-ghost" onClick={() => setDlg({ kind: 'analyze' })}>Phân tích ảnh</button>
        <button className="btn-primary" onClick={() => setDlg({ kind: 'form' })}>Thêm camera</button>
      </PageHeader>
      <p className="muted mb-4 text-sm">
        Camera có nhãn Mô phỏng dùng khung hình mô phỏng được sinh định kỳ, không phải video trực tiếp. Kết quả nhận dạng chỉ mang tính tham khảo.
      </p>

      {list.isLoading ? <Loading rows={6} /> : list.isError ? <ErrorState error={list.error} retry={() => list.refetch()} />
        : !list.data?.length ? <div className="panel"><Empty text="Chưa có camera nào." /></div>
        : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {list.data.map((c) => {
              const d = c.latest_detection
              return (
                <article key={c.id} className="panel flex flex-col overflow-hidden">
                  {d ? <img src={d.result_image_url} alt={`Kết quả nhận dạng ngập gần nhất của camera ${c.code}`} className="aspect-video w-full bg-black/10 object-cover" loading="lazy" />
                    : <div className="muted flex aspect-video items-center justify-center bg-black/5 text-sm">Chưa có ảnh phân tích</div>}
                  <div className="flex flex-1 flex-col gap-2 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold">{c.code} – {c.name}</h2>
                      {c.source.is_simulated && <DemoBadge />}
                    </div>
                    <p className="muted text-sm">
                      {STATUS_VI[c.status] ?? c.status} · {c.is_public ? 'Công khai' : 'Nội bộ'} · {c.area?.name ?? 'Chưa gán khu vực'} · lưu {c.retention_days} ngày
                    </p>
                    {d ? (
                      <dl className="grid grid-cols-2 gap-x-3 text-sm">
                        <dt className="muted">Tỉ lệ ngập</dt><dd className="num font-semibold">{fmtPct(d.flood_ratio)}</dd>
                        <dt className="muted">Độ tin cậy</dt><dd className="num">{fmtPct(d.confidence)}</dd>
                        <dt className="muted">Phương pháp</dt><dd>{methodVi(d.method)}</dd>
                        <dt className="muted">Thời điểm</dt><dd className="num">{fmtDateTime(d.detected_at)}</dd>
                      </dl>
                    ) : <p className="muted text-sm">Chưa có kết quả nhận dạng.</p>}
                    <div className="mt-auto flex flex-wrap gap-1 pt-2">
                      <button className="btn-ghost" onClick={() => setDlg({ kind: 'detections', cam: c })}>Lịch sử nhận dạng</button>
                      <button className="btn-ghost" onClick={() => setDlg({ kind: 'form', cam: c })}>Sửa</button>
                      <button className="btn-ghost text-risk-high" onClick={() => setDlg({ kind: 'delete', cam: c })}>Xoá</button>
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        )}

      {dlg?.kind === 'form' && <CameraForm cam={dlg.cam} onClose={close} />}
      {dlg?.kind === 'analyze' && <AnalyzeModal cameras={list.data ?? []} onClose={close} />}
      {dlg?.kind === 'detections' && <DetectionsModal cam={dlg.cam} onClose={close} />}
      {dlg?.kind === 'delete' && (
        <Confirm title="Xoá camera" danger confirmLabel="Xoá camera" onClose={close}
          text={`Xoá camera ${dlg.cam.code} – ${dlg.cam.name}? Camera sẽ bị ẩn khỏi hệ thống (xoá mềm).`}
          onConfirm={async () => { await act(() => api.del(`/cameras/${dlg.cam.id}`), 'Đã xoá camera', ['cameras']) }} />
      )}
    </div>
  )
}

const camSchema = z.object({
  code: z.string().min(2, 'Tối thiểu 2 ký tự').max(30).regex(/^[A-Za-z0-9_-]+$/, 'Chỉ gồm chữ, số, "_" và "-"'),
  name: z.string().trim().min(2, 'Tối thiểu 2 ký tự').max(150),
  latitude: reqNum(num().min(-90, 'Vĩ độ từ -90 đến 90').max(90, 'Vĩ độ từ -90 đến 90')),
  longitude: reqNum(num().min(-180, 'Kinh độ từ -180 đến 180').max(180, 'Kinh độ từ -180 đến 180')),
  stream_url: z.string().trim().max(500).refine((v) => !v || /^(https?|rtsp):\/\//.test(v), 'URL phải bắt đầu bằng http://, https:// hoặc rtsp://'),
  status: z.enum(['ACTIVE', 'INACTIVE', 'MAINTENANCE']),
  is_public: z.boolean(),
  retention_days: reqNum(num().int('Phải là số nguyên').min(1, 'Từ 1 đến 365 ngày').max(365, 'Từ 1 đến 365 ngày')),
})

function CameraForm({ cam, onClose }: { cam?: Camera; onClose: () => void }) {
  const act = useAction()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof camSchema>>({
    resolver: zodResolver(camSchema),
    defaultValues: cam ?? { code: '', name: '', stream_url: '', status: 'ACTIVE', is_public: false, retention_days: 30 },
  })
  const submit = handleSubmit(async (v) => {
    const ok = cam
      ? await act(() => api.patch(`/cameras/${cam.id}`, { ...v, code: undefined }), 'Đã cập nhật camera', ['cameras'])
      : await act(() => api.post('/cameras', v), 'Đã thêm camera', ['cameras'])
    if (ok) onClose()
  })
  const input = (k: 'code' | 'name' | 'latitude' | 'longitude' | 'stream_url' | 'retention_days', label: string, type = 'text') => (
    <Field id={`cf-${k}`} label={label} error={errors[k]?.message} className={k === 'stream_url' ? 'sm:col-span-2' : undefined}>
      <input id={`cf-${k}`} className="input" type={type} step="any" readOnly={k === 'code' && !!cam} {...register(k)} />
    </Field>
  )
  return (
    <Modal title={cam ? `Sửa camera ${cam.code}` : 'Thêm camera'} onClose={onClose} wide>
      <form noValidate onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        {input('code', 'Mã camera')}
        {input('name', 'Tên camera')}
        {input('latitude', 'Vĩ độ', 'number')}
        {input('longitude', 'Kinh độ', 'number')}
        {input('stream_url', 'URL nguồn (http(s):// hoặc rtsp://, có thể để trống)')}
        <Field id="cf-status" label="Trạng thái" error={errors.status?.message}>
          <select id="cf-status" className="input" {...register('status')}>
            {Object.entries(STATUS_VI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        {input('retention_days', 'Số ngày lưu ảnh (1–365)', 'number')}
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" {...register('is_public')} /> Công khai cho người dân
        </label>
        <div className="sm:col-span-2"><FormActions busy={isSubmitting} onCancel={onClose} /></div>
      </form>
    </Modal>
  )
}

const analyzeSchema = z.object({ file: fileSchema(['.jpg', '.jpeg', '.png'], 10), camera_id: z.string() })

function AnalyzeModal({ cameras, onClose }: { cameras: Camera[]; onClose: () => void }) {
  const act = useAction()
  const [res, setRes] = useState<Detection | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof analyzeSchema>>({
    resolver: zodResolver(analyzeSchema), defaultValues: { camera_id: '' },
  })
  return (
    <Modal title="Phân tích ảnh ngập" onClose={onClose} wide>
      <form noValidate className="grid gap-3 sm:grid-cols-2" onSubmit={handleSubmit(async (v) => {
        await act(async () => setRes(await api.post<Detection>('/cameras/analyze', formData({ file: v.file[0], camera_id: v.camera_id }))),
          'Đã phân tích ảnh', ['cameras', 'detections'])
      })}>
        <Field id="an-file" label="Ảnh (.jpg, .png)" error={errors.file?.message}>
          <input id="an-file" type="file" accept=".jpg,.jpeg,.png" className="input" {...register('file')} />
        </Field>
        <Field id="an-cam" label="Gắn với camera (tuỳ chọn)">
          <select id="an-cam" className="input" {...register('camera_id')}>
            <option value="">Không gắn camera</option>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.code} – {c.name}</option>)}
          </select>
          <p className="muted mt-1 text-xs">Chọn camera để kết quả đưa vào cảnh báo; ảnh không gắn camera chỉ để xem thử.</p>
        </Field>
        <div className="sm:col-span-2"><button className="btn-primary" disabled={isSubmitting}>{isSubmitting ? 'Đang phân tích…' : 'Phân tích'}</button></div>
      </form>
      {res && (
        <div className="mt-4" role="status">
          <div className="grid gap-3 sm:grid-cols-2">
            <figure><img src={res.image_url} alt="Ảnh đầu vào" className="w-full rounded-lg" /><figcaption className="muted mt-1 text-xs">Ảnh đầu vào</figcaption></figure>
            <figure><img src={res.result_image_url} alt="Ảnh kết quả với vùng ngập được tô màu" className="w-full rounded-lg" /><figcaption className="muted mt-1 text-xs">Vùng ngập phát hiện</figcaption></figure>
          </div>
          <p className="mt-2 text-sm">
            Tỉ lệ ngập <b className="num">{fmtPct(res.flood_ratio)}</b> · độ tin cậy <span className="num">{fmtPct(res.confidence)}</span> · {res.num_regions} vùng · phương pháp <b>{methodVi(res.method)}</b>
          </p>
          {res.details?.trained_on_simulated && <p className="muted text-xs">Mô hình huấn luyện trên ảnh mô phỏng, kết quả chỉ để tham khảo.</p>}
          {res.method === 'HEURISTIC' && <p className="muted text-xs">Chưa có trọng số YOLO đã huấn luyện nên hệ thống dùng phương pháp heuristic dự phòng; kết quả kém tin cậy hơn.</p>}
        </div>
      )}
    </Modal>
  )
}

function DetectionsModal({ cam, onClose }: { cam: Camera; onClose: () => void }) {
  const [page, setPage] = useState(1)
  const q = useQuery({ queryKey: ['detections', cam.id, page], queryFn: () => api.get<Page<Detection>>(`/cameras/${cam.id}/detections`, { page, size: 10 }) })
  return (
    <Modal title={`Lịch sử nhận dạng · ${cam.code}`} onClose={onClose} wide>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} retry={() => q.refetch()} />
        : !q.data?.items.length ? <Empty text="Chưa có kết quả nhận dạng." />
        : (
          <div className="overflow-x-auto">
            <table className="table min-w-[560px]">
              <thead><tr><th>Ảnh</th><th>Thời điểm</th><th className="text-right">Tỉ lệ ngập</th><th className="text-right">Tin cậy</th><th>Phương pháp</th></tr></thead>
              <tbody>
                {q.data.items.map((d) => (
                  <tr key={d.id}>
                    <td><a href={d.result_image_url} target="_blank" rel="noreferrer"><img src={d.result_image_url} alt={`Kết quả lúc ${fmtDateTime(d.detected_at)}`} className="h-12 w-20 rounded object-cover" loading="lazy" /></a></td>
                    <td className="num">{fmtDateTime(d.detected_at)} {d.is_simulated && <DemoBadge />}</td>
                    <td className="num text-right">{fmtPct(d.flood_ratio)}</td>
                    <td className="num text-right">{fmtPct(d.confidence)}</td>
                    <td>{methodVi(d.method)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {q.data && <Pager page={page} size={q.data.size} total={q.data.total} onPage={setPage} />}
    </Modal>
  )
}
