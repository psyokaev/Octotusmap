"""Các panel bên phải trang Bản đồ: tình hình, chi tiết điểm, báo cáo, camera, chỉ đường, mô phỏng."""
import plotly.graph_objects as go
import streamlit as st

import api
import auth
import nav
from common import (
    RISK,
    RISK_RANK,
    SEVERITY,
    STATUS,
    flood_cause,
    fmt_distance,
    fmt_dt,
    fmt_duration,
    fmt_num,
    fmt_pct,
    refresh,
    risk_badge,
    risk_md,
    risk_of,
    risk_text,
    run_action,
    show_error,
    sim_badge,
)
from views.map_layers import centroid

SEARCH_TYPE = {"area": "Khu vực", "station": "Điểm đo", "camera": "Camera", "flood_point": "Điểm ngập", "address": "Địa chỉ", "coordinate": "Toạ độ"}
RECO = {
    "LOW": ["Tiếp tục theo dõi."],
    "MEDIUM": ["Tăng cường giám sát; kiểm tra khả năng thoát nước; chuẩn bị phương án ứng phó."],
    "HIGH": ["Ưu tiên xác minh hiện trường; hạn chế lưu thông qua khu vực trũng thấp; theo dõi thông tin chính thức."],
}
_STATUS_MD = {"DRY": "blue", "AT_RISK": "orange", "LIKELY_FLOODED": "red", "REPORTED_FLOODED": "violet"}


def open_panel(name: str) -> None:
    """Đổi panel ở lần chạy sau (không được ghi vào key của widget đã tạo)."""
    st.session_state["m-panel-next"] = name


def go_to(lat: float, lon: float, zoom: int = 14) -> None:
    """Chủ động di chuyển bản đồ ở lần chạy sau (xem map.view_prop)."""
    st.session_state["m-prop"] = ((lat, lon), zoom)
    st.session_state["m-goto"] = True


def place_search(key: str, label: str, placeholder: str) -> dict | None:
    """Ô tìm địa điểm (/search, gồm toạ độ). Trả về kết quả khi người dùng bấm Chọn."""
    q = st.text_input(label, key=f"{key}-q", placeholder=placeholder).strip()
    if len(q) < 2:
        return None
    try:
        data = api.get("/search", {"q": q}, ttl=60)
    except api.ApiError as e:
        show_error(e)
        return None
    res = data.get("results", [])
    if not res:
        st.caption(f"Không tìm thấy “{q}”")
        return None
    i = st.selectbox("Kết quả", range(len(res)), key=f"{key}-sel", label_visibility="collapsed",
                     format_func=lambda i: f"{SEARCH_TYPE.get(res[i]['type'], res[i]['type'])} · {res[i]['label']}")
    if any(r["type"] == "address" for r in res) and data.get("attribution"):
        st.caption(data["attribution"])
    return res[i] if st.button("Chọn", key=f"{key}-pick") else None


# ------------------------------------------------------------------ tình hình
def hydro(latest: list[dict]) -> list[float | None]:
    """Xác suất ngập (ước tính) lớn nhất toàn TP theo mốc giờ."""
    out = []
    for h in range(7):
        probs = [p["flood_probability"] for s in latest for p in s["points"] if p["horizon_h"] == max(h, 1)]
        out.append(max(probs) if probs else None)
    return out


def hydro_chart(vals: list[float | None], issued_at) -> go.Figure:
    lv = ["NO_DATA" if p is None else "HIGH" if p >= 0.8 else "MEDIUM" if p >= 0.5 else "LOW" for p in vals]
    x = ["Nay" if h == 0 else f"+{h}h" for h in range(7)]
    fig = go.Figure(go.Bar(x=x, y=[(p or 0) * 100 for p in vals], marker_color=[RISK[v]["color"] for v in lv],
                           customdata=[fmt_pct(p) for p in vals], hovertemplate="%{x}: %{customdata} (ước tính)<extra></extra>"))
    fig.update_layout(height=150, margin={"l": 30, "r": 5, "t": 10, "b": 25}, yaxis={"range": [0, 100], "title": "%"})
    return fig


