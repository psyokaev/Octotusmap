"""Bộ lọc thời gian/khu vực, biểu đồ Plotly và bảng dữ liệu dùng chung (Tổng quan, Thống kê, Mô hình).

Khớp frontend/src/features/analytics/{analytics.ts,components.tsx}.
"""
from datetime import datetime, timedelta, timezone

import api
import plotly.graph_objects as go
import streamlit as st
from common import (
    RISK,
    VN_TZ,
    _utc_iso,
    area_select,
    fmt_dec,
    fmt_pct,
    pager,
    reset_page_on_change,
    show_error,
    vn_date_to_iso,
)
from plotly.subplots import make_subplots

PRESETS = {"today": "Hôm nay", "7d": "7 ngày", "30d": "30 ngày", "month": "Tháng này", "year": "Năm nay", "custom": "Tuỳ chọn"}
GROUP_VI = {"hour": "giờ", "day": "ngày", "month": "tháng", "year": "năm"}
EMPTY = "Không có dữ liệu trong khoảng thời gian đã chọn"
C = {"water": "#1C7CB5", "ink": "#4F6B7D", "amber": "#D99A00", "purple": "#6B4E9B"}
LEVELS = ("LOW", "MEDIUM", "HIGH")
MODEL_STATUS_VI = {"TRAINED": "Đã huấn luyện", "DEPLOYED": "Đang triển khai", "ARCHIVED": "Lưu trữ", "FAILED": "Lỗi"}
FORECAST_METRICS = [
    ("rainfall.mae", "MAE mưa (mm)", False), ("rainfall.rmse", "RMSE mưa (mm)", False), ("water_level.mae", "MAE mực nước (cm)", False),
    ("flood.precision", "Precision ngập", True), ("flood.recall", "Recall ngập", True), ("flood.f1", "F1 ngập", True),
    ("flood.brier", "Brier", False), ("flood.roc_auc", "ROC AUC", False),
    ("heavy_rain.precision", "Precision mưa to (≥5 mm/h)", True), ("heavy_rain.recall", "Recall mưa to", True), ("heavy_rain.f1", "F1 mưa to", True),
]
VISION_METRICS = [
    ("box_map50", "Box mAP50", True), ("mask_map50", "Mask mAP50", True), ("mask_map50_95", "Mask mAP50-95", True),
    ("precision", "Precision", True), ("recall", "Recall", True),
]


def is_vision(model_type: str) -> bool:
    return model_type == "YOLOV8_SEG"


def metric(m, path: str):
    """Đọc số theo đường dẫn 'a.b.c' trong JSON metrics; thiếu khoá -> None."""
    x = m
    for k in path.split("."):
        x = x.get(k) if isinstance(x, dict) else None
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def fetch(path: str, params: dict | None = None):
    """GET, lỗi thì hiện thông báo và trả None."""
    try:
        return api.get(path, params)
    except api.ApiError as e:
        show_error(e)
        return None


# ------------------------------------------------------------------ bộ lọc
def preset_range(preset: str, d_from=None, d_to=None, now: datetime | None = None) -> tuple[str, str]:
    """Khoảng [from, to) dạng ISO UTC cho preset (ngày theo giờ VN)."""
    now = now or datetime.now(timezone.utc)
    vn = now.astimezone(VN_TZ)
    midnight = vn.replace(hour=0, minute=0, second=0, microsecond=0)
    if preset == "custom" and d_from and d_to:
        return vn_date_to_iso(d_from), vn_date_to_iso(d_to, True)
    start = {"today": midnight, "30d": now - timedelta(days=30), "month": midnight.replace(day=1),
             "year": midnight.replace(month=1, day=1)}.get(preset, now - timedelta(days=7))
    return _utc_iso(start), _utc_iso(now)


