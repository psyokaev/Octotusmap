// npm run dev: bật PostgreSQL nếu chưa chạy, rồi backend (:8000) và Streamlit (:5173), tự mở trình duyệt.
// Một bên dừng thì dừng bên còn lại (PostgreSQL để chạy tiếp). Yêu cầu đã chạy bootstrap.py một lần.
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { connect } from 'node:net'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const win = process.platform === 'win32'
const python = join(root, 'backend', '.venv', win ? 'Scripts/python.exe' : 'bin/python')
const PG_HOME = process.env.PG_HOME ?? 'E:\\pgsql'
const UI_PORT = process.env.UI_PORT ?? '5173'

const listening = (port) =>
  new Promise((ok) => {
    const s = connect({ port: Number(port), host: '127.0.0.1' })
    s.once('connect', () => { s.destroy(); ok(true) })
    s.once('error', () => ok(false))
  })

if (!(await listening(5432))) {
  const pgCtl = join(PG_HOME, 'bin', win ? 'pg_ctl.exe' : 'pg_ctl')
  if (!existsSync(pgCtl)) {
    console.error(`PostgreSQL chưa chạy và không thấy ${pgCtl}. Đặt PG_HOME hoặc tự bật PostgreSQL.`)
    process.exit(1)
  }
  console.log('Đang bật PostgreSQL...')
  // tách khỏi console: Ctrl+C dừng dev không được tắt luôn PostgreSQL
  spawn(pgCtl, ['-D', join(PG_HOME, 'data'), '-l', join(PG_HOME, 'server.log'), 'start'],
    { detached: true, stdio: 'ignore', windowsHide: true }).unref()
  let up = false
  for (let i = 0; i < 60 && !up; i++) {
    await new Promise((r) => setTimeout(r, 500))
    up = await listening(5432)
  }
  if (!up) {
    console.error(`Không bật được PostgreSQL, xem ${join(PG_HOME, 'server.log')}`)
    process.exit(1)
  }
}

for (const [port, what] of [['8000', 'backend'], [UI_PORT, 'giao diện']]) {
  if (await listening(port)) {
    console.error(`Cổng ${port} (${what}) đang bị chiếm, có thể do lần chạy trước chưa tắt. Tắt tiến trình đó rồi chạy lại.`)
    process.exit(1)
  }
}

const procs = [
  spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1'], {
    cwd: join(root, 'backend'),
    env: { ...process.env, PYTHONUTF8: '1' },
    stdio: 'inherit',
  }),
  // cwd = streamlit_app để nạp streamlit_app/.streamlit/config.toml (theme, headless: không hỏi email lần đầu)
  spawn(python, ['-m', 'streamlit', 'run', 'app.py', '--server.port', UI_PORT], {
    cwd: join(root, 'streamlit_app'),
    env: { ...process.env, PYTHONUTF8: '1', API_BASE: 'http://127.0.0.1:8000/api/v1' },
    stdio: 'inherit',
  }),
]
console.log(`\nGiao diện: http://localhost:${UI_PORT}   API: http://127.0.0.1:8000/docs\n`)

const stop = (code) => {
  procs.forEach((p) => p.kill())
  process.exitCode = code ?? 0
}
for (const p of procs) {
  p.on('error', (e) => {
    console.error(`Không khởi động được ${p.spawnfile}: ${e.message}`)
    stop(1)
  })
  p.on('exit', stop)
}

// tự mở trình duyệt khi giao diện đã nghe cổng
const url = `http://localhost:${UI_PORT}`
for (let i = 0; i < 120 && !(await listening(UI_PORT)); i++) await new Promise((r) => setTimeout(r, 500))
if (!process.env.NO_BROWSER) {
  const [cmd, args] = win ? ['cmd', ['/c', 'start', '', url]] : [process.platform === 'darwin' ? 'open' : 'xdg-open', [url]]
  spawn(cmd, args, { stdio: 'ignore', detached: true }).on('error', () => {}).unref()
}
