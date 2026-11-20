"""Cảnh báo ngập (AlertsPage.tsx). Người dân chỉ thấy cảnh báo công khai, không có thông tin xử lý nội bộ."""
import api
import auth
import streamlit as st
from common import (
    RISK,
    STATUS_VI,
    area_select,
    err_text,
    esc_md,
    flood_cause,
    fmt_dt,
    fmt_num,
    fmt_pct,
    pager,
    refresh,
    reset_page_on_change,
    risk_md,
    run_action,
    show_error,
    sim_badge,
    vn_date_to_iso,
)

# Khớp alert_service.TRANSITIONS ở backend
TRANSITIONS = {
    "NEW": ["ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CLOSED"], "ACKNOWLEDGED": ["IN_PROGRESS", "RESOLVED", "CLOSED"],
    "IN_PROGRESS": ["RESOLVED", "CLOSED"], "RESOLVED": ["CLOSED", "IN_PROGRESS"], "CLOSED": [],
}
LEVELS = ["HIGH", "MEDIUM", "LOW", "INSUFFICIENT_DATA"]
OUTCOME_VI = {"CONFIRMED": "Xác nhận có ngập", "FALSE_ALARM": "Báo động sai", "UNVERIFIED": "Chưa xác minh"}
SORTS = {"triggered_at": "Thời điểm phát sinh", "risk_level": "Mức rủi ro", "status": "Trạng thái", "score": "Điểm rủi ro"}
WEIGHT_VI = {"flood_probability": "Xác suất ngập (mô hình)", "rainfall": "Lượng mưa", "water_level": "Mực nước",
             "camera": "Camera", "history": "Lịch sử ngập"}


def cause_lines(a: dict) -> None:
    cause = flood_cause(a.get("cause"), a.get("depth_cm"))
    if cause:
        st.caption(cause)
    if a.get("wards"):
        st.caption("Phường: " + ", ".join(a["wards"]))


def _filters(staff: bool) -> dict:
    with st.expander("Bộ lọc", expanded=True):
        c = st.columns(5)
        q = c[0].text_input("Tìm kiếm", placeholder="Mã, tiêu đề, nội dung", key="al-q")
        with c[1]:
            area = area_select("Khu vực", "al-area")
        d_from = c[2].date_input("Từ ngày", value=None, key="al-from", format="DD/MM/YYYY")
        d_to = c[3].date_input("Đến ngày", value=None, key="al-to", format="DD/MM/YYYY")
        sorts = {k: v for k, v in SORTS.items() if staff or k != "status"}
        sort = c[4].selectbox("Sắp xếp", list(sorts), format_func=sorts.get, key="al-sort")
        direction = st.radio("Thứ tự", ["desc", "asc"], format_func=lambda x: "Giảm dần" if x == "desc" else "Tăng dần",
                             horizontal=True, key="al-dir")
        level = st.multiselect("Mức", LEVELS, format_func=lambda x: RISK[x]["label"], key="al-level", placeholder="Tất cả mức")
        status = st.multiselect("Trạng thái", list(TRANSITIONS), format_func=STATUS_VI.get, key="al-status", placeholder="Tất cả trạng thái") if staff else []
    return {"status": status, "level": level, "area_id": area, "q": q, "date_from": vn_date_to_iso(d_from),
            "date_to": vn_date_to_iso(d_to, True), "sort": sort, "direction": direction}


