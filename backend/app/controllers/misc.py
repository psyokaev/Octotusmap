"""Tìm kiếm, định tuyến, thông báo, SSE."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.core.database import SessionLocal
from app.core.deps import DB, CurrentUser, OptionalUser, get_optional_user, is_staff
from app.core.errors import NotFound
from app.core.security import RateLimiter
from app.models import Notification
from app.repositories.base import paginate
from app.schemas.views import NotificationOut
from app.services import routing_service, search_service
from app.services.events import bus

router = APIRouter(tags=["Search & realtime"])
route_limiter = RateLimiter(limit=30, window_s=60, name="route")


@router.get("/search")
def search(db: DB, user: OptionalUser, q: str = Query(min_length=1, max_length=120), geocode: bool = True):
    return search_service.search(db, q, include_private=is_staff(user), use_geocoder=geocode)


class RouteIn(BaseModel):
    start: tuple[float, float] = Field(description="[lon, lat]")
    end: tuple[float, float] = Field(description="[lon, lat]")
    horizon_h: int = Field(0, ge=0, le=6)


@router.post("/routing/route")
def route(body: RouteIn, request: Request, db: DB, user: OptionalUser):
    if not route_limiter.allow(request.client.host if request.client else "?"):
        raise HTTPException(429, "Quá nhiều yêu cầu chỉ đường, thử lại sau 1 phút")
    # ngập mô phỏng chỉ ảnh hưởng tuyến của cán bộ; người dân/khách luôn nhận kết quả theo dữ liệu thật
    return routing_service.route(db, body.start, body.end, body.horizon_h, include_simulations=is_staff(user))


@router.get("/notifications")
def notifications(db: DB, user: CurrentUser, unread_only: bool = False, page: int = Query(1, ge=1),
                  size: int = Query(20, le=100)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    rows, total = paginate(db, stmt, page, size, Notification.created_at, "desc")
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.is_read.is_(False)))
    return {"items": [NotificationOut.model_validate(n) for n in rows], "total": total, "unread": unread}


@router.post("/notifications/{nid}/read", status_code=204)
def read(nid: int, db: DB, user: CurrentUser):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise NotFound("Thông báo")
    n.is_read = True
    db.commit()


@router.post("/notifications/read-all", status_code=204)
def read_all(db: DB, user: CurrentUser):
    db.execute(update(Notification).where(Notification.user_id == user.id).values(is_read=True))
    db.commit()


@router.get("/events")
async def events(request: Request):
    """Server-Sent Events: 'alert' (cảnh báo mới/thay đổi), 'cycle' (dữ liệu dự báo mới)."""
    # không dùng Depends(DB): stream sống lâu sẽ giữ kết nối DB và khoá bảng suốt thời gian mở tab
    with SessionLocal() as db:
        staff = is_staff(get_optional_user(request, db))
    q = bus.subscribe(staff=staff)

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while not await request.is_disconnected():
                try:
                    yield await asyncio.wait_for(q.get(), timeout=20)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
