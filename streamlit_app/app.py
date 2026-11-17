"""OctotusMap - giao diện Streamlit (REST client của backend FastAPI).

Chạy: backend/.venv/Scripts/python -m streamlit run streamlit_app/app.py --server.port 8501
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import auth  # noqa: E402
import nav  # noqa: E402
import streamlit as st  # noqa: E402

st.set_page_config(page_title="OctotusMap", page_icon="🌊", layout="wide")
_pages = nav.build_pages()
_nav = st.navigation(list(_pages.values()))

with st.sidebar:
    if notice := st.session_state.pop("auth_notice", None):  # 401 đã đăng xuất phiên cũ
        st.warning(notice)
    u = auth.user()
    if u:
        st.markdown(f"**{u.get('full_name') or u['username']}**  \n{', '.join(u['role_codes'])}")
        from views import notifications
        notifications.render(_pages.get("alerts"))
        if st.button("Đăng xuất", key="logout"):
            auth.logout()
            st.rerun()
    else:
        st.caption("Bạn đang xem công khai. Đăng nhập để báo ngập hoặc xử lý cảnh báo.")

_nav.run()