def situation(risk: dict, alert_count: int, horizon: int, latest: list[dict]) -> None:
    props = [f["properties"] for f in risk.get("features", [])]
    issued = (risk.get("properties") or {}).get("issued_at")
    st.markdown(f"**Tình hình {'hiện tại' if horizon == 0 else f'sau {horizon} giờ'}**")
    st.caption(f"Cập nhật {fmt_dt(issued)} {sim_badge(any(p.get('is_simulated') for p in props))}")
    districts = sorted((p for p in props if p["level"] == "DISTRICT"),
                       key=lambda a: (-RISK_RANK[risk_of(a["risk_level"])], -(a["score"] if a["score"] is not None else -1)))
    wards_of = lambda i: sorted((p for p in props if p.get("parent_id") == i), key=lambda w: -(w["score"] if w["score"] is not None else -1))
    for d in districts:
        ws = wards_of(d["id"])
        hot = sum(1 for w in ws if w["risk_level"] in ("MEDIUM", "HIGH"))
        with st.expander(f"{d['name']} {risk_badge(d['risk_level'])}"):
            if flood_cause(d.get("cause"), d.get("depth_cm")):
                st.caption(flood_cause(d.get("cause"), d.get("depth_cm")))
            if hot:
                st.caption(f"{hot} phường nguy cơ trung bình/cao")
            for w in ws:
                c1, c2 = st.columns([3, 2])
                c1.markdown(f"{w['name']}" + (f"  \n:gray[{flood_cause(w.get('cause'), w.get('depth_cm'))}]" if flood_cause(w.get('cause'), w.get('depth_cm')) else ""))
                if c2.button(risk_text(w["risk_level"]), key=f"ward-{w['id']}"):
                    show_area(risk, w["id"])
                    refresh()
    high = [p for p in props if p["level"] == "WARD" and p["risk_level"] == "HIGH"]
    if high:
        deepest = max(high, key=lambda w: w.get("depth_cm") if w.get("depth_cm") is not None else -1)
        cause = flood_cause(deepest.get("cause"), deepest.get("depth_cm"))
        st.caption(f"{len(high)} phường nguy cơ cao" + (f" · {cause}" if cause else ""))
    if latest:
        st.plotly_chart(hydro_chart(hydro(latest), issued), width="stretch", key="m-hydro")
        st.caption("Xác suất ngập ước tính lớn nhất toàn thành phố theo giờ.")
    st.caption(f"Cảnh báo đang hoạt động: {alert_count}")


def show_area(risk: dict, area_id: int) -> None:
    f = next(x for x in risk["features"] if x["properties"]["id"] == area_id)
    lon, lat = centroid(f["geometry"])
    go_to(lat, lon, 13)
    st.session_state["m-point"] = {"lat": lat, "lon": lon, "label": None}
    open_panel("Chi tiết")


