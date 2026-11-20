"""Kiểm thử trang cán bộ/quản trị bằng AppTest với api giả."""
import api
import auth
import nav
import pytest
import streamlit as st
from conftest import ADMIN, OPERATOR, USER, run_view
from test_views import no_exception, texts

STAFF_PAGES = ["dashboard", "statistics", "stations", "cameras"]
ADMIN_PAGES = ["models", "users", "settings"]
PW = "Mật khẩu (tối thiểu 10 ký tự, gồm chữ và số)"


@pytest.fixture
def cam_on(fake, monkeypatch):
    monkeypatch.setattr(api, "health", lambda: {"camera_enabled": True})
    return fake


def w(seq, label):
    """Widget theo nhãn."""
    return next(x for x in seq if x.label == label)


def writes(fake, method):
    return [c for c in fake.calls if c[0] == method]


def errors(at):
    return [e.value for e in at.error]


# ---- mọi trang hiển thị với dữ liệu mẫu theo vai trò
@pytest.mark.parametrize("page", STAFF_PAGES)
@pytest.mark.parametrize("user", [OPERATOR, ADMIN])
def test_staff_pages_render(cam_on, page, user):
    at = run_view(page, user)
    no_exception(at)
    assert not errors(at)


@pytest.mark.parametrize("page", ADMIN_PAGES)
def test_admin_pages_render(fake, page):
    at = run_view(page, ADMIN)
    no_exception(at)
    assert not errors(at)


def test_settings_all_tabs_render(fake):
    at = run_view("settings", ADMIN)
    for tab in ["settings", "audit", "sources", "ops"]:
        at.radio(key="cfg-tab").set_value(tab).run()
        no_exception(at)
        assert not errors(at), (tab, errors(at))


def test_statistics_all_tabs_render(cam_on):
    at = run_view("statistics", ADMIN)
    for tab in at.radio(key="stt-tab").options:
        at.radio(key="stt-tab").set_value(tab).run()
        no_exception(at)
        assert not errors(at), (tab, errors(at))


# ---- phân quyền menu và camera
@pytest.mark.parametrize("user,hidden", [(None, {"dashboard", "models"}), (USER, {"stations", "settings"}), (OPERATOR, {"users", "models"}),
                                         (ADMIN, set())])
def test_staff_menu_gating(cam_on, monkeypatch, user, hidden):
    st.session_state.pop("_camera_enabled", None)
    monkeypatch.setattr(auth, "user", lambda: user)
    pages = nav.build_pages()
    assert not hidden & set(pages)
    assert ("cameras" in pages) == bool(user and ("ADMIN" in user["role_codes"] or "OPERATOR" in user["role_codes"]))


def test_camera_page_hidden_when_disabled(fake, monkeypatch):
    st.session_state.pop("_camera_enabled", None)
    monkeypatch.setattr(auth, "user", lambda: ADMIN)
    assert "cameras" not in nav.build_pages()  # fake.health: camera_enabled False


# ---- Tổng quan
def test_dashboard_kpis_and_camera_gate(cam_on, monkeypatch):
    at = run_view("dashboard", ADMIN)
    labels = [m.label for m in at.metric]
    assert any("Khu vực nguy cơ cao hiện tại" in x for x in labels) and "Camera" in labels
    assert "gồm dự báo tới 6 giờ" in texts(at)
    assert len(at.get("plotly_chart")) >= 7
    monkeypatch.setattr(api, "health", lambda: {"camera_enabled": False})
    at = run_view("dashboard", ADMIN)
    assert "Camera" not in [m.label for m in at.metric]
    assert "Nhận diện ngập qua camera" not in texts(at)


def test_dashboard_filters_reach_api(fake):
    at = run_view("dashboard", ADMIN)
    call = next(c for c in fake.calls if c[1] == "/statistics/overview")
    assert call[2]["risk_level"] is None and call[2]["data_type"] is None and call[2]["date_from"].endswith("Z")
    at.selectbox(key="db-preset").set_value("today").run()
    assert any(c[1] == "/statistics/rainfall" and c[2]["group"] == "hour" for c in fake.calls)


def test_dashboard_shows_backend_error(fake):
    fake.routes["/statistics/overview"] = api.ApiError(500, "X", "Máy chủ lỗi")
    at = run_view("dashboard", ADMIN)
    no_exception(at)
    assert "Máy chủ lỗi" in errors(at)


