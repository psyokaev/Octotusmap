"""Dựng các lớp Folium cho trang Bản đồ (thuần Python, không gọi API)."""
import math
from html import escape

import folium
from common import RISK, SEVERITY, STATUS, flood_cause, risk_of

CENTER = (10.78, 106.70)
LINE = "#5F6368"
_PX = {"bubbling_mouse_events": False}  # click marker không lan thành click bản đồ


def area_tooltip(p: dict) -> str:
    cause = flood_cause(p.get("cause"), p.get("depth_cm"))
    return escape(f"{p['name']} · {RISK[risk_of(p['risk_level'])]['label']}" + (f" · {cause}" if cause else ""))


def add_areas(m: folium.Map, fc: dict, show_risk: bool, show_boundary: bool) -> None:
    """Phường tô theo mức: THẤP xanh rất nhạt, TRUNG BÌNH/CAO đậm hơn; quận chỉ vẽ viền."""
    feats = [{**f, "properties": {**f["properties"], "tip": area_tooltip(f["properties"])}} for f in fc.get("features", [])]
    wards = [f for f in feats if f["properties"]["level"] == "WARD"]
    districts = [f for f in feats if f["properties"]["level"] == "DISTRICT"]

    def ward_style(f):
        p = f["properties"]
        lv = p["risk_level"]
        opacity = (0.22 if lv in ("MEDIUM", "HIGH") else 0.06 if lv == "LOW" else 0) if show_risk else 0
        return {"fill": True, "fillColor": RISK[risk_of(lv)]["color"], "fillOpacity": opacity,
                "color": LINE, "weight": 0.7 if show_boundary else 0, "dashArray": "2 2"}

    if wards:
        folium.GeoJson({"type": "FeatureCollection", "features": wards}, name="wards", style_function=ward_style,
                       tooltip=folium.GeoJsonTooltip(fields=["tip"], labels=False)).add_to(m)
    if districts and show_boundary:
        folium.GeoJson({"type": "FeatureCollection", "features": districts}, name="districts",
                       style_function=lambda f: {"fill": False, "color": LINE, "weight": 2}).add_to(m)


def _rain_color(mm: float) -> str:
    return "#0D47A1" if mm >= 20 else "#1C7CB5" if mm >= 5 else "#4FB0E6" if mm >= 1 else "#9AA0A6"


def add_stations(m: folium.Map, fc: dict) -> None:
    for f in fc.get("features", []):
        p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
        rain = p.get("rainfall_mm") or 0
        rain_station = p.get("station_type") == "RAIN"
        folium.CircleMarker(
            (lat, lon), radius=4 + min(rain, 20) * 9 / 20 if rain_station else 7, color="#fff", weight=1.5, fill=True,
            fill_color=_rain_color(rain) if rain_station else "#1C7CB5", fill_opacity=0.95,
            tooltip=f"Trạm {escape(str(p['code']))} · mã {int(p['id'])}", **_PX).add_to(m)


def add_hotspots(m: folium.Map, rows: list[dict]) -> None:
    for h in rows:
        folium.CircleMarker((h["latitude"], h["longitude"]), radius=5, color="#5F3B00", weight=1.5, fill=True, fill_color="#F29900",
                            fill_opacity=1, tooltip=f"Điểm ngập thường xuyên: {escape(str(h['name']))} · mã {int(h['id'])}", **_PX).add_to(m)


def add_reports(m: folium.Map, rows: list[dict]) -> None:
    for r in rows:
        folium.CircleMarker((r["latitude"], r["longitude"]), radius=9, color="#fff", weight=3, fill=True, fill_color="#8E24AA",
                            fill_opacity=1, tooltip=f"Báo cáo ngập: {escape(str(SEVERITY.get(r['severity'], r['severity'])))} · mã {int(r['id'])}", **_PX).add_to(m)


def add_cameras(m: folium.Map, fc: dict) -> None:
    for f in fc.get("features", []):
        lon, lat = f["geometry"]["coordinates"]
        folium.CircleMarker((lat, lon), radius=4, color="#fff", weight=1, fill=True, fill_color="#0E2A3B", fill_opacity=1,
                            tooltip=f"Camera: {escape(str(f['properties']['name']))} · mã {int(f['properties']['id'])}", **_PX).add_to(m)


def circle_polygon(lon: float, lat: float, radius_m: float, steps: int = 64) -> list[tuple[float, float]]:
    """Vòng tròn xấp xỉ (lat, lon) để vẽ vùng ngập mô phỏng."""
    d_lat = radius_m / 111_320
    d_lon = d_lat / math.cos(math.radians(lat))
    return [(lat + d_lat * math.sin(a), lon + d_lon * math.cos(a)) for a in (2 * math.pi * i / steps for i in range(steps + 1))]


def add_simulations(m: folium.Map, rows: list[dict]) -> None:
    for s in rows:
        label = s.get("label") or f"MÔ PHỎNG {s['depth_cm']} cm"
        folium.Polygon(circle_polygon(s["longitude"], s["latitude"], s["radius_m"]), color="#00695C", weight=2, dash_array="6 3",
                       fill=True, fill_color="#00897B", fill_opacity=0.3, tooltip=escape(str(label))).add_to(m)


def add_routes(m: folium.Map, routes: list[dict], selected: int) -> None:
    """Tuyến khác màu xám, tuyến chọn màu xanh, đoạn không khô tô màu theo trạng thái (nét đứt)."""
    chosen = next((r for r in routes if r["index"] == selected), None)
    for r in routes:
        if r is not chosen:
            folium.PolyLine([(y, x) for x, y in r["geometry"]["coordinates"]], color="#9AA0A6", weight=6).add_to(m)
    if not chosen:
        return
    pts = [(y, x) for x, y in chosen["geometry"]["coordinates"]]
    folium.PolyLine(pts, color="#fff", weight=11).add_to(m)
    folium.PolyLine(pts, color="#1A73E8", weight=7).add_to(m)
    for s in chosen["segments"]:
        if s["status"] == "DRY":
            continue
        why = escape("; ".join(s.get("reasons") or []))
        folium.PolyLine([(y, x) for x, y in s["geometry"]["coordinates"]], color=STATUS[s["status"]]["color"], weight=8,
                        dash_array="8 4", tooltip=STATUS[s["status"]]["label"] + (f": {why}" if why else "")).add_to(m)


def add_endpoints(m: folium.Map, start: dict | None, end: dict | None) -> None:
    for p, color, name in ((start, "green", "Điểm đi"), (end, "red", "Điểm đến")):
        if p:
            folium.Marker((p["lat"], p["lon"]), icon=folium.Icon(color=color), tooltip=f"{name}: {escape(str(p['label']))}").add_to(m)


def route_bounds(route: dict) -> list[list[float]]:
    ys = [c[1] for c in route["geometry"]["coordinates"]]
    xs = [c[0] for c in route["geometry"]["coordinates"]]
    return [[min(ys), min(xs)], [max(ys), max(xs)]]


def centroid(geometry: dict) -> tuple[float, float]:
    """Trung bình các đỉnh (lon, lat) của hình học bất kỳ."""
    pts: list = []

    def walk(x):
        if x and isinstance(x[0], (int, float)):
            pts.append(x)
        else:
            for y in x:
                walk(y)

    walk(geometry["coordinates"])
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