# ------------------------------------------------------------------ chi tiết điểm
def point_detail(p: dict, horizon: int) -> None:
    lat, lon, label = p["lat"], p["lon"], p.get("label")
    try:
        d = api.get("/gis/identify", {"lat": round(lat, 5), "lon": round(lon, 5)}, ttl=60)
    except api.ApiError as e:
        show_error(e)
        return
    area = (d.get("area") or {}).get("name")
    st.subheader(label or area or "Ngoài ranh giới dữ liệu")
    if label or d.get("district"):
        st.caption(", ".join(x for x in [area if label else None, d.get("district")] if x))
    st.caption(f"{lat:.5f}, {lon:.5f} · cập nhật {fmt_dt(d.get('issued_at'))}")
    if st.button("Chỉ đường tới đây", key="pd-dir"):
        st.session_state["m-end"] = {"label": label or area or f"{lat:.5f}, {lon:.5f}", "lon": lon, "lat": lat}
        open_panel("Chỉ đường")
        refresh()
    with st.expander("Báo ngập tại đây"):
        report_form(lat, lon)
    cur = next((r for r in d["risk"] if r["horizon_h"] == horizon), None)
    if cur:
        st.markdown(f"{risk_md(cur['risk_level'])} · xác suất ngập ước tính {fmt_pct(cur['flood_probability'])} · mưa {fmt_num(cur['rainfall_mm'], ' mm/h')}")
    if d["risk"]:
        st.markdown("**Mức rủi ro 0–6 giờ**")
        for col, r in zip(st.columns(len(d["risk"])), d["risk"]):
            col.caption("Nay" if r["horizon_h"] == 0 else f"+{r['horizon_h']}h")
            col.write(RISK[risk_of(r["risk_level"])]["symbol"] + " " + RISK[risk_of(r["risk_level"])]["label"].split()[0])
    ex = (cur or {}).get("explanation") or {}  # công dân nhận explanation null -> chỉ hiện phần có sẵn
    if flood_cause(ex.get("cause"), ex.get("depth_cm")):
        st.markdown(f"**{flood_cause(ex.get('cause'), ex.get('depth_cm'))}**")
    lines = [f"- {o}" for o in ex.get("overrides") or []] + [f"- {n}" for n in ex.get("notes") or []]
    if lines:
        st.markdown("\n".join(lines))
    if cur and cur["risk_level"] in RECO:
        st.markdown("**Khuyến nghị**\n" + "\n".join(f"- {x}" for x in RECO[cur["risk_level"]]))
    h = d.get("history") or {}
    if h.get("events_within_1500m", 0) > 0:
        st.markdown(f"**Lịch sử ngập (bán kính 1,5 km)**  \n{h['events_within_1500m']} sự kiện · gần nhất {fmt_dt(h.get('last_event_at'))} · sâu nhất {fmt_num(h.get('max_depth_cm'), ' cm')}")


def station_detail(sid: int) -> None:
    try:
        s, obs, fc = (api.get(f"/stations/{sid}", ttl=30), api.get(f"/stations/{sid}/observations", ttl=30),
                      api.get(f"/stations/{sid}/forecast", ttl=30))
    except api.ApiError as e:
        show_error(e)
        return
    st.subheader(s["name"])
    st.caption(f"{s['code']} · {s['address']} · {(s.get('area') or {}).get('name', '')}")
    st.markdown(("Đang kết nối" if s["connection_status"] == "ONLINE" else "Mất kết nối") + f" {sim_badge(s['source']['is_simulated'])}")
    c = st.columns(2)
    c[0].metric("Mưa hiện tại", fmt_num(s.get("latest_rainfall_mm"), " mm/h"))
    c[1].metric("Mực nước / ngưỡng", f"{fmt_num(s.get('latest_water_level_cm'))} / {s['flood_threshold_cm']} cm")
    st.caption(f"Cập nhật {fmt_dt(s.get('last_observation_at'))} · nguồn {s['source']['name']}")
    fig = go.Figure()
    fig.add_bar(x=[o["observed_at"] for o in obs], y=[o["rainfall_mm"] for o in obs], name="Mưa (mm/h)", marker_color="#1C7CB5")
    fig.add_scatter(x=[o["observed_at"] for o in obs], y=[o["water_level_cm"] for o in obs], name="Mực nước (cm)", yaxis="y2", line={"color": "#0E2A3B"})
    pts = fc.get("points", [])
    fig.add_scatter(x=[p["target_time"] for p in pts], y=[p["water_level_cm"] for p in pts], name="Dự báo mực nước", yaxis="y2", line={"color": "#D99A00", "dash": "dash"})
    fig.update_layout(height=240, margin={"l": 30, "r": 30, "t": 30, "b": 25}, legend={"orientation": "h", "y": 1.25},
                      yaxis2={"overlaying": "y", "side": "right"})
    st.plotly_chart(fig, width="stretch", key=f"st-chart-{sid}")
    if pts:
        st.dataframe([{"Mốc": f"+{p['horizon_h']}h", "Mưa": fmt_num(p["rainfall_mm"]), "Mực nước": fmt_num(p["water_level_cm"]),
                       "XS ngập (ước tính)": fmt_pct(p["flood_probability"])} for p in pts], hide_index=True)
    else:
        st.caption("Chưa có dự báo cho trạm này")