# ---- Thống kê
def test_statistics_exports(cam_on):
    at = run_view("statistics", OPERATOR)
    assert "Camera" in at.radio(key="stt-tab").options
    assert [b for b in at.button if b.label == "Xuất CSV"]  # tab mặc định là Lượng mưa
    w(at.button, "Xuất Excel").click().run()
    call = next(c for c in cam_on.calls if c[0] == "DOWNLOAD")
    assert call[1] == "/exports/excel" and call[2]["report"] == "rainfall"
    w(at.button, "Xuất CSV").click().run()
    call = [c for c in cam_on.calls if c[0] == "DOWNLOAD"][-1]  # lần chạy lại còn gọi API khác sau tải
    assert call[1] == "/exports/csv" and call[2]["kind"] == "rainfall"
    at.radio(key="stt-tab").set_value("risk").run()
    assert not [b for b in at.button if b.label == "Xuất CSV"]
    assert at.selectbox(key="stt-report-risk").value == "full"


def test_statistics_camera_tab_gated(fake):
    at = run_view("statistics", ADMIN)
    assert "Camera" not in at.radio(key="stt-tab").options


# ---- Tài khoản
def test_users_create_posts_payload(fake):
    at = run_view("users", ADMIN)
    at.button(key="usr-new").click().run()
    w(at.text_input, "Tên đăng nhập").set_value("canbo2")
    w(at.text_input, "Email").set_value("cb2@b.vn")
    w(at.text_input, PW).set_value("matkhau12345")
    w(at.multiselect, "Vai trò").set_value(["OPERATOR"])
    w(at.button, "Tạo người dùng").click().run()
    no_exception(at)
    assert ("POST", "/admin/users", {"username": "canbo2", "password": "matkhau12345", "email": "cb2@b.vn", "full_name": "", "roles": ["OPERATOR"]}) in fake.calls


def test_users_weak_password_blocked_and_backend_error_shown(fake, monkeypatch):
    at = run_view("users", ADMIN)
    at.button(key="usr-new").click().run()
    w(at.text_input, "Tên đăng nhập").set_value("canbo2")
    w(at.text_input, "Email").set_value("cb2@b.vn")
    w(at.text_input, PW).set_value("ngan")
    w(at.button, "Tạo người dùng").click().run()
    assert "Mật khẩu tối thiểu 10 ký tự" in errors(at)
    assert not writes(fake, "POST")

    def bad(path, body=None, params=None):
        raise api.ApiError(422, "VALIDATION", "Dữ liệu không hợp lệ", [{"loc": ["body", "email"], "msg": "đã tồn tại"}])
    monkeypatch.setattr(api, "post", bad)
    w(at.text_input, PW).set_value("matkhau12345")
    w(at.button, "Tạo người dùng").click().run()
    assert "Dữ liệu không hợp lệ — email: đã tồn tại" in errors(at)


def test_users_edit_and_delete_need_confirmation(fake):
    at = run_view("users", ADMIN)
    at.selectbox(key="usr-pick").set_value(2).run()
    at.button(key="usr-edit").click().run()
    w(at.checkbox, "Tài khoản đang hoạt động").uncheck()
    w(at.text_input, "Đặt lại mật khẩu (để trống nếu giữ nguyên)").set_value("matkhaumoi99")
    w(at.button, "Lưu").click().run()
    assert ("PATCH", "/admin/users/2", {"email": "nd@b.vn", "full_name": "Người Dân", "roles": ["USER"], "is_active": False,
                                         "new_password": "matkhaumoi99"}) in fake.calls
    at = run_view("users", ADMIN)
    at.selectbox(key="usr-pick").set_value(2).run()
    at.button(key="usr-del").click().run()
    assert not writes(fake, "DELETE")  # chưa xác nhận thì chưa xoá
    assert "Xoá tài khoản nguoidan?" in texts(at)
    at.button(key="usr-del-p-ok").click().run()
    assert ("DELETE", "/admin/users/2", None) in fake.calls


def test_users_cannot_delete_self(fake):
    at = run_view("users", ADMIN)  # chọn mặc định là admin (id 1) = chính mình
    assert not [b for b in at.button if b.key == "usr-del"]
    assert "Không thể xoá chính mình." in texts(at)