def _export(f: dict) -> None:
    lv = f["level"][0] if len(f["level"]) == 1 and f["level"][0] != "INSUFFICIENT_DATA" else None
    sig = repr(f)
    if st.button("Chuẩn bị tệp Excel", key="al-export"):
        try:
            name, data = api.download("/exports/excel", {"report": "alerts", "date_from": f["date_from"], "date_to": f["date_to"],
                                                         "area_id": f["area_id"], "risk_level": lv})
        except api.ApiError as e:
            show_error(e)
            return
        st.session_state["al-xlsx"] = (sig, name, data)
    if st.session_state.get("al-xlsx", (None,))[0] == sig:  # bộ lọc đổi thì bỏ tệp cũ
        _, name, data = st.session_state["al-xlsx"]
        st.download_button(f"Tải {name}", data, file_name=name, key="al-xlsx-dl",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render() -> None:
    staff = auth.is_staff()
    st.title("Cảnh báo ngập")
    f = _filters(staff)
    if staff:
        _export(f)
    reset_page_on_change("al-page", repr(f))
    _body(f, staff)


@st.fragment(run_every=60)
def _body(f: dict, staff: bool) -> None:
    """Danh sách + chi tiết, tự làm mới 60 giây (tương đương SSE của bản React)."""
    try:
        data = api.get("/alerts", {**f, "page": st.session_state.get("al-page", 1), "size": 20})
    except api.ApiError as e:
        show_error(e)
        return
    open_id = st.session_state.get("alert_open")
    if open_id:
        _detail(open_id, staff)
    items = data["items"]
    if not items:
        st.info("Không có cảnh báo phù hợp bộ lọc." if staff else "Hiện không có cảnh báo công khai nào đang hoạt động.")
        return
    counts = {lv: sum(1 for a in items if a["risk_level"] == lv) for lv in LEVELS}
    st.caption("Trên trang này: " + " · ".join(f"{RISK[k]['symbol']} {RISK[k]['label']}: {n}" for k, n in counts.items() if n))
    widths = [1.2, 3, 1.6, 1.3] + ([1.2] if staff else []) + [0.8, 1.4, 1]
    heads = ["Mã", "Tiêu đề", "Khu vực", "Mức"] + (["Trạng thái"] if staff else []) + ["Điểm", "Phát sinh", "Thao tác"]
    for c, h in zip(st.columns(widths), heads):
        c.markdown(f"**{h}**")
    for a in items:
        c = st.columns(widths)
        c[0].write(a["code"])
        with c[1]:
            st.write(f"{a['title']} {sim_badge(a.get('is_simulated'))}")
            cause_lines(a)
        c[2].write(a["area"]["name"])
        c[3].markdown(risk_md(a["risk_level"]))
        i = 4
        if staff:
            c[4].write(STATUS_VI.get(a["status"], a["status"]))
            i = 5
        c[i].write(fmt_num(a["score"]))
        c[i + 1].write(fmt_dt(a["triggered_at"]))
        if c[i + 2].button("Chi tiết", key=f"al-open-{a['id']}"):
            st.session_state["alert_open"] = a["id"]
            refresh()
    pager("al-page", data["total"], data["size"])


def _detail(aid: int, staff: bool) -> None:
    try:
        a = api.get(f"/alerts/{aid}")
    except api.ApiError as e:
        st.session_state.pop("alert_open", None)
        if aid > 0:  # cảnh báo mô phỏng mất khi tắt mô phỏng: chỉ đóng chi tiết, không báo lỗi
            show_error(e)
        return
    ex = a.get("explanation")
    with st.container(border=True):
        h1, h2 = st.columns([8, 1])
        h1.subheader(f"{a['code']} · {a['title']}")
        if h2.button("Đóng", key="al-close"):
            st.session_state.pop("alert_open", None)
            refresh()
        st.markdown(f"{risk_md(a['risk_level'])} " + (f"`{STATUS_VI.get(a['status'], a['status'])}` " if staff else "")
                    + f"{sim_badge(a.get('is_simulated'))} {a['area']['name']} · điểm {fmt_num(a['score'])} · tầm dự báo {a['horizon_h']} giờ")
        st.write(a["message"])
        cause_lines(a)
        if a.get("recommendations"):
            st.markdown("**Khuyến nghị**\n" + "\n".join(f"- {r}" for r in a["recommendations"]))
        if ex:
            _explanation(ex)
        times = [("Phát sinh", a["triggered_at"])]
        if staff:
            times += [("Tiếp nhận", a.get("acknowledged_at")), ("Xử lý xong", a.get("resolved_at")), ("Đóng", a.get("closed_at"))]
        for col, (lbl, v) in zip(st.columns(len(times)), times):
            col.caption(lbl)
            col.write(fmt_dt(v))
        if staff:
            st.caption(f"Phụ trách: {a.get('assignee_name') or '—'} · Xác minh: {OUTCOME_VI.get(a['verified_outcome'], a['verified_outcome'])}")
            _staff_actions(a)
            _history(a.get("history") or [])


def _explanation(ex: dict) -> None:
    st.markdown("**Giải thích mức cảnh báo**")
    if ex.get("level_reason"):
        st.write(ex["level_reason"])
    if ex.get("confidence") is not None:
        rv = f" · quy tắc phiên bản {ex['rule_version']}" if ex.get("rule_version") else ""
        st.caption(f"Độ tin cậy dữ liệu: {fmt_pct(ex['confidence'])}{rv}")
    if ex.get("contributions"):
        norm = ex.get("normalized") or {}
        st.table([{"Thành phần": WEIGHT_VI.get(k, k), "Giá trị chuẩn hoá": fmt_num(norm.get(k)), "Đóng góp": fmt_num(v)}
                  for k, v in ex["contributions"].items()])
    for title, key in (("Điều kiện nâng mức", "overrides"), ("Ghi chú", "notes")):
        if ex.get(key):
            st.markdown(f"**{title}:**\n" + "\n".join(f"- {x}" for x in ex[key]))
    if ex.get("stations"):
        st.write("Trạm liên quan: " + ", ".join(ex["stations"]))


def _history(rows: list[dict]) -> None:
    st.markdown("**Lịch sử xử lý**")
    if not rows:
        st.caption("Chưa có thao tác.")
    for h in rows:
        move = f": {STATUS_VI.get(h['from_status'] or '', h['from_status'] or '—')} → {STATUS_VI.get(h['to_status'], h['to_status'])}" if h.get("to_status") else ""
        st.markdown(f"- {fmt_dt(h['changed_at'])} · {esc_md(h.get('username') or 'hệ thống')} — {h['action']}{move}" + (f"  \n  _{esc_md(h['note'])}_" if h.get("note") else ""))


def _act(fn, ok: str) -> None:
    if run_action(fn, ok):
        refresh()


def _staff_actions(a: dict) -> None:
    aid, nxt = a["id"], TRANSITIONS.get(a["status"], [])
    if st.session_state.get("al-cur") != aid:  # sang cảnh báo khác: bỏ thao tác chờ và ghi chú đang nhập
        for k in ("al-pending", "al-snote", "al-anote", "al-vnote"):
            st.session_state.pop(k, None)
        st.session_state["al-cur"] = aid
    if a["id"] < 0:  # cảnh báo mô phỏng: không xử lý, mất khi admin tắt mô phỏng
        st.info("Cảnh báo MÔ PHỎNG: không cần xử lý, tự mất khi admin tắt mô phỏng ở Bản đồ › Mô phỏng.")
        return
    st.markdown("**Xử lý cảnh báo**")
    if a["status"] == "NEW" and st.button("Tiếp nhận", type="primary", key="al-ack"):
        _act(lambda: api.post(f"/alerts/{aid}/acknowledge"), "Đã tiếp nhận cảnh báo")
    left, right = st.columns(2)
    with left:
        if nxt:
            with st.form("al-status-form"):
                new = st.selectbox("Chuyển trạng thái", [""] + nxt, format_func=lambda s: STATUS_VI.get(s, "Chọn trạng thái…"))
                note = st.text_input("Ghi chú (tuỳ chọn)", max_chars=2000, key="al-snote")
                if st.form_submit_button("Cập nhật trạng thái", type="primary"):
                    if new:
                        st.session_state["al-pending"] = {"alert_id": aid, "status": new, "note": note}
                    else:
                        st.error("Chọn trạng thái mới")
        else:
            st.caption("Cảnh báo đã đóng, không thể chuyển trạng thái.")
        pend = st.session_state.get("al-pending")
        if pend and pend.get("alert_id") == aid and pend["status"] in nxt:
            st.warning(f"Chuyển cảnh báo {a['code']} từ \"{STATUS_VI[a['status']]}\" sang \"{STATUS_VI[pend['status']]}\"?")
            ok, no = st.columns(2)
            if ok.button("Chuyển trạng thái", key="al-confirm", type="primary"):
                st.session_state.pop("al-pending")
                _act(lambda: api.post(f"/alerts/{aid}/status", {"status": pend["status"], "note": pend["note"]}), "Đã cập nhật trạng thái")
            if no.button("Huỷ", key="al-cancel"):
                st.session_state.pop("al-pending")
                refresh()
        with st.form("al-note-form", clear_on_submit=True):
            text = st.text_area("Thêm ghi chú", max_chars=2000, height=70)
            if st.form_submit_button("Thêm ghi chú"):
                if text.strip():
                    _act(lambda: api.post(f"/alerts/{aid}/notes", {"note": text.strip()}), "Đã thêm ghi chú")
                else:
                    st.error("Nhập nội dung ghi chú")
    with right:
        try:
            staff_users = api.get("/alerts/assignees", ttl=60)
        except api.ApiError as e:
            st.error(err_text(e))
            staff_users = []
        users = {None: "Không phân công"} | {u["id"]: u.get("full_name") or u["username"] for u in staff_users}
        with st.form("al-assign-form"):
            uid = st.selectbox("Phân công cán bộ", list(users), format_func=users.get,
                               index=list(users).index(a["assigned_to"]) if a.get("assigned_to") in users else 0)
            note = st.text_input("Ghi chú (tuỳ chọn)", max_chars=2000, key="al-anote")
            if st.form_submit_button("Phân công", type="primary"):
                _act(lambda: api.post(f"/alerts/{aid}/assign", {"user_id": uid, "note": note}), "Đã cập nhật phân công")
        with st.form("al-verify-form"):
            out = st.selectbox("Xác minh thực địa", list(OUTCOME_VI), format_func=OUTCOME_VI.get)
            note = st.text_input("Ghi chú (tuỳ chọn)", max_chars=2000, key="al-vnote")
            if st.form_submit_button("Lưu xác minh", type="primary"):
                _act(lambda: api.post(f"/alerts/{aid}/verify", {"outcome": out, "note": note}), "Đã ghi nhận kết quả xác minh")
