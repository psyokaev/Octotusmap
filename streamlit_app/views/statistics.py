"""Thống kê (StatisticsPage.tsx): các tab báo cáo, bảng sắp xếp/phân trang, xuất Excel và CSV."""
import api
import streamlit as st
from analytics import (
    C,
    EMPTY,
    GROUP_VI,
    LEVELS,
    chart,
    data_table,
    fetch,
    filter_bar,
    is_vision,
    metric,
    model_metrics,
    pie,
    risk_pie,
    section,
)
from common import (
    RISK,
    STATUS_VI,
    camera_enabled,
    fmt_dec,
    fmt_dt,
    fmt_num,
    fmt_pct,
    pager,
    reset_page_on_change,
    show_error,
    sim_badge,
)

TABS = [  # (id, nhãn, báo cáo Excel mặc định)
    ("rainfall", "Lượng mưa", "rainfall"), ("water", "Mực nước", "water_level"), ("risk", "Nguy cơ ngập", "full"),
    ("alerts", "Lịch sử cảnh báo", "alerts"), ("events", "Sự kiện ngập lịch sử", "history"), ("perf", "Hiệu quả dự báo", "forecasts"),
    ("cameras", "Camera", "cameras"), ("stations", "Trạm quan trắc", "stations"), ("quality", "Dữ liệu thiếu/lỗi", "stations"),
    ("handling", "Hoạt động xử lý cảnh báo", "alerts"),
]
REPORTS = {
    "full": "Báo cáo tổng hợp", "rainfall": "Lượng mưa", "water_level": "Mực nước", "alerts": "Cảnh báo ngập", "history": "Sự kiện ngập lịch sử",
    "forecasts": "Dự báo AI", "models": "Đánh giá mô hình", "stations": "Trạm quan trắc", "cameras": "Camera",
}
ACTION_VI = {"CREATED": "Tạo cảnh báo", "ESCALATED": "Nâng mức", "STATUS": "Đổi trạng thái", "ASSIGN": "Phân công", "NOTE": "Ghi chú", "VERIFY": "Xác minh"}
CONN_VI = {"ONLINE": "Đang kết nối", "OFFLINE": "Mất kết nối", "NO_DATA": "Chưa có dữ liệu"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _export(path: str, params: dict, extra: dict, label: str, key: str, mime: str) -> None:
    """Chuẩn bị tệp rồi hiện nút tải (Streamlit không tải trực tiếp khi bấm nút)."""
    sig = repr((path, params, extra))
    if st.button(label, key=key):
        try:
            st.session_state[f"{key}-file"] = (sig, *api.download(path, {**params, **extra}))
        except api.ApiError as e:
            show_error(e)
    if st.session_state.get(f"{key}-file", (None,))[0] == sig:  # bộ lọc đổi thì bỏ tệp cũ
        _, name, data = st.session_state[f"{key}-file"]
        st.download_button(f"Tải {name}", data, file_name=name, key=f"{key}-dl", mime=mime)


def render() -> None:
    st.title("Thống kê")
    cam = camera_enabled()
    tabs = [t for t in TABS if t[0] != "cameras" or cam]
    ids = [t[0] for t in tabs]
    tab = st.radio("Nhóm thống kê", ids, format_func=lambda i: next(t[1] for t in tabs if t[0] == i), horizontal=True, key="stt-tab")
    default = next(t[2] for t in tabs if t[0] == tab)
    params, group = filter_bar("stt", extended=True)
    c1, c2, c3 = st.columns([3, 2, 2])
    ids_r = list(REPORTS)  # khoá riêng theo tab: đổi tab thì chọn lại báo cáo mặc định
    report = c1.selectbox("Loại báo cáo Excel", ids_r, index=ids_r.index(default), format_func=REPORTS.get, key=f"stt-report-{tab}")
    with c2:
        _export("/exports/excel", params, {"report": report}, "Xuất Excel", "stt-xlsx", XLSX)
    if tab in ("rainfall", "water"):
        with c3:
            _export("/exports/csv", params, {"kind": "rainfall" if tab == "rainfall" else "water_level"}, "Xuất CSV", "stt-csv", "text/csv")
    reset_page_on_change("stt-obs-page", (tab, repr(params)))
    {"rainfall": _obs, "water": _obs, "risk": _risk, "alerts": _alerts, "events": _events, "perf": _perf, "cameras": _cameras,
     "stations": _stations, "quality": _quality, "handling": _handling}[tab](params, group, tab)


# ------------------------------------------------------------------ mưa / mực nước
def _obs(params: dict, group: str, tab: str) -> None:
    rain = tab == "rainfall"
    kind, unit = ("rainfall", "mm") if rain else ("water_level", "cm")
    stats = fetch("/statistics/rainfall" if rain else "/statistics/water-level", {**params, "group": group})
    with section("Lượng mưa theo thời gian" if rain else "Mực nước theo thời gian"):
        s = (stats or {}).get("series") or []
        if not s:
            st.caption(EMPTY)
        elif rain:
            chart([x["bucket"] for x in s], [
                {"name": f"Tổng ({unit})", "y": [x["sum"] for x in s], "color": C["water"]},
                {"name": f"Cao nhất 1 lần đo ({unit})", "kind": "line", "y": [x["max"] for x in s], "color": RISK["HIGH"]["color"]}],
                ytitle=unit, key="st-obs-chart")
        else:
            chart([x["bucket"] for x in s], [
                {"name": f"Cao nhất ({unit})", "kind": "line", "y": [x["max"] for x in s], "color": RISK["HIGH"]["color"]},
                {"name": f"Trung bình ({unit})", "kind": "line", "y": [x["avg"] for x in s], "color": C["water"]}], ytitle=unit, key="st-obs-chart")
    with section("Tổng hợp theo trạm"):
        cols = [("Mã trạm", lambda r: r["code"], None), ("Tên trạm", lambda r: r["name"], None)]
        if rain:
            cols.append((f"Tổng ({unit})", lambda r: r["sum"], lambda r: fmt_num(r["sum"])))
        cols += [(f"Trung bình ({unit})", lambda r: r["avg"], lambda r: fmt_num(r["avg"])),
                 (f"Cao nhất ({unit})", lambda r: r["max"], lambda r: fmt_num(r["max"])),
                 ("Số lần đo hợp lệ", lambda r: r["count"], lambda r: fmt_num(r["count"]))]
        data_table((stats or {}).get("by_station") or [], cols, f"st-{kind}-bystation")
    with section("Dữ liệu quan trắc chi tiết"):
        page = st.session_state.get("stt-obs-page", 1)
        d = fetch("/statistics/observations", {**params, "kind": kind, "page": page, "size": 50})
        if not d or not d["items"]:
            st.caption(EMPTY)
            return
        st.dataframe([{"Thời điểm": fmt_dt(r["observed_at"]), "Trạm": f"{r['station_code']} · {r['station_name']}", "Khu vực": r["area"] or "—",
                       f"Giá trị ({unit})": fmt_num(r["value"]), "Chất lượng": r["quality"], "Nguồn": "Mô phỏng" if r["is_simulated"] else "Thật"}
                      for r in d["items"]], hide_index=True, width="stretch")
        pager("stt-obs-page", d["total"], d["size"])


# ------------------------------------------------------------------ nguy cơ
def _risk(params: dict, group: str, _tab: str) -> None:
    d = fetch("/statistics/risk", {**params, "group": group})
    if not d:
        return
    left, right = st.columns([2, 1])
    s = d["trend"]
    with left, section("Xu hướng đánh giá nguy cơ (hiện tại, theo khu vực)"):
        if s:
            chart([x["bucket"] for x in s], [
                *({"name": RISK[k]["label"], "y": [x[k] for x in s], "color": RISK[k]["color"]} for k in (*LEVELS, "INSUFFICIENT_DATA")),
                {"name": "Điểm TB", "kind": "line", "y2": True, "y": [x["avg_score"] for x in s], "color": C["ink"]}],
                stack=True, ytitle="lượt", y2title="điểm", key="st-risk-trend")
        else:
            st.caption(EMPTY)
    with right, section("Phân bố mức nguy cơ mới nhất"):
        if d["current"]:
            risk_pie(d["current"], "st-risk-pie")
        else:
            st.caption("Chưa có đánh giá")
    with section("Bảng số liệu"):
        data_table(s, [("Thời gian", lambda r: r["bucket"], None),
                       *((RISK[k]["label"], (lambda r, k=k: r[k]), None) for k in LEVELS),
                       ("Thiếu dữ liệu", lambda r: r["INSUFFICIENT_DATA"], None),
                       ("Điểm TB", lambda r: r["avg_score"], lambda r: fmt_dec(r["avg_score"]))], "st-risk-table")


# ------------------------------------------------------------------ cảnh báo
def _alerts(params: dict, group: str, _tab: str) -> None:
    d = fetch("/statistics/alerts", {**params, "group": group})
    if not d:
        return
    v = d.get("verification") or {}
    k = st.columns(4)
    k[0].metric("Tổng cảnh báo", fmt_num(d["total"]))
    k[1].metric("Tỉ lệ đúng (đã xác minh)", fmt_pct(d["precision_verified"]))
    k[1].caption(f"Xác nhận {v.get('CONFIRMED', 0)} · báo nhầm {v.get('FALSE_ALARM', 0)}")
    k[2].metric("Thời gian tiếp nhận TB", fmt_num(d["avg_minutes_to_ack"], " phút"))
    k[3].metric("Thời gian xử lý TB", fmt_num(d["avg_minutes_to_resolve"], " phút"))
    if not d["total"]:
        st.caption("Không có cảnh báo trong khoảng thời gian đã chọn")
        return
    t, a = d["by_time"], d["by_area"][:15]
    left, right = st.columns(2)
    with left, section("Cảnh báo theo thời gian và mức"):
        chart([x["bucket"] for x in t], [{"name": RISK[k]["label"], "y": [x[k] for x in t], "color": RISK[k]["color"]} for k in LEVELS],
              stack=True, key="st-al-time")
    with right, section("Cảnh báo theo khu vực"):
        chart([x["area"] for x in a], [{"name": "Số cảnh báo", "y": [x["count"] for x in a], "color": C["amber"]}], horizontal=True,
              height=max(220, len(a) * 26 + 60), key="st-al-area")
    left, right = st.columns(2)
    with left, section("Theo trạng thái"):
        data_table([{"k": k, "v": n} for k, n in d["by_status"].items()],
                   [("Trạng thái", lambda r: STATUS_VI.get(r["k"], r["k"]), None), ("Số lượng", lambda r: r["v"], None)], "st-al-status")
    with right, section("Theo khu vực"):
        data_table(d["by_area"], [("Khu vực", lambda r: r["area"], None), ("Số cảnh báo", lambda r: r["count"], None)], "st-al-areatbl")


# ------------------------------------------------------------------ sự kiện ngập lịch sử
def _events(params: dict, group: str, _tab: str) -> None:
    d = fetch("/statistics/flood-events", {**params, "group": group})
    if not d:
        return
    if not d["total"]:
        st.info("Không có sự kiện ngập trong khoảng thời gian đã chọn")
        return
    s = d["by_time"]
    left, right = st.columns([2, 1])
    with left, section(f"Sự kiện ngập theo thời gian ({fmt_num(d['total'])} sự kiện)"):
        chart([x["bucket"] for x in s], [
            {"name": "Số sự kiện", "y": [x["count"] for x in s], "color": C["purple"]},
            {"name": "Độ sâu lớn nhất (cm)", "kind": "line", "y2": True, "y": [x["max_depth_cm"] for x in s], "color": RISK["HIGH"]["color"]}],
            ytitle="sự kiện", y2title="cm", key="st-ev")
    with right, section("Theo khu vực"):
        data_table(d["by_area"], [("Khu vực", lambda r: r["area"], None), ("Số sự kiện", lambda r: r["count"], None)], "st-ev-area", 10)


# ------------------------------------------------------------------ hiệu quả dự báo
def _perf(params: dict, _group: str, _tab: str) -> None:
    d = fetch("/statistics/model-performance", params)
    if not d:
        return
    cam = camera_enabled()
    models = [m for m in d["models"] if cam or not is_vision(m["type"])]
    left, right = st.columns(2)
    with left, section("Sai số dự báo mưa đối chiếu quan trắc"):
        sk = d["online_rainfall_skill"]
        if sk:
            chart([f"+{x['horizon_h']}h" for x in sk], [{"name": "MAE (mm)", "y": [x["mae"] for x in sk], "color": C["water"]},
                                                       {"name": "RMSE (mm)", "y": [x["rmse"] for x in sk], "color": C["ink"]}], ytitle="mm", key="st-perf")
            st.dataframe([{"Mốc": f"+{x['horizon_h']}h", "MAE (mm)": fmt_dec(x["mae"]), "RMSE (mm)": fmt_dec(x["rmse"]), "Số cặp": fmt_num(x["n"])}
                          for x in sk], hide_index=True, width="stretch")
        else:
            st.caption("Chưa đủ cặp dự báo – quan trắc trong khoảng thời gian này.")
    with right, section("Mô hình đang hoạt động"):
        active = [m for m in models if m["active"]]
        for m in active:
            st.markdown(f"**{m['name']} ({m['type']})** {sim_badge(m['trained_on_simulated'])}")
            model_metrics(m["type"], m["metrics"])
        if not active:
            st.caption("Chưa có mô hình hoạt động")
        st.caption("Xác minh cảnh báo trong kỳ: " + (" · ".join(f"{k}: {v}" for k, v in d["alert_verification"].items()) or "chưa có"))

    def key1(m):
        return metric(m["metrics"], "mask_map50" if is_vision(m["type"]) else "rainfall.mae")

    def key2(m):
        x = m["metrics"]
        return metric(x, "recall" if is_vision(m["type"]) else "heavy_rain.f1" if (x or {}).get("heavy_rain") else "flood.f1")
    with section("Tất cả phiên bản mô hình"):
        data_table(models, [
            ("Mô hình", lambda m: m["name"], lambda m: m["name"] + (" (mô phỏng)" if m["trained_on_simulated"] else "")),
            ("Loại", lambda m: m["type"], None), ("Phiên bản", lambda m: m["version"], None),
            ("Đang dùng", lambda m: "Có" if m["active"] else "Không", None),
            ("MAE mưa / mask mAP50", key1, lambda m: fmt_dec(key1(m))), ("F1 ngập hoặc mưa to / recall", key2, lambda m: fmt_pct(key2(m)))], "st-perf-models")


# ------------------------------------------------------------------ camera
def _cameras(params: dict, _group: str, _tab: str) -> None:
    d = fetch("/statistics/cameras", params)
    if not d:
        st.info("Chưa có camera")
        return
    with section("Tỉ lệ vùng ngập phát hiện qua camera"):
        s = [x for x in d if x["detections"] > 0]
        if s:
            def pct(v):
                return None if v is None else round(v * 100)
            chart([x["code"] for x in s], [
                {"name": "Tỉ lệ ngập lớn nhất (%)", "y": [pct(x["max_flood_ratio"]) for x in s], "color": RISK["HIGH"]["color"]},
                {"name": "Tỉ lệ ngập trung bình (%)", "y": [pct(x["avg_flood_ratio"]) for x in s], "color": C["water"]}], ytitle="%", key="st-cam")
        else:
            st.caption("Không có lượt phân tích trong khoảng thời gian đã chọn")
    with section("Danh sách camera"):
        data_table(d, [
            ("Mã", lambda r: r["code"], None), ("Tên camera", lambda r: r["name"], lambda r: r["name"] + (" (mô phỏng)" if r["is_simulated"] else "")),
            ("Khu vực", lambda r: r["area"], None), ("Trạng thái", lambda r: r["status"], None), ("Lượt phân tích", lambda r: r["detections"], None),
            ("Ngập lớn nhất", lambda r: r["max_flood_ratio"], lambda r: fmt_pct(r["max_flood_ratio"])),
            ("Ngập trung bình", lambda r: r["avg_flood_ratio"], lambda r: fmt_pct(r["avg_flood_ratio"])),
            ("Lần cuối", lambda r: r["last_detection_at"], lambda r: fmt_dt(r["last_detection_at"]))], "st-cam-table")


# ------------------------------------------------------------------ trạm
def _stations(params: dict, _group: str, _tab: str) -> None:
    d = fetch("/statistics/stations")
    if d is None:
        return
    # endpoint không nhận bộ lọc -> lọc khu vực/trạm phía client
    rows = [s for s in d if (not params["area_id"] or s["area_id"] == params["area_id"]) and (not params["station_id"] or s["id"] == params["station_id"])]
    left, right = st.columns([1, 2])
    with left, section("Tình trạng kết nối"):
        if rows:
            counts: dict = {}
            for s in rows:
                counts[s["connection"]] = counts.get(s["connection"], 0) + 1
            color = {"ONLINE": RISK["LOW"]["color"], "OFFLINE": RISK["HIGH"]["color"]}
            pie({CONN_VI.get(k, k): (v, color.get(k, RISK["NO_DATA"]["color"])) for k, v in counts.items()}, "st-conn")
        else:
            st.caption("Không có trạm phù hợp bộ lọc")
    with right, section("Danh sách trạm"):
        data_table(rows, [
            ("Mã", lambda r: r["code"], None), ("Tên trạm", lambda r: r["name"], lambda r: r["name"] + (" (mô phỏng)" if r["is_simulated"] else "")),
            ("Loại", lambda r: r["type"], None), ("Khu vực", lambda r: r["area"], None), ("Trạng thái", lambda r: r["status"], None),
            ("Kết nối", lambda r: CONN_VI.get(r["connection"], r["connection"]), None),
            ("Quan trắc gần nhất", lambda r: r["last_observation_at"], lambda r: fmt_dt(r["last_observation_at"])),
            ("Ngưỡng ngập (cm)", lambda r: r["flood_threshold_cm"], None), ("Nguồn", lambda r: r["source"], None)], "st-stations-table")


# ------------------------------------------------------------------ chất lượng dữ liệu
_QUALITY_BASE = {"kind", "code", "name", "total", "valid_ratio"}


def _quality(params: dict, _group: str, _tab: str) -> None:
    d = fetch("/statistics/data-quality", params)
    if not d:
        st.info(EMPTY)
        return
    flags = sorted({k for r in d for k in r if k not in _QUALITY_BASE})
    codes = list(dict.fromkeys(r["code"] for r in d))
    with section("Tỉ lệ dữ liệu hợp lệ theo trạm"):
        def ratio(kind):
            out = []
            for c in codes:
                r = next((x for x in d if x["code"] == c and x["kind"] == kind), None)
                out.append(None if r is None or r["valid_ratio"] is None else round(r["valid_ratio"] * 1000) / 10)
            return out
        chart(codes, [{"name": f"{k} hợp lệ (%)", "y": ratio(k), "color": C["ink"] if i else C["water"]}
                      for i, k in enumerate(dict.fromkeys(r["kind"] for r in d))], ytitle="%", key="st-quality")
    with section("Chi tiết bản ghi theo cờ chất lượng"):
        data_table(d, [("Loại", lambda r: r["kind"], None), ("Mã trạm", lambda r: r["code"], None), ("Tên trạm", lambda r: r["name"], None),
                       ("Tổng bản ghi", lambda r: r["total"], None),
                       *((f, (lambda r, f=f: r[f] if isinstance(r.get(f), (int, float)) else 0), None) for f in flags),
                       ("Tỉ lệ hợp lệ", lambda r: r["valid_ratio"], lambda r: fmt_pct(r["valid_ratio"]))], "st-quality-table")


# ------------------------------------------------------------------ xử lý cảnh báo
def _handling(params: dict, _group: str, _tab: str) -> None:
    d = fetch("/statistics/alert-handling", params)
    if not d:
        st.info("Không có hoạt động xử lý trong khoảng thời gian đã chọn")
        return
    by: dict = {}
    for r in d:
        by[r["action"]] = by.get(r["action"], 0) + r["count"]
    left, right = st.columns(2)
    with left, section("Thao tác theo loại"):
        chart([ACTION_VI.get(k, k) for k in by], [{"name": "Số thao tác", "y": list(by.values()), "color": C["water"]}], key="st-handling")
    with right, section("Chi tiết"):
        data_table(d, [("Thao tác", lambda r: ACTION_VI.get(r["action"], r["action"]), None),
                       ("Trạng thái sau", lambda r: STATUS_VI.get(r["to_status"], r["to_status"]) if r["to_status"] else None, None),
                       ("Số lượng", lambda r: r["count"], None)], "st-handling-table")
