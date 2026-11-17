"""Kiểm thử giao diện Streamlit bằng AppTest với api giả."""
import api
import auth
import common
import nav
import pytest
from conftest import ADMIN, ALERT_PUBLIC, OPERATOR, USER, run_view
from streamlit.testing.v1 import AppTest


def texts(at) -> str:
    parts = [e.value for e in at.markdown] + [e.value for e in at.caption] + [e.value for e in at.subheader] + [e.value for e in at.title]
    parts += [e.value for e in at.warning] + [e.value for e in at.error] + [e.value for e in at.info]
    return "\n".join(str(p) for p in parts)


def no_exception(at):
    assert not at.exception, [e.value for e in at.exception]


# ---- flood_cause: các ca của frontend/src/lib/risk.test.ts
def test_flood_cause_matches_react():
    assert common.flood_cause("TIDE", 40) == "Ngập do triều, khoảng 40 cm (ước tính)"
    assert common.flood_cause("RAIN_TIDE", None) == "Ngập do mưa kết hợp triều"
    assert common.flood_cause("REPORT") == "Người dân báo ngập"
    assert common.flood_cause(None, 30) is None
    assert common.flood_cause(None) is None
    assert common.flood_cause("RAIN", 12.5) == "Ngập do mưa, khoảng 12.5 cm (ước tính)"
    assert common.flood_cause("UNKNOWN", 5) is None
    assert common.flood_cause("CAMERA").startswith("Camera phát hiện ngập")


def test_time_is_shown_in_vietnam_zone():
    assert common.fmt_dt("2025-06-01T03:00:00Z") == "01/06/2025 10:00"
    assert common.fmt_dt("2025-06-01T03:00:00") == "01/06/2025 10:00"  # không có Z vẫn là UTC
    assert common.fmt_dt(None) == "—"
    assert common.vn_date_to_iso(__import__("datetime").date(2025, 6, 1)) == "2025-05-31T17:00:00Z"


# ---- đăng nhập và phân quyền menu
def test_login_page_renders(fake):
    at = run_view("login")
    no_exception(at)
    assert [t.label for t in at.text_input][:2] == ["Tên đăng nhập", "Mật khẩu"]
    assert [t.label for t in at.tabs] == ["Đăng nhập", "Tạo tài khoản người dân"]


def test_login_validation_and_success(fake, monkeypatch):
    fake.routes["POST /auth/login"] = {"access_token": "secret", "user": USER}
    fake.routes["/auth/me"] = USER
    at = run_view("login")
    at.text_input[0].set_value("nd").run()
    at.button[0].click().run()
    assert "tối thiểu 3 ký tự" in texts(at)
    at.text_input[0].set_value("nguoidan")
    at.text_input[1].set_value("matkhau12345")
    at.button[0].click().run()
    no_exception(at)
    assert at.session_state["user"]["role_codes"] == ["USER"]
    assert ("POST", "/auth/login", {"username": "nguoidan", "password": "matkhau12345"}) in fake.calls


def test_login_error_is_shown_in_vietnamese(fake, monkeypatch):
    def bad(path, body=None, params=None):
        raise api.ApiError(401, "INVALID", "Sai tên đăng nhập hoặc mật khẩu")
    monkeypatch.setattr(api, "post", bad)
    at = run_view("login")
    at.text_input[0].set_value("nguoidan")
    at.text_input[1].set_value("sai")
    at.button[0].click().run()
    assert at.error[0].value == "Sai tên đăng nhập hoặc mật khẩu"
    assert "sai" not in texts(at)  # mật khẩu không bị in ra


@pytest.mark.parametrize("user,expected_hidden,expected_shown", [
    (None, {"dashboard", "statistics", "stations", "models", "users", "settings"}, {"map", "alerts", "forecasts", "history", "login"}),
    (USER, {"dashboard", "models", "users", "settings"}, {"map", "alerts", "forecasts", "history", "account"}),
    (OPERATOR, {"models", "users", "settings"}, {"dashboard", "statistics", "stations", "map"}),
    (ADMIN, set(), {"dashboard", "models", "users", "settings", "map"}),
])
def test_role_gating(fake, monkeypatch, user, expected_hidden, expected_shown):
    monkeypatch.setattr(auth, "user", lambda: user)
    pages = nav.build_pages()
    assert not expected_hidden & set(pages)
    assert expected_shown <= set(pages)
    assert ("login" in pages) == (user is None)


