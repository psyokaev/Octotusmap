"""Chỉ đường (OSRM) + đánh giá NGẬP ƯỚC TÍNH theo từng đoạn ~200 m.

Mỗi đoạn: độ cao DEM (Open-Meteo), mưa hiện tại/dự báo tại điểm lưới gần nhất, triều, khoảng cách tới
báo cáo ngập còn hiệu lực của người dân và điểm ngập thường xuyên đã công bố -> flood_index.
Chỉ mang tính tham khảo: không khẳng định đoạn đường an toàn.
"""

import math
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.spatial import valid_hcm_coordinate
from app.models import AdministrativeArea, FloodHotspot, FloodSimulation, Forecast
from app.repositories import observations as obs_repo
from app.services import flood_index, report_service
from app.services import openmeteo_service as om

SEGMENT_M = 200
REPORT_RADIUS_M = 100
HOTSPOT_RADIUS_M = 150
TIDE_CENTROID_M = 1500
MAX_KM = 80
DISCLAIMER = ("Trạng thái ngập là ƯỚC TÍNH từ mưa mô hình (Open-Meteo), triều, độ cao DEM 90 m, điểm ngập đã công bố "
              "và báo cáo của người dân — không phải đo đạc tại chỗ. Không đảm bảo đoạn đường an toàn; "
              "tuân thủ hướng dẫn của lực lượng chức năng.")


def dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Khoảng cách (m) giữa 2 điểm (lon, lat) — xấp xỉ equirectangular, đủ chính xác ở quy mô đô thị."""
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return 6371000 * math.hypot(math.radians(b[0] - a[0]) * k, math.radians(b[1] - a[1]))


def split_line(coords: list[list[float]], step_m: float = SEGMENT_M) -> list[list[list[float]]]:
    """Chia polyline thành các đoạn liên tiếp dài ~step_m (giữ nguyên đỉnh gốc, không nội suy)."""
    segs, cur, acc = [], [coords[0]], 0.0
    for p, q in zip(coords, coords[1:], strict=False):
        acc += dist_m(p, q)
        cur.append(q)
        if acc >= step_m:
            segs.append(cur)
            cur, acc = [q], 0.0
    if len(cur) > 1:
        segs.append(cur)
    return segs or [coords]


MODIFIER = {"left": "trái", "right": "phải", "slight left": "chếch trái", "slight right": "chếch phải",
            "sharp left": "gắt trái", "sharp right": "gắt phải", "straight": "thẳng", "uturn": "quay đầu"}


def instruction(step: dict) -> str:
    m = step.get("maneuver", {})
    t, mod, name = m.get("type", ""), m.get("modifier", ""), step.get("name") or ""
    side = MODIFIER.get(mod, "")
    into = f" vào {name}" if name else ""
    if t == "depart":
        return f"Xuất phát{(' trên ' + name) if name else ''}"
    if t == "arrive":
        return "Đến nơi" + (f" ({'bên ' + side})" if side in ("trái", "phải") else "")
    if t in ("roundabout", "rotary"):
        return f"Vào vòng xoay, đi lối ra thứ {m.get('exit', 1)}{into}"
    if t == "fork":
        return f"Giữ bên {side.replace('chếch ', '')}{into}"
    if t in ("on ramp", "off ramp"):
        return f"{'Lên' if t == 'on ramp' else 'Rời'} đường dẫn{into}"
    if t == "merge":
        return f"Nhập làn{into}"
    if mod == "uturn":
        return f"Quay đầu{into}"
    if mod == "straight" or t in ("continue", "new name"):
        return f"Đi thẳng{into}"
    return f"Rẽ {side}{into}" if side else f"Tiếp tục{into}"


def _rain_context(db: Session, horizon: int) -> dict[int, tuple[float, float, float, float]]:
    """{station_id: (lat, lon, mưa_1h, mưa_3h)} tại mốc horizon cho các điểm lưới mưa."""
    rain_sts, _ = om.stations(db)
    issued = db.scalar(select(func.max(Forecast.issued_at)))
    now = obs_repo.latest_time(db) or issued
    out = {}
    for st in rain_sts:
        past = obs_repo.series(db, st.id, now - timedelta(hours=2), now)["rain_mm"].fillna(0).tolist()
        fut = []
        if horizon and issued:
            fut = [f.rainfall_mm for f in db.scalars(select(Forecast).where(
                Forecast.station_id == st.id, Forecast.issued_at == issued, Forecast.horizon_h <= horizon)
                .order_by(Forecast.horizon_h))]
        seq = past + fut
        out[st.id] = (st.latitude, st.longitude, seq[-1] if seq else 0.0, sum(seq[-3:]))
    return out


def classify_segments(segs, rain_ctx, tide_ratio, elevations, hotspots, reports, sims=(), tide_centroids=()):
    """Phân loại từng đoạn; trả danh sách dict (geometry, status, probability, reasons, length_m)."""
    out = []
    for seg, elev in zip(segs, elevations, strict=True):
        mid = seg[len(seg) // 2]
        near = min(rain_ctx.values(), key=lambda r: dist_m(mid, (r[1], r[0]))) if rain_ctx else (0, 0, 0.0, 0.0)
        hot = any(dist_m(mid, h) <= HOTSPOT_RADIUS_M for h in hotspots)
        rep = any(min(dist_m(p, r) for p in seg) <= REPORT_RADIUS_M for r in reports)
        x = flood_index.FloodInputs(near[2], near[3], tide_ratio, elev, hot)
        p = flood_index.probability(x)
        low = elev is not None and elev < flood_index.LOW_ELEVATION_M
        # shortcut: gần đúng theo tâm phường để khỏi truy vấn không gian từng đoạn
        tide_d = flood_index.tide_depth_cm(tide_ratio) if low and any(
            dist_m(mid, c) <= TIDE_CENTROID_M for c in tide_centroids) else 0.0
        rain_d = flood_index.rain_depth_cm(near[3]) if low or hot else 0.0
        raw = max(tide_d, rain_d)
        depth = flood_index.round_depth(raw)
        cause = "TIDE" if tide_d >= rain_d else "RAIN"
        st, why = flood_index.status(p, rep), flood_index.reasons(x, rep, depth, cause)
        if not rep and depth:
            st = "LIKELY_FLOODED" if raw >= 20 else "AT_RISK" if st == "DRY" else st
        hit = [s for s in sims if min(dist_m(q, (s.longitude, s.latitude)) for q in seg) <= s.radius_m]
        if hit:
            st = "REPORTED_FLOODED" if rep else "LIKELY_FLOODED"
            why = [f"MÔ PHỎNG: ngập {max(s.depth_cm for s in hit)} cm", *why]
        out.append({"coords": seg, "status": st, "probability": round(p, 3), "reasons": why, "elevation_m": elev,
                    "length_m": round(sum(dist_m(a, b) for a, b in zip(seg, seg[1:], strict=False)))})
    return out


def _merge(segments: list[dict]) -> list[dict]:
    """Gộp các đoạn liền kề cùng trạng thái để giảm số feature trên bản đồ."""
    merged: list[dict] = []
    for s in segments:
        if merged and merged[-1]["status"] == s["status"]:
            m = merged[-1]
            m["coords"] += s["coords"][1:]
            m["length_m"] += s["length_m"]
            m["probability"] = max(m["probability"], s["probability"])
            m["reasons"] = list(dict.fromkeys(m["reasons"] + s["reasons"]))
        else:
            merged.append({**s, "coords": list(s["coords"])})
    return merged


def route(db: Session, start: tuple[float, float], end: tuple[float, float], horizon: int = 0,
          include_simulations: bool = False) -> dict:
    for lon, lat in (start, end):
        if not valid_hcm_coordinate(lat, lon):
            raise AppError(422, "OUT_OF_AREA", "Điểm đi/đến nằm ngoài TP.HCM")
    if dist_m(start, end) > MAX_KM * 1000:
        raise AppError(422, "TOO_FAR", f"Khoảng cách tối đa {MAX_KM} km")
    s = get_settings()
    try:
        r = httpx.get(f"{s.osrm_url}/route/v1/driving/{start[0]},{start[1]};{end[0]},{end[1]}", timeout=15,
                      headers={"User-Agent": s.external_user_agent},
                      params={"alternatives": "true", "steps": "true", "geometries": "geojson", "overview": "full"})
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise AppError(503, "ROUTING_UNAVAILABLE", "Dịch vụ chỉ đường tạm thời không khả dụng") from e
    if data.get("code") != "Ok" or not data.get("routes"):
        raise AppError(404, "NO_ROUTE", "Không tìm được tuyến đường")

    issued = obs_repo.latest_time(db)
    tide = om.tide_ratio(om.tide_at(db, issued + timedelta(hours=horizon)) if issued else None, om.tide_stats(db))
    rain_ctx = _rain_context(db, horizon)
    hotspots = [(h.longitude, h.latitude) for h in db.scalars(select(FloodHotspot))]
    reports = [(x.longitude, x.latitude) for x in report_service.active(db)]
    sims = list(db.scalars(select(FloodSimulation))) if include_simulations else []
    from app.services.risk_service import tide_exposed_wards  # import trong hàm để tránh vòng

    ex_ids = tide_exposed_wards(db)
    centroids = [(a.centroid_lon, a.centroid_lat) for a in db.scalars(
        select(AdministrativeArea).where(AdministrativeArea.id.in_(ex_ids)))] if ex_ids else []

    routes, missing_elev = [], 0
    all_segs = [split_line(rt["geometry"]["coordinates"]) for rt in data["routes"][:3]]
    mids = [seg[len(seg) // 2] for segs in all_segs for seg in segs]
    elev_iter = iter(om.elevations([(m[1], m[0]) for m in mids]))
    for i, (rt, segs) in enumerate(zip(data["routes"][:3], all_segs, strict=True)):
        elevs = [next(elev_iter) for _ in segs]
        missing_elev += sum(e is None for e in elevs)
        classified = classify_segments(segs, rain_ctx, tide, elevs, hotspots, reports, sims, centroids)
        km = {st: round(sum(c["length_m"] for c in classified if c["status"] == st) / 1000, 2)
              for st in ("DRY", "AT_RISK", "LIKELY_FLOODED", "REPORTED_FLOODED")}
        steps = [{"instruction": instruction(st), "name": st.get("name") or "", "distance_m": round(st["distance"]),
                  "duration_s": round(st["duration"]), "location": st["maneuver"]["location"]}
                 for leg in rt["legs"] for st in leg["steps"]]
        routes.append({
            "index": i, "distance_m": rt["distance"], "duration_s": rt["duration"], "geometry": rt["geometry"],
            "segments": [{"geometry": {"type": "LineString", "coordinates": c["coords"]}, "status": c["status"],
                          "probability": c["probability"], "length_m": c["length_m"], "reasons": c["reasons"]}
                         for c in _merge(classified)],
            "summary": {"km_by_status": km, "flooded_km": round(km["LIKELY_FLOODED"] + km["REPORTED_FLOODED"], 2),
                        "at_risk_km": km["AT_RISK"],
                        "max_probability": max((c["probability"] for c in classified), default=0)},
            "steps": steps,
        })
    best = min(routes, key=lambda x: (x["summary"]["flooded_km"], x["summary"]["at_risk_km"] > 0.5, x["duration_s"]))
    return {"routes": routes, "recommended_index": best["index"], "horizon_h": horizon,
            "data_time": issued.isoformat() + "Z" if issued else None, "tide_ratio": tide,
            "active_reports": len(reports), "disclaimer": DISCLAIMER,
            "elevation_missing_ratio": round(missing_elev / max(len(mids), 1), 3),
            "attribution": "Đường: © OpenStreetMap contributors (OSRM). Mưa/triều/độ cao: Open-Meteo (CC BY 4.0)."}


