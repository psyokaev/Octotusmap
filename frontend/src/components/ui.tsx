import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import * as echarts from 'echarts'
import clsx from 'clsx'
import { RISK, riskOf } from '../lib/risk'

/* ------------------------------------------------------------------ toast */
type Toast = { id: number; kind: 'ok' | 'error' | 'info'; text: string }
const ToastCtx = createContext<(kind: Toast['kind'], text: string) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((kind: Toast['kind'], text: string) => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, kind, text }])
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 5000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} role="status"
            className={clsx('pointer-events-auto max-w-sm rounded-lg px-4 py-2.5 text-sm text-white shadow-lg',
              t.kind === 'ok' && 'bg-risk-low', t.kind === 'error' && 'bg-risk-high', t.kind === 'info' && 'bg-ink')}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => useContext(ToastCtx)

/* ------------------------------------------------------------------ modal / confirm */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('input,select,textarea,button')?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); prev?.focus() }
  }, [onClose])
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/40 p-4" onMouseDown={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className={clsx('panel max-h-[90vh] w-full overflow-auto p-5 shadow-xl', wide ? 'max-w-3xl' : 'max-w-lg')}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button className="btn-ghost px-2" onClick={onClose} aria-label="Đóng">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Confirm({ title, text, confirmLabel, danger, onConfirm, onClose }: {
  title: string; text: string; confirmLabel: string; danger?: boolean; onConfirm: () => void | Promise<void>; onClose: () => void
}) {
  const [busy, setBusy] = useState(false)
  return (
    <Modal title={title} onClose={onClose}>
      <p className="mb-5">{text}</p>
      <div className="flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Huỷ</button>
        <button className={danger ? 'btn-danger' : 'btn-primary'} disabled={busy}
          onClick={async () => { setBusy(true); try { await onConfirm(); onClose() } finally { setBusy(false) } }}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ states */
export const Skeleton = ({ className }: { className?: string }) => (
  <div className={clsx('animate-pulse rounded-md bg-black/10 dark:bg-white/10', className)} aria-hidden />
)
export function Loading({ rows = 4 }: { rows?: number }) {
  return <div className="space-y-2 p-2" aria-busy="true" aria-label="Đang tải">
    {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-6" />)}
  </div>
}
export function Empty({ text, action }: { text: string; action?: ReactNode }) {
  return <div className="muted flex flex-col items-center gap-3 p-8 text-center text-sm">{text}{action}</div>
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 p-6 text-center text-sm text-risk-high">
      <span>{error instanceof Error ? error.message : 'Không tải được dữ liệu'}</span>
      {retry && <button className="btn-ghost" onClick={retry}>Thử lại</button>}
    </div>
  )
}

/* ------------------------------------------------------------------ badges */
export function RiskBadge({ level, compact }: { level?: string | null; compact?: boolean }) {
  const r = RISK[riskOf(level)]
  return (
    <span className="chip text-white" style={{ background: r.color }} title={r.label}>
      <span aria-hidden>{r.symbol}</span>{compact ? null : r.label}
    </span>
  )
}
export const DemoBadge = ({ on = true }: { on?: boolean }) =>
  on ? <span className="chip border border-dashed border-current text-[#8a5a00] dark:text-amber-300"
    title="Dữ liệu sinh tự động phục vụ trình diễn, không phải quan trắc thật">Mô phỏng</span> : null

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: string }) {
  return (
    <div className="panel p-4">
      <div className="muted text-sm">{label}</div>
      <div className="num mt-1 text-2xl font-semibold" style={tone ? { color: tone } : undefined}>{value}</div>
      {hint && <div className="muted mt-1 text-xs">{hint}</div>}
    </div>
  )
}

/* ------------------------------------------------------------------ chart */
export function Chart({ option, height = 280, ariaLabel }: { option: echarts.EChartsCoreOption; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    if (!ref.current) return
    const dark = document.documentElement.classList.contains('dark')
    inst.current = echarts.init(ref.current, dark ? 'dark' : undefined, { renderer: 'canvas' })
    const ro = new ResizeObserver(() => inst.current?.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); inst.current?.dispose() }
  }, [])
  useEffect(() => {
    inst.current?.setOption({ backgroundColor: 'transparent', textStyle: { fontFamily: 'Google Sans, Roboto, Arial, sans-serif' },
      aria: { enabled: true }, ...option }, true)
  }, [option])
  return <div ref={ref} style={{ height }} role="img" aria-label={ariaLabel} />
}

/* ------------------------------------------------------------------ pagination */
export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className="flex items-center justify-between gap-2 px-1 py-2 text-sm">
      <span className="muted num">{total.toLocaleString('vi-VN')} bản ghi</span>
      <div className="flex items-center gap-2">
        <button className="btn-ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>Trước</button>
        <span className="num">Trang {page}/{pages}</span>
        <button className="btn-ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>Sau</button>
      </div>
    </div>
  )
}

export function SortTh({ label, col, sort, dir, onSort }: { label: string; col: string; sort: string; dir: 'asc' | 'desc'; onSort: (c: string) => void }) {
  const active = sort === col
  return (
    <th aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button className="font-semibold" onClick={() => onSort(col)}>{label} {active ? (dir === 'asc' ? '↑' : '↓') : ''}</button>
    </th>
  )
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}
