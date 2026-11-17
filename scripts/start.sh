#!/usr/bin/env sh
# Linux/macOS (không Docker). Chạy từ thư mục gốc: sh scripts/start.sh
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT/backend"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu; }
[ -f .env ] || { cp .env.example .env; echo "Điền POSTGRES_PASSWORD trong backend/.env rồi chạy lại"; exit 1; }
.venv/bin/python scripts/bootstrap.py
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1 &
cd "$ROOT"
API_BASE=http://127.0.0.1:8000/api/v1 backend/.venv/bin/python -m streamlit run streamlit_app/app.py --server.port 8501 --server.headless true
