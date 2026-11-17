import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useForm, type UseFormRegisterReturn } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { api, type Page } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import { useAuth, type User } from '../auth/AuthContext'
import { Confirm, Empty, ErrorState, Loading, Modal, PageHeader, Pager } from '../components/ui'
import { Field, FormActions } from '../features/ops/Field'
import { useAction } from '../features/ops/lib'

const ROLE_VI = { ADMIN: 'Quản trị', OPERATOR: 'Cán bộ vận hành', USER: 'Người dân' } as const
const ROLES = Object.keys(ROLE_VI) as (keyof typeof ROLE_VI)[]

const password = z.string().min(10, 'Tối thiểu 10 ký tự').max(128, 'Tối đa 128 ký tự').regex(/(?=.*\d)(?=.*[a-zA-Z])/, 'Cần cả chữ và số')
const roles = z.array(z.enum(['ADMIN', 'OPERATOR', 'USER']), { invalid_type_error: 'Chọn ít nhất một vai trò' }).min(1, 'Chọn ít nhất một vai trò')
const baseSchema = { email: z.string().email('Email không hợp lệ'), full_name: z.string().max(120, 'Tối đa 120 ký tự'), roles }
const createSchema = z.object({
  username: z.string().regex(/^[a-zA-Z0-9_.]{3,50}$/, '3–50 ký tự: chữ, số, dấu chấm, gạch dưới'), password, ...baseSchema,
})
const editSchema = z.object({ ...baseSchema, is_active: z.boolean(), new_password: z.union([z.literal(''), password]) })

type Dialog = { kind: 'create' } | { kind: 'edit' | 'delete'; user: User } | null