def test_guest_app_has_no_staff_navigation(fake):
    at = AppTest.from_file(str(__import__("conftest").APP_DIR / "app.py"), default_timeout=30).run()
    no_exception(at)
    assert "Đăng nhập" in texts(at)  # sidebar nhắc đăng nhập
    assert not at.sidebar.button  # khách không có nút Đăng xuất/Thông báo


# ---- bản đồ
def test_map_renders_for_guest(fake):
    at = run_view("map")
    no_exception(at)
    t = texts(at)
    assert "Quận 1" in "".join(e.label for e in at.expander)
    assert "Cập nhật 01/06/2025 10:00" in t
    assert "phường nguy cơ cao · Ngập do triều, khoảng 40 cm (ước tính)" in t
    assert [r.label for r in at.radio if r.key == "m-panel"] == ["Panel"]
    assert at.radio(key="m-panel").options == ["Tình hình", "Chi tiết", "Chỉ đường", "Báo cáo ngập"]  # khách không có "Mô phỏng"
    assert ("GET", "/gis/risk-layers", {"horizon": 0}) in fake.calls
    assert not any(c[1] == "/admin/simulations" for c in fake.calls)


def test_map_admin_has_simulation_panel(fake):
    at = run_view("map", ADMIN)
    no_exception(at)
    assert "Mô phỏng" in at.radio(key="m-panel").options
    at.radio(key="m-panel").set_value("Mô phỏng").run()
    assert "Bấm lên bản đồ để chọn tâm vùng ngập." in texts(at)
    assert at.button(key="sim-create").disabled


def test_map_point_detail_with_cause_and_cm(fake):
    at = AppTest.from_string(
        __import__("conftest").PRELUDE + "import streamlit as st\nfrom views import map\n"
        "st.session_state['m-point'] = {'lat': 10.7, 'lon': 106.7, 'label': None}\nst.session_state['m-panel-next'] = 'Chi tiết'\nmap.render()\n",
        default_timeout=30).run()
    no_exception(at)
    t = texts(at)
    assert "Ngập do triều, khoảng 40 cm (ước tính)" in t
    assert "Phường Bến Nghé" in t and "Quận 1" in t
    assert "Khuyến nghị" in t and "3 sự kiện" in t


def test_map_point_detail_for_citizen_with_null_explanation(fake):
    risk = [{**r, "explanation": None} for r in fake.routes["/gis/identify"]["risk"]]
    fake.routes["/gis/identify"] = {**fake.routes["/gis/identify"], "risk": risk}
    at = AppTest.from_string(
        __import__("conftest").PRELUDE + "import streamlit as st\nfrom views import map\n"
        "st.session_state['m-point'] = {'lat': 10.7, 'lon': 106.7, 'label': None}\nst.session_state['m-panel-next'] = 'Chi tiết'\nmap.render()\n",
        default_timeout=30).run()
    no_exception(at)
    assert "ước tính" in texts(at)  # xác suất ngập vẫn ghi "ước tính"
    assert "Ngập do triều" not in texts(at)


def test_map_search_by_coordinate_opens_detail(fake):
    fake.routes["/search"] = {"results": [{"type": "coordinate", "label": "10.78000, 106.70000", "lat": 10.78, "lon": 106.7}], "attribution": ""}
    at = run_view("map")
    at.text_input(key="m-search-q").set_value("10.78, 106.70").run()
    at.button(key="m-search-pick").click().run()
    no_exception(at)
    assert at.radio(key="m-panel").value == "Chi tiết"
    assert at.session_state["m-center"] == (10.78, 106.7)