def group_for(preset: str, date_from: str, date_to: str) -> str:
    """Nhóm thời gian hợp lý: hôm nay -> giờ, 7/30 ngày -> ngày, năm -> tháng."""
    if preset == "today":
        return "hour"
    if preset == "year":
        return "month"
    days = (datetime.fromisoformat(date_to.replace("Z", "+00:00")) - datetime.fromisoformat(date_from.replace("Z", "+00:00"))).total_seconds() / 86400
    return "hour" if days <= 2 else "day" if days <= 92 else "month"


def filter_bar(p: str, extended: bool = False) -> tuple[dict, str]:
    """Thanh lọc; trả (tham số thống kê, nhóm thời gian)."""
    with st.container(border=True):
        c = st.columns(4)
        preset = c[0].selectbox("Khoảng thời gian", list(PRESETS), index=1, format_func=PRESETS.get, key=f"{p}-preset")
        d_from = d_to = None
        if preset == "custom":
            d_from = c[1].date_input("Từ ngày", value=None, key=f"{p}-from", format="DD/MM/YYYY")
            d_to = c[2].date_input("Đến ngày", value=None, key=f"{p}-to", format="DD/MM/YYYY")
            if d_from and d_to and d_from > d_to:
                st.error("Ngày bắt đầu phải trước ngày kết thúc")
                d_from = d_to = None
            elif not (d_from and d_to):
                st.caption("Chọn đủ hai ngày; tạm dùng 7 ngày gần nhất.")
        with c[3]:
            area = area_select("Khu vực", f"{p}-area")
        stations = _station_options(area)
        opts = {"Tất cả trạm": None} | {f"{s['code']} · {s['name']}": s["id"] for s in stations}
        station = opts[st.selectbox("Trạm quan trắc", list(opts), key=f"{p}-station-{area}")]
        risk = data_type = None
        if extended:
            e = st.columns(2)
            risk = e[0].selectbox("Mức nguy cơ", [None, *LEVELS], format_func=lambda k: "Tất cả mức" if k is None else RISK[k]["label"], key=f"{p}-risk")
            data_type = e[1].selectbox("Loại dữ liệu", [None, "REAL", "SIMULATED"], key=f"{p}-dtype",
                                       format_func={None: "Tất cả", "REAL": "Dữ liệu thật", "SIMULATED": "Dữ liệu mô phỏng"}.get)
    date_from, date_to = preset_range(preset, d_from, d_to)
    return ({"date_from": date_from, "date_to": date_to, "area_id": area, "station_id": station, "risk_level": risk, "data_type": data_type},
            group_for(preset, date_from, date_to))


def _station_options(area_id) -> list[dict]:
    try:
        return (api.get("/stations", {"size": 200, "area_id": area_id}, ttl=300) or {}).get("items", [])
    except api.ApiError:
        return []


