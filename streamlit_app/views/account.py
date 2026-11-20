"""Đổi mật khẩu của tài khoản đang đăng nhập."""
import re

import api
import streamlit as st
from common import show_error


def render() -> None:
    st.title("Đổi mật khẩu")
    with st.form("change-password"):
        cur = st.text_input("Mật khẩu hiện tại", type="password")
        new = st.text_input("Mật khẩu mới (tối thiểu 10 ký tự, có chữ và số)", type="password")
        if st.form_submit_button("Đổi mật khẩu", type="primary"):
            if len(new) < 10 or not (re.search(r"\d", new) and re.search(r"[a-zA-Z]", new)):
                st.error("Mật khẩu mới tối thiểu 10 ký tự, gồm cả chữ và số")
                return
            try:
                r = api.post("/auth/change-password", {"current_password": cur, "new_password": new})
            except api.ApiError as e:
                show_error(e)
                return
            st.session_state["token"] = st.session_state["cookie_set"] = r["access_token"]  # token mới sau khi đổi
            st.success("Đã đổi mật khẩu.")
