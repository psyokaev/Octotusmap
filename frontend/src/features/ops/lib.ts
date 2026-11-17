import { useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api, ApiError } from '../../lib/api'
import { useToast } from '../../components/ui'

export interface Area { id: number; code: string; name: string; level: string }
export interface ImportReport { total_rows: number; inserted: number; duplicates: number; rejected: number; errors: string[] }

/** Thông báo lỗi kèm chi tiết validation (422: [{loc, msg}] hoặc danh sách chuỗi). */
export function errText(e: unknown): string {
  if (!(e instanceof Error)) return 'Đã có lỗi xảy ra'
  const parts = errDetails(e)
  return parts.length ? `${e.message} — ${parts.join('; ')}` : e.message
}
export function errDetails(e: unknown): string[] {
  const d = e instanceof ApiError && Array.isArray(e.details) ? e.details : []
  return d.map((x: unknown) => {
    if (typeof x === 'string') return x
    const o = x as { loc?: (string | number)[]; msg?: string }
    return `${(o.loc ?? []).filter((p) => p !== 'body').join('.')}: ${o.msg ?? ''}`
  })
}

export const useAreas = () =>
  useQuery({ queryKey: ['areas'], queryFn: () => api.get<Area[]>('/gis/areas'), staleTime: 5 * 60_000 })

/** Chạy một thao tác ghi: toast kết quả + invalidate các query liên quan. Trả về true nếu thành công. */
export function useAction() {
  const toast = useToast()
  const qc = useQueryClient()
  return async (fn: () => Promise<unknown>, ok: string, keys: string[] = []): Promise<boolean> => {
    try {
      await fn()
      toast('ok', ok)
      keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
      return true
    } catch (e) {
      toast('error', errText(e))
      return false
    }
  }
}

/** z.number() với thông báo tiếng Việt (NaN -> "Phải là số"). */
export const num = () => z.number({ required_error: 'Bắt buộc nhập', invalid_type_error: 'Phải là số' })
const toNum = (v: unknown) => (v === '' || v === null || v === undefined ? undefined : Number(v))
/** Số bắt buộc từ ô input. */
export const reqNum = (s: z.ZodNumber) => z.preprocess(toNum, s)
/** Số tuỳ chọn từ ô input (chuỗi rỗng -> undefined). */
export const optNum = (s: z.ZodNumber) => z.preprocess(toNum, s.optional())

/** Ô input type=date (ngày giờ VN) -> ISO UTC; `end` = đầu ngày hôm sau (khoảng [from, to)). */
export function vnDateToIso(d: string, end = false): string | undefined {
  if (!d) return undefined
  const t = new Date(`${d}T00:00:00+07:00`).getTime() + (end ? 86_400_000 : 0)
  return new Date(t).toISOString()
}

/** Ô chọn tệp (FileList) với đuôi cho phép và dung lượng tối đa. */
export const fileSchema = (exts: string[], maxMb: number) =>
  z.custom<FileList>((v) => v instanceof FileList && v.length > 0, 'Chọn một tệp')
    .refine((f) => exts.some((x) => f[0].name.toLowerCase().endsWith(x)), `Chỉ chấp nhận ${exts.join(', ')}`)
    .refine((f) => f[0].size <= maxMb * 1024 * 1024, `Tệp tối đa ${maxMb} MB`)

export const formData = (fields: Record<string, string | Blob | number | null | undefined>) => {
  const fd = new FormData()
  for (const [k, v] of Object.entries(fields)) if (v !== null && v !== undefined && v !== '') fd.append(k, typeof v === 'number' ? String(v) : v)
  return fd
}

export const WEIGHT_VI: Record<string, string> = {
  flood_probability: 'Xác suất ngập (mô hình)', rainfall: 'Lượng mưa', water_level: 'Mực nước', camera: 'Camera', history: 'Lịch sử ngập',
}
