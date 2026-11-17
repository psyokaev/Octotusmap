import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useAuth, type Role } from '../auth/AuthContext'
import { api } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import { useCameraEnabled } from '../lib/health'
import { useToast } from './ui'

const NAV: { to: string; label: string; roles?: Role[] }[] = [
  { to: '/', label: 'Bản đồ' },
  { to: '/alerts', label: 'Cảnh báo' },
  { to: '/forecasts', label: 'Dự báo AI' },
  { to: '/history', label: 'Lịch sử ngập' },
  { to: '/dashboard', label: 'Tổng quan', roles: ['ADMIN', 'OPERATOR'] },
  { to: '/statistics', label: 'Thống kê', roles: ['ADMIN', 'OPERATOR'] },
  { to: '/stations', label: 'Trạm quan trắc', roles: ['ADMIN', 'OPERATOR'] },
  { to: '/cameras', label: 'Camera', roles: ['ADMIN', 'OPERATOR'] },
  { to: '/models', label: 'Mô hình AI', roles: ['ADMIN'] },
  { to: '/users', label: 'Tài khoản', roles: ['ADMIN'] },
  { to: '/settings', label: 'Cấu hình', roles: ['ADMIN'] },
]

export function useDarkMode() {
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem('theme') === 'dark' } catch { return false }
  })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try { localStorage.setItem('theme', dark ? 'dark' : 'light') } catch { /* chế độ riêng tư */ }
  }, [dark])
  return [dark, setDark] as const
}

interface NotifList { items: { id: number; title: string; body: string; is_read: boolean; created_at: string; alert_id: number | null }[]; unread: number }

function Notifications() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['notifications'], queryFn: () => api.get<NotifList>('/notifications', { size: 15 }),
    refetchInterval: 60_000 })
  return (
    <div className="relative">
      <button className="btn-ghost relative border-white/20 text-white" aria-label={`Thông báo, ${q.data?.unread ?? 0} chưa đọc`}
        onClick={() => setOpen(!open)}>
        Thông báo
        {!!q.data?.unread && <span className="num rounded-full bg-risk-high px-1.5 text-xs">{q.data.unread}</span>}
      </button>
      {open && (
        <div className="panel absolute right-0 z-50 mt-2 w-80 overflow-hidden text-[var(--text)] shadow-xl">
          <div className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
            <span className="font-semibold">Thông báo</span>
            <button className="text-sm text-water" onClick={async () => {
              await api.post('/notifications/read-all'); qc.invalidateQueries({ queryKey: ['notifications'] })
            }}>Đánh dấu đã đọc</button>
          </div>
          <ul className="max-h-96 overflow-auto">
            {q.data?.items.length ? q.data.items.map((n) => (
              <li key={n.id}>
                <button className={clsx('block w-full px-3 py-2 text-left text-sm hover:bg-black/5', !n.is_read && 'font-semibold')}
                  onClick={async () => {
                    await api.post(`/notifications/${n.id}/read`)
                    qc.invalidateQueries({ queryKey: ['notifications'] })
                    setOpen(false)
                    if (n.alert_id) nav(`/alerts?open=${n.alert_id}`)
                  }}>
                  <div>{n.title}</div>
                  <div className="muted text-xs font-normal">{fmtDateTime(n.created_at)}</div>
                </button>
              </li>
            )) : <li className="muted p-4 text-sm">Chưa có thông báo</li>}
          </ul>
        </div>
      )}
    </div>
  )
}

/** Lắng nghe SSE: làm mới dữ liệu khi có chu kỳ dự báo/cảnh báo mới. */
function useLiveEvents() {
  const qc = useQueryClient()
  const toast = useToast()
  useEffect(() => {
    const es = new EventSource('/api/v1/events')
    es.addEventListener('cycle', () => qc.invalidateQueries())
    es.addEventListener('report', () => {
      qc.invalidateQueries({ queryKey: ['reports'] })
      qc.invalidateQueries({ queryKey: ['route'] })
    })
    es.addEventListener('alert', (e) => {
      const d = JSON.parse((e as MessageEvent).data)
      if (d.type === 'CREATED') toast('info', `Cảnh báo mới mức ${d.level}: ${d.area}`)
      qc.invalidateQueries({ queryKey: ['alerts'] })
      qc.invalidateQueries({ queryKey: ['notifications'] })
      qc.invalidateQueries({ queryKey: ['features'] })
    })
    return () => es.close()
  }, [qc, toast])
}

export function TopBar({ dark, setDark }: { dark: boolean; setDark: (v: boolean) => void }) {
  const { user, logout, hasRole } = useAuth()
  const nav = useNavigate()
  const [menu, setMenu] = useState(false)
  const cameraEnabled = useCameraEnabled()
  useLiveEvents()
  return (
    <header className="relative z-40 flex h-14 items-center gap-3 bg-ink px-3 text-white">
      <button className="btn px-2 xl:hidden" aria-label="Mở menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>☰</button>
      <NavLink to="/" className="flex items-center gap-2 font-semibold">
        <img src="/logo-white.png" alt="" width="30" height="30" />
        <span className="hidden whitespace-nowrap sm:inline">OctotusMap</span>
      </NavLink>
      <nav aria-label="Điều hướng chính"
        className={clsx('xl:static xl:flex xl:min-w-0 xl:flex-row xl:overflow-x-auto xl:bg-transparent xl:p-0',
          menu ? 'absolute left-0 right-0 top-14 flex flex-col bg-ink p-2' : 'hidden')}>
        {NAV.filter((n) => (!n.roles || hasRole(...n.roles)) && (n.to !== '/cameras' || cameraEnabled)).map((n) => (
          <NavLink key={n.to} to={n.to} end onClick={() => setMenu(false)}
            className={({ isActive }) => clsx('whitespace-nowrap rounded-md px-2 py-1.5 text-sm', isActive ? 'bg-white/15' : 'text-white/80 hover:text-white')}>
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="ml-auto flex shrink-0 items-center gap-2 whitespace-nowrap">
        <button className="btn-ghost border-white/20 px-2 text-white" onClick={() => setDark(!dark)}
          aria-label={dark ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối'}>{dark ? '☀' : '☾'}</button>
        {user ? (
          <>
            {user && <Notifications />}
            <span className="hidden whitespace-nowrap text-sm 2xl:inline" title={user.role_codes.join(', ')}>{user.full_name || user.username}</span>
            <button className="btn-ghost border-white/20 text-white" onClick={async () => { await logout(); nav('/') }}>Đăng xuất</button>
          </>
        ) : (
          <NavLink to="/login" className="btn-primary">Đăng nhập</NavLink>
        )}
      </div>
    </header>
  )
}

export function AppLayout() {
  const [dark, setDark] = useDarkMode()
  return (
    <div className="flex h-full flex-col">
      <TopBar dark={dark} setDark={setDark} />
      <main className="flex-1 overflow-auto p-4 md:p-6"><div className="mx-auto max-w-7xl"><Outlet /></div></main>
    </div>
  )
}

export function MapLayout() {
  const [dark, setDark] = useDarkMode()
  return (
    <div className="flex h-full flex-col">
      <TopBar dark={dark} setDark={setDark} />
      <main className="relative flex-1 overflow-hidden"><Outlet context={{ dark }} /></main>
    </div>
  )
}
