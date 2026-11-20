"""Cấu hình (SettingsPage.tsx): quy tắc cảnh báo, cấu hình hệ thống, nhật ký, nguồn dữ liệu, vận hành."""
import copy
import json

import api
import streamlit as st
from analytics import fetch
from common import confirm_pending, fmt_dt, pager, reset_page_on_change, show_error

TABS = {"rules": "Quy tắc cảnh báo", "settings": "Cấu hình hệ thống", "audit": "Nhật ký", "sources": "Nguồn dữ liệu", "ops": "Vận hành"}
WEIGHT_VI = {"flood_probability": "Xác suất ngập (mô hình)", "rainfall": "Lượng mưa", "water_level": "Mực nước", "camera": "Camera", "history": "Lịch sử ngập"}
LEVEL_VI = {"LOW": "Thấp", "MEDIUM": "Trung bình", "HIGH": "Cao"}
MAX_GEO_MB = 30


def render() -> None:
    st.title("Cấu hình")
    tab = st.radio("Nhóm cấu hình", list(TABS), format_func=TABS.get, horizontal=True, key="cfg-tab")
    {"rules": _rules, "settings": _settings, "audit": _audit, "sources": _sources, "ops": _ops}[tab]()


# ------------------------------------------------------------------ (a) quy tắc
def rule_errors(name: str, c: dict) -> list[str]:
    """Kiểm tra giống ruleSchema của bản React; backend vẫn kiểm tra lại."""
    e = []
    if len(name.strip()) < 2:
        e.append("Tên phiên bản tối thiểu 2 ký tự")
    if not any(w > 0 for w in c["weights"].values()):
        e.append("Cần ít nhất một trọng số lớn hơn 0")
    t = c["thresholds"]
    if not (0 < t["medium"] <= 1 and 0 < t["high"] <= 1):
        e.append("Ngưỡng phải lớn hơn 0 và tối đa 1")
    if t["medium"] >= t["high"]:
        e.append("Ngưỡng trung bình phải nhỏ hơn ngưỡng cao")
    if not 0 <= c["hysteresis"] < 0.3:
        e.append("Độ trễ hạ mức từ 0 đến dưới 0,3")
    if c["rainfall_ref_mm"] <= 0 or c["overrides"]["water_level_ratio_high"] <= 0:
        e.append("Lượng mưa tham chiếu và tỉ lệ mực nước phải lớn hơn 0")
    return e


def _rules() -> None:
    rules = fetch("/admin/rules")
    if rules is None:
        return
    active = next((r for r in rules if r["is_active"]), None)
    st.warning("Các trọng số và ngưỡng chỉ phục vụ nghiên cứu/trình diễn, chưa phải ngưỡng vận hành chính thức của cơ quan quản lý. "
               "Mỗi lần lưu tạo một phiên bản quy tắc mới và kích hoạt ngay.")
    if active:
        _rule_editor(active)
    else:
        st.info("Chưa có quy tắc đang áp dụng.")
    st.subheader("Các phiên bản")
    if not rules:
        st.info("Chưa có phiên bản nào.")
        return
    for r in rules:
        c = st.columns([1, 3, 4, 2, 2])
        c[0].write(f"v{r['version']}")
        c[1].write(r["name"])
        c[2].write(r.get("notes") or "—")
        c[3].write(fmt_dt(r["created_at"]))
        if r["is_active"]:
            c[4].markdown(":green[**Đang áp dụng**]")
        else:
            c[4].button("Kích hoạt lại", key=f"rule-act-{r['id']}", on_click=lambda rid=r["id"]: st.session_state.update({"rule-act-p": rid}))
    by_id = {r["id"]: r for r in rules}
    pend = by_id.get(st.session_state.get("rule-act-p"))
    if pend:
        confirm_pending("rule-act-p", f"Áp dụng quy tắc v{pend['version']} \"{pend['name']}\" cho các chu kỳ cảnh báo tiếp theo?",
                        lambda rid: api.post(f"/admin/rules/{rid}/activate"), "Đã kích hoạt quy tắc", "Kích hoạt")


