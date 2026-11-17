from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import DB, CurrentUser, Operator, OptionalUser, is_staff
from app.models import Camera, FloodHotspot
from app.schemas.common import ORM, UtcDatetime
from app.services import report_service
from app.services.routing_service import dist_m
from app.services.traffic_camera_service import CODE_PREFIX

router = APIRouter(tags=["Flood reports & hotspots"])
CAMERA_RADIUS_M = 500


class ReportIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    severity: Literal["ANKLE", "KNEE", "DEEP"]
    note: str = Field(default="", max_length=300)


class ReportOut(ORM):
    id: int
    latitude: float
    longitude: float
    severity: str
    note: str
    status: str
    confirmations: int
    reported_at: UtcDatetime
    expires_at: UtcDatetime
    reporter: str | None = None


class HotspotOut(ORM):
    id: int
    name: str
    street: str
    latitude: float
    longitude: float
    note: str
    source_url: str
    camera_id: int | None = None
    camera_name: str | None = None


def _out(r, staff: bool) -> ReportOut:
    o = ReportOut.model_validate(r)
    o.reporter = (r.user.username if r.user else None) if staff else None  # người dân không thấy danh tính
    return o


@router.get("/reports/active", response_model=list[ReportOut])
def active_reports(db: DB, user: OptionalUser):
    return [_out(r, is_staff(user)) for r in report_service.active(db)]


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(body: ReportIn, user: CurrentUser, request: Request, db: DB):
    return _out(report_service.create(db, user, body.latitude, body.longitude, body.severity, body.note, request),
                is_staff(user))


@router.post("/reports/{rid}/confirm", response_model=ReportOut)
def confirm_report(rid: int, user: CurrentUser, db: DB):
    return _out(report_service.confirm(db, rid, user), is_staff(user))


@router.post("/reports/{rid}/reject", response_model=ReportOut)
def reject_report(rid: int, user: Operator, request: Request, db: DB):
    return _out(report_service.reject(db, rid, user, request), True)


@router.get("/gis/hotspots", response_model=list[HotspotOut])
def hotspots(db: DB):
    """Điểm có nguy cơ ngập thường xuyên đã công bố (toạ độ geocode gần đúng)."""
    cams = db.execute(select(Camera.id, Camera.name, Camera.longitude, Camera.latitude).where(
        Camera.code.like(CODE_PREFIX + "%"), Camera.status == "ACTIVE", Camera.deleted_at.is_(None))).all()
    out = []
    for h in db.scalars(select(FloodHotspot).order_by(FloodHotspot.name)):
        o = HotspotOut.model_validate(h)
        near = min(cams, key=lambda c: dist_m((c[2], c[3]), (h.longitude, h.latitude)), default=None)
        if near and dist_m((near[2], near[3]), (h.longitude, h.latitude)) <= CAMERA_RADIUS_M:
            o.camera_id, o.camera_name = near[0], near[1]
        out.append(o)
    return out