def test_map_directions_shows_routes_and_legend(fake):
    fake.routes["POST /routing/route"] = __import__("conftest").ROUTE
    at = AppTest.from_string(
        __import__("conftest").PRELUDE + "import streamlit as st\nfrom views import map\n"
        "st.session_state['m-start'] = {'label': 'A', 'lon': 106.7, 'lat': 10.78}\n"
        "st.session_state['m-end'] = {'label': 'B', 'lon': 106.71, 'lat': 10.79}\nst.session_state['m-panel-next'] = 'Chỉ đường'\nmap.render()\n",
        default_timeout=30).run()
    no_exception(at)
    t = texts(at)
    assert any("Tuyến đề xuất" in b.label for b in at.button)
    assert "0.3 km có thể ngập" in t and "Đoạn cần chú ý" in t and "Triều cao" in t
    assert "Chỉ mang tính tham khảo." in t
    for label in ("Không có dấu hiệu ngập", "Có nguy cơ ngập", "Có thể đang ngập", "Người dân báo ngập"):
        assert label in t


def test_map_reports_confirm_and_staff_reject(fake):
    for user, rejects in ((USER, False), (OPERATOR, True)):
        at = AppTest.from_string(
            __import__("conftest").PRELUDE + "import streamlit as st\nfrom views import map\nst.session_state['m-panel-next'] = 'Báo cáo ngập'\nmap.render()\n",
            default_timeout=30)
        at.session_state["user"], at.session_state["token"] = user, "t"
        at.run()
        no_exception(at)
        assert "Ngập đầu gối" in texts(at)
        assert at.button(key="rp-ok-3") is not None
        assert any(b.key == "rp-no-3" for b in at.button) == rejects


# ---- cảnh báo
def test_alerts_citizen_sees_public_fields_only(fake):
    fake.routes["/alerts"] = {"items": [ALERT_PUBLIC], "total": 1, "page": 1, "size": 20}
    at = run_view("alerts", USER)
    no_exception(at)
    t = texts(at)
    assert "AL-10" in [m.value for m in at.markdown] and "Nguy cơ ngập cao" in t
    assert "Ngập do mưa kết hợp triều, khoảng 30 cm (ước tính)" in t
    assert "Phường: Phường Bến Nghé" in t
    assert not any(m.value == "**Trạng thái**" for m in at.markdown)  # cột trạng thái chỉ cho cán bộ
    assert [m.label for m in at.multiselect] == ["Mức"]
    assert not any(b.label == "Chuẩn bị tệp Excel" for b in at.button)


def test_alerts_citizen_detail_has_no_staff_panel(fake):
    fake.routes["/alerts/10"] = {**ALERT_PUBLIC, "history": []}
    at = AppTest.from_string(__import__("conftest").PRELUDE + "import streamlit as st\nfrom views import alerts\nst.session_state['alert_open'] = 10\nalerts.render()\n", default_timeout=30)
    at.session_state["user"], at.session_state["token"] = USER, "t"
    at.run()
    no_exception(at)
    t = texts(at)
    assert "Khuyến nghị" in t and "Tránh khu vực trũng" in t
    assert "Xử lý cảnh báo" not in t and "Lịch sử xử lý" not in t and "Giải thích mức cảnh báo" not in t


def test_alerts_staff_detail_actions_and_export(fake):
    at = AppTest.from_string(__import__("conftest").PRELUDE + "import streamlit as st\nfrom views import alerts\nst.session_state['alert_open'] = 10\nalerts.render()\n", default_timeout=30)
    at.session_state["user"], at.session_state["token"] = OPERATOR, "t"
    at.run()
    no_exception(at)
    t = texts(at)
    assert "Giải thích mức cảnh báo" in t and "Lịch sử xử lý" in t and "Triều > 1.5 m" in t and "Trạm liên quan: R01" in t
    assert [m.label for m in at.multiselect] == ["Mức", "Trạng thái"]
    at.button(key="al-ack").click().run()
    assert ("POST", "/alerts/10/acknowledge", None) in fake.calls
    at.button(key="al-export").click().run()
    assert at.get("download_button")


