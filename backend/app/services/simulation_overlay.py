"""Phủ ngập mô phỏng của admin lên dữ liệu đọc cho cán bộ (rủi ro, cảnh báo, lịch sử, thống kê).

Tính lúc đọc, không ghi vào bảng thật: xoá mô phỏng là hết. Người dân/khách không bao giờ nhận dữ liệu này.
"""
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AdministrativeArea, FloodSimulation
from app.services.alert_service import LEVEL_VI
from app.services.flood_index import round_depth
from app.services.gis_service import area_at

CAUSE = "SIMULATION"
HIGH_CM = 20  # cùng ngưỡng flood_depth_cm_high của luật cảnh báo
RANK = {"NO_DATA": -1, "INSUFFICIENT_DATA": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def level_for(depth_cm: float) -> str:
    return "HIGH" if depth_cm >= HIGH_CM else "MEDIUM"


def affected(db: Session) -> dict[int, dict]:
    """area_id -> {level, depth_cm, wards, started_at} cho quận/phường giao với vùng mô phỏng."""
    rows = db.execute(text(
        "SELECT a.id, a.level, a.parent_id, a.name, max(s.depth_cm), min(s.created_at) "
        "FROM flood_simulations s JOIN administrative_areas a "
        "ON ST_DWithin(a.geom::geography, s.location::geography, s.radius_m) "
        "GROUP BY a.id, a.level, a.parent_id, a.name")).all()
    out = {r[0]: {"level": r[1], "parent_id": r[2], "name": r[3], "depth": float(r[4]), "started_at": r[5]}
           for r in rows}
    for aid, a in out.items():
        wards = [w for w in out.values() if w["parent_id"] == aid] if a["level"] == "DISTRICT" else [a]
        a["wards"] = sorted(w["name"] for w in wards)
        a["depth_cm"] = round_depth(a["depth"]) or int(a["depth"])
        a["risk_level"] = level_for(a["depth"])
    return out


def explanation(a: dict) -> dict:
    return {"cause": CAUSE, "depth_cm": a["depth_cm"], "wards": a["wards"],
            "level_reason": f"MÔ PHỎNG: ngập khoảng {a['depth_cm']} cm (do admin tạo, không phải dữ liệu thật)"}


def raise_level(current: str | None, a: dict) -> bool:
    return RANK.get(a["risk_level"], 0) >= RANK.get(current or "NO_DATA", 0)


def overlay_risk(row: dict, a: dict | None) -> dict:
    """Nâng một dòng rủi ro (dict) theo mô phỏng; giữ nguyên nếu mức thật đã cao hơn."""
    if a and raise_level(row.get("risk_level"), a):
        ex = explanation(a)
        row.update(risk_level=a["risk_level"], cause=CAUSE, depth_cm=a["depth_cm"], is_simulated=True)
        if "explanation" in row:
            row["explanation"] = {**(row["explanation"] or {}), **ex}
    return row


def virtual_alerts(db: Session, aff: dict[int, dict]) -> list[dict]:
    """Một cảnh báo ảo cho mỗi quận bị mô phỏng; id âm để không trùng và không xử lý được như cảnh báo thật."""
    out = []
    for aid, a in sorted(aff.items()):
        if a["level"] != "DISTRICT":
            continue
        area = db.get(AdministrativeArea, aid)
        where = f" tại {', '.join(a['wards'])}" if a["wards"] else ""
        out.append({
            "id": -aid, "code": f"SIM-{area.code}", "area": area, "risk_level": a["risk_level"], "status": "NEW",
            "title": f"[MÔ PHỎNG] [{LEVEL_VI.get(a['risk_level'], a['risk_level'])}] {area.name}",
            "message": f"MÔ PHỎNG: ngập khoảng {a['depth_cm']} cm{where}. "
                       "Do admin tạo để diễn tập, không phải dữ liệu thật.",
            "recommendations": None, "explanation": explanation(a), "cause": CAUSE, "depth_cm": a["depth_cm"],
            "wards": a["wards"], "score": 1.0 if a["risk_level"] == "HIGH" else 0.6, "horizon_h": 0,
            "is_simulated": True, "is_public": False, "verified_outcome": "UNVERIFIED", "assigned_to": None,
            "triggered_at": a["started_at"], "acknowledged_at": None, "resolved_at": None, "closed_at": None,
            "updated_at": a["started_at"]})
    return out


def virtual_events(db: Session) -> list[dict]:
    """Mỗi vùng mô phỏng là một dòng lịch sử ngập ảo (id âm)."""
    out = []
    for s in db.scalars(select(FloodSimulation).order_by(FloodSimulation.created_at.desc())):
        area = area_at(db, s.longitude, s.latitude, "DISTRICT")
        out.append({
            "id": -s.id, "location_name": f"MÔ PHỎNG: vùng bán kính {s.radius_m} m",
            "latitude": s.latitude, "longitude": s.longitude, "started_at": s.created_at, "ended_at": None,
            "max_depth_cm": float(s.depth_cm), "cause": CAUSE, "is_simulated": True, "area": area,
            "description": "Ngập giả định do admin tạo để diễn tập; tự mất khi tắt mô phỏng."})
    return out


def in_range(t: datetime, date_from: datetime | None, date_to: datetime | None) -> bool:
    return (date_from is None or t >= date_from) and (date_to is None or t < date_to)
