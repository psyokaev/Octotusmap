"""Camera giám sát (CamerasPage.tsx): CRUD camera thủ công, lịch sử nhận dạng, phân tích ảnh tải lên."""
import json
import re

import api
import nav
import streamlit as st
from common import confirm_action, fmt_dt, fmt_pct, pager, refresh, run_action, show_error, sim_badge

from views import map_panels as mp
from views.map import DEFAULT_LAYERS

STATUS_VI = {"ACTIVE": "Hoạt động", "INACTIVE": "Ngừng", "MAINTENANCE": "Bảo trì"}
MAX_MB = 10


def method_vi(m: str) -> str:
    return "Heuristic (ngưỡng màu – không phải YOLO)" if m == "HEURISTIC" else "YOLOv8-seg" if m == "YOLOV8_SEG" else m


def _img(url: str, caption: str) -> None:
    """Ảnh camera chỉ phục vụ qua API có kiểm tra quyền nên tải kèm token."""
    try:
        st.image(api.get_bytes(url.removeprefix("/api/v1")), caption=caption)
    except api.ApiError:
        st.caption(f"Không tải được ảnh: {caption}")


TRAFFIC_PAGE = 6


def render() -> None:
    st.title("Camera giám sát")
    traffic, managed = st.tabs(["Camera giao thông TP.HCM", "Camera tự quản lý"])
    with traffic:
        _traffic()
    with managed:
        _managed()


