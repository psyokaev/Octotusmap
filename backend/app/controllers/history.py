from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import or_, select

from app.core.deps import DB, Operator
from app.core.errors import AppError, NotFound
from app.core.spatial import point_wkt, valid_hcm_coordinate
from app.models import DataSource, HistoricalFloodEvent
from app.repositories.base import contains, paginate
from app.schemas.common import Page, to_utc_naive
from app.schemas.views import FloodEventIn, FloodEventOut
from app.services import gis_service
from app.services.audit_service import audit

router = APIRouter(prefix="/history", tags=["Flood history"])


@router.get("/events", response_model=Page[FloodEventOut])
def events(db: DB, q: str | None = None, area_id: int | None = None, date_from: datetime | None = None,
           date_to: datetime | None = None, min_depth: float | None = None, page: int = Query(1, ge=1),
           size: int = Query(20, ge=1, le=200), sort: str = "started_at",
           direction: Literal["asc", "desc"] = "desc"):
    stmt = select(HistoricalFloodEvent)
    if q:
        stmt = stmt.where(or_(contains(HistoricalFloodEvent.location_name, q),
                              contains(HistoricalFloodEvent.description, q)))
    if area_id:
        stmt = stmt.where(HistoricalFloodEvent.area_id == area_id)
    if date_from:
        stmt = stmt.where(HistoricalFloodEvent.started_at >= to_utc_naive(date_from))
    if date_to:
        stmt = stmt.where(HistoricalFloodEvent.started_at < to_utc_naive(date_to))
    if min_depth is not None:
        stmt = stmt.where(HistoricalFloodEvent.max_depth_cm >= min_depth)
    col = {"started_at": HistoricalFloodEvent.started_at, "max_depth_cm": HistoricalFloodEvent.max_depth_cm,
           "location_name": HistoricalFloodEvent.location_name}.get(sort, HistoricalFloodEvent.started_at)
    rows, total = paginate(db, stmt, page, size, col, direction)
    return Page(items=rows, total=total, page=page, size=size)


@router.post("/events", response_model=FloodEventOut, status_code=201)
def create_event(body: FloodEventIn, user: Operator, request: Request, db: DB):
    if not valid_hcm_coordinate(body.latitude, body.longitude):
        raise AppError(422, "OUT_OF_AREA", "Toạ độ nằm ngoài phạm vi TP.HCM")
    if body.ended_at and body.ended_at < body.started_at:
        raise AppError(422, "INVALID_RANGE", "Thời điểm kết thúc phải sau thời điểm bắt đầu")
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    area = gis_service.nearest_area(db, body.longitude, body.latitude, level="DISTRICT")
    ev = HistoricalFloodEvent(**body.model_dump(exclude={"started_at", "ended_at"}),
                              started_at=to_utc_naive(body.started_at),
                              ended_at=to_utc_naive(body.ended_at) if body.ended_at else None,
                              location=point_wkt(body.longitude, body.latitude), area_id=area.id if area else None,
                              source_id=src.id, is_simulated=False)
    db.add(ev)
    db.flush()
    audit(db, user, "FLOOD_EVENT_CREATE", "flood_event", ev.id, {"location": body.location_name}, request)
    db.commit()
    return ev


@router.delete("/events/{eid}", status_code=204)
def delete_event(eid: int, user: Operator, request: Request, db: DB):
    ev = db.get(HistoricalFloodEvent, eid)
    if not ev:
        raise NotFound("Sự kiện ngập")
    audit(db, user, "FLOOD_EVENT_DELETE", "flood_event", eid, {"location": ev.location_name}, request)
    db.delete(ev)
    db.commit()