def test_alerts_status_transition_needs_confirmation(fake):
    at = AppTest.from_string(__import__("conftest").PRELUDE + "import streamlit as st\nfrom views import alerts\nst.session_state['alert_open'] = 10\nalerts.render()\n", default_timeout=30)
    at.session_state["user"], at.session_state["token"] = OPERATOR, "t"
    at.run()
    sel = next(s for s in at.selectbox if s.label == "Chuyển trạng thái")
    assert sel.options == ["Chọn trạng thái…", "Đã tiếp nhận", "Đang xử lý", "Đã xử lý", "Đã đóng"]
    sel.set_value("CLOSED")
    next(b for b in at.button if b.label == "Cập nhật trạng thái").click().run()
    assert not any(c[1].endswith("/status") for c in fake.calls)  # chưa gửi khi chưa xác nhận
    at.button(key="al-confirm").click().run()
    assert ("POST", "/alerts/10/status", {"status": "CLOSED", "note": ""}) in fake.calls


# ---- dự báo AI
def test_forecasts_render_with_reason_column(fake):
    at = run_view("forecasts")
    no_exception(at)
    assert "LSTM-rain" in texts(at)
    assert [m.label for m in at.metric] == ["MAE mưa (mm)", "RMSE mưa (mm)"]
    assert at.metric[0].value == "0.512"
    tables = [d.value for d in at.dataframe]
    ranking = next(t for t in tables if "Lý do" in t.columns)
    assert ranking["Lý do"].tolist() == ["Ngập do triều, khoảng 40 cm (ước tính)", "—"]  # explanation null -> "—"
    station = next(t for t in tables if "+6h" in t.columns)
    assert station["+1h"][0] == "1,5 mm · 15%"
    assert at.get("plotly_chart")


def test_forecasts_warning_and_empty(fake):
    fake.routes["/forecasts/model-status"] = {**fake.routes["/forecasts/model-status"], "forecast_model": None, "warning": "Mô hình quá cũ"}
    fake.routes["/forecasts/latest"] = []
    at = run_view("forecasts")
    no_exception(at)
    assert at.warning[0].value == "Mô hình quá cũ"
    assert "Chưa có bản dự báo nào" in texts(at)


# ---- lịch sử ngập
def test_history_citizen_sees_list_without_stats_or_delete(fake):
    at = run_view("history", USER)
    no_exception(at)
    assert not at.get("plotly_chart")
    assert not any(c[1] == "/statistics/flood-events" for c in fake.calls)
    assert not any(b.label == "Xoá" for b in at.button)
    assert not at.expander
    assert any("Đường Nguyễn Hữu Cảnh" in m.value for m in at.markdown)
    assert "40 cm" in [m.value for m in at.markdown]


def test_history_staff_sees_chart_create_and_delete(fake):
    at = run_view("history", OPERATOR)
    no_exception(at)
    assert at.get("plotly_chart")
    assert [e.label for e in at.expander] == ["Thêm sự kiện ngập"]
    at.button(key="hist-del-7").click().run()
    assert "Xoá sự kiện \"Đường Nguyễn Hữu Cảnh\" (14/10/2024 08:00)" in texts(at)
    at.button(key="hist-del-ok").click().run()
    assert ("DELETE", "/history/events/7", None) in fake.calls


def test_history_empty_state(fake):
    fake.routes["/history/events"] = {"items": [], "total": 0, "page": 1, "size": 20}
    at = run_view("history", USER)
    assert "Không có sự kiện ngập phù hợp bộ lọc." in texts(at)


def test_api_error_is_shown(fake):
    fake.routes["/history/events"] = api.ApiError(500, "SERVER", "Máy chủ gặp sự cố")
    at = run_view("history", USER)
    assert at.error[0].value == "Máy chủ gặp sự cố"


def test_client_ip_is_forwarded_to_backend(monkeypatch):
    from types import SimpleNamespace

    import api

    monkeypatch.setattr(api.st, "context", SimpleNamespace(ip_address="203.0.113.7"))
    assert api._headers()["X-Forwarded-For"] == "203.0.113.7"
    monkeypatch.setattr(api.st, "context", SimpleNamespace(ip_address=None))
    assert "X-Forwarded-For" not in api._headers()
