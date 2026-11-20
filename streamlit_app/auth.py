"""Phiên đăng nhập trong st.session_state (token Bearer + hồ sơ từ /auth/me), giữ qua tải lại trang bằng cookie."""
import re

import api
import streamlit as st

COOKIE = "octo_session"
TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")  # JWT: chỉ ký tự an toàn để ghi vào JS

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
    st.session_state["cookie_set"] = r["access_token"]
    return st.session_state["user"]


def restore() -> None:
    """Tải lại trang làm mất session_state: khôi phục phiên từ cookie (một lần mỗi phiên)."""
    s = st.session_state
    if s.get("user") or s.get("cookie_tried"):
        return
    s["cookie_tried"] = True
    try:
        tok = st.context.cookies.get(COOKIE)
    except Exception:  # ngoài phiên trình duyệt (AppTest, script)
        tok = None
    if not isinstance(tok, str) or not TOKEN_RE.fullmatch(tok):
        return
    s["token"] = tok
    try:
        s["user"] = api.get("/auth/me")
    except api.ApiError:  # token đã hết hạn/bị vô hiệu (đổi mật khẩu, đăng xuất ở nơi khác)
        for k in ("token", "user", "auth_notice"):
            s.pop(k, None)
        s["cookie_clear"] = True


def cookie_script() -> str | None:
    """JS ghi/xoá cookie phiên ở trang cha (chạy trong iframe cùng origin của components.html)."""
    s = st.session_state
    tok = s.pop("cookie_set", None)
    if tok and TOKEN_RE.fullmatch(tok):
        return (f'const c="{COOKIE}={tok}; path=/; max-age={api.JWT_MAX_AGE_S}; SameSite=Strict"'
                '+(parent.location.protocol==="https:"?"; Secure":""); parent.document.cookie=c;')
    if s.pop("cookie_clear", False):
        return f'parent.document.cookie="{COOKIE}=; path=/; max-age=0; SameSite=Strict";'
    return None


def logout() -> None:
    try:
        api.post("/auth/logout")
    except api.ApiError:
        pass  # token hết hạn cũng coi như đã đăng xuất
    st.session_state.clear()  # không để dữ liệu của người dùng này cho người sau
    st.session_state["cookie_tried"] = True  # cookie cũ vẫn nằm trong request đầu của phiên: không khôi phục lại
    st.session_state["cookie_clear"] = True