# ------------------------------------------------------------------ báo cáo ngập, điểm ngập, camera
def report_form(lat: float, lon: float) -> None:
    if not auth.user():
        st.info("Đăng nhập để gửi báo cáo ngập.")
        return
    with st.form(f"report-{lat:.5f}-{lon:.5f}"):
        sev = st.radio("Mức ngập", list(SEVERITY), format_func=SEVERITY.get, horizontal=True)
        note = st.text_input("Ghi chú (không bắt buộc)", max_chars=300)
        if st.form_submit_button("Gửi báo cáo", type="primary"):
            if run_action(lambda: api.post("/reports", {"latitude": lat, "longitude": lon, "severity": sev, "note": note}),
                          "Đã gửi báo cáo ngập. Báo cáo có hiệu lực 3 giờ."):
                refresh()


def report_card(r: dict) -> None:
    st.markdown(f"**:violet[{SEVERITY.get(r['severity'], r['severity'])}]** · Người dân báo ngập")
    if r.get("note"):
        st.text(r["note"])
    st.caption(f"Báo lúc {fmt_dt(r['reported_at'])}, hiệu lực đến {fmt_dt(r['expires_at'])}. {r['confirmations']} người xác nhận."
               + (f" Người báo: {r['reporter']}." if r.get("reporter") else ""))
    c1, c2, _ = st.columns([2, 1, 1])
    if auth.user() and c1.button("Xác nhận vẫn ngập", key=f"rp-ok-{r['id']}"):
        if run_action(lambda: api.post(f"/reports/{r['id']}/confirm"), "Đã xác nhận báo cáo"):
            refresh()
    if auth.is_staff() and c2.button("Từ chối", key=f"rp-no-{r['id']}"):
        if run_action(lambda: api.post(f"/reports/{r['id']}/reject"), "Đã từ chối báo cáo"):
            st.session_state.pop("m-sel", None)
            refresh()


def reports_panel(reports: list[dict]) -> None:
    st.markdown(f"**Báo cáo ngập đang hiệu lực ({len(reports)})**")
    if not reports:
        st.caption("Hiện chưa có báo cáo ngập nào.")
    for r in reports:
        with st.container(border=True):
            report_card(r)
    st.caption("Để báo ngập: chọn một điểm trên bản đồ, mở “Chi tiết” rồi “Báo ngập tại đây”.")


def alert_brief(a: dict) -> None:
    st.subheader(a["title"])
    st.markdown(f"{risk_md(a['risk_level'])} · phát sinh {fmt_dt(a['triggered_at'])}")
    if st.button("Mở cảnh báo", key="pd-alert", type="primary"):
        st.session_state["alert_open"] = a["id"]
        st.switch_page(nav.build_pages()["alerts"])


def hotspot_detail(h: dict) -> None:
    st.subheader(h["name"])
    if h.get("note"):
        st.text(h["note"])
    if h.get("camera_id"):
        camera_view(h["camera_id"], h.get("camera_name"))
    if h.get("source_url"):
        st.markdown(f"[Xem nguồn]({h['source_url']})")


def camera_view(cid: int, name: str | None) -> None:
    """Ảnh mới nhất của camera giao thông qua proxy backend (backend cache 30 giây)."""
    key = f"m-cam-{cid}"
    if key not in st.session_state or st.button("Làm mới ảnh", key=f"cam-refresh-{cid}"):
        try:
            st.session_state[key] = api.get_bytes(f"/cameras/{cid}/snapshot")
        except api.ApiError:
            st.session_state[key] = None
    if st.session_state[key]:
        st.image(st.session_state[key], caption=name or "Camera giao thông", width="stretch")
    else:
        st.caption("Camera hiện không có ảnh.")


