// HTTP client: cookie httpOnly (same-origin qua Vite proxy) + chuẩn hoá lỗi từ backend
export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>

export function qs(params?: Params): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)))
    else sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  const isForm = body instanceof FormData
  const res = await fetch(`/api/v1${path}${qs(params)}`, {
    method,
    credentials: 'same-origin',
    headers: body && !isForm ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const e = data?.error
    if (res.status === 401) window.dispatchEvent(new Event('auth:expired'))
    throw new ApiError(res.status, e?.code ?? 'HTTP_ERROR', e?.message ?? `Lỗi ${res.status}`, e?.details)
  }
  return data as T
}

export const api = {
  get: <T,>(path: string, params?: Params) => request<T>('GET', path, undefined, params),
  post: <T,>(path: string, body?: unknown, params?: Params) => request<T>('POST', path, body, params),
  patch: <T,>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  put: <T,>(path: string, body?: unknown) => request<T>('PUT', path, body),
  del: <T,>(path: string) => request<T>('DELETE', path),
}

/** Tải file (Excel/CSV) qua fetch để giữ cookie và báo lỗi rõ ràng. */
export async function download(path: string, params?: Params): Promise<string> {
  const res = await fetch(`/api/v1${path}${qs(params)}`, { credentials: 'same-origin' })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, data?.error?.code ?? 'HTTP_ERROR', data?.error?.message ?? 'Xuất tệp thất bại')
  }
  const cd = res.headers.get('Content-Disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? 'bao_cao'
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return name
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  size: number
}
