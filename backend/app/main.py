import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import fastapi.encoders
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.controllers import (
    admin,
    alerts,
    auth,
    cameras,
    exports,
    forecasts,
    gis,
    history,
    misc,
    reports,
    stations,
    statistics,
)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import register_error_handlers
from app.schemas.common import _utc_iso
from app.services.events import bus

# DB lưu UTC naive -> mọi datetime trong response dạng dict cũng xuất ISO có 'Z'
fastapi.encoders.ENCODERS_BY_TYPE[datetime] = _utc_iso

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.jwt_secret or len(settings.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET chưa cấu hình (>= 32 ký tự) trong backend/.env")
    bus.bind(asyncio.get_running_loop())
    task = None
    if settings.scheduler_enabled:
        from app.jobs.pipeline import scheduler_loop

        task = asyncio.create_task(scheduler_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
              description="API hệ thống hỗ trợ ra quyết định cảnh báo sớm ngập úng đô thị TP.HCM. "
                          "Dữ liệu gắn nhãn SIMULATED/DEMO là dữ liệu mô phỏng.")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
register_error_handlers(app)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


api = APIRouter(prefix="/api/v1")
for r in (auth, stations, gis, forecasts, cameras, alerts, history, statistics, exports, misc, admin, reports):
    api.include_router(r.router)
app.include_router(api)


@app.get("/health", tags=["System"])
def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # health check báo trạng thái thay vì ném lỗi
        db_ok = False
    from app.jobs.pipeline import last_run

    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "demo_mode": settings.demo_mode,
            "camera_enabled": settings.camera_enabled,
            "last_cycle_seconds": last_run.get("seconds")}
