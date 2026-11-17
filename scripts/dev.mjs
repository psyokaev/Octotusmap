// Chạy backend (:8000) và giao diện Streamlit (:8501) cùng lúc; một bên dừng thì dừng bên còn lại. Yêu cầu đã chạy bootstrap.py một lần.
import { spawn } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const python = join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const procs = [
  spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1'], {
    cwd: join(root, 'backend'),
    env: { ...process.env, PYTHONUTF8: '1' },
    stdio: 'inherit',
  }),
  spawn(python, ['-m', 'streamlit', 'run', join('streamlit_app', 'app.py'), '--server.port', '8501', '--server.headless', 'true'], {
    cwd: root,
    env: { ...process.env, PYTHONUTF8: '1', API_BASE: 'http://127.0.0.1:8000/api/v1' },
    stdio: 'inherit',
  }),
]

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
