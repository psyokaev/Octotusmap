from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.core.deps import DB, Operator, OptionalUser, is_staff
from app.models import AlertHistory
from app.schemas.common import Page, to_utc_naive
from app.schemas.views import (
    AlertAssignIn,
    AlertDetailOut,
    AlertHistoryOut,
    AlertNoteIn,
    AlertOut,
    AlertStatusIn,
    AlertVerifyIn,
    UserOut,
)
from app.services import alert_service, simulation_overlay
from app.services.audit_service import audit

router = APIRouter(prefix="/alerts", tags=["Alerts"])


def _out(a, staff: bool = True) -> AlertOut:
    o = AlertOut.model_validate(a)
    ex = a.explanation or {}  # công khai: chỉ nguyên nhân/độ sâu/phường, không lộ toàn bộ explanation
    o.cause, o.depth_cm, o.wards = ex.get("cause"), ex.get("depth_cm"), ex.get("wards") or []
    if staff:
        o.assignee_name = (a.assignee.full_name or a.assignee.username) if a.assignee else None
    else:  # thông tin xử lý nội bộ không công khai
        o.assigned_to, o.verified_outcome, o.explanation = None, "UNVERIFIED", None
        o.acknowledged_at = o.resolved_at = o.closed_at = None
        o.status, o.updated_at = "NEW", o.triggered_at
    return o


@router.get("", response_model=Page[AlertOut])
def list_alerts(db: DB, user: OptionalUser, status: list[str] | None = Query(None),
                level: list[str] | None = Query(None), area_id: int | None = None, q: str | None = None,
                date_from: datetime | None = None, date_to: datetime | None = None,
                page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200), sort: str = "triggered_at",
                direction: Literal["asc", "desc"] = "desc"):
    """Người dùng công khai chỉ thấy cảnh báo công khai đang hoạt động."""
    if not is_staff(user):  # trạng thái xử lý là nội bộ: không lọc/sắp xếp theo nó
        status, sort = None, "triggered_at" if sort == "status" else sort
    d_from, d_to = (to_utc_naive(date_from) if date_from else None), (to_utc_naive(date_to) if date_to else None)
    rows, total = alert_service.list_alerts(
        db, public_only=not is_staff(user), status=status, level=level, area_id=area_id, q=q,
        date_from=d_from, date_to=d_to, page=page, size=size, sort=sort, direction=direction)
    items = [_out(a, is_staff(user)) for a in rows]
    if is_staff(user):  # cảnh báo mô phỏng: chỉ cán bộ, đứng đầu trang 1, mất khi tắt mô phỏng
        sims = [AlertOut(**v) for v in _sim_alerts(db) if (not status or "NEW" in status)
                and (not level or v["risk_level"] in level) and (not area_id or v["area"].id == area_id)
                and (not q or q.lower() in (v["title"] + v["message"] + v["code"]).lower())
                and simulation_overlay.in_range(v["triggered_at"], d_from, d_to)]
        total += len(sims)
        if page == 1:
            items = sims + items
    return Page(items=items, total=total, page=page, size=size)


def _sim_alerts(db) -> list[dict]:
    return simulation_overlay.virtual_alerts(db, simulation_overlay.affected(db))


@router.get("/assignees", response_model=list[UserOut])
def assignees(db: DB, _: Operator):
    return alert_service.staff_users(db)


@router.get("/{aid}", response_model=AlertDetailOut)
def detail(aid: int, db: DB, user: OptionalUser):
    if aid < 0:  # cảnh báo mô phỏng: chỉ cán bộ, không có lịch sử xử lý
        v = next((v for v in _sim_alerts(db) if v["id"] == aid), None) if is_staff(user) else None
        if not v:
            raise HTTPException(404, "Cảnh báo mô phỏng không còn (mô phỏng đã tắt)")
        return AlertDetailOut(**AlertOut(**v).model_dump(), history=[])
    a = alert_service.get(db, aid)
    staff = is_staff(user)
    if not staff and not (a.is_public and a.status in alert_service.OPEN):
        raise HTTPException(403, "Cảnh báo không công khai")
    hist = [AlertHistoryOut(id=h.id, action=h.action, from_status=h.from_status, to_status=h.to_status, note=h.note,
                            changed_at=h.changed_at, username=h.user.username if h.user else "hệ thống")
            for h in db.scalars(select(AlertHistory).where(AlertHistory.alert_id == a.id).order_by(AlertHistory.changed_at))] if staff else []
    return AlertDetailOut(**_out(a, staff).model_dump(), history=hist)


@router.post("/{aid}/acknowledge", response_model=AlertOut)
def acknowledge(aid: int, user: Operator, request: Request, db: DB):
    a = alert_service.change_status(db, alert_service.get(db, aid), "ACKNOWLEDGED", user, "Đã tiếp nhận")
    audit(db, user, "ALERT_ACK", "alert", aid, None, request)
    db.commit()
    return _out(a)


@router.post("/{aid}/status", response_model=AlertOut)
def set_status(aid: int, body: AlertStatusIn, user: Operator, request: Request, db: DB):
    a = alert_service.change_status(db, alert_service.get(db, aid), body.status, user, body.note)
    audit(db, user, "ALERT_STATUS", "alert", aid, body.model_dump(), request)
    db.commit()
    return _out(a)


@router.post("/{aid}/assign", response_model=AlertOut)
def assign(aid: int, body: AlertAssignIn, user: Operator, request: Request, db: DB):
    a = alert_service.assign(db, alert_service.get(db, aid), body.user_id, user, body.note)
    audit(db, user, "ALERT_ASSIGN", "alert", aid, body.model_dump(), request)
    db.commit()
    return _out(a)


@router.post("/{aid}/notes", status_code=201)
def note(aid: int, body: AlertNoteIn, user: Operator, db: DB):
    alert_service.add_note(db, alert_service.get(db, aid), user, body.note)
    return {"message": "Đã thêm ghi chú"}


@router.post("/{aid}/verify", response_model=AlertOut)
def verify(aid: int, body: AlertVerifyIn, user: Operator, request: Request, db: DB):
    a = alert_service.verify(db, alert_service.get(db, aid), user, body.outcome, body.note)
    audit(db, user, "ALERT_VERIFY", "alert", aid, body.model_dump(), request)
    db.commit()
    return _out(a)
