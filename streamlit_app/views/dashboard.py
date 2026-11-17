"""Tổng quan (DashboardPage.tsx): KPI, mưa, mực nước, dự báo, tỉ lệ rủi ro, cảnh báo, xu hướng, hiệu quả mô hình."""
import streamlit as st
from analytics import (
    C,
    EMPTY,
    GROUP_VI,
    LEVELS,
    chart,
    fetch,
    filter_bar,
    is_vision,
    model_metrics,
    risk_pie,
    section,
)
from common import RISK, camera_enabled, fmt_dec, fmt_dt, fmt_num, fmt_pct, sim_badge


def _kpis(o: dict, cam: bool) -> None:
    items = [
        ("Tổng số trạm", fmt_num(o["stations_total"]), None), ("Trạm đang kết nối", fmt_num(o["stations_online"]), None),
        ("Trạm mất kết nối", fmt_num(o["stations_offline"]), None),
        *([("Camera", fmt_num(o["cameras_total"]), None)] if cam else []),
        ("Khu vực", fmt_num(o["areas_total"]), f"{o['areas_insufficient']} khu vực thiếu dữ liệu" if o["areas_insufficient"] else None),
        (f"{RISK['LOW']['symbol']} Khu vực nguy cơ thấp hiện tại", fmt_num(o["areas_low"]), None),
        (f"{RISK['MEDIUM']['symbol']} Khu vực nguy cơ trung bình hiện tại", fmt_num(o["areas_medium"]), None),
        (f"{RISK['HIGH']['symbol']} Khu vực nguy cơ cao hiện tại", fmt_num(o["areas_high"]), None),
        ("Cảnh báo đang mở", fmt_num(o["alerts_active"]), "gồm dự báo tới 6 giờ"),
        ("Cảnh báo đã xử lý", fmt_num(o["alerts_handled"]), f"trên {fmt_num(o['alerts_in_range'])} cảnh báo trong kỳ"),
        ("Mưa trung bình", fmt_num(o["rainfall_avg_mm"], " mm/h"), None), ("Mực nước cao nhất", fmt_num(o["water_level_max_cm"], " cm"), None),
        ("Dữ liệu hợp lệ", fmt_pct(o["valid_data_ratio"]), None), ("Dự báo mới nhất", fmt_dt(o["latest_forecast_at"]), None),
    ]
    for row in range(0, len(items), 5):
        for col, (label, value, hint) in zip(st.columns(5), items[row: row + 5]):
            col.metric(label, value)
            if hint:
                col.caption(hint)


def _forecast_chart(fc: list[dict]) -> None:
    hs = range(1, 7)

    def top(h, field):
        v = [p[field] for s in fc for p in s["points"] if p["horizon_h"] == h and p[field] is not None]
        return max(v) if v else None
    chart([f"+{h}h" for h in hs], [
        {"name": "Mưa lớn nhất (mm)", "y": [top(h, "rainfall_mm") for h in hs], "color": C["water"]},
        {"name": "Xác suất ngập lớn nhất (%, ước tính)", "kind": "line", "y2": True, "color": RISK["HIGH"]["color"],
         "y": [None if top(h, "flood_probability") is None else round(top(h, "flood_probability") * 100) for h in hs]},
    ], ytitle="mm", y2title="%", y2_range=[0, 100], key="db-fc")
    st.caption(f"Phát hành {fmt_dt(fc[0]['issued_at'])}")


def _performance(perf: dict, cam: bool) -> None:
    models = perf["models"]
    fc = next((m for m in models if m["active"] and not is_vision(m["type"]) and m["type"] != "BASELINE"), None)
    vis = next((m for m in models if m["active"] and is_vision(m["type"])), None)
    left, right = st.columns(2)
    with left:
        st.markdown(f"**Dự báo:** {fc['name'] if fc else 'chưa có mô hình hoạt động'} {sim_badge(bool(fc and fc['trained_on_simulated']))}")
        if fc:
            model_metrics(fc["type"], fc["metrics"])
        if cam:
            st.markdown(f"**Nhận diện ngập qua camera:** {vis['name'] if vis else 'chưa có mô hình hoạt động'} "
                        f"{sim_badge(bool(vis and vis['trained_on_simulated']))}")
            if vis:
                model_metrics(vis["type"], vis["metrics"])
    with right:
        st.markdown("**Sai số dự báo mưa thực tế theo mốc**")
        skill = perf["online_rainfall_skill"]
        if not skill:
            st.caption("Chưa đủ cặp dự báo – quan trắc để đánh giá.")
            return
        chart([f"+{x['horizon_h']}h" for x in skill], [{"name": "MAE (mm)", "y": [x["mae"] for x in skill], "color": C["water"]},
                                                      {"name": "RMSE (mm)", "y": [x["rmse"] for x in skill], "color": C["ink"]}],
              ytitle="mm", height=240, key="db-skill")
        st.caption("Số cặp so sánh: " + " · ".join(f"+{x['horizon_h']}h: {fmt_dec(x['n'], 0)}" for x in skill))


