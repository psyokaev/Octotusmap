"""Trang Bản đồ (MapPage.tsx): bản đồ Folium phủ kín trang, panel/chip lớp/thanh giờ nổi trên bản đồ như bản React."""
import hashlib
import json
import re

import api
import auth
import folium
import streamlit as st
from common import refresh
from jinja2 import Template
from streamlit_folium import st_folium

from views import map_layers as ml
from views import map_panels as mp

HORIZONS = list(range(7))
LAYERS = {"risk": "Nguy cơ ngập", "alerts": "Cảnh báo", "rain": "Mưa", "hotspots": "Điểm ngập thường xuyên",
          "reports": "Báo cáo ngập",
          "cameras": "Camera", "boundary": "Ranh giới"}
DEFAULT_LAYERS = ["risk", "alerts", "rain", "hotspots", "reports", "boundary"]
ATTRIBUTION = "© OpenStreetMap contributors · nền HOT, OSM France"
KINDS = (("Báo cáo ngập", "report"), ("Điểm ngập thường xuyên", "hotspot"), ("Camera", "camera"), ("Trạm", "station"),
         ("Cảnh báo", "alert"))
ENDPOINTS = (("Điểm đi:", "m-start"), ("Điểm đến:", "m-end"))


class FullHeight(folium.MacroElement):
    """streamlit_folium gán cứng height px cho map_div: cho bản đồ cao bằng iframe; bỏ khung focus của vùng tô màu."""
    _template = Template("""{% macro script(this, kwargs) %}
    (function (map) {
      map.getContainer().style.height = "100vh";
      // trình duyệt vẽ khung chữ nhật quanh vùng quận/phường vừa bấm (focus của SVG): bỏ đi
      document.head.insertAdjacentHTML("beforeend", "<style>.leaflet-interactive:focus{outline:none}</style>");
      map.invalidateSize();
      window.addEventListener("resize", function () { map.invalidateSize(); });
      // kéo thả điểm đi/đến: thả xong thì "bấm" vào marker để st_folium gửi toạ độ mới về Python
      map.on("layeradd", function (e) {
        var l = e.layer;
        if (l.dragging && l.options.draggable && !l._dropHook) {
          l._dropHook = true;
          l.on("dragend", function () { l.fire("click", {latlng: l.getLatLng()}); });
        }
      });
      // nút "Vị trí của tôi": định vị MỘT lần (không theo dõi liên tục, tránh chạy lại trang liên tục),
      // xong thì coi như bấm bản đồ tại đó (xem chi tiết / đặt điểm đi)
      var Locate = L.Control.extend({options: {position: "bottomright"}, onAdd: function () {
        var a = L.DomUtil.create("a", "leaflet-bar octo-locate");
        a.href = "#"; a.title = "Vị trí của tôi"; a.innerHTML = "&#9678;";
        a.setAttribute("role", "button"); a.setAttribute("aria-label", "Vị trí của tôi");
        a.style.cssText = "display:block;width:34px;height:34px;line-height:34px;text-align:center;font-size:20px;" +
          "background:#fff;color:#1B2B36;cursor:pointer;text-decoration:none";
        L.DomEvent.on(a, "click", function (e) {
          L.DomEvent.stop(e);
          map.locate({setView: false, enableHighAccuracy: true, timeout: 10000, maximumAge: 60000});
        });
        return a;
      }});
      new Locate().addTo(map);
      map.on("locationfound", function (e) {
        map.flyTo(e.latlng, 16);
        // lệch ~1 cm để Python không coi là lần bấm cũ (chống lặp theo toạ độ) khi bấm nút lần nữa ở cùng chỗ
        var j = (Math.random() - 0.5) * 2e-7;
        map.fire("click", {latlng: L.latLng(e.latlng.lat + j, e.latlng.lng + j)});
      });
      map.on("locationerror", function () {
        var d = document.createElement("div");
        d.textContent = "Không lấy được vị trí: hãy cho phép trình duyệt truy cập vị trí rồi thử lại.";
        d.style.cssText = "position:absolute;right:56px;bottom:24px;z-index:1000;background:#fff;color:#C62828;" +
          "padding:6px 10px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.2);font:13px sans-serif";
        map.getContainer().appendChild(d);
        setTimeout(function () { d.remove(); }, 5000);
      });
    })({{ this._parent.get_name() }});
    {% endmacro %}""")


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
    # tile.openstreetmap.org bị chặn ở mạng phát triển (Carto cần API key); dùng OSM France, cùng dữ liệu OSM
    m = folium.Map(location=ml.CENTER, zoom_start=11, control_scale=True, tiles=None, zoom_control="bottomright")
    folium.TileLayer("https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png", name="Nền",
                     attr=ATTRIBUTION, subdomains="abc", max_zoom=19).add_to(m)
    FullHeight().add_to(m)
    ml.add_areas(m, d["risk"], "risk" in layers, "boundary" in layers)
    if "alerts" in layers:
        ml.add_alerts(m, d["alerts"])
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


