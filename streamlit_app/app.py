"""OctotusMap - giao diện Streamlit (REST client của backend FastAPI), bố cục theo bản React cũ.

Chạy (trong thư mục streamlit_app để nạp .streamlit/config.toml):
  ..\\backend\\.venv\\Scripts\\python -m streamlit run app.py --server.port 5173
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import api  # noqa: E402
import auth  # noqa: E402
import live  # noqa: E402
import nav  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

st.set_page_config(page_title="OctotusMap", page_icon=str(HERE / "static" / "favicon.png"), layout="wide")
st.html(f"<style>{(HERE / 'style.css').read_text(encoding='utf-8')}</style>")
st.logo(str(HERE / "static" / "logo-white.png"), size="large", link=None)
auth.restore()  # tải lại trang: lấy lại phiên từ cookie trước khi dựng menu theo vai trò
_pages = nav.build_pages()
_nav = st.navigation(list(_pages.values()), position="top")

if notice := st.session_state.pop("auth_notice", None):  # 401 đã đăng xuất phiên cũ
    st.warning(notice)
live.watch()  # có sự kiện mới từ backend (SSE) thì chạy lại trang ngay
if auth.is_staff():
    try:
        sims = api.get("/gis/simulations", ttl=10)
    except api.ApiError:
        sims = []
    if sims:
        with st.container(key="simbanner"):
            st.markdown(f"**Đang bật mô phỏng {len(sims)} vùng ngập.** Cảnh báo, Dự báo AI, Lịch sử ngập, Thống kê "
                        "có dữ liệu MÔ PHỎNG (chỉ cán bộ thấy). Admin tắt ở Bản đồ › Mô phỏng.")
with st.container(key="topbar", horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
    u = auth.user()
    if u:
        from views import notifications
        notifications.render(_pages.get("alerts"))
        st.page_link(_pages["account"], label=u.get("full_name") or u["username"],
                     help=f"{', '.join(u['role_codes'])} · bấm để đổi mật khẩu")
        if st.button("Đăng xuất", key="logout"):
            auth.logout()
            st.rerun()
    elif "login" in _pages:
        st.page_link(_pages["login"], label="Đăng nhập")

_nav.run()

# sau khi trang chạy: đăng nhập/đổi mật khẩu/đăng xuất trong lần chạy này đã đặt cờ ghi/xoá cookie
if js := auth.cookie_script():
    with st.container(key="jsbox"):
        components.html(f"<script>{js}</script>", height=0)
