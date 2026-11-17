"""Đăng nhập / tạo tài khoản người dân."""
import re

import api
import auth
import streamlit as st
from common import show_error


def _register(username: str, email: str, full_name: str, password: str) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_.]{3,50}", username):
        st.error("Tên đăng nhập 3–50 ký tự: chữ, số, dấu chấm, gạch dưới")
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        st.error("Email không hợp lệ")
    elif len(password) < 10 or not (re.search(r"\d", password) and re.search(r"[a-zA-Z]", password)):
        st.error("Mật khẩu tối thiểu 10 ký tự, gồm cả chữ và số")
    else:
        try:
            api.post("/auth/register", {"username": username, "email": email, "full_name": full_name or None, "password": password})
        except api.ApiError as e:
            show_error(e)
        else:
            st.success("Đã tạo tài khoản. Hãy đăng nhập ở thẻ bên cạnh.")


def render() -> None:
    st.title("OctotusMap")
    tab_in, tab_up = st.tabs(["Đăng nhập", "Tạo tài khoản người dân"])
    with tab_in, st.form("login"):
        username = st.text_input("Tên đăng nhập")
        password = st.text_input("Mật khẩu", type="password")
        if st.form_submit_button("Đăng nhập", type="primary"):
            if len(username.strip()) < 3 or not password:
                st.error("Nhập tên đăng nhập (tối thiểu 3 ký tự) và mật khẩu")
            else:
                try:
                    auth.login(username.strip(), password)
                except api.ApiError as e:
                    show_error(e)
                else:
                    st.rerun()
    with tab_up, st.form("register"):
        r_user = st.text_input("Tên đăng nhập", key="r-user")
        r_mail = st.text_input("Email", key="r-mail")
        r_name = st.text_input("Họ tên", key="r-name")
        r_pass = st.text_input("Mật khẩu", type="password", key="r-pass")
        if st.form_submit_button("Tạo tài khoản"):
            _register(r_user.strip(), r_mail.strip(), r_name.strip(), r_pass)
