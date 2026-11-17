# Khởi động hệ thống trên Windows (không Docker). Chạy từ thư mục gốc: powershell -File scripts\start-windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) {
  py -3.13 -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
}
if (-not (Test-Path ".env")) { Copy-Item .env.example .env; Write-Host "Đã tạo backend\.env - hãy điền POSTGRES_PASSWORD rồi chạy lại"; exit 1 }
$env:PYTHONUTF8 = "1"
.venv\Scripts\python scripts\bootstrap.py
Start-Process -FilePath ".venv\Scripts\python" -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1" -WorkingDirectory "$root\backend"
$env:API_BASE = "http://127.0.0.1:8000/api/v1"
Start-Process -FilePath ".venv\Scripts\python" -ArgumentList "-m streamlit run streamlit_app\app.py --server.port 8501 --server.headless true" -WorkingDirectory $root
Write-Host "Giao diện Streamlit: http://localhost:8501   API docs: http://127.0.0.1:8000/docs"
