"""Trạm quan trắc (StationsPage.tsx): danh sách, tạo/sửa/xoá mềm, chi tiết, nhập quan trắc và nhập tệp CSV/XLSX."""
import re
from datetime import datetime

import api
import plotly.graph_objects as go
import streamlit as st
from analytics import fetch
from common import (
    area_select,
    VN_TZ,
    confirm_action,
    esc_md,
    fmt_dt,
    fmt_num,
    fmt_pct,
    pager,
    refresh,
    reset_page_on_change,
    run_action,
    show_error,
    sim_badge,
    vn_date_to_iso,
    vn_local_to_iso,
)
from plotly.subplots import make_subplots

TYPE_VI = {"RAIN": "Đo mưa", "WATER_LEVEL": "Đo mực nước", "COMBINED": "Kết hợp"}
STATUS_VI = {"ACTIVE": "Hoạt động", "INACTIVE": "Ngừng", "MAINTENANCE": "Bảo trì"}
CONN_VI = {"ONLINE": "Trực tuyến", "OFFLINE": "Mất kết nối", "NO_DATA": "Chưa có dữ liệu", "UNKNOWN": "Không rõ"}
DATA_VI = {"DEMO": "Mô phỏng", "REAL": "Thật"}
SORTS = {"code": "Mã", "name": "Tên trạm", "last_observation_at": "Quan trắc gần nhất", "updated_at": "Cập nhật"}
MAX_MB = 10


def _filters() -> dict:
    with st.container(border=True):
        c = st.columns(5)
        q = c[0].text_input("Tìm kiếm", placeholder="Mã hoặc tên trạm", key="stn-q")
        typ = c[1].selectbox("Loại trạm", [None, *TYPE_VI], format_func=lambda k: "Tất cả" if k is None else TYPE_VI[k], key="stn-type")
        status = c[2].selectbox("Trạng thái", [None, *STATUS_VI], format_func=lambda k: "Tất cả" if k is None else STATUS_VI[k], key="stn-status")
        with c[3]:
            area = area_select("Khu vực", "stn-area")
        conn = c[4].selectbox("Kết nối", [None, "ONLINE", "OFFLINE", "NO_DATA"], format_func=lambda k: "Tất cả" if k is None else CONN_VI[k], key="stn-conn")
        s = st.columns([3, 2])
        sort = s[0].selectbox("Sắp xếp theo", list(SORTS), format_func=SORTS.get, key="stn-sort")
        direction = s[1].radio("Thứ tự", ["asc", "desc"], format_func=lambda x: "Tăng dần" if x == "asc" else "Giảm dần", horizontal=True, key="stn-dir")
    return {"q": q, "station_type": typ, "status": status, "area_id": area, "connection": conn, "sort": sort, "direction": direction}


