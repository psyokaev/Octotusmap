"""Sinh cảnh báo từ snapshot rủi ro (chống lặp, escalate, cooldown) và quy trình xử lý cảnh báo."""

import secrets
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError, NotFound
from app.models import (
    AdministrativeArea,
    Alert,
    AlertHistory,
    FloodRiskSnapshot,
    Notification,
    Role,
    User,
    user_roles,
)
from app.repositories.base import contains, paginate
from app.services.events import bus
from app.services.risk_service import active_rule
from app.services.rule_engine import DEFAULT_RULE_CONFIG, RANK, RECOMMENDATIONS, should_alert

OPEN = ("NEW", "ACKNOWLEDGED", "IN_PROGRESS")
TRANSITIONS = {
    "NEW": {"ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CLOSED"},
    "ACKNOWLEDGED": {"IN_PROGRESS", "RESOLVED", "CLOSED"},
    "IN_PROGRESS": {"RESOLVED", "CLOSED"},
    "RESOLVED": {"CLOSED", "IN_PROGRESS"},
    "CLOSED": set(),
}
LEVEL_VI = {"LOW": "THẤP", "MEDIUM": "TRUNG BÌNH", "HIGH": "CAO"}
CAUSE_VI = {"TIDE": "Ngập do triều", "RAIN": "Ngập do mưa", "RAIN_TIDE": "Ngập do mưa kết hợp triều",
            "REPORT": "Người dân báo ngập", "CAMERA": "Camera phát hiện ngập (mô hình thử nghiệm, tham khảo)",
            "STORM": "Nguy cơ mưa dông cục bộ (ước tính)"}


def staff_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).join(user_roles).join(Role).where(
        Role.code.in_(["ADMIN", "OPERATOR"]), User.is_active.is_(True), User.deleted_at.is_(None)).distinct()))


def _notify(db: Session, alert: Alert, title: str) -> None:
    for u in staff_users(db):
        db.add(Notification(user_id=u.id, alert_id=alert.id, title=title, level=alert.risk_level,
                            body=f"{alert.area.name}: {alert.message}"))


def _message(snap: FloodRiskSnapshot, area_name: str) -> str:
    when = "hiện tại" if snap.horizon_h == 0 else f"trong {snap.horizon_h} giờ tới"
    parts = [f"Nguy cơ ngập {LEVEL_VI[snap.risk_level]} tại {area_name} {when}"]
    if snap.flood_probability is not None:
        parts.append(f"xác suất ngập {snap.flood_probability:.0%}")
    if snap.rainfall_mm is not None:
        parts.append(f"mưa {snap.rainfall_mm:.1f} mm/h")
    msg = ", ".join(parts) + "."
    ex = snap.explanation or {}
    if ex.get("cause") in CAUSE_VI:
        cause = CAUSE_VI[ex["cause"]] + (f", khoảng {ex['depth_cm']} cm (ước tính)" if ex.get("depth_cm") else "")
        msg += f" {cause}"
        if ex.get("wards"):
            more = ex.get("wards_total", 0) - len(ex["wards"])
            msg += f" tại {', '.join(ex['wards'])}" + (f" và {more} phường khác" if more > 0 else "")
        msg += "."
    return msg


def process(db: Session, issued_at: datetime, notify: bool = True) -> dict:
    """Mỗi khu vực tối đa 1 cảnh báo mở; mức cao hơn -> escalate; cooldown sau khi đóng."""
    rule = active_rule(db)
    cfg = rule.config if rule else DEFAULT_RULE_CONFIG
    # chỉ cảnh báo cấp quận: phường đã hiện trên bản đồ, cảnh báo từng phường sẽ gây nhiễu
    snaps = list(db.scalars(select(FloodRiskSnapshot).join(
        AdministrativeArea, AdministrativeArea.id == FloodRiskSnapshot.area_id).where(
        FloodRiskSnapshot.issued_at == issued_at, AdministrativeArea.level == "DISTRICT")))
    worst: dict[int, FloodRiskSnapshot] = {}
    for s in sorted(snaps, key=lambda s: s.horizon_h):  # cùng mức -> giữ mốc sớm nhất
        if s.risk_level in RANK and (s.area_id not in worst or RANK[s.risk_level] > RANK[worst[s.area_id].risk_level]):
            worst[s.area_id] = s
    created = escalated = 0
    for area_id, snap in worst.items():
        if not should_alert(snap.risk_level, cfg):
            continue
        open_alert = db.scalar(select(Alert).where(Alert.area_id == area_id, Alert.status.in_(OPEN))
                               .order_by(Alert.triggered_at.desc()).limit(1))
        if open_alert:
            if RANK[snap.risk_level] > RANK[open_alert.risk_level]:
                old = open_alert.risk_level
                open_alert.risk_level, open_alert.score, open_alert.horizon_h = snap.risk_level, snap.score, snap.horizon_h
                open_alert.explanation = snap.explanation
                open_alert.recommendations = RECOMMENDATIONS[snap.risk_level]
                open_alert.message = _message(snap, open_alert.area.name)
                open_alert.title = f"[{LEVEL_VI[snap.risk_level]}] {open_alert.area.name}"
                db.add(AlertHistory(alert_id=open_alert.id, action="ESCALATED", from_status=open_alert.status,
                                    to_status=open_alert.status, note=f"Nâng mức {old} → {snap.risk_level}"))
                if notify:
                    _notify(db, open_alert, f"Nâng mức cảnh báo: {open_alert.title}")
                escalated += 1
                bus.publish("alert", {"id": open_alert.id, "type": "ESCALATED", "level": snap.risk_level},
                            public=open_alert.is_public)
            elif snap.risk_level == open_alert.risk_level and (
                    (msg := _message(snap, open_alert.area.name)) != open_alert.message
                    or snap.explanation != open_alert.explanation):  # cùng mức: chỉ làm mới nội dung
                open_alert.message, open_alert.explanation = msg, snap.explanation
                open_alert.title = f"[{LEVEL_VI[snap.risk_level]}] {open_alert.area.name}"
                open_alert.score, open_alert.horizon_h = snap.score, snap.horizon_h
            continue
        recent = db.scalar(select(Alert).where(
            Alert.area_id == area_id, Alert.risk_level == snap.risk_level,
            or_(Alert.resolved_at >= issued_at - timedelta(minutes=cfg["cooldown_minutes"]),
                Alert.closed_at >= issued_at - timedelta(minutes=cfg["cooldown_minutes"]))).limit(1))
        if recent:
            continue
        area_name = db.get(AdministrativeArea, area_id).name
        a = Alert(code=f"AL-{issued_at:%y%m%d%H}-{area_id:02d}-{secrets.token_hex(2).upper()}", area_id=area_id,
                  risk_level=snap.risk_level, status="NEW", title=f"[{LEVEL_VI[snap.risk_level]}] {area_name}",
                  message=_message(snap, area_name), recommendations=RECOMMENDATIONS[snap.risk_level],
                  explanation=snap.explanation, score=snap.score, horizon_h=snap.horizon_h,
                  rule_id=snap.rule_id, is_simulated=snap.is_simulated, triggered_at=issued_at)
        db.add(a)
        db.flush()
        db.add(AlertHistory(alert_id=a.id, action="CREATED", to_status="NEW",
                            note=f"Sinh tự động bởi rule v{rule.version if rule else 0}"))
        if notify:
            _notify(db, a, f"Cảnh báo mới: {a.title}")
        created += 1
        bus.publish("alert", {"id": a.id, "type": "CREATED", "level": a.risk_level, "area": area_name},
                    public=a.is_public)
    db.commit()
    return {"created": created, "escalated": escalated}


