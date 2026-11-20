"""Lịch sử ngập (HistoryPage.tsx)."""
from datetime import datetime, time, timedelta, timezone

import api
import auth
import plotly.graph_objects as go
import streamlit as st
from common import (
    CAUSE_VI,
    area_select,
    esc_md,
    fmt_dt,
    fmt_num,
    pager,
    reset_page_on_change,
    run_action,
    show_error,
    sim_badge,
    vn_date_to_iso,
    vn_local_to_iso,
)
from plotly.subplots import make_subplots

SORTS = {"started_at": "Bắt đầu", "max_depth_cm": "Độ sâu lớn nhất", "location_name": "Địa điểm"}


def monthly_chart(by_time: list[dict]) -> go.Figure:
    x = [b["bucket"] for b in by_time]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=x, y=[b["count"] for b in by_time], name="Số trận ngập", marker_color="#1C7CB5")
    fig.add_scatter(x=x, y=[b["max_depth_cm"] for b in by_time], name="Độ sâu lớn nhất (cm)", mode="lines+markers",
                    line={"color": "#C62828"}, secondary_y=True)
    fig.update_yaxes(title_text="trận", dtick=1, secondary_y=False)
    fig.update_yaxes(title_text="cm", secondary_y=True)
    fig.update_layout(height=260, margin={"l": 40, "r": 40, "t": 30, "b": 30}, legend={"orientation": "h", "y": 1.2})
    return fig


