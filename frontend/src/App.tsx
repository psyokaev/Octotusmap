import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth, type Role } from './auth/AuthContext'
import { AppLayout, MapLayout } from './components/Layout'
import { Loading } from './components/ui'
import LoginPage from './pages/LoginPage'
import MapPage from './pages/MapPage'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const StatisticsPage = lazy(() => import('./pages/StatisticsPage'))
const StationsPage = lazy(() => import('./pages/StationsPage'))
const CamerasPage = lazy(() => import('./pages/CamerasPage'))
const ForecastsPage = lazy(() => import('./pages/ForecastsPage'))
const AlertsPage = lazy(() => import('./pages/AlertsPage'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const ModelsPage = lazy(() => import('./pages/ModelsPage'))
const UsersPage = lazy(() => import('./pages/UsersPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

/** Bảo vệ route phía giao diện; quyền thật được kiểm tra ở backend (RBAC). */
export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading, hasRole } = useAuth()
  const loc = useLocation()
  if (loading) return <Loading />
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  if (!hasRole(...roles))
    return <div role="alert" className="panel p-6">Tài khoản của bạn không có quyền truy cập trang này.</div>
  return <>{children}</>
}

const staff: Role[] = ['ADMIN', 'OPERATOR']
const admin: Role[] = ['ADMIN']

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route element={<MapLayout />}>
            <Route path="/" element={<MapPage />} />
          </Route>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AppLayout />}>
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/forecasts" element={<ForecastsPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/dashboard" element={<RequireRole roles={staff}><DashboardPage /></RequireRole>} />
            <Route path="/statistics" element={<RequireRole roles={staff}><StatisticsPage /></RequireRole>} />
            <Route path="/stations" element={<RequireRole roles={staff}><StationsPage /></RequireRole>} />
            <Route path="/cameras" element={<RequireRole roles={staff}><CamerasPage /></RequireRole>} />
            <Route path="/models" element={<RequireRole roles={admin}><ModelsPage /></RequireRole>} />
            <Route path="/users" element={<RequireRole roles={admin}><UsersPage /></RequireRole>} />
            <Route path="/settings" element={<RequireRole roles={admin}><SettingsPage /></RequireRole>} />
            <Route path="*" element={<div className="panel p-6">Không tìm thấy trang. <a className="text-water" href="/">Về bản đồ</a></div>} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
