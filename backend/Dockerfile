# Build context = thư mục gốc dự án (xem docker-compose.yml)
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 DATASETS_DIR=/datasets
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
COPY backend/ .
COPY datasets/gis/ /datasets/gis/
# bootstrap idempotent (tạo DB, migrate, seed, huấn luyện lần đầu) rồi chạy API
# BOOTSTRAP_ARGS: vd "--forecast-epochs 1" để CI khởi động nhanh
CMD ["sh", "-c", "python scripts/bootstrap.py $BOOTSTRAP_ARGS && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
