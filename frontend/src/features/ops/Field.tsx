import type { ReactNode } from 'react'
import { useAreas } from './lib'

/** Nhãn + ô nhập + lỗi. `id` phải trùng id của control con. */
export function Field({ id, label, error, hint, children, className }: {
  id: string; label: string; error?: string; hint?: string; children: ReactNode; className?: string
}) {
  return (
    <div className={className}>
      <label className="label" htmlFor={id}>{label}</label>
      {children}
      {hint && !error && <p className="muted mt-1 text-xs">{hint}</p>}
      {error && <p className="field-error" role="alert">{error}</p>}
    </div>
  )
}

export function AreaSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const areas = useAreas()
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Tất cả khu vực</option>
      {areas.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
  )
}

export function FormActions({ busy, onCancel, label = 'Lưu' }: { busy: boolean; onCancel: () => void; label?: string }) {
  return (
    <div className="mt-5 flex justify-end gap-2">
      <button type="button" className="btn-ghost" onClick={onCancel}>Huỷ</button>
      <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Đang lưu…' : label}</button>
    </div>
  )
}