def render() -> None:
    st.title("Trạm quan trắc")
    b = st.columns([1, 1, 4])
    b[0].button("Thêm trạm", type="primary", key="stn-new", on_click=lambda: st.session_state.update({"stn-form": "new"}))
    b[1].button("Nhập dữ liệu từ tệp", key="stn-import-open", on_click=lambda: st.session_state.update({"stn-import": True}))
    if st.session_state.get("stn-import"):
        _global_import()
    f = _filters()
    reset_page_on_change("stn-page", repr(f))
    try:
        data = api.get("/stations", {**f, "page": st.session_state.get("stn-page", 1), "size": 20})
    except api.ApiError as e:
        show_error(e)
        return
    items = data["items"]
    if st.session_state.get("stn-form") == "new":
        _form(None)
    if not items:
        st.info("Không có trạm nào phù hợp bộ lọc.")
        return
    st.dataframe([{
        "Mã": s["code"], "Tên trạm": s["name"], "Loại": TYPE_VI.get(s["station_type"], s["station_type"]), "Khu vực": (s["area"] or {}).get("name", "—"),
        "Trạng thái": STATUS_VI.get(s["status"], s["status"]), "Kết nối": CONN_VI.get(s["connection_status"], s["connection_status"]),
        "Mưa (mm)": fmt_num(s["latest_rainfall_mm"]), "Mực nước (cm)": fmt_num(s["latest_water_level_cm"]),
        "Quan trắc gần nhất": fmt_dt(s["last_observation_at"]), "Cập nhật": fmt_dt(s["updated_at"]),
        "Dữ liệu": DATA_VI.get(s["data_status"], s["data_status"])} for s in items], hide_index=True, width="stretch")
    pager("stn-page", data["total"], data["size"])
    by_id = {s["id"]: s for s in items}
    pick = st.selectbox("Chọn trạm để thao tác", list(by_id), format_func=lambda i: f"{by_id[i]['code']} – {by_id[i]['name']}", key="stn-pick")
    s = by_id[pick]
    a = st.columns(3)
    a[0].button("Chi tiết", key="stn-detail", on_click=lambda: st.session_state.update({"stn-view": pick}))
    a[1].button("Sửa", key="stn-edit", on_click=lambda: st.session_state.update({"stn-form": pick}))
    with a[2]:
        confirm_action("stn-del", "Xoá", f"Ngừng theo dõi trạm {s['code']} – {s['name']}? Trạm sẽ bị ẩn (xoá mềm), dữ liệu quan trắc vẫn được giữ lại.",
                       lambda: api.delete(f"/stations/{pick}"), "Đã xoá trạm", "Xoá trạm")
    if st.session_state.get("stn-form") == pick:
        _form(s)
    if st.session_state.get("stn-view") in by_id:
        _detail(by_id[st.session_state["stn-view"]])


# ------------------------------------------------------------------ tạo / sửa
def _form(s: dict | None) -> None:
    with st.form("stn-form-f"):
        st.subheader(f"Sửa trạm {s['code']}" if s else "Thêm trạm quan trắc")
        d = s or {}
        c = st.columns(2)
        code = c[0].text_input("Mã trạm", value=d.get("code", ""), disabled=bool(s))
        name = c[1].text_input("Tên trạm", value=d.get("name", ""))
        typ = c[0].selectbox("Loại trạm", list(TYPE_VI), format_func=TYPE_VI.get, index=list(TYPE_VI).index(d.get("station_type", "COMBINED")))
        status = c[1].selectbox("Trạng thái", list(STATUS_VI), format_func=STATUS_VI.get, index=list(STATUS_VI).index(d.get("status", "ACTIVE")))
        lat = c[0].number_input("Vĩ độ", -90.0, 90.0, d.get("latitude", 10.78), format="%.6f")
        lon = c[1].number_input("Kinh độ", -180.0, 180.0, d.get("longitude", 106.7), format="%.6f")
        interval = c[0].number_input("Chu kỳ gửi dữ liệu (phút)", 1, 1440, d.get("interval_minutes", 60))
        thr = c[1].number_input("Ngưỡng ngập (cm)", 0.0, 1000.0, float(d.get("flood_threshold_cm", 60)))
        addr = c[0].text_input("Địa chỉ", value=d.get("address", ""), max_chars=255)
        unit = c[1].text_input("Đơn vị quản lý", value=d.get("managing_unit", ""), max_chars=150)
        notes = st.text_area("Ghi chú", value=d.get("notes", ""), max_chars=2000, height=70)
        ok = st.form_submit_button("Lưu", type="primary")
    st.button("Huỷ", key="stn-form-cancel", on_click=lambda: st.session_state.pop("stn-form", None))
    if not ok:
        return
    if not s and not re.fullmatch(r"[A-Za-z0-9_-]{2,30}", code):
        st.error('Mã trạm 2–30 ký tự, chỉ gồm chữ, số, "_" và "-"')
    elif len(name.strip()) < 2:
        st.error("Tên trạm tối thiểu 2 ký tự")
    elif thr <= 0:
        st.error("Ngưỡng ngập phải lớn hơn 0")
    else:
        body = {"name": name.strip(), "station_type": typ, "address": addr, "latitude": lat, "longitude": lon, "managing_unit": unit,
                "status": status, "interval_minutes": int(interval), "flood_threshold_cm": thr, "notes": notes}
        if s:
            done = run_action(lambda: api.patch(f"/stations/{s['id']}", body), "Đã cập nhật trạm")
        else:
            done = run_action(lambda: api.post("/stations", {**body, "code": code}), "Đã thêm trạm")
        if done:
            st.session_state.pop("stn-form", None)
            refresh()