# ---- Cấu hình: quy tắc
def test_rules_save_needs_confirm_then_posts_new_version(fake):
    at = run_view("settings", ADMIN)
    at.text_input(key="rule-name").set_value("Quy tắc v3")
    at.text_input(key="rule-notes").set_value("tăng ngưỡng cao")
    at.number_input(key="rule-high").set_value(0.8)
    w(at.button, "Lưu thành phiên bản mới").click().run()
    no_exception(at)
    assert not writes(fake, "POST")
    assert "kích hoạt ngay" in texts(at)
    at.button(key="rule-save-p-ok").click().run()
    _, path, body = next(c for c in fake.calls if c[0] == "POST")
    assert path == "/admin/rules" and body["name"] == "Quy tắc v3" and body["notes"] == "tăng ngưỡng cao"
    assert body["config"]["thresholds"] == {"medium": 0.4, "high": 0.8}
    assert body["config"]["weights"]["rainfall"] == 0.3 and body["config"]["alert_min_level"] == "MEDIUM"


def test_rules_invalid_thresholds_blocked(fake):
    at = run_view("settings", ADMIN)
    at.number_input(key="rule-high").set_value(0.3)
    w(at.button, "Lưu thành phiên bản mới").click().run()
    assert "Ngưỡng trung bình phải nhỏ hơn ngưỡng cao" in errors(at)[0]
    assert not writes(fake, "POST") and "rule-save-p" not in at.session_state


def test_rules_activate_old_version_confirmed(fake):
    at = run_view("settings", ADMIN)
    at.button(key="rule-act-1").click().run()
    assert not writes(fake, "POST")
    at.button(key="rule-act-p-ok").click().run()
    assert ("POST", "/admin/rules/1/activate", None) in fake.calls


def test_rules_server_validation_errors_shown(fake, monkeypatch):
    def bad(path, body=None, params=None):
        raise api.ApiError(422, "VALIDATION", "Quy tắc không hợp lệ", ["tổng trọng số phải bằng 1"])
    monkeypatch.setattr(api, "post", bad)
    at = run_view("settings", ADMIN)
    w(at.button, "Lưu thành phiên bản mới").click().run()
    at.button(key="rule-save-p-ok").click().run()
    assert "Quy tắc không hợp lệ — tổng trọng số phải bằng 1" in errors(at)


# ---- Cấu hình: thiết lập, vận hành
def test_setting_save_confirm_then_put(fake):
    at = run_view("settings", ADMIN)
    at.radio(key="cfg-tab").set_value("settings").run()
    at.text_area(key="set-txt-alert.default").set_value('{"a": 2}')
    w(at.button, "Lưu").click().run()
    assert not writes(fake, "PUT")
    at.button(key="set-p-alert.default-ok").click().run()
    assert ("PUT", "/admin/settings/alert.default", {"value": {"a": 2}}) in fake.calls


def test_setting_invalid_json_rejected(fake):
    at = run_view("settings", ADMIN)
    at.radio(key="cfg-tab").set_value("settings").run()
    at.text_area(key="set-txt-alert.default").set_value("{khong json")
    w(at.button, "Lưu").click().run()
    assert "JSON không hợp lệ" in errors(at) and not writes(fake, "PUT")


def test_run_cycle_needs_confirmation(fake):
    at = run_view("settings", ADMIN)
    at.radio(key="cfg-tab").set_value("ops").run()
    at.button(key="ops-run").click().run()
    assert not writes(fake, "POST")
    at.button(key="ops-run-p-ok").click().run()
    assert ("POST", "/admin/jobs/run-cycle", None) in fake.calls


# ---- Mô hình AI
def test_model_activate_and_train_need_confirmation(fake):
    at = run_view("models", ADMIN)
    at.selectbox(key="mdl-pick").set_value(3).run()
    at.button(key="mdl-activate").click().run()
    assert not writes(fake, "POST")
    at.button(key="mdl-act-p-ok").click().run()
    assert ("POST", "/admin/models/3/activate", None) in fake.calls
    at = run_view("models", ADMIN)
    at.number_input(key="mdl-ep-vision").set_value(20)
    at.button(key="mdl-train-vision").click().run()
    assert not [c for c in fake.calls if c[1] == "/admin/models/train"]
    at.button(key="mdl-train-p-ok").click().run()
    assert ("POST", "/admin/models/train", {"task": "vision", "epochs": 20}) in fake.calls


def test_active_model_has_no_activate_button(fake):
    at = run_view("models", ADMIN)  # chọn mặc định = mô hình đang dùng
    assert not [b for b in at.button if b.key == "mdl-activate"]


# ---- Trạm quan trắc
def test_station_create_posts_payload(fake):
    at = run_view("stations", OPERATOR)
    at.button(key="stn-new").click().run()
    w(at.text_input, "Mã trạm").set_value("R02")
    w(at.text_input, "Tên trạm").set_value("Trạm mới")
    w(at.button, "Lưu").click().run()
    no_exception(at)
    _, path, body = next(c for c in fake.calls if c[0] == "POST")
    assert path == "/stations" and body["code"] == "R02" and body["station_type"] == "COMBINED" and body["interval_minutes"] == 60


