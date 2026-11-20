"""Dự báo AI 1–6 giờ (ForecastsPage.tsx)."""
import api
import plotly.graph_objects as go
import streamlit as st
from common import (
    RISK,
    flood_cause,
    fmt_dec,
    fmt_dt,
    fmt_num,
    fmt_pct,
    fmt_time,
    risk_text,
    show_error,
    sim_badge,
)
from plotly.subplots import make_subplots

HOURS = [1, 2, 3, 4, 5, 6]
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


def metric(m, path: str):
    """Đọc số theo đường dẫn 'a.b.c' trong JSON metrics (an toàn khi thiếu khoá)."""
    x = m
    for k in path.split("."):
        x = x.get(k) if isinstance(x, dict) else None
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def model_metrics(model_type: str, metrics) -> None:
    if not metrics:
        st.caption("Chưa có chỉ số đánh giá")
        return
    defs = VISION_METRICS if model_type == "YOLOV8_SEG" else FORECAST_METRICS
    shown = [(label, fmt_pct(metric(metrics, p)) if pct else fmt_dec(metric(metrics, p))) for p, label, pct in defs if metric(metrics, p) is not None]
    for row in range(0, len(shown), 4):
        for col, (label, val) in zip(st.columns(4), shown[row:row + 4]):
            col.metric(label, val)


def station_chart(station: dict) -> go.Figure:
    pts = station["points"]
    x = [f"+{p['horizon_h']}h ({fmt_time(p['target_time'])})" for p in pts]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=x, y=[p["rainfall_mm"] for p in pts], name="Mưa dự báo (mm)", marker_color="#1C7CB5")
    fig.add_scatter(x=x, y=[round(p["flood_probability"] * 100) for p in pts], name="Xác suất ngập ước tính (%)",
                    mode="lines+markers", line={"color": RISK["HIGH"]["color"]}, secondary_y=True)
    if any(p.get("water_level_cm") is not None for p in pts):
        fig.add_scatter(x=x, y=[p.get("water_level_cm") for p in pts], name="Mực nước (cm)", mode="lines",
                        line={"color": "#4F6B7D", "dash": "dash"}, yaxis="y3")
        fig.update_layout(yaxis3={"overlaying": "y", "side": "right", "showgrid": False, "visible": False})
    fig.update_yaxes(title_text="mm", secondary_y=False)
    fig.update_yaxes(title_text="%", range=[0, 100], secondary_y=True)
    fig.update_layout(height=340, margin={"l": 40, "r": 40, "t": 40, "b": 30}, legend={"orientation": "h", "y": 1.15})
    return fig


def station_table(rows: list[dict]) -> list[dict]:
    out = []
    for s in rows:
        by_h = {p["horizon_h"]: p for p in s["points"]}
        row = {"Trạm": f"{s['station_code']} · {s['station_name']}"}
        for h in HOURS:
            p = by_h.get(h)
            row[f"+{h}h"] = f"{fmt_num(p['rainfall_mm'])} mm · {fmt_pct(p['flood_probability'])}" if p else "—"
        row["Chất lượng dữ liệu"] = s["data_quality"]
        row["Ghi chú"] = ", ".join(x for x in ("Cold-start" if s.get("is_cold_start") else "", "Mô phỏng" if s.get("is_simulated") else "") if x)
        out.append(row)
    return out


def risk_table(rows: list[dict]) -> list[dict]:
    return [{"#": i + 1, "Khu vực": r["area_name"] + (" (mô phỏng)" if r.get("is_simulated") else ""),
             "Mức nguy cơ": risk_text(r["risk_level"]),
             "Lý do": flood_cause((r.get("explanation") or {}).get("cause"), (r.get("explanation") or {}).get("depth_cm")) or "—",
             "Điểm": fmt_dec(r["score"]), "Xác suất ngập (ước tính)": fmt_pct(r.get("flood_probability")),
             "Mưa (mm/h)": fmt_num(r.get("rainfall_mm")),
             "LSTM: ngập trong 6 giờ tới": fmt_pct((r.get("explanation") or {}).get("lstm_flood_6h"))}
            for i, r in enumerate(rows)]


def _model_section() -> None:
    st.subheader("Mô hình dự báo đang dùng")
    try:
        d = api.get("/forecasts/model-status")
    except api.ApiError as e:
        show_error(e)
        return
    if d.get("warning"):
        st.warning(d["warning"])
    m = d.get("forecast_model")
    if m:
        st.markdown(f"**{m['name']}** · `{m['model_type']}` · `{MODEL_STATUS_VI.get(m['status'], m['status'])}` {sim_badge(m.get('trained_on_simulated'))}")
        model_metrics(m["model_type"], m.get("metrics"))
    else:
        st.caption("Chưa có mô hình dự báo hoạt động.")
    st.caption(f"Lần phát hành gần nhất: {fmt_dt(d.get('latest_issued_at'))}")


def _station_section() -> None:
    st.subheader("Dự báo theo trạm")
    try:
        rows = api.get("/forecasts/latest", {"area_id": ""})
    except api.ApiError as e:
        show_error(e)
        return
    if not rows:
        st.info("Chưa có bản dự báo nào")
        return
    names = {str(s["station_id"]): f"{s['station_code']} · {s['station_name']}" for s in rows}
    pick = st.selectbox("Trạm hiển thị biểu đồ", list(names), format_func=names.get, key="fc-station")
    st.caption(f"Phát hành {fmt_dt(rows[0]['issued_at'])} · giờ Việt Nam")
    st.plotly_chart(station_chart(next(s for s in rows if str(s["station_id"]) == pick)), width="stretch", key="fc-chart")
    st.dataframe(station_table(rows), hide_index=True, width="stretch")
    st.caption("Mỗi ô: lượng mưa dự báo và xác suất ngập (ước tính).")


def _risk_section() -> None:
    st.subheader("Xếp hạng nguy cơ theo khu vực")
    h = st.radio("Mốc dự báo", list(range(7)), format_func=lambda x: "Hiện tại" if x == 0 else f"+{x} giờ", horizontal=True, key="fc-h")
    try:
        rows = api.get("/forecasts/risk", {"horizon": h})
    except api.ApiError as e:
        show_error(e)
        return
    if not rows:
        st.info("Chưa có đánh giá nguy cơ")
        return
    st.caption(f"Đánh giá phát hành {fmt_dt(rows[0]['issued_at'])}")
    st.dataframe(risk_table(rows), hide_index=True, width="stretch")
    st.caption("Cột LSTM: mô hình LSTM học từ 246 trận ngập báo chí, xác suất quận có ngập trong 6 giờ tới (đã hiệu chỉnh, "
               "ước tính). Chỉ để tham khảo, không dùng để phát cảnh báo; mức nguy cơ và cảnh báo theo hệ luật.")


@st.fragment(run_every=60)
def _body() -> None:
    _model_section()
    _station_section()
    _risk_section()


def render() -> None:
    st.title("Dự báo ngập 1–6 giờ")
    _body()