def view_prop(data: dict, layers: list[str]) -> tuple:
    """(center, zoom) truyền cho st_folium.

    st_folium gọi setView mỗi khi center/zoom khác lần truyền trước. Không được truyền lại vị trí component vừa
    trả về: người dùng kéo tiếp trong lúc trang chạy lại thì bản đồ bị giật về vị trí cũ. Chỉ đổi giá trị khi
    chủ động di chuyển (go_to) hoặc khi dữ liệu đổi (script đổi -> component dựng lại, cần giữ vị trí người dùng).
    """
    s = st.session_state
    sig = hashlib.md5(json.dumps([data, layers, s.get("m-sim-point")], sort_keys=True, default=str).encode()).hexdigest()
    if s.pop("m-goto", False):
        s["m-sig"] = sig
    elif sig != s.get("m-sig"):
        s["m-sig"] = sig
        if s.get("m-view"):
            s["m-prop"] = s["m-view"]
    return s.get("m-prop") or (None, None)


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
        drop = next((k for prefix, k in ENDPOINTS if tip.startswith(prefix)), None)
        if drop:  # kéo thả điểm đi/đến (hoặc bấm lại vào nó): đặt lại điểm theo vị trí marker
            s[drop] = _place(obj["lat"], obj["lng"])
            mp.open_panel("Chỉ đường")
            return True
        hit = re.search(r" · mã (-?\d+)$", tip.strip())  # id âm: cảnh báo mô phỏng
        kind = next((k for prefix, k in KINDS if tip.startswith(prefix)), None)
        if hit and kind and not (panel == "Chỉ đường" and not (s.get("m-start") and s.get("m-end"))) and panel != "Mô phỏng":
            s["m-sel"] = {"kind": kind, "id": int(hit.group(1))}
            mp.open_panel("Chi tiết")
            return True
        if hit:
            loc = (obj["lat"], obj["lng"])  # điểm đánh dấu khi đang chọn điểm chỉ đường/mô phỏng
    # bấm trúng vùng tô màu quận/phường (tooltip không có mã) vẫn là bấm bản đồ
    if loc is None and click and click_key != s.get("m-seen-click"):
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
    if s.get("m-horizon") is None:  # segmented_control trả None khi bấm lại mốc đang chọn
        s["m-horizon"] = s.get("m-hdir", 0)

    # Thứ tự khung trong DOM không quan trọng: m-side/m-chips/m-hours nổi trên bản đồ bằng CSS (style.css)
    page = st.container(key="m-page")
    with page:
        mapbox, side, chips, hours = (st.container(key=k) for k in ("m-mapbox", "m-side", "m-chips", "m-hours"))
    with chips:
        layers = st.pills("Lớp bản đồ", list(LAYERS), selection_mode="multi",
                          default=None if "m-layers" in s else DEFAULT_LAYERS,  # trang Camera có thể đặt sẵn
                          format_func=LAYERS.get, key="m-layers", label_visibility="collapsed")
    with hours:
        horizon = st.segmented_control("Nguy cơ ngập theo giờ", HORIZONS, key="m-horizon", on_change=_sync_hdir,
                                       format_func=lambda h: "Nay" if h == 0 else f"+{h}h")

    risk = _fetch(errors, "/gis/risk-layers", {"horizon": horizon}, ttl=30, default={"features": []})
    feats = _fetch(errors, "/gis/features", {"horizon": horizon}, ttl=30, default={"stations": {"features": []}, "alerts": {"features": []}})
    latest = _fetch(errors, "/forecasts/latest", ttl=30, default=[])
    hotspots = _fetch(errors, "/gis/hotspots", ttl=3600, default=[])
    reports = _fetch(errors, "/reports/active", ttl=20, default=[])
    cams = _fetch(errors, "/gis/traffic-cameras", ttl=3600, default={"features": []}) if "cameras" in layers else {"features": []}
    sims = _fetch(errors, "/gis/simulations", ttl=10, default=[]) if auth.is_staff() else []
    start, end = s.get("m-start"), s.get("m-end")
    route = mp.get_route(start, end, horizon) if start and end and s.get("m-panel") == "Chỉ đường" else None

    data = {"risk": risk, "alerts": feats["alerts"], "stations": feats["stations"], "hotspots": hotspots, "reports": reports, "cameras": cams, "sims": sims,
            "route": route, "start": start, "end": end, "selected": s.get("m-sel-route", route["recommended_index"] if route else 0)}
    m = build_map(data, layers)
    if s.pop("m-fit", False) and route:  # st_folium bỏ fitBounds của Folium: tự tính tâm/zoom rồi di chuyển chủ động
        (lat0, lon0), (lat1, lon1) = ml.route_bounds(next(x for x in route["routes"] if x["index"] == data["selected"]))
        mp.go_to((lat0 + lat1) / 2, (lon0 + lon1) / 2, ml.zoom_for(lat1 - lat0, lon1 - lon0))
    center, zoom = view_prop(data, layers)
    with mapbox:
        out = st_folium(m, key="m-map", height=760, use_container_width=True,
                        returned_objects=["last_clicked", "last_object_clicked", "last_object_clicked_tooltip", "center", "zoom"],
                        center=center, zoom=zoom)
    if out:
        if out.get("center"):
            s["m-view"] = ((out["center"]["lat"], out["center"]["lng"]), out.get("zoom"))
        if handle_interaction(out):
            refresh()

    with side:
        if errors:
            st.error(" · ".join(dict.fromkeys(e.message for e in errors)))
        with st.container(key="m-searchbox"):
            r = mp.place_search("m-search", "Tìm kiếm địa điểm", "Tìm đường, quận, điểm ngập, toạ độ…")
        if r:
            mp.go_to(r["lat"], r["lon"], 12 if r["type"] == "area" else 15)
            s["m-point"], s["m-sel"] = {"lat": r["lat"], "lon": r["lon"], "label": r["label"]}, None
            if r["type"] == "station" and r.get("id"):
                s["m-sel"] = {"kind": "station", "id": r["id"]}
            mp.open_panel("Chi tiết")
            refresh()
        panel = st.radio("Panel", panels, horizontal=True, key="m-panel", label_visibility="collapsed")
        if panel == "Tình hình":
            mp.situation(risk, len(feats["alerts"]["features"]), horizon, latest)
        elif panel == "Chi tiết":
            _detail(reports, hotspots, cams, horizon, feats["alerts"])
        elif panel == "Chỉ đường":
            mp.directions_panel(start, end, route)
        elif panel == "Báo cáo ngập":
            mp.reports_panel(reports)
        else:
            mp.simulation_panel(sims)
        st.caption("Ranh giới: geoBoundaries, GADM · Mưa/triều: mô hình Open-Meteo CC BY 4.0, không phải trạm đo. "
                   "Trạng thái ngập là ước tính, chưa kiểm chứng với ngập thật. Camera: Cổng thông tin giao thông TP.HCM.")


def _detail(reports: list, hotspots: list, cams: dict, horizon: int, alerts: dict) -> None:
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
        elif kind == "alert" and (a := next((f["properties"] for f in alerts["features"] if f["properties"]["id"] == i), None)):
            mp.alert_brief(a)
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
    _body()