def test_station_bad_code_blocked(fake):
    at = run_view("stations", OPERATOR)
    at.button(key="stn-new").click().run()
    w(at.text_input, "Mã trạm").set_value("R 02")
    w(at.text_input, "Tên trạm").set_value("Trạm mới")
    w(at.button, "Lưu").click().run()
    assert any("Mã trạm" in e for e in errors(at)) and not writes(fake, "POST")


def test_station_edit_omits_code_and_delete_is_soft_confirmed(fake):
    at = run_view("stations", OPERATOR)
    at.button(key="stn-edit").click().run()
    w(at.text_input, "Tên trạm").set_value("Tên mới")
    w(at.button, "Lưu").click().run()
    _, path, body = next(c for c in fake.calls if c[0] == "PATCH")
    assert path == "/stations/5" and body["name"] == "Tên mới" and "code" not in body
    at = run_view("stations", OPERATOR)
    at.button(key="stn-del").click().run()
    assert not writes(fake, "DELETE") and "xoá mềm" in texts(at)
    at.button(key="stn-del-p-ok").click().run()
    assert ("DELETE", "/stations/5", None) in fake.calls


def test_station_detail_shows_quality_forecast_and_manual_form(fake):
    at = run_view("stations", OPERATOR)
    at.button(key="stn-detail").click().run()
    no_exception(at)
    t = texts(at)
    assert "Chất lượng dữ liệu 7 ngày" in t and "Dự báo của trạm (ước tính)" in t and "Nhập quan trắc thủ công" in t
    w(at.button, "Gửi quan trắc").click().run()
    assert "Nhập ít nhất lượng mưa hoặc mực nước" in errors(at)


# ---- Camera
def test_camera_create_and_delete(cam_on):
    at = run_view("cameras", OPERATOR)
    assert "mô phỏng" in texts(at).lower()
    at.button(key="cam-new").click().run()
    w(at.text_input, "Mã camera").set_value("CAM2")
    w(at.text_input, "Tên camera").set_value("Camera hai")
    w(at.button, "Lưu").click().run()
    _, path, body = next(c for c in cam_on.calls if c[0] == "POST")
    assert path == "/cameras" and body["code"] == "CAM2" and body["roi"] is None and body["retention_days"] == 30
    at = run_view("cameras", OPERATOR)
    at.button(key="cam-del-4").click().run()
    assert not writes(cam_on, "DELETE")
    at.button(key="cam-del-4-p-ok").click().run()
    assert ("DELETE", "/cameras/4", None) in cam_on.calls


def test_camera_bad_roi_and_url_rejected(cam_on):
    at = run_view("cameras", OPERATOR)
    at.button(key="cam-new").click().run()
    url = "URL nguồn (http(s):// hoặc rtsp://, có thể để trống)"
    w(at.text_input, "Mã camera").set_value("CAM2")
    w(at.text_input, "Tên camera").set_value("Camera hai")
    w(at.text_input, url).set_value("ftp://x")
    w(at.button, "Lưu").click().run()
    assert "URL phải bắt đầu" in errors(at)[0]
    w(at.text_input, url).set_value("")
    w(at.text_input, "Vùng quan tâm ROI (tuỳ chọn, JSON: [[x,y],…] tỉ lệ 0..1, ≥3 điểm)").set_value("khong")
    w(at.button, "Lưu").click().run()
    assert "ROI không phải JSON hợp lệ" in errors(at) and not writes(cam_on, "POST")


def test_camera_detections_and_analyze_panels(cam_on):
    at = run_view("cameras", OPERATOR)
    at.button(key="cam-hist-4").click().run()
    no_exception(at)
    assert "Lịch sử nhận dạng · CAM1" in texts(at)
    at.button(key="cam-an-open").click().run()
    no_exception(at)
    assert "Phân tích ảnh ngập" in texts(at)
    at.button(key="cam-an-go").click().run()
    assert "Chọn một tệp" in errors(at)


# ---- vòng sửa lỗi sau review
ALERT_PRELUDE = "import streamlit as st\nfrom views import alerts\nst.session_state.setdefault('alert_open', {})\nalerts.render()\n"