def _rule_editor(rule: dict) -> None:
    cfg = rule["config"]
    w, t, o = cfg["weights"], cfg["thresholds"], cfg["overrides"]
    with st.form(f"rule-form-{rule['id']}"):
        st.markdown(f"**Quy tắc đang áp dụng · v{rule['version']}**")
        c = st.columns(2)
        name = c[0].text_input("Tên phiên bản mới", value=rule["name"], key="rule-name")
        notes = c[1].text_input("Ghi chú thay đổi", max_chars=2000, key="rule-notes")
        st.caption("Trọng số thành phần")
        weights = {k: col.number_input(WEIGHT_VI[k], min_value=0.0, value=float(w[k]), step=0.05, format="%g", key=f"rule-w-{k}")
                   for k, col in zip(WEIGHT_VI, st.columns(5))}
        st.caption("Ngưỡng mức rủi ro")
        c = st.columns(4)
        med = c[0].number_input("Ngưỡng trung bình (0–1)", value=float(t["medium"]), step=0.05, format="%g", key="rule-med")
        high = c[1].number_input("Ngưỡng cao (0–1)", value=float(t["high"]), step=0.05, format="%g", key="rule-high")
        hyst = c[2].number_input("Độ trễ hạ mức [0; 0,3)", value=float(cfg["hysteresis"]), step=0.01, format="%g", key="rule-hyst")
        ref = c[3].number_input("Lượng mưa tham chiếu (mm/giờ)", value=float(cfg["rainfall_ref_mm"]), step=1.0, format="%g", key="rule-ref")
        st.caption("Điều kiện nâng thẳng lên mức cao")
        c = st.columns(3)
        o_fp = c[0].number_input("Xác suất ngập ≥ (0–1)", 0.0, 1.0, float(o["flood_probability_high"]), step=0.05, format="%g", key="rule-ofp")
        o_wl = c[1].number_input("Tỉ lệ mực nước/ngưỡng ≥", value=float(o["water_level_ratio_high"]), step=0.05, format="%g", key="rule-owl")
        o_cam = c[2].number_input("Tỉ lệ ngập camera ≥ (0–1)", 0.0, 1.0, float(o["camera_ratio_high"]), step=0.05, format="%g", key="rule-ocam")
        st.caption("Điều kiện phát cảnh báo")
        c = st.columns(4)
        conf = c[0].number_input("Độ tin cậy tối thiểu (0–1)", 0.0, 1.0, float(cfg["min_confidence"]), step=0.05, format="%g", key="rule-conf")
        fresh = c[1].number_input("Tuổi dữ liệu tối đa (phút)", 1, value=int(cfg["freshness_max_minutes"]), key="rule-fresh")
        cool = c[2].number_input("Thời gian chờ sau khi đóng (phút)", 0, value=int(cfg["cooldown_minutes"]), key="rule-cool")
        lv = list(LEVEL_VI)
        level = c[3].selectbox("Mức tối thiểu để phát cảnh báo", lv, format_func=LEVEL_VI.get, index=lv.index(cfg["alert_min_level"]), key="rule-level")
        ok = st.form_submit_button("Lưu thành phiên bản mới", type="primary")
    if ok:
        new = copy.deepcopy(cfg)  # giữ nguyên khoá form không chỉnh
        new.update({"weights": weights, "thresholds": {"medium": med, "high": high}, "hysteresis": hyst, "rainfall_ref_mm": ref,
                    "overrides": {"flood_probability_high": o_fp, "water_level_ratio_high": o_wl, "camera_ratio_high": o_cam},
                    "min_confidence": conf, "freshness_max_minutes": int(fresh), "alert_min_level": level, "cooldown_minutes": int(cool)})
        errs = rule_errors(name, new)
        if errs:
            st.error("\n".join(f"- {e}" for e in errs))
        else:
            st.session_state["rule-save-p"] = {"name": name.strip(), "notes": notes, "config": new}
    confirm_pending("rule-save-p", "Phiên bản mới sẽ được kích hoạt ngay và áp dụng cho chu kỳ đánh giá rủi ro tiếp theo. Tiếp tục?",
                    lambda body: api.post("/admin/rules", body), "Đã lưu và kích hoạt phiên bản quy tắc mới", "Lưu và kích hoạt")


# ------------------------------------------------------------------ (b) cấu hình hệ thống
def _settings() -> None:
    rows = fetch("/admin/settings")
    if rows is None:
        return
    if not rows:
        st.info("Chưa có cấu hình nào.")
        return
    for s in rows:
        with st.form(f"set-form-{s['key']}"):
            text = st.text_area(s["key"], value=json.dumps(s["value"], ensure_ascii=False, indent=2), height=120, key=f"set-txt-{s['key']}",
                                help=f"{s.get('description') or 'Không có mô tả'} · cập nhật {fmt_dt(s['updated_at'])}")
            ok = st.form_submit_button("Lưu", type="primary")
        st.caption(f"{s.get('description') or 'Không có mô tả'} · cập nhật {fmt_dt(s['updated_at'])}")
        if ok:
            try:
                st.session_state[f"set-p-{s['key']}"] = json.loads(text)
            except ValueError:
                st.error("JSON không hợp lệ")
        confirm_pending(f"set-p-{s['key']}", f"Cập nhật cấu hình \"{s['key']}\"? Thay đổi có hiệu lực ngay và được ghi nhật ký.",
                        lambda v, k=s["key"]: api.put(f"/admin/settings/{k}", {"value": v}), "Đã lưu cấu hình", "Lưu")


