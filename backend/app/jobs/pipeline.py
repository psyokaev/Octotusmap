"""Chu kỳ xử lý gần thời gian thực:
thu thập (DEMO: mô phỏng) -> camera -> dự báo LSTM/GRU -> rule engine -> cảnh báo -> SSE."""

import asyncio
import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import delete, text

from app.core.config import get_settings
from app.core.database import SessionLocal, engine, utcnow
from app.models import RateLimitHit
from app.repositories import observations as obs_repo
from app.services import alert_service, camera_service, forecast_service, risk_service
from app.services.events import bus

log = logging.getLogger("app.pipeline")
_lock = threading.Lock()
last_run = bus.last_cycle  # cùng dict để worker không chạy lịch vẫn thấy chu kỳ gần nhất
_last_scan = 0.0  # monotonic; quét camera giao thông theo chu kỳ riêng
_last_imerg = -1e9


def run_cycle() -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "BUSY"}
    t0 = time.time()
    try:
        with SessionLocal() as db:
            out: dict = {}
            s = get_settings()
            if s.demo_mode:
                from app.jobs import simulator

                out["ingested"] = simulator.ingest_until_now(db)
                if s.camera_enabled:
                    out["camera_frames"] = simulator.simulate_cameras(db)
            else:
                from app.services import openmeteo_service

                try:
                    out["ingested"] = openmeteo_service.ingest_latest(db)
                except Exception:  # mất mạng: dùng dữ liệu đã có, chu kỳ sau thử lại
                    log.exception("Open-Meteo ingest lỗi")
                    out["ingested"] = 0
            from app.services import report_service

            out["reports_expired"] = report_service.expire(db)
            global _last_scan
            if s.camera_scan_enabled and time.monotonic() - _last_scan >= s.camera_scan_interval_minutes * 60:
                _last_scan = time.monotonic()
                try:
                    out["camera_scan"] = camera_service.scan_traffic_cameras(db)
                except Exception:  # không để lỗi quét làm hỏng chu kỳ
                    log.exception("Quét camera giao thông lỗi")
            if not s.demo_mode and s.camera_health_per_cycle > 0:
                from app.services import traffic_camera_service

                try:  # camera hỏng/đổi đường dẫn: tự ngừng, có ảnh lại thì tự bật
                    out["camera_health"] = traffic_camera_service.check_health(db, s.camera_health_per_cycle)
                except Exception:
                    db.rollback()
                    log.exception("Kiểm tra camera giao thông lỗi")
            global _last_imerg
            if not s.demo_mode and s.earthdata_token and time.monotonic() - _last_imerg >= 6 * 3600:
                from app.services import imerg_service

                _last_imerg = time.monotonic()  # bản ngày IMERG ra 1 lần/ngày: thử bù tối đa 4 lần/ngày
                try:
                    out["imerg"] = imerg_service.ingest_recent(db, utcnow().date())
                except Exception:
                    db.rollback()
                    log.exception("Lấy mưa vệ tinh IMERG lỗi")
            issued = obs_repo.latest_time(db)
            if issued:
                out["forecast"] = forecast_service.run_inference(db, issued)
                out["risk"] = risk_service.evaluate_all(db, issued)
                out["alerts"] = alert_service.process(db, issued)
                out["issued_at"] = issued
            out["purged_frames"] = camera_service.purge_expired(db)
            db.execute(delete(RateLimitHit).where(RateLimitHit.window_start < utcnow() - timedelta(days=1)))
            db.commit()
        out["seconds"] = round(time.time() - t0, 2)
        last_run.clear()
        last_run.update(out)
        bus.publish("cycle", {"issued_at": out.get("issued_at"), "alerts": out.get("alerts"),
                              "seconds": out["seconds"]})
        log.info("cycle done %s", out)
        return out
    finally:
        _lock.release()


_leader = None  # kết nối giữ khoá phiên; worker chết thì PostgreSQL tự nhả khoá cho worker khác


def is_leader() -> bool:
    """Chỉ một worker uvicorn chạy lịch: worker giữ được pg_try_advisory_lock."""
    global _leader
    if _leader is not None:
        try:
            _leader.execute(text("SELECT 1"))
            return True
        except Exception:
            log.warning("mất kết nối giữ khoá lịch, giành lại")
            _leader = None
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    # dạng 2 khoá int4 không trùng không gian khoá bigint mà risk_service dùng
    if conn.execute(text("SELECT pg_try_advisory_lock(7340, 1)")).scalar():
        _leader = conn
        return True
    conn.close()
    return False


async def scheduler_loop() -> None:
    s = get_settings()
    while True:
        try:
            if await asyncio.to_thread(is_leader):
                await asyncio.to_thread(run_cycle)
        except Exception:
            log.exception("pipeline cycle failed")  # chu kỳ sau thử lại; lỗi được ghi log
        await asyncio.sleep(s.scheduler_interval_seconds)
