"""Thông báo của người dùng (popover ở thanh trên), làm mới mỗi 60 giây."""
import api
import streamlit as st
from common import fmt_dt, refresh, show_error


@st.fragment(run_every=60)
def render(alerts_page=None) -> None:
    try:
        data = api.get("/notifications", {"size": 15})
    except api.ApiError as e:
        show_error(e)
        return
    unread = data.get("unread", 0)
    with st.popover(f"Thông báo · {unread}" if unread else "Thông báo", help=f"{unread} chưa đọc" if unread else None):
        if not data["items"]:
            st.caption("Chưa có thông báo")
            return
        if st.button("Đánh dấu tất cả đã đọc", key="notif-all"):
            try:
                api.post("/notifications/read-all")
            except api.ApiError as e:
                show_error(e)
            refresh()
        for n in data["items"]:
            label = f"{'' if n['is_read'] else '● '}{n['title']}\n\n{fmt_dt(n['created_at'])}"
            if st.button(label, key=f"notif-{n['id']}", width="stretch"):
                try:
                    api.post(f"/notifications/{n['id']}/read")
                except api.ApiError as e:
                    show_error(e)
                if n.get("alert_id") and alerts_page is not None:
                    st.session_state["alert_open"] = n["alert_id"]
                    st.switch_page(alerts_page)
                refresh()
