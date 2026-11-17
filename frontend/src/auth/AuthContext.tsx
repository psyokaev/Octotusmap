import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../lib/api'

export type Role = 'ADMIN' | 'OPERATOR' | 'USER'
export interface User {
  id: number
  username: string
  email: string
  full_name: string
  role_codes: Role[]
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

interface AuthState {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<User>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  hasRole: (...roles: Role[]) => boolean
  isStaff: boolean
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setUser(await api.get<User | null>('/auth/session'))
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const onExpired = () => setUser(null)
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [refresh])

  const login = async (username: string, password: string) => {
    const r = await api.post<{ user: User }>('/auth/login', { username, password })
    setUser(r.user)
    return r.user
  }
  const logout = async () => {
    await api.post('/auth/logout').catch(() => undefined)
    setUser(null)
  }
  const hasRole = (...roles: Role[]) => !!user && roles.some((r) => user.role_codes.includes(r))

  return (
    <Ctx.Provider value={{ user, loading, login, logout, refresh, hasRole, isStaff: hasRole('ADMIN', 'OPERATOR') }}>
      {children}
    </Ctx.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth ngoài AuthProvider')
  return c
}