def _stats(staff: bool, area_id, d_from, d_to) -> None:
    if not staff:
        return
    # shortcut: thống kê mặc định 10 năm gần nhất khi không chọn "Từ ngày" (backend giới hạn 3700 ngày)
    date_from = d_from or (datetime.now(timezone.utc) - timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        s = api.get("/statistics/flood-events", {"group": "month", "area_id": area_id, "date_from": date_from, "date_to": d_to})
    except api.ApiError as e:
        show_error(e)
        return
    with st.container(border=True):
        st.markdown(f"**Số trận ngập theo tháng · tổng {s['total']}**")
        if s["by_time"]:
            st.plotly_chart(monthly_chart(s["by_time"]), width="stretch", key="hist-chart")
        else:
            st.caption("Không có sự kiện trong khoảng thời gian này.")


def _create_form() -> None:
    with st.expander("Thêm sự kiện ngập"), st.form("hist-new", clear_on_submit=False):
        c = st.columns(2)
        name = st.text_input("Địa điểm", max_chars=200)
        lat = c[0].number_input("Vĩ độ (trong TP.HCM)", -90.0, 90.0, 10.78, format="%.6f")
        lon = c[1].number_input("Kinh độ (trong TP.HCM)", -180.0, 180.0, 106.70, format="%.6f")
        d1, t1 = c[0].date_input("Bắt đầu (giờ Việt Nam)", key="hn-d1", format="DD/MM/YYYY"), c[0].time_input("Giờ bắt đầu", time(0, 0), key="hn-t1")
        end = c[1].checkbox("Có thời điểm kết thúc")
        d2, t2 = c[1].date_input("Kết thúc", key="hn-d2", format="DD/MM/YYYY"), c[1].time_input("Giờ kết thúc", time(0, 0), key="hn-t2")
        depth = c[0].number_input("Độ sâu lớn nhất (cm, 0–500; 0 = không rõ)", 0.0, 500.0, 0.0)
        cause = c[1].selectbox("Nguyên nhân", list(CAUSE_VI), format_func=CAUSE_VI.get)
        desc = st.text_area("Mô tả", max_chars=2000, height=80)
        if st.form_submit_button("Lưu", type="primary"):
            if len(name.strip()) < 2:
                st.error("Địa điểm tối thiểu 2 ký tự")
            elif end and datetime.combine(d2, t2) <= datetime.combine(d1, t1):
                st.error("Kết thúc phải sau thời điểm bắt đầu")
            else:
                body = {"location_name": name.strip(), "latitude": lat, "longitude": lon, "started_at": vn_local_to_iso(d1, t1),
                        "ended_at": vn_local_to_iso(d2, t2) if end else None, "max_depth_cm": depth or None, "cause": cause,
                        "description": desc}
                if run_action(lambda: api.post("/history/events", body), "Đã thêm sự kiện ngập"):
                    st.rerun()


def _confirm_delete(ev: dict) -> None:
    st.warning(f"Xoá sự kiện \"{ev['location_name']}\" ({fmt_dt(ev['started_at'])})? Thao tác không thể hoàn tác.")
    ok, no = st.columns(2)
    if ok.button("Xoá vĩnh viễn", type="primary", key="hist-del-ok"):
        st.session_state.pop("hist-del")
        if run_action(lambda: api.delete(f"/history/events/{ev['id']}"), "Đã xoá sự kiện"):
            st.rerun()
    if no.button("Huỷ", key="hist-del-no"):
        st.session_state.pop("hist-del")
        st.rerun()


def render() -> None:
    staff = auth.is_staff()
    st.title("Lịch sử ngập")
    if staff:
        _create_form()
    with st.container(border=True):
        c = st.columns(5)
        q = c[0].text_input("Tìm kiếm", placeholder="Địa điểm, mô tả", key="h-q")
        with c[1]:
            area = area_select("Khu vực", "h-area")
        d_from = c[2].date_input("Từ ngày", value=None, key="h-from", format="DD/MM/YYYY")
        d_to = c[3].date_input("Đến ngày", value=None, key="h-to", format="DD/MM/YYYY")
        min_depth = c[4].number_input("Độ sâu tối thiểu (cm)", min_value=0.0, value=None, key="h-depth")
        s1, s2 = st.columns([3, 2])
        sort = s1.selectbox("Sắp xếp theo", list(SORTS), format_func=SORTS.get, key="h-sort")
        direction = s2.radio("Thứ tự", ["desc", "asc"], format_func=lambda x: "Giảm dần" if x == "desc" else "Tăng dần",
                             horizontal=True, key="h-dir")
    date_from, date_to = vn_date_to_iso(d_from), vn_date_to_iso(d_to, True)
    _stats(staff, area, date_from, date_to)
    f = {"q": q, "area_id": area, "date_from": date_from, "date_to": date_to, "min_depth": min_depth, "sort": sort, "direction": direction}
    reset_page_on_change("h-page", repr(f))
    try:
        data = api.get("/history/events", {**f, "page": st.session_state.get("h-page", 1), "size": 20})
    except api.ApiError as e:
        show_error(e)
        return
    if "hist-del" in st.session_state:
        _confirm_delete(st.session_state["hist-del"])
    if not data["items"]:
        st.info("Không có sự kiện ngập phù hợp bộ lọc.")
        return
    widths = [3, 1.6, 1.6, 1.6, 1.4, 1.4, 3] + ([0.9] if staff else [])
    for col, h in zip(st.columns(widths), ["Địa điểm", "Khu vực", "Bắt đầu", "Kết thúc", "Độ sâu lớn nhất", "Nguyên nhân", "Mô tả", ""][: len(widths)]):
        col.markdown(f"**{h}**")
    for e in data["items"]:
        c = st.columns(widths)
        c[0].markdown(f"**{esc_md(e['location_name'])}** {sim_badge(e.get('is_simulated'))}")
        c[1].write((e.get("area") or {}).get("name", "—"))
        c[2].write(fmt_dt(e["started_at"]))
        c[3].write(fmt_dt(e.get("ended_at")))
        c[4].write(fmt_num(e.get("max_depth_cm"), " cm"))
        c[5].write(CAUSE_VI.get(e["cause"], e["cause"]))
        c[6].text(e.get("description") or "—")
        if staff and e["id"] > 0 and c[7].button("Xoá", key=f"hist-del-{e['id']}"):  # id âm: dòng mô phỏng
            st.session_state["hist-del"] = e
            st.rerun()
    pager("h-page", data["total"], data["size"])
