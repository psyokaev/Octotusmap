import { useEffect, useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { api } from '../../lib/api'

export interface SearchResult { type: string; id?: number; label: string; sub?: string; lat: number; lon: number }

const TYPE: Record<string, string> = {
  area: 'Khu vực', station: 'Điểm đo', camera: 'Camera', flood_point: 'Điểm ngập', address: 'Địa chỉ', coordinate: 'Toạ độ',
}

/** Ô tìm địa điểm có autocomplete; dùng cho thanh tìm kiếm và 2 ô điểm đi/điểm đến. */
export function PlaceSearch({ value, label, placeholder, className, onPick }: {
  value?: string; label: string; placeholder: string; className?: string; onPick: (r: SearchResult) => void
}) {
  const listId = useId()
  const [q, setQ] = useState(value ?? '')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  useEffect(() => { setQ(value ?? '') }, [value])
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 350); return () => clearTimeout(t) }, [q])
  const r = useQuery({
    queryKey: ['search', debounced], enabled: open && debounced.length >= 2,
    queryFn: () => api.get<{ results: SearchResult[]; attribution: string }>('/search', { q: debounced }),
  })
  const items = r.data?.results ?? []
  const pick = (x: SearchResult) => { onPick(x); setOpen(false); setQ(x.label) }
  return (
    <div className="relative">
      <input className={clsx('input', className)} placeholder={placeholder} value={q} role="combobox"
        aria-expanded={open && debounced.length >= 2} aria-controls={listId} aria-autocomplete="list" aria-label={label}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0) }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          if (e.key === 'Enter' && items[active]) pick(items[active])
          if (e.key === 'Escape') setOpen(false)
        }} />
      {open && debounced.length >= 2 && (
        <ul id={listId} role="listbox" className="panel absolute z-30 mt-1 max-h-80 w-full overflow-auto shadow-xl">
          {r.isFetching && <li className="muted px-3 py-2 text-sm">Đang tìm…</li>}
          {!r.isFetching && !items.length && <li className="muted px-3 py-2 text-sm">Không tìm thấy “{debounced}”</li>}
          {items.map((x, i) => (
            <li key={`${x.type}-${x.id ?? i}-${x.label}`} role="option" aria-selected={i === active}>
              <button className={clsx('block w-full px-3 py-2 text-left text-sm', i === active && 'bg-water/10')}
                onMouseDown={(e) => { e.preventDefault(); pick(x) }}>
                <span className="muted mr-2 text-xs">{TYPE[x.type] ?? x.type}</span>{x.label}
              </button>
            </li>
          ))}
          {items.some((x) => x.type === 'address') && <li className="muted px-3 py-1 text-[10px]">{r.data?.attribution}</li>}
        </ul>
      )}
    </div>
  )
}
