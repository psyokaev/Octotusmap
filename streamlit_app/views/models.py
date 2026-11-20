"""Mô hình AI (ModelsPage.tsx): phiên bản, chỉ số, kích hoạt, huấn luyện lại, lịch sử huấn luyện."""
import json
import time

import api
import streamlit as st
from analytics import MODEL_STATUS_VI, fetch, is_vision, metric, model_metrics, section
from common import confirm_pending, fmt_dec, fmt_dt, fmt_num, sim_badge

RUN_STATUS_VI = {"RUNNING": "Đang chạy", "SUCCESS": "Hoàn tất", "FAILED": "Lỗi"}
TASK_VI = {"forecast": "mô hình dự báo (LSTM/GRU)", "vision": "mô hình camera (YOLOv8-seg)", "FORECAST": "Dự báo", "VISION": "Camera"}
POLL_S = 10
WATCH_S = 60  # run mới được tạo ở luồng nền sau khi POST trả về -> theo dõi thêm 1 phút


def key_metrics(m: dict) -> str:
    x, d = m["metrics"], fmt_dec
    if not x:
        return "—"
    if is_vision(m["model_type"]):
        return (f"mask mAP50 {d(metric(x, 'mask_map50'))} · mAP50-95 {d(metric(x, 'mask_map50_95'))} · box mAP50 {d(metric(x, 'box_map50'))}"
                f" · P {d(metric(x, 'precision'))} · R {d(metric(x, 'recall'))}")
    if x.get("heavy_rain"):
        return (f"Mưa MAE {d(metric(x, 'rainfall.mae'))} · RMSE {d(metric(x, 'rainfall.rmse'))} · Mưa to ≥5 mm/h: P {d(metric(x, 'heavy_rain.precision'))}"
                f" · R {d(metric(x, 'heavy_rain.recall'))} · F1 {d(metric(x, 'heavy_rain.f1'))}")
    return (f"Mưa MAE {d(metric(x, 'rainfall.mae'))} · RMSE {d(metric(x, 'rainfall.rmse'))} · mực nước MAE {d(metric(x, 'water_level.mae'))}"
            f" · P {d(metric(x, 'flood.precision'))} · R {d(metric(x, 'flood.recall'))} · F1 {d(metric(x, 'flood.f1'))}"
            f" · Brier {d(metric(x, 'flood.brier'))} · AUC {d(metric(x, 'flood.roc_auc'))}")


def render() -> None:
    st.title("Mô hình AI")
    runs = fetch("/admin/training-runs") or []
    watching = time.time() < st.session_state.get("mdl-watch-until", 0)
    live = watching or any(r["status"] == "RUNNING" for r in runs)
    _train(any(r["status"] == "RUNNING" for r in runs))
    # chỉ tự làm mới khi đang có phiên huấn luyện chạy
    st.fragment(run_every=POLL_S if live else None)(_lists)()


def _train(running: bool) -> None:
    with section("Huấn luyện lại"):
        cols = st.columns(2)
        for col, (task, label, default) in zip(cols, (("forecast", "dự báo", 8), ("vision", "camera", 15))):
            with col:
                st.number_input("Số epoch (1–100)", 1, 100, default, key=f"mdl-ep-{task}")
                st.button(f"Huấn luyện lại {label}", key=f"mdl-train-{task}", disabled=running,
                          on_click=lambda t=task: st.session_state.update({"mdl-train-p": {"task": t, "epochs": int(st.session_state[f"mdl-ep-{t}"])}}))  # đọc lúc bấm, không dùng giá trị của lần vẽ trước
        st.caption("Đang có phiên huấn luyện chạy; danh sách tự cập nhật mỗi 10 giây." if running
                   else "Huấn luyện chạy nền trên máy chủ và có thể mất vài phút.")
        confirm_pending("mdl-train-p", "Bắt đầu huấn luyện lại mô hình? Quá trình chạy nền và tốn tài nguyên máy chủ.", _start_training,
                        "Đã bắt đầu huấn luyện", "Bắt đầu huấn luyện")


def _start_training(p: dict) -> None:
    api.post("/admin/models/train", None, {"task": p["task"], "epochs": p["epochs"]})
    st.session_state["mdl-watch-until"] = time.time() + WATCH_S


