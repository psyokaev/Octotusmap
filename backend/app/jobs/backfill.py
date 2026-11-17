"""Chạy lại pipeline (dự báo -> rule engine -> cảnh báo) cho từng giờ quá khứ.

Tạo lịch sử dự báo/snapshot để dashboard và thống kê có dữ liệu (sinh bởi chính mô hình và hệ luật).
DEMO (alerts=True): thêm cảnh báo, đóng tự động và xác minh bằng chuỗi mực nước mô phỏng.
LIVE (alerts=False): chỉ dự báo + snapshot tính lại từ quan trắc thật; không dựng cảnh báo chưa từng phát.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Alert, AlertHistory, FloodRiskSnapshot, MonitoringStation, WaterLevelObservation
from app.repositories import observations as obs_repo
from app.services import alert_service, forecast_service, risk_service

AUTO_CLOSE_AFTER = timedelta(hours=6)


def _flooded(db: Session, area_id: int, start, end) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(WaterLevelObservation)
        .join(MonitoringStation, MonitoringStation.id == WaterLevelObservation.station_id)
        .where(MonitoringStation.area_id == area_id, WaterLevelObservation.quality_flag == "VALID",
               WaterLevelObservation.observed_at > start, WaterLevelObservation.observed_at <= end,
               WaterLevelObservation.water_level_cm > MonitoringStation.flood_threshold_cm)))


def _auto_close(db: Session, now) -> None:
    for a in db.scalars(select(Alert).where(Alert.status.in_(alert_service.OPEN), Alert.is_simulated.is_(True),
                                            Alert.triggered_at <= now - AUTO_CLOSE_AFTER)):
        hit = _flooded(db, a.area_id, a.triggered_at, a.triggered_at + timedelta(hours=a.horizon_h + 2))
        a.verified_outcome = "CONFIRMED" if hit else "FALSE_ALARM"
        a.acknowledged_at = a.triggered_at + timedelta(minutes=10)
        a.resolved_at = a.closed_at = now
        note = "Tự động đóng (backfill DEMO); xác minh bằng chuỗi mực nước mô phỏng"
        db.add(AlertHistory(alert_id=a.id, action="STATUS", from_status=a.status, to_status="CLOSED", note=note,
                            changed_at=now))
        db.add(AlertHistory(alert_id=a.id, action="VERIFY", from_status="CLOSED", to_status="CLOSED",
                            note=f"Xác minh tự động: {a.verified_outcome}", changed_at=now))
        a.status = "CLOSED"
    db.commit()


def backfill(db: Session, days: int = 14, log=print, alerts: bool = True, force: bool = False) -> int:
    end = obs_repo.latest_time(db)
    if not end or not forecast_service.active_model(db):
        return 0
    have = db.scalar(select(func.min(FloodRiskSnapshot.issued_at)))
    start = end - timedelta(days=days) - timedelta(hours=1)  # +1h đệm: hysteresis `prev` lấy từ snapshot vừa tính lại
    if not force and have and have <= start + timedelta(hours=1):
        return 0  # đã backfill
    n = 0
    t = start
    while t <= end:
        forecast_service.run_inference(db, t)
        risk_service.evaluate_all(db, t)
        if alerts:
            alert_service.process(db, t, notify=False)
            _auto_close(db, t)
        n += 1
        if n % 24 == 0:
            log(f"      backfill {n // 24}/{days} ngày")
        t += timedelta(hours=1)
    return n
