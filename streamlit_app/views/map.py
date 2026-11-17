"""Trang Bản đồ (MapPage.tsx): Folium + streamlit_folium, panel bên phải thay cho side panel của bản React."""
import re

import api
import auth
import folium
import streamlit as st
from common import refresh
from streamlit_folium import st_folium

from views import map_layers as ml
from views import map_panels as mp

HORIZONS = list(range(7))
LAYERS = {"risk": "Nguy cơ ngập", "rain": "Mưa", "hotspots": "Điểm ngập thường xuyên", "reports": "Báo cáo ngập",
          "cameras": "Camera", "boundary": "Ranh giới"}
DEFAULT_LAYERS = ["risk", "rain", "hotspots", "reports", "boundary"]
KINDS = (("Báo cáo ngập", "report"), ("Điểm ngập thường xuyên", "hotspot"), ("Camera", "camera"), ("Trạm", "station"))


def _sync_hdir() -> None:
    st.session_state["m-hdir"] = st.session_state["m-horizon"]


def _fetch(errors: list, path: str, params=None, ttl: float = 0, default=None):
    try:
        return api.get(path, params, ttl=ttl)
    except api.ApiError as e:
        errors.append(e)
        return default


def build_map(d: dict, layers: list[str]) -> folium.Map:
    """Dựng bản đồ từ dữ liệu đã tải. `d` có: risk, stations, hotspots, reports, cameras, sims, route, start, end, selected."""
    st_ = st.session_state
    m = folium.Map(location=ml.CENTER, zoom_start=11, control_scale=True, tiles="OpenStreetMap")
    ml.add_areas(m, d["risk"], "risk" in layers, "boundary" in layers)
    if "rain" in layers:
        ml.add_stations(m, d["stations"])
    if "hotspots" in layers:
        ml.add_hotspots(m, d["hotspots"])
    if "reports" in layers:
        ml.add_reports(m, d["reports"])
    if "cameras" in layers:
        ml.add_cameras(m, d["cameras"])
    sims = list(d["sims"])
    if st_.get("m-panel") == "Mô phỏng" and st_.get("m-sim-point"):
        p = st_["m-sim-point"]
        sims.append({"longitude": p["lon"], "latitude": p["lat"], "radius_m": st_.get("m-sim-radius", 500), "label": "Vùng sẽ tạo", "depth_cm": 0})
    ml.add_simulations(m, sims)
    if d["route"]:
        ml.add_routes(m, d["route"]["routes"], d["selected"])
    ml.add_endpoints(m, d["start"], d["end"])
    return m


def _place(lat: float, lon: float) -> dict:
    return {"label": f"{lat:.5f}, {lon:.5f}", "lon": lon, "lat": lat}


def handle_interaction(out: dict) -> bool:
    """Xử lý click bản đồ/điểm đánh dấu theo panel đang mở. Trả True nếu trạng thái đổi (cần vẽ lại)."""
    s = st.session_state
    obj, tip = out.get("last_object_clicked"), out.get("last_object_clicked_tooltip") or ""
    click = out.get("last_clicked")
    obj_key, click_key = repr((obj, tip)), repr(click)
    panel = s.get("m-panel")
    loc = None
    if obj and obj_key != s.get("m-seen-obj"):
        s["m-seen-obj"] = obj_key
        hit = re.search(r" · mã (\d+)$", tip.strip())
        kind = next((k for prefix, k in KINDS if tip.startswith(prefix)), None)
        loc = (obj["lat"], obj["lng"])
        if hit and kind and not (panel == "Chỉ đường" and not (s.get("m-start") and s.get("m-end"))) and panel != "Mô phỏng":
            s["m-sel"] = {"kind": kind, "id": int(hit.group(1))}
            mp.open_panel("Chi tiết")
            return True
        if not hit:
            loc = None  # tooltip khu vực: để click bản đồ đi kèm xử lý
    elif click and click_key != s.get("m-seen-click"):
        loc = (click["lat"], click["lng"])
    if click:
        s["m-seen-click"] = click_key
    if not loc:
        return False
    lat, lon = loc
    if panel == "Chỉ đường":
        if not s.get("m-start"):
            s["m-start"] = _place(lat, lon)
        elif not s.get("m-end"):
            s["m-end"] = _place(lat, lon)
        else:
            return False
    elif panel == "Mô phỏng":
        s["m-sim-point"] = {"lat": lat, "lon": lon}
    else:
        s["m-point"], s["m-sel"] = {"lat": lat, "lon": lon, "label": None}, None
        mp.open_panel("Chi tiết")
    return True