export default function UsersPage() {
  const { user: me } = useAuth()
  const act = useAction()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [page, setPage] = useState(1)
  const [dlg, setDlg] = useState<Dialog>(null)
  const close = useCallback(() => setDlg(null), []) // ổn định để Modal không lấy lại focus mỗi lần render
  const params = { q, role, page, size: 20 }
  const list = useQuery({ queryKey: ['users', params], queryFn: () => api.get<Page<User>>('/admin/users', params) })

  return (
    <div>
      <PageHeader title="Người dùng">
        <button className="btn-primary" onClick={() => setDlg({ kind: 'create' })}>Thêm người dùng</button>
      </PageHeader>

      <div className="panel mb-4 grid gap-3 p-4 sm:grid-cols-2">
        <Field id="u-q" label="Tìm kiếm"><input id="u-q" className="input" placeholder="Tên đăng nhập, email, họ tên" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
        <Field id="u-role" label="Vai trò">
          <select id="u-role" className="input" value={role} onChange={(e) => { setRole(e.target.value); setPage(1) }}>
            <option value="">Tất cả</option>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_VI[r]}</option>)}
          </select>
        </Field>
      </div>

      <div className="panel mb-6 overflow-x-auto">
        {list.isLoading ? <Loading rows={6} /> : list.isError ? <ErrorState error={list.error} retry={() => list.refetch()} />
          : !list.data?.items.length ? <Empty text="Không có người dùng phù hợp." />
          : (
            <table className="table min-w-[860px]">
              <thead><tr><th>Tên đăng nhập</th><th>Họ tên</th><th>Email</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th>Ngày tạo</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
              <tbody>
                {list.data.items.map((u) => (
                  <tr key={u.id}>
                    <td className="font-medium">{u.username}</td>
                    <td>{u.full_name || '—'}</td>
                    <td>{u.email}</td>
                    <td><div className="flex flex-wrap gap-1">{u.role_codes.map((r) => <span key={r} className="chip border border-current">{ROLE_VI[r] ?? r}</span>)}</div></td>
                    <td>{u.is_active ? 'Hoạt động' : <span className="text-risk-high">Đã khoá</span>}</td>
                    <td className="num">{fmtDateTime(u.last_login_at)}</td>
                    <td className="num">{fmtDateTime(u.created_at)}</td>
                    <td className="whitespace-nowrap">
                      <button className="btn-ghost" onClick={() => setDlg({ kind: 'edit', user: u })}>Sửa</button>{' '}
                      {u.id !== me?.id && <button className="btn-ghost text-risk-high" onClick={() => setDlg({ kind: 'delete', user: u })}>Xoá</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        {list.data && <Pager page={page} size={list.data.size} total={list.data.total} onPage={setPage} />}
      </div>

      <ChangeMyPassword />

      {dlg?.kind === 'create' && <CreateUser onClose={close} />}
      {dlg?.kind === 'edit' && <EditUser user={dlg.user} onClose={close} />}
      {dlg?.kind === 'delete' && (
        <Confirm title="Xoá người dùng" danger confirmLabel="Xoá người dùng" onClose={close}
          text={`Xoá tài khoản ${dlg.user.username}? Người dùng sẽ không thể đăng nhập nữa.`}
          onConfirm={async () => { await act(() => api.del(`/admin/users/${dlg.user.id}`), 'Đã xoá người dùng', ['users']) }} />
      )}
    </div>
  )
}

function RoleChecks({ reg, error }: { reg: UseFormRegisterReturn; error?: string }) {
  return (
    <fieldset className="sm:col-span-2">
      <legend className="label">Vai trò</legend>
      <div className="flex flex-wrap gap-4 text-sm">
        {ROLES.map((r) => <label key={r} className="flex items-center gap-1"><input type="checkbox" value={r} {...reg} />{ROLE_VI[r]}</label>)}
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </fieldset>
  )
}

function CreateUser({ onClose }: { onClose: () => void }) {
  const act = useAction()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof createSchema>>({
    resolver: zodResolver(createSchema), defaultValues: { username: '', email: '', full_name: '', password: '', roles: ['USER'] },
  })
  return (
    <Modal title="Thêm người dùng" onClose={onClose}>
      <form noValidate className="grid gap-3 sm:grid-cols-2" onSubmit={handleSubmit(async (v) => {
        if (await act(() => api.post('/admin/users', v), 'Đã tạo người dùng', ['users'])) onClose()
      })}>
        <Field id="cu-username" label="Tên đăng nhập" error={errors.username?.message}><input id="cu-username" className="input" autoComplete="off" {...register('username')} /></Field>
        <Field id="cu-full" label="Họ tên" error={errors.full_name?.message}><input id="cu-full" className="input" {...register('full_name')} /></Field>
        <Field id="cu-email" label="Email" error={errors.email?.message}><input id="cu-email" type="email" className="input" {...register('email')} /></Field>
        <Field id="cu-pw" label="Mật khẩu" error={errors.password?.message} hint="Tối thiểu 10 ký tự, gồm chữ và số"><input id="cu-pw" type="password" autoComplete="new-password" className="input" {...register('password')} /></Field>
        <RoleChecks reg={register('roles')} error={errors.roles?.message} />
        <div className="sm:col-span-2"><FormActions busy={isSubmitting} onCancel={onClose} label="Tạo người dùng" /></div>
      </form>
    </Modal>
  )
}

function EditUser({ user, onClose }: { user: User; onClose: () => void }) {
  const act = useAction()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof editSchema>>({
    resolver: zodResolver(editSchema),
    defaultValues: { email: user.email, full_name: user.full_name, roles: user.role_codes, is_active: user.is_active, new_password: '' },
  })
  return (
    <Modal title={`Sửa người dùng ${user.username}`} onClose={onClose}>
      <form noValidate className="grid gap-3 sm:grid-cols-2" onSubmit={handleSubmit(async (v) => {
        const body = { ...v, new_password: v.new_password || undefined }
        if (await act(() => api.patch(`/admin/users/${user.id}`, body), 'Đã cập nhật người dùng', ['users'])) onClose()
      })}>
        <Field id="eu-full" label="Họ tên" error={errors.full_name?.message}><input id="eu-full" className="input" {...register('full_name')} /></Field>
        <Field id="eu-email" label="Email" error={errors.email?.message}><input id="eu-email" type="email" className="input" {...register('email')} /></Field>
        <Field id="eu-pw" label="Đặt lại mật khẩu (để trống nếu giữ nguyên)" error={errors.new_password?.message} className="sm:col-span-2">
          <input id="eu-pw" type="password" autoComplete="new-password" className="input" {...register('new_password')} />
        </Field>
        <RoleChecks reg={register('roles')} error={errors.roles?.message} />
        <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" {...register('is_active')} /> Tài khoản đang hoạt động</label>
        <div className="sm:col-span-2"><FormActions busy={isSubmitting} onCancel={onClose} /></div>
      </form>
    </Modal>
  )
}

const pwSchema = z.object({ current_password: z.string().min(1, 'Nhập mật khẩu hiện tại'), new_password: password, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { message: 'Mật khẩu nhập lại không khớp', path: ['confirm'] })
  .refine((v) => v.new_password !== v.current_password, { message: 'Mật khẩu mới phải khác mật khẩu hiện tại', path: ['new_password'] })

function ChangeMyPassword() {
  const act = useAction()
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<z.infer<typeof pwSchema>>({
    resolver: zodResolver(pwSchema), defaultValues: { current_password: '', new_password: '', confirm: '' },
  })
  return (
    <section className="panel max-w-xl p-4" aria-label="Đổi mật khẩu của tôi">
      <h2 className="mb-3 font-semibold">Đổi mật khẩu của tôi</h2>
      <form noValidate className="grid gap-3 sm:grid-cols-3" onSubmit={handleSubmit(async (v) => {
        if (await act(() => api.post('/auth/change-password', { current_password: v.current_password, new_password: v.new_password }), 'Đã đổi mật khẩu')) reset()
      })}>
        <Field id="pw-cur" label="Mật khẩu hiện tại" error={errors.current_password?.message}><input id="pw-cur" type="password" autoComplete="current-password" className="input" {...register('current_password')} /></Field>
        <Field id="pw-new" label="Mật khẩu mới" error={errors.new_password?.message}><input id="pw-new" type="password" autoComplete="new-password" className="input" {...register('new_password')} /></Field>
        <Field id="pw-cf" label="Nhập lại" error={errors.confirm?.message}><input id="pw-cf" type="password" autoComplete="new-password" className="input" {...register('confirm')} /></Field>
        <div className="sm:col-span-3"><button className="btn-primary" disabled={isSubmitting}>{isSubmitting ? 'Đang lưu…' : 'Đổi mật khẩu'}</button></div>
      </form>
    </section>
  )
}