# ------------------------------------------------------------------ (c) nhật ký
def _audit() -> None:
    c = st.columns(2)
    q = c[0].text_input("Người dùng hoặc đối tượng", key="aud-q")
    action = c[1].text_input("Mã thao tác", key="aud-action", help="Ví dụ: LOGIN, ALERT_STATUS, RULE_CREATE").strip().upper()
    reset_page_on_change("aud-page", (q, action))
    d = fetch("/admin/audit-logs", {"q": q, "action": action, "page": st.session_state.get("aud-page", 1), "size": 50})
    if not d:
        return
    if not d["items"]:
        st.info("Không có bản ghi nhật ký phù hợp.")
        return
    st.dataframe([{"Thời điểm": fmt_dt(a["created_at"]), "Người dùng": a.get("username") or "—", "Thao tác": a["action"],
                   "Đối tượng": a["entity_type"] + (f" #{a['entity_id']}" if a.get("entity_id") else ""), "IP": a.get("ip") or "—",
                   "Chi tiết": json.dumps(a["detail"], ensure_ascii=False) if a.get("detail") else "—"} for a in d["items"]],
                 hide_index=True, width="stretch")
    pager("aud-page", d["total"], d["size"])


# ------------------------------------------------------------------ (d) nguồn dữ liệu
def _sources() -> None:
    rows = fetch("/admin/data-sources")
    if not rows:
        if rows is not None:
            st.info("Chưa có nguồn dữ liệu.")
        return
    st.dataframe([{"Mã": s["code"], "Tên": s["name"], "Loại": s["kind"], "Tính chất": "Mô phỏng" if s["is_simulated"] else "Dữ liệu thật",
                   "Giấy phép": s.get("license") or "—", "Liên kết": s.get("url") or "—"} for s in rows], hide_index=True, width="stretch")


# ------------------------------------------------------------------ (e) vận hành
def _ops() -> None:
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Chu kỳ xử lý")
        st.caption("Thu thập dữ liệu, dự báo, đánh giá rủi ro và sinh cảnh báo ngay lập tức thay vì chờ lịch chạy định kỳ.")
        st.button("Chạy chu kỳ xử lý ngay", key="ops-run", type="primary", on_click=lambda: st.session_state.update({"ops-run-p": True}))
        confirm_pending("ops-run-p", "Chạy toàn bộ chu kỳ xử lý (có thể mất vài chục giây và sinh cảnh báo mới)?", _run_cycle,
                        "Đã chạy xong chu kỳ xử lý", "Chạy ngay")
        if "ops-cycle" in st.session_state:
            st.json(st.session_state["ops-cycle"])
    with right, st.container(border=True):
        st.subheader("Nhập ranh giới hành chính (GeoJSON)")
        st.caption(f"Tệp GeoJSON hệ toạ độ WGS84, tối đa {MAX_GEO_MB} MB. Khu vực mới sẽ được dùng cho bản đồ và đánh giá rủi ro.")
        f = st.file_uploader("Tệp GeoJSON", type=["geojson", "json"], key="geo-file")
        c = st.columns(2)
        level = c[0].selectbox("Cấp hành chính", ["WARD", "DISTRICT"], format_func={"WARD": "Phường/xã", "DISTRICT": "Quận/huyện"}.get, key="geo-level")
        src = c[1].text_input("Tên nguồn", value="Ranh giới do quản trị viên nhập", max_chars=200, key="geo-src")
        name_f = c[0].text_input("Thuộc tính tên", value="name", key="geo-name")
        code_f = c[1].text_input("Thuộc tính mã", value="code", key="geo-code")
        if st.button("Nhập ranh giới", key="geo-go", type="primary"):
            if f is None:
                st.error("Chọn một tệp")
            elif f.size > MAX_GEO_MB * 1024 * 1024:
                st.error(f"Tệp tối đa {MAX_GEO_MB} MB")
            elif not name_f.strip() or not code_f.strip() or len(src.strip()) < 2:
                st.error("Nhập tên thuộc tính, mã và tên nguồn (tối thiểu 2 ký tự)")
            else:
                params = {"level": level, "name_field": name_f.strip(), "code_field": code_f.strip(), "source_name": src.strip()}
                try:
                    r = api.upload("/gis/import", f.name, f.getvalue(), params=params)
                    st.session_state["geo-result"] = r
                    st.toast("Đã nhập ranh giới")
                except api.ApiError as e:
                    show_error(e)
        if "geo-result" in st.session_state:
            st.success(f"Đã thêm {st.session_state['geo-result']['inserted']} khu vực.")


def _run_cycle(_payload) -> None:
    st.session_state["ops-cycle"] = api.post("/admin/jobs/run-cycle")