# ------------------------------------------------------------------ chỉ đường
def _badge(s: dict) -> tuple[str, str]:
    km = s["km_by_status"]
    if km.get("REPORTED_FLOODED", 0) > 0:
        return f"{km['REPORTED_FLOODED']:.1f} km có báo cáo ngập", "violet"
    if s["flooded_km"] > 0:
        return f"{s['flooded_km']:.1f} km có thể ngập", "red"
    if s["at_risk_km"] > 0:
        return f"{s['at_risk_km']:.1f} km có nguy cơ ngập", "orange"
    return "Không có đoạn ngập", "green"


def _set_place(key: str, r: dict) -> None:
    st.session_state[key] = {"label": r["label"], "lon": r["lon"], "lat": r["lat"]}
    go_to(r["lat"], r["lon"], 14)


def get_route(start: dict, end: dict, horizon: int) -> dict | None:
    """Gọi /routing/route; giữ kết quả 60 giây trong phiên (backend giới hạn 30 yêu cầu/phút)."""
    import time
    key = (start["lon"], start["lat"], end["lon"], end["lat"], horizon, st.session_state.get("token"))
    c = st.session_state.get("m-route")
    if c and c[0] == key and time.monotonic() - c[1] < 60:
        return c[2]
    try:
        res = api.post("/routing/route", {"start": [start["lon"], start["lat"]], "end": [end["lon"], end["lat"]], "horizon_h": horizon})
    except api.ApiError as e:
        st.session_state["m-route"] = (key, time.monotonic(), None)
        st.session_state["m-route-err"] = e
        return None
    st.session_state.pop("m-route-err", None)
    if not c or c[0] != key:
        st.session_state["m-sel-route"], st.session_state["m-fit"] = res["recommended_index"], True
    st.session_state["m-route"] = (key, time.monotonic(), res)
    return res