def test_map_tooltips_escape_html():
    import folium
    from views import map_layers as ml
    evil = '<img src=x onerror=alert(1)>`'
    m = folium.Map()
    ml.add_hotspots(m, [{"id": 7, "name": evil, "latitude": 10.7, "longitude": 106.7}])
    ml.add_endpoints(m, {"lat": 1, "lon": 2, "label": evil}, None)
    html = m.get_root().render()
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html and "mã 7" in html
    assert ml.area_tooltip({"name": evil, "risk_level": "LOW"}).startswith("&lt;img")


def test_pending_status_does_not_carry_to_other_alert(fake):
    from conftest import PRELUDE
    from streamlit.testing.v1 import AppTest
    fake.routes["/alerts/11"] = {**fake.routes["/alerts/10"], "id": 11, "code": "A-11"}
    at = AppTest.from_string(PRELUDE + ALERT_PRELUDE.format(10), default_timeout=30)
    at.session_state["user"], at.session_state["token"] = OPERATOR, "t"
    at.run()
    next(s for s in at.selectbox if s.label == "Chuyển trạng thái").set_value("CLOSED")
    next(b for b in at.button if b.label == "Cập nhật trạng thái").click().run()
    assert at.session_state["al-pending"]["alert_id"] == 10
    at.session_state["alert_open"] = 11
    at.run()
    assert "al-confirm" not in [b.key for b in at.button]
    assert not any(c[1].endswith("/status") for c in fake.calls)


def test_logout_clears_whole_session(fake):
    st.session_state.clear()
    st.session_state.update({"user": ADMIN, "token": "t", "al-xlsx": ("s", "n", b"x"), "m-point": 1})
    auth.logout()
    assert dict(st.session_state) == {"cookie_tried": True, "cookie_clear": True}  # chỉ còn cờ xoá cookie phiên


def test_session_restored_from_cookie_and_bad_cookie_cleared(monkeypatch):
    jwt = "aaa.bbb.ccc"
    for me, user_ok in ((lambda *a, **k: ADMIN, True), (lambda *a, **k: (_ for _ in ()).throw(api.ApiError(401, "U", "x")), False)):
        st.session_state.clear()
        monkeypatch.setattr(st, "context", type("C", (), {"cookies": {auth.COOKIE: jwt}})())
        monkeypatch.setattr(api, "get", me)
        auth.restore()
        assert (st.session_state.get("user") == ADMIN) == user_ok
        assert ("token" in st.session_state) == user_ok and st.session_state.get("cookie_clear", False) != user_ok
    st.session_state.clear()
    monkeypatch.setattr(st, "context", type("C", (), {"cookies": {auth.COOKIE: 'x";alert(1);"'}})())
    auth.restore()
    assert "token" not in st.session_state  # cookie không đúng dạng JWT bị bỏ qua (không được ghi vào JS)
    st.session_state.update({"cookie_set": jwt})
    assert jwt in auth.cookie_script() and auth.cookie_script() is None


def test_login_drops_token_when_me_fails(monkeypatch):
    st.session_state.clear()
    monkeypatch.setattr(api, "post", lambda *a, **k: {"access_token": "t"})
    monkeypatch.setattr(api, "get", lambda *a, **k: (_ for _ in ()).throw(api.ApiError(500, "X", "lỗi")))
    with pytest.raises(api.ApiError):
        auth.login("abc", "x")
    assert "token" not in st.session_state and "user" not in st.session_state


def test_export_hidden_after_filters_change(cam_on):
    at = run_view("statistics", OPERATOR)
    w(at.button, "Xuất Excel").click().run()
    assert at.get("download_button")
    at.radio(key="stt-tab").set_value("risk").run()  # đổi tab -> đổi chữ ký -> ẩn tệp cũ
    assert not at.get("download_button")


def test_esc_md_neutralizes_markdown_image():
    from common import esc_md
    assert esc_md("![x](http://e.com/a.png)") == r"\!\[x\]\(http://e\.com/a\.png\)"


def test_ward_layers_faint_green_for_low():
    import folium
    from views import map_layers as ml
    wards = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [106.7, 10.7]},
              "properties": {"name": n, "level": "WARD", "risk_level": lv}} for n, lv in (("a", "LOW"), ("b", "HIGH"), ("c", "NO_DATA"))]
    m = folium.Map()
    ml.add_areas(m, {"features": wards}, True, False)
    html = m.get_root().render()
    assert '"fillOpacity": 0.06' in html and '"fillOpacity": 0.22' in html and '"fillOpacity": 0' in html
    m2 = folium.Map()
    ml.add_areas(m2, {"features": wards}, False, False)
    assert '"fillOpacity": 0.06' not in m2.get_root().render()