# ------------------------------------------------------------------ chi tiết
def _detail(s: dict) -> None:
    with st.container(border=True):
        h = st.columns([8, 1])
        h[0].subheader(f"{s['code']} – {s['name']}")
        h[1].button("Đóng", key="stn-detail-close", on_click=lambda: st.session_state.pop("stn-view", None))
        st.markdown(f"{sim_badge(s['data_status'] == 'DEMO')} {TYPE_VI.get(s['station_type'])} · {(s['area'] or {}).get('name', 'Chưa gán khu vực')}"
                    f" · ngưỡng ngập {fmt_num(s['flood_threshold_cm'], ' cm')}")
        _observations(s)
        _quality(s)
        _forecast(s)
        left, right = st.columns(2)
        with left:
            _manual(s["id"])
        with right:
            st.markdown("**Nhập tệp CSV/XLSX cho trạm này**")
            _import_form(f"/stations/{s['id']}/observations/import", f"stn-imp-{s['id']}")


def _observations(s: dict) -> None:
    c = st.columns([1, 1, 3])
    d1 = c[0].date_input("Từ ngày", value=None, key="stn-obs-from", format="DD/MM/YYYY")
    d2 = c[1].date_input("Đến ngày", value=None, key="stn-obs-to", format="DD/MM/YYYY")
    c[2].caption("Để trống: 48 giờ gần nhất (tối đa 93 ngày)")
    obs = fetch(f"/stations/{s['id']}/observations", {"date_from": vn_date_to_iso(d1), "date_to": vn_date_to_iso(d2, True)})
    if not obs:
        st.info("Không có quan trắc trong khoảng thời gian này.")
        return
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    xs = [o["observed_at"] for o in obs]
    fig.add_trace(go.Bar(name="Lượng mưa (mm)", x=xs, y=[o["rainfall_mm"] for o in obs], marker_color="#1C7CB5"))
    fig.add_trace(go.Scatter(name="Mực nước (cm)", x=xs, y=[o["water_level_cm"] for o in obs], mode="lines", line={"color": "#D99A00"}), secondary_y=True)
    fig.add_hline(y=s["flood_threshold_cm"], line_dash="dash", line_color="#C62828", secondary_y=True,
                  annotation_text=f"Ngưỡng ngập {s['flood_threshold_cm']:g} cm")
    fig.update_yaxes(title_text="mm", secondary_y=False)
    fig.update_yaxes(title_text="cm", secondary_y=True)
    fig.update_layout(height=340, margin={"l": 10, "r": 10, "t": 24, "b": 10}, legend={"orientation": "h", "y": -0.2}, hovermode="x unified")
    st.plotly_chart(fig, width="stretch", key=f"stn-obs-{s['id']}")


def _quality(s: dict) -> None:
    st.markdown("**Chất lượng dữ liệu 7 ngày · phát hiện dữ liệu bất thường**")
    q = fetch(f"/stations/{s['id']}/quality", {"days": 7})
    if not q:
        return
    rain, wl = q.get("rainfall") or {}, q.get("water_level") or {}
    k = st.columns(3)
    k[0].metric("Độ đầy đủ", fmt_pct(q["completeness"]))
    k[0].caption(f"Kỳ vọng {fmt_num(q['expected_records'])} bản ghi")
    k[1].metric("Độ trễ dữ liệu", fmt_num(q["delay_minutes"], " phút"))
    k[1].caption(f"Chu kỳ {s['interval_minutes']} phút" + (" · trễ quá 3 chu kỳ" if q["delay_minutes"] is not None and q["delay_minutes"] > 3 * s["interval_minutes"] else ""))
    k[2].metric("Bản ghi nghi ngờ / thiếu", f"{rain.get('SUSPECT', 0) + wl.get('SUSPECT', 0)} / {rain.get('MISSING', 0) + wl.get('MISSING', 0)}")
    st.dataframe([{"Chuỗi": n, "Hợp lệ": fmt_num(r.get("VALID", 0)), "Nghi ngờ": fmt_num(r.get("SUSPECT", 0)), "Thiếu": fmt_num(r.get("MISSING", 0))}
                  for n, r in (("Lượng mưa", rain), ("Mực nước", wl))], hide_index=True, width="stretch")