# ------------------------------------------------------------------ biểu đồ
def chart(cats, series: list[dict], *, ytitle: str = "", y2title: str = "", horizontal: bool = False, stack: bool = False,
          height: int = 340, key: str, y2_range=None) -> None:
    """Cột/đường trên trục danh mục. series: {name, y, color, kind='bar'|'line', y2=False}."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])  # trục phụ chỉ hiện khi có chuỗi y2
    for s in series:
        x, y = (s["y"], list(cats)) if horizontal else (list(cats), s["y"])
        if s.get("kind", "bar") == "bar":
            tr = go.Bar(name=s["name"], x=x, y=y, marker_color=s.get("color"), orientation="h" if horizontal else "v")
        else:
            tr = go.Scatter(name=s["name"], x=x, y=y, mode="lines", line={"color": s.get("color")})
        fig.add_trace(tr, secondary_y=bool(s.get("y2")))
    fig.update_layout(height=height, margin={"l": 10, "r": 10, "t": 24, "b": 10}, legend={"orientation": "h", "y": -0.25},
                      barmode="stack" if stack else "group", hovermode="y unified" if horizontal else "x unified")
    if horizontal:
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(title_text=ytitle)
    else:
        fig.update_yaxes(title_text=ytitle, secondary_y=False)
        fig.update_yaxes(title_text=y2title, secondary_y=True, range=y2_range, showgrid=False, visible=any(s.get("y2") for s in series))
    st.plotly_chart(fig, width="stretch", key=key)


def pie(values: dict[str, tuple[float, str]], key: str, height: int = 300) -> None:
    """values: nhãn -> (số lượng, màu). Bỏ phần tử bằng 0."""
    items = [(k, v, c) for k, (v, c) in values.items() if v]
    fig = go.Figure(go.Pie(labels=[i[0] for i in items], values=[i[1] for i in items], marker={"colors": [i[2] for i in items]}, hole=0.55))
    fig.update_layout(height=height, margin={"l": 10, "r": 10, "t": 10, "b": 10}, legend={"orientation": "h"})
    st.plotly_chart(fig, width="stretch", key=key)


def risk_pie(counts: dict, key: str, extra_insufficient: bool = True) -> None:
    keys = [*LEVELS, "INSUFFICIENT_DATA"] if extra_insufficient else list(LEVELS)
    pie({RISK[k]["label"]: (counts.get(k) or 0, RISK[k]["color"]) for k in keys}, key)


# ------------------------------------------------------------------ bảng
def section(title: str):
    """Khung có tiêu đề (tương đương Section của bản React)."""
    box = st.container(border=True)
    box.subheader(title)
    return box


def data_table(rows: list, cols: list[tuple], key: str, page_size: int = 20) -> None:
    """Bảng có tìm kiếm, sắp xếp và phân trang phía client. cols: (nhãn, hàm giá trị, hàm hiển thị | None)."""
    if not rows:
        st.info(EMPTY)
        return
    c1, c2, c3 = st.columns([3, 3, 1])
    q = c1.text_input("Tìm kiếm", key=f"{key}-q", placeholder="Tìm kiếm…").strip().lower()
    labels = [c[0] for c in cols]
    sort = c2.selectbox("Sắp xếp theo", [""] + labels, format_func=lambda x: x or "Mặc định", key=f"{key}-sort")
    desc = c3.checkbox("Giảm dần", key=f"{key}-desc")
    view = [r for r in rows if not q or any(q in str(c[1](r) if c[1](r) is not None else "").lower() for c in cols)]
    if sort:
        val = next(c[1] for c in cols if c[0] == sort)
        have = sorted((r for r in view if val(r) is not None), key=lambda r: (str(val(r)).lower() if not isinstance(val(r), (int, float)) else val(r)),
                      reverse=desc)
        view = have + [r for r in view if val(r) is None]  # giá trị trống luôn ở cuối
    reset_page_on_change(f"{key}-page", (q, sort, desc, len(rows)))
    if not view:
        st.info("Không có kết quả phù hợp")
        return
    page = pager(f"{key}-page", len(view), page_size) if len(view) > page_size else 1
    st.dataframe([{c[0]: (c[2](r) if c[2] else ("—" if c[1](r) is None else c[1](r))) for c in cols}
                  for r in view[(page - 1) * page_size: page * page_size]], hide_index=True, width="stretch")


# ------------------------------------------------------------------ chỉ số mô hình
def model_metrics(model_type: str, metrics) -> None:
    """Lưới chỉ số chính của một mô hình (dự báo hoặc YOLO)."""
    if not metrics:
        st.caption("Chưa có chỉ số đánh giá")
        return
    defs = [d for d in (VISION_METRICS if is_vision(model_type) else FORECAST_METRICS) if metric(metrics, d[0]) is not None]
    for row in range(0, len(defs), 4):
        for col, (path, label, pct) in zip(st.columns(4), defs[row: row + 4]):
            v = metric(metrics, path)
            col.metric(label, fmt_pct(v) if pct else fmt_dec(v))