def _lists() -> None:
    models = fetch("/admin/models")
    with section("Phiên bản mô hình"):
        if not models:
            st.info("Chưa có mô hình nào")
        else:
            st.dataframe([{"Mô hình": f"{m['name']} {m['version']}" + (" (mô phỏng)" if m["trained_on_simulated"] else ""), "Loại": m["model_type"],
                           "Trạng thái": "Đang dùng" if m["is_active"] else MODEL_STATUS_VI.get(m["status"], m["status"]),
                           "Huấn luyện": fmt_dt(m["trained_at"]), "Thời gian": fmt_num(m["training_seconds"], " giây"), "Chỉ số chính": key_metrics(m)}
                          for m in models], hide_index=True, width="stretch")
            _pick(models)
    runs = fetch("/admin/training-runs")
    with section("Lịch sử huấn luyện"):
        if not runs:
            st.info("Chưa có phiên huấn luyện")
            return
        st.dataframe([{"#": r["id"], "Tác vụ": TASK_VI.get(r["task"], r["task"]), "Trạng thái": RUN_STATUS_VI.get(r["status"], r["status"]),
                       "Mô hình": f"#{r['model_version_id']}" if r["model_version_id"] else "—", "Bắt đầu": fmt_dt(r["started_at"]),
                       "Kết thúc": fmt_dt(r["finished_at"]),
                       "Tham số": " · ".join(f"{k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}" for k, v in (r["params"] or {}).items()) or "—"}
                      for r in runs], hide_index=True, width="stretch")
        for r in runs:
            if r["log"]:
                with st.expander(f"Nhật ký phiên #{r['id']}"):
                    st.code(r["log"], language=None)


def _pick(models: list[dict]) -> None:
    by_id = {m["id"]: m for m in models}
    pick = st.selectbox("Chọn mô hình", list(by_id), format_func=lambda i: f"{by_id[i]['name']} {by_id[i]['version']} ({by_id[i]['model_type']})", key="mdl-pick")
    m = by_id[pick]
    st.button("Chi tiết", key="mdl-detail", on_click=lambda: st.session_state.update({"mdl-view": pick}))
    if m["model_type"] != "BASELINE" and not m["is_active"]:
        st.button("Kích hoạt", key="mdl-activate", type="primary", on_click=lambda: st.session_state.update({"mdl-act-p": pick}))
    confirm_pending("mdl-act-p", f"Kích hoạt {m['name']} {m['version']}? Mô hình cùng nhóm đang dùng sẽ chuyển sang lưu trữ và các lần dự báo tiếp theo sẽ dùng mô hình này.",
                    lambda mid: api.post(f"/admin/models/{mid}/activate"), "Đã kích hoạt mô hình", "Kích hoạt")
    if st.session_state.get("mdl-view") in by_id:
        _detail(by_id[st.session_state["mdl-view"]])


def _detail(m: dict) -> None:
    x = m["metrics"] or {}
    with st.container(border=True):
        h = st.columns([8, 1])
        h[0].subheader(f"{m['name']} {m['version']}")
        h[1].button("Đóng", key="mdl-detail-close", on_click=lambda: st.session_state.pop("mdl-view", None))
        st.markdown(f"`{m['model_type']}` `{'Đang dùng' if m['is_active'] else MODEL_STATUS_VI.get(m['status'], m['status'])}` {sim_badge(m['trained_on_simulated'])}")
        st.caption(f"Huấn luyện lúc {fmt_dt(m['trained_at'])} · {fmt_num(m['training_seconds'], ' giây')} · tạo lúc {fmt_dt(m['created_at'])}")
        if m.get("dataset_description"):
            st.write(f"Dữ liệu: {m['dataset_description']}")
        model_metrics(m["model_type"], m["metrics"])
        rain_h = (x.get("rainfall") or {}).get("per_horizon") or {}
        wl_h = (x.get("water_level") or {}).get("per_horizon") or {}
        hs = sorted(set(rain_h) | set(wl_h), key=lambda h: int(h[1:]))
        if hs:
            st.markdown("**Sai số theo mốc dự báo**")
            st.dataframe([{"Mốc": f"+{h[1:]}h", "MAE mưa (mm)": fmt_dec(metric(rain_h.get(h), "mae")), "RMSE mưa (mm)": fmt_dec(metric(rain_h.get(h), "rmse")),
                           "MAE mực nước (cm)": fmt_dec(metric(wl_h.get(h), "mae")), "RMSE mực nước (cm)": fmt_dec(metric(wl_h.get(h), "rmse"))}
                          for h in hs], hide_index=True, width="stretch")
        cm = (x.get("flood") or {}).get("confusion_matrix")
        if cm:
            st.markdown(f"**Ma trận nhầm lẫn (ngưỡng {fmt_dec(metric(x, 'flood.threshold'), 2)})**")
            st.dataframe([{"": "Thực tế ngập", "Dự báo ngập": f"{fmt_num(cm.get('tp'))} (TP)", "Dự báo không ngập": f"{fmt_num(cm.get('fn'))} (FN)"},
                          {"": "Thực tế không ngập", "Dự báo ngập": f"{fmt_num(cm.get('fp'))} (FP)", "Dự báo không ngập": f"{fmt_num(cm.get('tn'))} (TN)"}],
                         hide_index=True, width="stretch")
        with st.expander("Toàn bộ chỉ số và tham số (JSON)"):
            st.json({"metrics": m["metrics"], "params": m["params"]})