# ------------------------------------------------------------------ nghiệp vụ xử lý
def get(db: Session, alert_id: int) -> Alert:
    a = db.get(Alert, alert_id)
    if not a:
        raise NotFound("Cảnh báo")
    return a


def list_alerts(db: Session, *, public_only: bool, status, level, area_id, q, date_from, date_to, page, size,
                sort, direction):
    stmt = select(Alert)
    if public_only:
        stmt = stmt.where(Alert.is_public.is_(True), Alert.status.in_(OPEN))
    if status:
        stmt = stmt.where(Alert.status.in_(status))
    if level:
        stmt = stmt.where(Alert.risk_level.in_(level))
    if area_id:
        stmt = stmt.where(Alert.area_id == area_id)
    if q:
        stmt = stmt.where(or_(contains(Alert.title, q), contains(Alert.code, q), contains(Alert.message, q)))
    if date_from:
        stmt = stmt.where(Alert.triggered_at >= date_from)
    if date_to:
        stmt = stmt.where(Alert.triggered_at < date_to)
    col = {"triggered_at": Alert.triggered_at, "risk_level": Alert.risk_level, "status": Alert.status,
           "score": Alert.score}.get(sort, Alert.triggered_at)
    return paginate(db, stmt, page, size, col, direction)


def change_status(db: Session, a: Alert, new: str, user: User, note: str = "") -> Alert:
    if new == a.status:
        raise AppError(409, "NO_CHANGE", "Cảnh báo đã ở trạng thái này")
    if new not in TRANSITIONS[a.status]:
        raise AppError(409, "INVALID_TRANSITION", f"Không thể chuyển {a.status} → {new}")
    now = utcnow()
    db.add(AlertHistory(alert_id=a.id, action="STATUS", from_status=a.status, to_status=new, note=note,
                        changed_by=user.id))
    a.status = new
    if new == "ACKNOWLEDGED" or (new == "IN_PROGRESS" and not a.acknowledged_at):
        a.acknowledged_at = a.acknowledged_at or now
    if new == "RESOLVED":
        a.resolved_at = now
    if new == "CLOSED":
        a.closed_at = now
    db.commit()
    bus.publish("alert", {"id": a.id, "type": "STATUS", "status": new}, public=False)
    return a


def assign(db: Session, a: Alert, user_id: int | None, actor: User, note: str = "") -> Alert:
    if user_id is not None:
        target = db.get(User, user_id)
        if not target or not {"ADMIN", "OPERATOR"} & set(target.role_codes) or not target.is_active:
            raise AppError(422, "INVALID_ASSIGNEE", "Chỉ phân công cho cán bộ vận hành/quản trị đang hoạt động")
        db.add(Notification(user_id=target.id, alert_id=a.id, title=f"Bạn được phân công: {a.title}",
                            level=a.risk_level, body=a.message))
    db.add(AlertHistory(alert_id=a.id, action="ASSIGN", from_status=a.status, to_status=a.status,
                        note=note or f"Phân công cho user #{user_id}", changed_by=actor.id))
    a.assigned_to = user_id
    db.commit()
    return a


def add_note(db: Session, a: Alert, actor: User, note: str) -> None:
    db.add(AlertHistory(alert_id=a.id, action="NOTE", from_status=a.status, to_status=a.status, note=note,
                        changed_by=actor.id))
    db.commit()


def verify(db: Session, a: Alert, actor: User, outcome: str, note: str) -> Alert:
    db.add(AlertHistory(alert_id=a.id, action="VERIFY", from_status=a.status, to_status=a.status,
                        note=f"Xác minh: {outcome}. {note}".strip(), changed_by=actor.id))
    a.verified_outcome = outcome
    db.commit()
    return a
