import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { api } from '../lib/api'
import { safeNext } from '../lib/format'
import { useToast } from '../components/ui'

const loginSchema = z.object({
  username: z.string().min(3, 'Nhập tên đăng nhập (tối thiểu 3 ký tự)'),
  password: z.string().min(1, 'Nhập mật khẩu'),
})
const registerSchema = z.object({
  username: z.string().regex(/^[a-zA-Z0-9_.]{3,50}$/, '3–50 ký tự: chữ, số, dấu chấm, gạch dưới'),
  email: z.string().email('Email không hợp lệ'),
  full_name: z.string().max(120).optional(),
  password: z.string().min(10, 'Tối thiểu 10 ký tự').regex(/(?=.*\d)(?=.*[a-zA-Z])/, 'Cần cả chữ và số'),
})

export default function LoginPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState('')
  const { login } = useAuth()
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const toast = useToast()
  const lf = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) })
  const rf = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema) })

  const next = safeNext(sp.get('next'))

  return (
    <div className="flex min-h-full items-center justify-center bg-ink p-4">
      <div className="panel w-full max-w-sm p-6 shadow-2xl">
        <Link to="/" className="mb-1 flex items-center gap-2 text-lg font-semibold">
          <img src="/logo-dark.png" alt="" width="36" height="36" className="dark:invert" />
          OctotusMap
        </Link>
        <div className="mb-5" />

        {mode === 'login' ? (
          <form noValidate onSubmit={lf.handleSubmit(async (v) => {
            setError('')
            try {
              const u = await login(v.username, v.password)
              const staff = u.role_codes.some((r) => r === 'ADMIN' || r === 'OPERATOR')
              nav(next ?? (staff ? '/dashboard' : '/'), { replace: true })
            } catch (e) { setError((e as Error).message) }
          })}>
            <label className="label" htmlFor="username">Tên đăng nhập</label>
            <input id="username" className="input" autoComplete="username" {...lf.register('username')} />
            {lf.formState.errors.username && <p className="field-error">{lf.formState.errors.username.message}</p>}
            <label className="label mt-3" htmlFor="password">Mật khẩu</label>
            <input id="password" type="password" className="input" autoComplete="current-password" {...lf.register('password')} />
            {lf.formState.errors.password && <p className="field-error">{lf.formState.errors.password.message}</p>}
            {error && <p role="alert" className="mt-3 text-sm text-risk-high">{error}</p>}
            <button className="btn-primary mt-5 w-full" disabled={lf.formState.isSubmitting}>
              {lf.formState.isSubmitting ? 'Đang đăng nhập…' : 'Đăng nhập'}
            </button>
          </form>
        ) : (
          <form noValidate onSubmit={rf.handleSubmit(async (v) => {
            setError('')
            try {
              await api.post('/auth/register', v)
              toast('ok', 'Đã tạo tài khoản. Hãy đăng nhập.')
              setMode('login')
              lf.setValue('username', v.username)
            } catch (e) { setError((e as Error).message) }
          })}>
            {(['username', 'email', 'full_name', 'password'] as const).map((k) => (
              <div key={k} className="mb-3">
                <label className="label" htmlFor={`r-${k}`}>
                  {{ username: 'Tên đăng nhập', email: 'Email', full_name: 'Họ tên', password: 'Mật khẩu' }[k]}
                </label>
                <input id={`r-${k}`} className="input" type={k === 'password' ? 'password' : k === 'email' ? 'email' : 'text'}
                  autoComplete={k === 'password' ? 'new-password' : undefined} {...rf.register(k)} />
                {rf.formState.errors[k] && <p className="field-error">{rf.formState.errors[k]?.message}</p>}
              </div>
            ))}
            {error && <p role="alert" className="text-sm text-risk-high">{error}</p>}
            <button className="btn-primary mt-2 w-full" disabled={rf.formState.isSubmitting}>Tạo tài khoản</button>
          </form>
        )}
        <div className="mt-4 flex justify-between text-sm">
          <button className="text-water" onClick={() => { setError(''); setMode(mode === 'login' ? 'register' : 'login') }}>
            {mode === 'login' ? 'Tạo tài khoản người dân' : 'Đã có tài khoản? Đăng nhập'}
          </button>
          <Link to="/" className="muted">Xem bản đồ công khai</Link>
        </div>
      </div>
    </div>
  )
}