def _forecast(s: dict) -> None:
    st.markdown("**Dự báo của trạm (ước tính)**")
    f = fetch(f"/stations/{s['id']}/forecast")
    if not f or not f.get("points"):
        st.caption("Chưa có bản dự báo cho trạm này.")
        return
    st.caption(f"Phát hành {fmt_dt(f['issued_at'])} {sim_badge(f.get('is_simulated'))}")
    st.dataframe([{"Mốc": f"+{p['horizon_h']}h", "Thời điểm": fmt_dt(p["target_time"]), "Mưa (mm)": fmt_num(p["rainfall_mm"]),
                   "Mực nước (cm)": fmt_num(p["water_level_cm"]), "Xác suất ngập (ước tính)": fmt_pct(p["flood_probability"])}
                  for p in f["points"]], hide_index=True, width="stretch")


def _manual(sid: int) -> None:
    st.markdown("**Nhập quan trắc thủ công**")
    with st.form(f"stn-manual-{sid}", clear_on_submit=False):
        c = st.columns(2)
        now = datetime.now(VN_TZ)
        day = c[0].date_input("Ngày (giờ Việt Nam)", value=now.date(), format="DD/MM/YYYY", key=f"stn-mo-d-{sid}")
        t = c[1].time_input("Giờ", value=now.time().replace(second=0, microsecond=0), key=f"stn-mo-t-{sid}", step=60)
        rain = c[0].number_input("Lượng mưa (mm)", 0.0, 500.0, None, key=f"stn-mo-r-{sid}")
        wl = c[1].number_input("Mực nước (cm)", -500.0, 2000.0, None, key=f"stn-mo-w-{sid}")
        ok = st.form_submit_button("Gửi quan trắc", type="primary")
    if not ok:
        return
    if rain is None and wl is None:
        st.error("Nhập ít nhất lượng mưa hoặc mực nước")
        return
    body = {"observed_at": vn_local_to_iso(day, t), "rainfall_mm": rain, "water_level_cm": wl}
    try:
        st.session_state[f"stn-mo-rep-{sid}"] = api.post(f"/stations/{sid}/observations", body)
    except api.ApiError as e:
        show_error(e)
        return
    st.toast("Đã gửi quan trắc")
    _report(st.session_state[f"stn-mo-rep-{sid}"])


# ------------------------------------------------------------------ nhập tệp
def _global_import() -> None:
    with st.container(border=True):
        st.subheader("Nhập dữ liệu quan trắc (nhiều trạm)")
        st.caption("Tệp CSV/XLSX gồm các cột station_code, observed_at, rainfall_mm, water_level_cm (hoặc water_level_m).")
        _import_form("/stations/import", "stn-imp-all")
        st.button("Đóng", key="stn-import-close", on_click=lambda: st.session_state.pop("stn-import", None))


def _import_form(path: str, key: str) -> None:
    f = st.file_uploader(f"Tệp dữ liệu (.csv, .xlsx, tối đa {MAX_MB} MB)", type=["csv", "xlsx"], key=f"{key}-file")
    if st.button("Nhập dữ liệu", key=f"{key}-go", type="primary"):
        if f is None:
            st.error("Chọn một tệp")
        elif f.size > MAX_MB * 1024 * 1024:
            st.error(f"Tệp tối đa {MAX_MB} MB")
        else:
            try:
                st.session_state[f"{key}-rep"] = api.upload(path, f.name, f.getvalue())
                st.toast("Đã xử lý tệp")
            except api.ApiError as e:
                show_error(e)
    if f"{key}-rep" in st.session_state:
        _report(st.session_state[f"{key}-rep"])


def _report(r: dict) -> None:
    st.info(f"Tổng {r['total_rows']} dòng · thêm mới {r['inserted']} · trùng lặp {r['duplicates']} · bị từ chối {r['rejected']}")
    if r.get("errors"):
        st.error("\n".join(f"- {esc_md(e)}" for e in r["errors"][:100]))
