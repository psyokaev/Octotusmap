"""Menu theo vai trò, khớp NAV trong frontend/src/components/Layout.tsx."""
import importlib

import auth
import common
import streamlit as st

# (module, nhãn, vai trò được phép) - khớp NAV trong frontend/src/components/Layout.tsx
NAV = [
    ("map", "Bản đồ", None), ("alerts", "Cảnh báo", None), ("forecasts", "Dự báo AI", None), ("history", "Lịch sử ngập", None),
    ("dashboard", "Tổng quan", ("ADMIN", "OPERATOR")), ("statistics", "Thống kê", ("ADMIN", "OPERATOR")),
    ("stations", "Trạm quan trắc", ("ADMIN", "OPERATOR")), ("cameras", "Camera", ("ADMIN", "OPERATOR")),
    ("models", "Mô hình AI", ("ADMIN",)), ("users", "Tài khoản", ("ADMIN",)), ("settings", "Cấu hình", ("ADMIN",)),
]


def _runner(mod: str):
    def run():
        try:
            m = importlib.import_module(f"views.{mod}")
        except ModuleNotFoundError as e:
            if e.name != f"views.{mod}":
                raise
            st.info("Trang này chưa có trong bản Streamlit hiện tại (giai đoạn sau).")
            return
        m.render()
    return run


def build_pages() -> dict:
    """Trang theo vai trò. Quyền thật được backend kiểm tra; đây chỉ là ẩn menu."""
    pages = {}
    for mod, label, roles in NAV:
        if roles and not auth.has_role(*roles):
            continue
        if mod == "cameras" and not common.camera_enabled():
            continue
        pages[mod] = st.Page(_runner(mod), title=label, url_path=mod, default=(mod == "map"))
    if auth.user():
        pages["account"] = st.Page(_runner("account"), title="Đổi mật khẩu", url_path="account")
    else:
        pages["login"] = st.Page(_runner("login"), title="Đăng nhập", url_path="login")
    return pages