def render() -> None:
    st.title("Tổng quan")
    params, group = filter_bar("db")
    p = {**params, "risk_level": None, "data_type": None}
    g = GROUP_VI[group]
    cam = camera_enabled()
    overview = fetch("/statistics/overview", p)
    rain = fetch("/statistics/rainfall", {**p, "group": group})
    water = fetch("/statistics/water-level", {**p, "group": group})
    alerts = fetch("/statistics/alerts", {**p, "group": group})
    risk = fetch("/statistics/risk", {**p, "group": group})
    perf = fetch("/statistics/model-performance", p)
    fc = fetch("/forecasts/latest", {"area_id": params["area_id"]})

    if fc and any(s.get("is_simulated") for s in fc):
        st.info(f"{sim_badge()} Có dữ liệu mô phỏng trong kỳ này.")
    if overview:
        _kpis(overview, cam)

    left, right = st.columns(2)
    with left, section(f"Lượng mưa theo {g}"):
        s = (rain or {}).get("series") or []
        if s:
            chart([x["bucket"] for x in s], [{"name": "Tổng lượng mưa (mm)", "y": [x["sum"] for x in s], "color": C["water"]}], ytitle="mm", key="db-rain")
        else:
            st.caption(EMPTY)
    with right, section(f"Mực nước theo {g}"):
        s = (water or {}).get("series") or []
        if s:
            chart([x["bucket"] for x in s], [
                {"name": "Cao nhất (cm)", "kind": "line", "y": [x["max"] for x in s], "color": RISK["HIGH"]["color"]},
                {"name": "Trung bình (cm)", "kind": "line", "y": [x["avg"] for x in s], "color": C["water"]}], ytitle="cm", key="db-water")
        else:
            st.caption(EMPTY)
    left, right = st.columns(2)
    with left, section("Dự báo 1–6 giờ tới (toàn bộ trạm)"):
        if fc:
            _forecast_chart(fc)
        else:
            st.caption("Chưa có bản dự báo")
    with right, section("Tỉ lệ khu vực theo mức nguy cơ hiện tại"):
        if overview:
            risk_pie({"LOW": overview["areas_low"], "MEDIUM": overview["areas_medium"], "HIGH": overview["areas_high"],
                      "INSUFFICIENT_DATA": overview["areas_insufficient"]}, "db-pie")
        elif risk:
            risk_pie(risk["current"], "db-pie")
    left, right = st.columns(2)
    with left, section(f"Cảnh báo theo {g}"):
        s = (alerts or {}).get("by_time") or []
        if s:
            chart([x["bucket"] for x in s], [{"name": RISK[k]["label"], "y": [x[k] for x in s], "color": RISK[k]["color"]} for k in LEVELS],
                  stack=True, key="db-al-time")
        else:
            st.caption("Không có cảnh báo trong khoảng thời gian đã chọn")
    with right, section("Cảnh báo theo khu vực"):
        s = ((alerts or {}).get("by_area") or [])[:15]
        if s:
            chart([x["area"] for x in s], [{"name": "Số cảnh báo", "y": [x["count"] for x in s], "color": C["amber"]}], horizontal=True,
                  height=max(220, len(s) * 26 + 60), key="db-al-area")
        else:
            st.caption("Không có cảnh báo trong khoảng thời gian đã chọn")
    with section("Xu hướng nguy cơ ngập"):
        s = (risk or {}).get("trend") or []
        if s:
            chart([x["bucket"] for x in s], [
                *({"name": RISK[k]["label"], "y": [x[k] for x in s], "color": RISK[k]["color"]} for k in LEVELS),
                {"name": "Điểm nguy cơ TB", "kind": "line", "y2": True, "y": [x["avg_score"] for x in s], "color": C["ink"]}],
                stack=True, ytitle="lượt", y2title="điểm", key="db-trend")
        else:
            st.caption(EMPTY)
    with section("Hiệu quả mô hình"):
        if perf:
            _performance(perf, cam)
