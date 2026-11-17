"""Phiên đăng nhập trong st.session_state (token Bearer + hồ sơ từ /auth/me)."""
import api
import streamlit as st

STAFF = ("ADMIN", "OPERATOR")


def user() -> dict | None:
    return st.session_state.get("user")


def has_role(*roles: str) -> bool:
    u = user()
    return bool(u) and any(r in u.get("role_codes", []) for r in roles)


def is_staff() -> bool:
    return has_role(*STAFF)


def is_admin() -> bool:
    return has_role("ADMIN")


def login(username: str, password: str) -> dict:
    r = api.post("/auth/login", {"username": username, "password": password})
    st.session_state["token"] = r["access_token"]
    try:
        st.session_state["user"] = api.get("/auth/me")  # vai trò lấy từ /auth/me
    except api.ApiError:
        st.session_state.pop("token", None)  # không giữ token khi chưa có hồ sơ
        raise
    return st.session_state["user"]


def logout() -> None:
    try:
        api.post("/auth/logout")
    except api.ApiError:
        pass  # token hết hạn cũng coi như đã đăng xuất
    st.session_state.clear()  # không để dữ liệu của người dùng này cho người sau
