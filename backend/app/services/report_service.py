"""Báo cáo ngập tại chỗ của người dân (crowdsourcing)."""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError, NotFound
from app.core.security import RateLimiter
from app.core.spatial import point_wkt, valid_hcm_coordinate
from app.models import FloodReport, User
from app.services import gis_service
from app.services.audit_service import audit
from app.services.events import bus

TTL = timedelta(hours=3)
EXTEND_ON_CONFIRM = timedelta(hours=1)
report_limiter = RateLimiter(limit=5, window_s=600, name="report")


def active(db: Session) -> list[FloodReport]:
    return list(db.scalars(select(FloodReport).where(FloodReport.status == "ACTIVE", FloodReport.expires_at > utcnow())
                           .order_by(FloodReport.reported_at.desc())))


def create(db: Session, user: User, lat: float, lon: float, severity: str, note: str, request=None) -> FloodReport:
    if not valid_hcm_coordinate(lat, lon):
        raise AppError(422, "OUT_OF_AREA", "Vị trí nằm ngoài phạm vi TP.HCM")
    if not report_limiter.allow(f"report:{user.id}"):
        raise AppError(429, "RATE_LIMITED", "Bạn đã gửi quá nhiều báo cáo, thử lại sau ít phút")
    area = gis_service.area_at(db, lon, lat)
    now = utcnow()
    r = FloodReport(user_id=user.id, latitude=lat, longitude=lon, location=point_wkt(lon, lat), severity=severity,
                    note=note.strip(), area_id=area.id if area else None, reported_at=now, expires_at=now + TTL,
                    confirmed_by=[])
    db.add(r)
    db.flush()
    audit(db, user, "FLOOD_REPORT_CREATE", "flood_report", r.id, {"severity": severity}, request)
    db.commit()
    bus.publish("report", {"id": r.id, "type": "CREATED"})
    return r


def _get_active(db: Session, rid: int) -> FloodReport:
    r = db.get(FloodReport, rid)
    if not r or r.status != "ACTIVE" or r.expires_at <= utcnow():
        raise NotFound("Báo cáo ngập còn hiệu lực")
    return r


def confirm(db: Session, rid: int, user: User) -> FloodReport:
    r = _get_active(db, rid)
    who = list(r.confirmed_by or [])
    if user.id == r.user_id or user.id in who:
        raise AppError(409, "ALREADY_CONFIRMED", "Bạn đã xác nhận hoặc là người báo cáo")
    r.confirmed_by = who + [user.id]
    r.confirmations = len(r.confirmed_by)
    r.expires_at = max(r.expires_at, utcnow() + EXTEND_ON_CONFIRM)
    db.commit()
    bus.publish("report", {"id": r.id, "type": "CONFIRMED"})
    return r


def reject(db: Session, rid: int, user: User, request=None) -> FloodReport:
    r = _get_active(db, rid)
    r.status = "REJECTED"
    audit(db, user, "FLOOD_REPORT_REJECT", "flood_report", r.id, None, request)
    db.commit()
    bus.publish("report", {"id": r.id, "type": "REJECTED"})
    return r


def expire(db: Session) -> int:
    n = db.execute(update(FloodReport).where(FloodReport.status == "ACTIVE", FloodReport.expires_at <= utcnow())
                   .values(status="EXPIRED")).rowcount
    db.commit()
    return n or 0
