"""Tìm kiếm: dữ liệu nội bộ (khu vực, trạm, camera, điểm ngập), toạ độ, và địa chỉ (Photon — dữ liệu OSM).

Tuân thủ chính sách sử dụng dịch vụ geocode công cộng: tối đa 1 request/giây, User-Agent định danh, cache kết quả,
giới hạn trong khung TP.HCM.
"""

import re
import threading
import time

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.spatial import valid_hcm_coordinate
from app.models import AdministrativeArea, Camera, HistoricalFloodEvent, MonitoringStation
from app.repositories.base import contains

COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)\s*$")
BBOX = "106.35,10.35,107.05,11.18"  # minLon,minLat,maxLon,maxLat
_cache: dict[str, list] = {}
_lock = threading.Lock()
_last_call = [0.0]


def parse_coordinates(q: str) -> tuple[float, float] | None:
    """'10.78, 106.70' (lat, lon) hoặc '106.70 10.78' -> (lat, lon)."""
    m = COORD_RE.match(q)
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if valid_hcm_coordinate(a, b):
        return a, b
    if valid_hcm_coordinate(b, a):
        return b, a
    return None


def local_search(db: Session, q: str, limit: int = 8, include_private: bool = False) -> list[dict]:
    out = []
    for a in db.scalars(select(AdministrativeArea).where(contains(AdministrativeArea.name, q)).limit(limit)):
        out.append({"type": "area", "id": a.id, "label": a.name, "lat": a.centroid_lat, "lon": a.centroid_lon})
    for s in db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None), or_(
            contains(MonitoringStation.name, q), contains(MonitoringStation.code, q),
            contains(MonitoringStation.address, q))).limit(limit)):
        out.append({"type": "station", "id": s.id, "label": f"{s.name} ({s.code})", "sub": s.address,
                    "lat": s.latitude, "lon": s.longitude})
    cams = select(Camera).where(Camera.deleted_at.is_(None), or_(contains(Camera.name, q), contains(Camera.code, q)))
    if not include_private:
        cams = cams.where(Camera.is_public.is_(True))
    for c in db.scalars(cams.limit(limit)):
        out.append({"type": "camera", "id": c.id, "label": c.name, "lat": c.latitude, "lon": c.longitude})
    seen = set()
    for e in db.scalars(select(HistoricalFloodEvent).where(contains(HistoricalFloodEvent.location_name, q))
                        .order_by(HistoricalFloodEvent.started_at.desc()).limit(limit * 3)):
        if e.location_name in seen:
            continue
        seen.add(e.location_name)
        out.append({"type": "flood_point", "id": e.id, "label": f"Điểm ngập: {e.location_name}",
                    "lat": e.latitude, "lon": e.longitude})
    return out[: limit * 2]


def geocode(q: str, limit: int = 5, layer: str | None = None) -> list[dict]:
    """Photon (dữ liệu OSM): ưu tiên kết quả trong khung TP.HCM."""
    key = f"{layer}|{q.strip().lower()}"
    if key in _cache:
        return _cache[key]
    s = get_settings()
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            params = {"q": q, "limit": limit, "lat": 10.78, "lon": 106.70, "bbox": BBOX}
            if layer:
                params["layer"] = layer
            r = httpx.get(f"{s.geocoder_url}/api/", timeout=8, headers={"User-Agent": s.external_user_agent},
                          params=params)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return []  # dịch vụ ngoài lỗi -> chỉ trả kết quả nội bộ (không cache để thử lại)
    res = []
    for f in data.get("features", []):
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"][:2]
        if not valid_hcm_coordinate(lat, lon):
            continue
        parts = [p.get("name"), p.get("street") if p.get("street") != p.get("name") else None, p.get("district"),
                 p.get("city")]
        res.append({"type": "address", "label": ", ".join(x for x in parts if x)[:200], "lat": lat, "lon": lon})
    if len(_cache) > 1000:
        _cache.clear()
    _cache[key] = res
    return res


def search(db: Session, q: str, include_private: bool, use_geocoder: bool = True) -> dict:
    q = q.strip()[:120]
    coord = parse_coordinates(q)
    results = []
    if coord:
        results.append({"type": "coordinate", "label": f"Toạ độ {coord[0]:.5f}, {coord[1]:.5f}",
                        "lat": coord[0], "lon": coord[1]})
    elif len(q) >= 2:
        results = local_search(db, q, include_private=include_private)
        if use_geocoder and len(q) >= 3 and len(results) < 5:
            results += geocode(q)
    return {"query": q, "results": results,
            "attribution": "Địa chỉ: © OpenStreetMap contributors (Photon/komoot)"}