def directions_panel(start, end, result) -> None:
    st.markdown("**Chỉ đường**")
    st.caption("Chọn điểm bằng ô tìm kiếm, bấm lên bản đồ (lần 1 = điểm đi, lần 2 = điểm đến) hoặc kéo thả marker. "
               "Nút ◎ (Vị trí của tôi) ở góc dưới phải bản đồ đặt điểm đi tại vị trí hiện tại của bạn.")
    for key, label, cur in (("m-start", "Điểm đi", start), ("m-end", "Điểm đến", end)):
        st.markdown(f"**{label}:** {cur['label'] if cur else '—'}")
        r = place_search(f"{key}-s", f"Tìm {label.lower()}", "Đường, quận, điểm ngập, toạ độ…")
        if r:
            _set_place(key, r)
            refresh()
    c1, c2 = st.columns(2)
    if c1.button("⇅ Đổi chiều", key="dir-swap"):
        st.session_state["m-start"], st.session_state["m-end"] = end, start
        refresh()
    if c2.button("Xoá tuyến", key="dir-clear"):
        for k in ("m-start", "m-end", "m-route"):
            st.session_state.pop(k, None)
        refresh()
    st.selectbox("Khởi hành", range(7), key="m-hdir", on_change=_sync_horizon, format_func=lambda h: "Bây giờ" if h == 0 else f"Sau {h} giờ")
    if not start or not end:
        st.caption("Chọn đủ điểm đi và điểm đến để xem tuyến đường và các đoạn có thể ngập.")
        return
    if not result:
        if st.session_state.get("m-route-err"):
            show_error(st.session_state["m-route-err"])
        return
    if result.get("elevation_missing_ratio", 0) > 0:
        st.warning(f"Thiếu dữ liệu độ cao ở {round(result['elevation_missing_ratio'] * 100)}% đoạn đường nên đánh giá ngập kém tin cậy. Thử lại sau ít phút.")
    sel = st.session_state.get("m-sel-route", result["recommended_index"])
    for r in result["routes"]:
        text, color = _badge(r["summary"])
        rec = " · Tuyến đề xuất" if r["index"] == result["recommended_index"] else ""
        if st.button(f"{fmt_duration(r['duration_s'])} · {fmt_distance(r['distance_m'])}{rec}  |  {text}", key=f"route-{r['index']}",
                     type="primary" if r["index"] == sel else "secondary", width="stretch"):
            st.session_state["m-sel-route"] = r["index"]
            refresh()
        st.markdown(f":{color}[**{text}**]")
    st.markdown(" &nbsp; ".join(f"<span style='color:{v['color']}'>{'━' if k == 'DRY' else '┅'}</span> {v['label']}" for k, v in STATUS.items()),
                unsafe_allow_html=True)
    route = next((r for r in result["routes"] if r["index"] == sel), None)
    if not route:
        return
    risky = [s for s in route["segments"] if s["status"] != "DRY"]
    if risky:
        st.markdown("**Đoạn cần chú ý**")
        for i, s in enumerate(risky):
            mid = s["geometry"]["coordinates"][len(s["geometry"]["coordinates"]) // 2]
            why = f"  \n:gray[{'; '.join(s['reasons'])}]" if s.get("reasons") else ""
            st.markdown(f":{_STATUS_MD[s['status']]}[**{STATUS[s['status']]['label']}**] · {fmt_distance(s['length_m'])}{why}")
            if st.button("Xem trên bản đồ", key=f"seg-{i}"):
                go_to(mid[1], mid[0], 16)
                refresh()
    with st.expander("Hướng dẫn từng bước"):
        for s in route["steps"]:
            st.markdown(f"1. {s['instruction']}" + (f" ({fmt_distance(s['distance_m'])})" if s["distance_m"] > 0 else ""))
    st.caption(f"Dữ liệu ngập cập nhật {fmt_dt(result.get('data_time'))} · {result.get('active_reports', 0)} báo cáo đang hiệu lực. "
               f"Trạng thái ngập là ước tính.")
    st.caption(result.get("disclaimer", ""))
    st.caption(result.get("attribution", ""))


def _sync_horizon() -> None:
    st.session_state["m-horizon"] = st.session_state["m-hdir"]


# ------------------------------------------------------------------ mô phỏng (admin)
def simulation_panel(sims: list[dict]) -> None:
    st.markdown("**Mô phỏng ngập** (chỉ cán bộ thấy): tham chiếu sang Cảnh báo, Dự báo AI, Lịch sử ngập, Thống kê và "
                "chỉ đường của cán bộ cho tới khi xoá vùng mô phỏng.")
    pt = st.session_state.get("m-sim-point")
    st.caption(f"Tâm: {pt['lat']:.5f}, {pt['lon']:.5f}" if pt else "Bấm lên bản đồ để chọn tâm vùng ngập.")
    radius = st.slider("Bán kính (m)", 100, 2000, 500, 50, key="m-sim-radius")
    depth = st.number_input("Độ sâu (cm)", 1, 300, 40, key="m-sim-depth")
    if st.button("Tạo vùng ngập", type="primary", key="sim-create", disabled=not pt):
        body = {"latitude": pt["lat"], "longitude": pt["lon"], "radius_m": radius, "depth_cm": depth}
        if run_action(lambda: api.post("/admin/simulations", body), "Đã tạo vùng ngập mô phỏng"):
            st.rerun()  # cả trang: dải thông báo mô phỏng ở app.py cập nhật ngay
    if sims:
        st.markdown(f"**Đang mô phỏng ({len(sims)})**")
        if st.button("Xoá tất cả", key="sim-del-all"):
            if run_action(lambda: api.delete("/admin/simulations"), "Đã xoá các vùng mô phỏng"):
                st.rerun()  # cả trang: dải thông báo mô phỏng ở app.py cập nhật ngay
        for s in sims:
            c1, c2 = st.columns([3, 1])
            c1.write(f"{s['radius_m']} m, sâu {s['depth_cm']} cm")
            if c2.button("Xoá", key=f"sim-del-{s['id']}"):
                if run_action(lambda: api.delete(f"/admin/simulations/{s['id']}"), "Đã xoá vùng mô phỏng"):
                    st.rerun()  # cả trang: dải thông báo mô phỏng ở app.py cập nhật ngay