def _traffic() -> None:
    """796 camera giao thông thật (Cổng thông tin giao thông TP.HCM); ảnh lấy trực tiếp qua backend (cache 30 s)."""
    try:
        fc = api.get("/gis/traffic-cameras", ttl=3600)
    except api.ApiError as e:
        show_error(e)
        return
    cams = [{**f["properties"], "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
            for f in fc["features"]]
    c = st.columns([3, 2])
    q = c[0].text_input("Tìm camera", key="tc-q", placeholder="Tên đường, nút giao…").strip().lower()
    districts = sorted({x["district"] for x in cams if x.get("district")})
    d = c[1].selectbox("Quận/huyện", districts, index=None, placeholder="Tất cả quận/huyện", key="tc-d")
    rows = [x for x in cams if (not q or q in x["name"].lower()) and (not d or x.get("district") == d)]
    st.caption(f"{len(rows)}/{len(cams)} camera đang hoạt động · ảnh tĩnh làm mới mỗi 30 giây, không phải video · "
               f"{fc.get('attribution', '')}")
    if not rows:
        st.info("Không có camera khớp bộ lọc.")
        return
    page = pager("tc-page", len(rows), TRAFFIC_PAGE)
    shown = rows[(page - 1) * TRAFFIC_PAGE: page * TRAFFIC_PAGE]
    for i in range(0, len(shown), 3):
        for col, cam in zip(st.columns(3), shown[i: i + 3]):
            with col, st.container(border=True):
                st.markdown(f"**{cam['name']}**")
                st.caption(cam.get("district") or "Chưa gán quận")
                mp.camera_view(cam["id"], None)
                if st.button("Xem trên bản đồ", key=f"tc-map-{cam['id']}"):
                    _show_on_map(cam)


def _show_on_map(cam: dict) -> None:
    s = st.session_state
    s["m-layers"] = list(dict.fromkeys([*s.get("m-layers", DEFAULT_LAYERS), "cameras"]))
    s["m-sel"], s["m-point"] = {"kind": "camera", "id": cam["id"]}, None
    mp.go_to(cam["lat"], cam["lon"], 16)
    mp.open_panel("Chi tiết")
    st.switch_page(nav.build_pages()["map"])


def _managed() -> None:
    b = st.columns([1, 1, 4])
    b[0].button("Thêm camera", type="primary", key="cam-new", on_click=lambda: st.session_state.update({"cam-form": "new"}))
    b[1].button("Phân tích ảnh", key="cam-an-open", on_click=lambda: st.session_state.update({"cam-analyze": True}))
    st.caption("Camera có nhãn Mô phỏng dùng khung hình mô phỏng được sinh định kỳ, không phải video trực tiếp. "
               "Kết quả nhận dạng chỉ mang tính tham khảo. Kết quả từ mô hình mô phỏng/heuristic không thay thế quan trắc thật.")
    try:
        cams = api.get("/cameras")
    except api.ApiError as e:
        show_error(e)
        return
    by_id = {c["id"]: c for c in cams}
    form = st.session_state.get("cam-form")
    if form == "new" or form in by_id:
        _form(by_id.get(form))
    if st.session_state.get("cam-analyze"):
        _analyze(cams)
    if st.session_state.get("cam-view") in by_id:
        _detections(by_id[st.session_state["cam-view"]])
    if not cams:
        st.info("Chưa có camera nào.")
        return
    for row in range(0, len(cams), 3):
        for col, c in zip(st.columns(3), cams[row: row + 3]):
            with col, st.container(border=True):
                _card(c)


def _card(c: dict) -> None:
    d = c.get("latest_detection")
    if d:
        _img(d["result_image_url"], f"Kết quả nhận dạng ngập gần nhất của camera {c['code']}")
    else:
        st.caption("Chưa có ảnh phân tích")
    st.markdown(f"**{c['code']} – {c['name']}** {sim_badge(c['source']['is_simulated'])}")
    st.caption(f"{STATUS_VI.get(c['status'], c['status'])} · {'Công khai' if c['is_public'] else 'Nội bộ'} · "
               f"{(c.get('area') or {}).get('name', 'Chưa gán khu vực')} · lưu {c['retention_days']} ngày")
    if d:
        st.markdown(f"Tỉ lệ ngập **{fmt_pct(d['flood_ratio'])}** · độ tin cậy {fmt_pct(d['confidence'])}  \n"
                    f"Phương pháp: {method_vi(d['method'])} · {fmt_dt(d['detected_at'])}")
    else:
        st.caption("Chưa có kết quả nhận dạng.")
    cid = c["id"]
    st.button("Lịch sử nhận dạng", key=f"cam-hist-{cid}", on_click=lambda: st.session_state.update({"cam-view": cid}))
    st.button("Sửa", key=f"cam-edit-{cid}", on_click=lambda: st.session_state.update({"cam-form": cid}))
    confirm_action(f"cam-del-{cid}", "Xoá", f"Xoá camera {c['code']} – {c['name']}? Camera sẽ bị ẩn khỏi hệ thống (xoá mềm).",
                   lambda: api.delete(f"/cameras/{cid}"), "Đã xoá camera", "Xoá camera")


def _form(c: dict | None) -> None:
    d = c or {}
    with st.form("cam-form-f"):
        st.subheader(f"Sửa camera {c['code']}" if c else "Thêm camera")
        f = st.columns(2)
        code = f[0].text_input("Mã camera", value=d.get("code", ""), disabled=bool(c))
        name = f[1].text_input("Tên camera", value=d.get("name", ""))
        lat = f[0].number_input("Vĩ độ", -90.0, 90.0, d.get("latitude", 10.78), format="%.6f")
        lon = f[1].number_input("Kinh độ", -180.0, 180.0, d.get("longitude", 106.7), format="%.6f")
        url = st.text_input("URL nguồn (http(s):// hoặc rtsp://, có thể để trống)", value=d.get("stream_url", ""), max_chars=500)
        g = st.columns(2)
        status = g[0].selectbox("Trạng thái", list(STATUS_VI), format_func=STATUS_VI.get, index=list(STATUS_VI).index(d.get("status", "ACTIVE")))
        days = g[1].number_input("Số ngày lưu ảnh (1–365)", 1, 365, d.get("retention_days", 30))
        roi_txt = st.text_input("Vùng quan tâm ROI (tuỳ chọn, JSON: [[x,y],…] tỉ lệ 0..1, ≥3 điểm)", value=json.dumps(d["roi"]) if d.get("roi") else "")
        public = st.checkbox("Công khai cho người dân", value=d.get("is_public", False))
        ok = st.form_submit_button("Lưu", type="primary")
    st.button("Huỷ", key="cam-form-cancel", on_click=lambda: st.session_state.pop("cam-form", None))
    if not ok:
        return
    roi = None
    if roi_txt.strip():
        try:
            roi = json.loads(roi_txt)
        except ValueError:
            st.error("ROI không phải JSON hợp lệ")
            return
    if not c and not re.fullmatch(r"[A-Za-z0-9_-]{2,30}", code):
        st.error('Mã camera 2–30 ký tự, chỉ gồm chữ, số, "_" và "-"')
    elif len(name.strip()) < 2:
        st.error("Tên camera tối thiểu 2 ký tự")
    elif url.strip() and not re.match(r"^(https?|rtsp)://", url.strip()):
        st.error("URL phải bắt đầu bằng http://, https:// hoặc rtsp://")
    else:
        body = {"name": name.strip(), "latitude": lat, "longitude": lon, "stream_url": url.strip(), "status": status,
                "is_public": public, "retention_days": int(days), "roi": roi}
        if c:
            done = run_action(lambda: api.patch(f"/cameras/{c['id']}", body), "Đã cập nhật camera")
        else:
            done = run_action(lambda: api.post("/cameras", {**body, "code": code}), "Đã thêm camera")
        if done:
            st.session_state.pop("cam-form", None)
            refresh()


def _analyze(cams: list[dict]) -> None:
    with st.container(border=True):
        st.subheader("Phân tích ảnh ngập")
        f = st.file_uploader("Ảnh (.jpg, .png)", type=["jpg", "jpeg", "png"], key="cam-an-file")
        opts = {None: "Không gắn camera"} | {c["id"]: f"{c['code']} – {c['name']}" for c in cams}
        cam_id = st.selectbox("Gắn với camera (tuỳ chọn)", list(opts), format_func=opts.get, key="cam-an-cam")
        st.caption("Chọn camera để kết quả đưa vào cảnh báo; ảnh không gắn camera chỉ để xem thử.")
        if st.button("Phân tích", key="cam-an-go", type="primary"):
            if f is None:
                st.error("Chọn một tệp")
            elif f.size > MAX_MB * 1024 * 1024:
                st.error(f"Tệp tối đa {MAX_MB} MB")
            else:
                try:
                    st.session_state["cam-an-res"] = api.upload("/cameras/analyze", f.name, f.getvalue(), {"camera_id": cam_id} if cam_id else None)
                    st.toast("Đã phân tích ảnh")
                except api.ApiError as e:
                    show_error(e)
        r = st.session_state.get("cam-an-res")
        if r:
            i1, i2 = st.columns(2)
            with i1:
                _img(r["image_url"], "Ảnh đầu vào")
            with i2:
                _img(r["result_image_url"], "Vùng ngập phát hiện")
            st.markdown(f"Tỉ lệ ngập **{fmt_pct(r['flood_ratio'])}** · độ tin cậy {fmt_pct(r['confidence'])} · {r['num_regions']} vùng · "
                        f"phương pháp **{method_vi(r['method'])}**")
            if (r.get("details") or {}).get("trained_on_simulated"):
                st.caption("Mô hình huấn luyện trên ảnh mô phỏng, kết quả chỉ để tham khảo.")
            if r["method"] == "HEURISTIC":
                st.caption("Chưa có trọng số YOLO đã huấn luyện nên hệ thống dùng phương pháp heuristic dự phòng; kết quả kém tin cậy hơn.")
        st.button("Đóng", key="cam-an-close", on_click=lambda: st.session_state.pop("cam-analyze", None))


def _detections(c: dict) -> None:
    with st.container(border=True):
        h = st.columns([8, 1])
        h[0].subheader(f"Lịch sử nhận dạng · {c['code']}")
        h[1].button("Đóng", key="cam-view-close", on_click=lambda: st.session_state.pop("cam-view", None))
        try:
            d = api.get(f"/cameras/{c['id']}/detections", {"page": st.session_state.get("cam-det-page", 1), "size": 10})
        except api.ApiError as e:
            show_error(e)
            return
        if not d["items"]:
            st.info("Chưa có kết quả nhận dạng.")
            return
        for x in d["items"]:
            cols = st.columns([2, 3, 1.5, 1.5, 3])
            with cols[0]:
                _img(x["result_image_url"], f"Kết quả lúc {fmt_dt(x['detected_at'])}")
            cols[1].markdown(f"{fmt_dt(x['detected_at'])} {sim_badge(x['is_simulated'])}")
            cols[2].write(f"Ngập {fmt_pct(x['flood_ratio'])}")
            cols[3].write(f"Tin cậy {fmt_pct(x['confidence'])}")
            cols[4].write(method_vi(x["method"]))
        pager("cam-det-page", d["total"], d["size"])