@st.fragment(run_every=60)
def _body() -> None:
    s, admin, errors = st.session_state, auth.is_admin(), []
    if nxt := s.pop("m-panel-next", None):
        s["m-panel"] = nxt
    panels = ["Tình hình", "Chi tiết", "Chỉ đường", "Báo cáo ngập"] + (["Mô phỏng"] if admin else [])
    if s.get("m-panel") not in panels:
        s["m-panel"] = "Tình hình"

    c1, c2 = st.columns([3, 3])
    horizon = c1.select_slider("Mốc dự báo", HORIZONS, key="m-horizon", on_change=_sync_hdir,
                               format_func=lambda h: "Nay" if h == 0 else f"+{h}h")
    layers = c2.multiselect("Lớp bản đồ", list(LAYERS), default=DEFAULT_LAYERS, format_func=LAYERS.get, key="m-layers")
    left, right = st.columns([7, 4])

    risk = _fetch(errors, "/gis/risk-layers", {"horizon": horizon}, ttl=30, default={"features": []})
    feats = _fetch(errors, "/gis/features", {"horizon": horizon}, ttl=30, default={"stations": {"features": []}, "alerts": {"features": []}})
    latest = _fetch(errors, "/forecasts/latest", ttl=30, default=[])
    hotspots = _fetch(errors, "/gis/hotspots", ttl=3600, default=[])
    reports = _fetch(errors, "/reports/active", ttl=20, default=[])
    cams = _fetch(errors, "/gis/traffic-cameras", ttl=3600, default={"features": []}) if "cameras" in layers else {"features": []}
    sims = _fetch(errors, "/admin/simulations", default=[]) if admin else []
    start, end = s.get("m-start"), s.get("m-end")
    route = mp.get_route(start, end, horizon) if start and end and s.get("m-panel") == "Chỉ đường" else None
    if errors:
        st.error(" · ".join(dict.fromkeys(e.message for e in errors)))

    data = {"risk": risk, "stations": feats["stations"], "hotspots": hotspots, "reports": reports, "cameras": cams, "sims": sims,
            "route": route, "start": start, "end": end, "selected": s.get("m-sel-route", route["recommended_index"] if route else 0)}
    m = build_map(data, layers)
    fit = s.pop("m-fit", False) and route
    if fit:
        m.fit_bounds(ml.route_bounds(next(x for x in route["routes"] if x["index"] == data["selected"])))
    with left:
        with st.expander("Tìm kiếm địa điểm"):
            r = mp.place_search("m-search", "Tìm đường, quận, điểm ngập, toạ độ…", "Ví dụ: Thủ Đức hoặc 10.78, 106.70")
            if r:
                mp.go_to(r["lat"], r["lon"], 12 if r["type"] == "area" else 15)
                s["m-point"], s["m-sel"] = {"lat": r["lat"], "lon": r["lon"], "label": r["label"]}, None
                if r["type"] == "station" and r.get("id"):
                    s["m-sel"] = {"kind": "station", "id": r["id"]}
                mp.open_panel("Chi tiết")
                refresh()
        out = st_folium(m, key="m-map", height=620, use_container_width=True,
                        returned_objects=["last_clicked", "last_object_clicked", "last_object_clicked_tooltip", "center", "zoom"],
                        center=None if fit else s.get("m-center"), zoom=None if fit else s.get("m-zoom"))
        st.caption("Ranh giới: geoBoundaries, GADM · Mưa/triều: mô hình Open-Meteo CC BY 4.0, không phải trạm đo. "
                   "Trạng thái ngập là ước tính, chưa kiểm chứng với ngập thật. Camera: Cổng thông tin giao thông TP.HCM.")
    if out:
        if out.get("center") and not s.pop("m-skip", 0):
            s["m-center"], s["m-zoom"] = (out["center"]["lat"], out["center"]["lng"]), out.get("zoom")
        if handle_interaction(out):
            refresh()

    with right:
        panel = st.radio("Panel", panels, horizontal=True, key="m-panel", label_visibility="collapsed")
        if panel == "Tình hình":
            mp.situation(risk, len(feats["alerts"]["features"]), horizon, latest)
        elif panel == "Chi tiết":
            _detail(reports, hotspots, cams, horizon)
        elif panel == "Chỉ đường":
            mp.directions_panel(start, end, route)
        elif panel == "Báo cáo ngập":
            mp.reports_panel(reports)
        else:
            mp.simulation_panel(sims)


def _detail(reports: list, hotspots: list, cams: dict, horizon: int) -> None:
    s = st.session_state
    sel, pt = s.get("m-sel"), s.get("m-point")
    if sel:
        kind, i = sel["kind"], sel["id"]
        if kind == "report" and (r := next((x for x in reports if x["id"] == i), None)):
            st.subheader("Người dân báo ngập")
            mp.report_card(r)
        elif kind == "hotspot" and (h := next((x for x in hotspots if x["id"] == i), None)):
            mp.hotspot_detail(h)
        elif kind == "camera":
            f = next((x for x in cams["features"] if x["properties"]["id"] == i), None)
            name = f["properties"]["name"] if f else f"Camera {i}"
            st.subheader(name)
            mp.camera_view(i, name)
        elif kind == "station":
            mp.station_detail(i)
        else:
            st.caption("Đối tượng không còn hiệu lực.")
    elif pt:
        mp.point_detail(pt, horizon)
    else:
        st.caption("Bấm lên bản đồ hoặc dùng ô tìm kiếm để xem chi tiết một vị trí.")
    if cams["features"]:
        with st.expander("Xem ảnh camera giao thông"):
            names = {f["properties"]["id"]: f["properties"]["name"] for f in cams["features"]}
            cid = st.selectbox("Chọn camera", list(names), format_func=names.get, index=None, key="m-cam-pick")
            if cid:
                mp.camera_view(cid, names[cid])


def render() -> None:
    st.title("Bản đồ nguy cơ ngập TP.HCM")
    _body()
