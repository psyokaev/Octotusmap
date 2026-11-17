"""Thí nghiệm: đầu ra ngập học từ nhãn báo chí so với công thức flood_index (cùng cửa sổ test).

Chạy: PYTHONUTF8=1 .venv/Scripts/python scripts/experiment_flood_head.py [--epochs 8] [--cells gru lstm]
Chỉ đọc CSDL; ghi JSON kết quả. Không đăng ký mô hình.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402

from app.ai.forecasting import flood_labels as fl  # noqa: E402
from app.ai.forecasting.preprocessing import HORIZON, LOOKBACK, Scaler, clean_station_frame, make_windows  # noqa: E402

OUT = Path(r"E:\Octotusmap\.superpowers\sdd\chuyen-dung-de-cuong\flood_head_result.json")
VN = timedelta(hours=7)
PERIOD = (datetime(2025, 8, 31, 17), datetime(2026, 11, 9, 17))  # 2025-09-01 .. 2026-11-09 giờ VN (UTC naive)


def load_everything(db):
    from sqlalchemy import select

    from app.ai.forecasting.train import load_frames_from_db
    from app.models import (
        AdministrativeArea,
        FloodHotspot,
        HistoricalFloodEvent,
        ModelVersion,
        MonitoringStation,
        WaterLevelObservation as W,
    )
    from app.services import openmeteo_service as om

    frames, _ = load_frames_from_db(db)
    areas = {a.id: (a.level, a.parent_id) for a in db.scalars(select(AdministrativeArea))}
    ev = {}
    for e in db.scalars(select(HistoricalFloodEvent).where(HistoricalFloodEvent.is_simulated.is_(False))):
        d = fl.district_of(e.area_id, areas)
        if d is not None and PERIOD[0] <= e.started_at < PERIOD[1]:
            ev.setdefault(d, []).append(e.started_at)
    st = {s.code: s for s in db.scalars(select(MonitoringStation))}
    hot = set(db.scalars(select(FloodHotspot.area_id).distinct()))
    hot |= {p for (p,) in db.execute(select(AdministrativeArea.parent_id).where(AdministrativeArea.id.in_(hot)))}
    tide = db.execute(select(W.observed_at, W.water_level_cm).where(W.station_id == st[om.TIDE_CODE].id)).all()
    tide = pd.Series({t: v for t, v in tide}).sort_index()
    active = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True),
                                                  ModelVersion.model_type.in_(["LSTM", "GRU"])))
    return frames, ev, st, areas, hot, tide, om.tide_stats(db), active


def formula_prob(clean, st, hot, tide, tstats, n):
    """Công thức hiện hành (như forecast_service._estimate_flood) cho từng (cửa sổ, giờ đích), dùng mưa quan trắc
    thật ở giờ đích (thuận lợi cho công thức hơn mưa dự báo)."""
    from app.services import flood_index
    from app.services import openmeteo_service as om

    idx = clean.index
    rain = clean["rain_mm"].to_numpy()
    lagged = idx - timedelta(hours=om.TIDE_LAG_H)
    tv = tide.reindex(tide.index.union(lagged)).ffill().reindex(lagged).to_numpy()  # như tide_at: giá trị gần nhất <= t-lag
    hs = st.area_id in hot
    p_hour = np.empty(len(idx), np.float32)
    for i in range(len(idx)):
        ratio = om.tide_ratio(None if np.isnan(tv[i]) else float(tv[i]), tstats)
        p_hour[i] = flood_index.probability(flood_index.FloodInputs(
            float(rain[i]), float(rain[max(0, i - 2): i + 1].sum()), ratio, st.elevation_m, hs))
    return p_hour[np.arange(n)[:, None] + LOOKBACK + np.arange(HORIZON)]


def best_thr(y, p):
    best, bt = -1.0, 0.5
    for t in np.unique(np.quantile(p, np.linspace(0.5, 0.9995, 200))):
        pr = p >= t
        f = 2 * (pr & (y == 1)).sum() / max(pr.sum() + (y == 1).sum(), 1)
        if f > best:
            best, bt = f, float(t)
    return bt


def metrics(y, p, thr, unit):
    pr = p >= thr
    tp = int((pr & (y == 1)).sum())
    prec, rec = tp / max(pr.sum(), 1), tp / max((y == 1).sum(), 1)
    g = pd.DataFrame({"u": unit, "hit": pr & (y == 1), "pos": y == 1}).query("pos").groupby("u").hit.any()
    return {"roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
            "brier": float(((p - y) ** 2).mean()), "threshold": thr, "precision": prec, "recall": rec,
            "f1": 2 * prec * rec / max(prec + rec, 1e-9),
            "event_day_recall": float(g.mean()) if len(g) else None, "event_days_test": int(len(g)),
            "positive_rate": float(y.mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--cells", nargs="+", default=["gru"])
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    import keras

    from app.ai.forecasting import inference
    from app.ai.forecasting.model import build_model
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        frames, ev, st, areas, hot, tide, tstats, active = load_everything(db)
    sc = Scaler.load(Path(active.artifact_path) / "scaler.json")  # cùng scaler với GRU đang chạy -> cùng X
    keras.utils.set_random_seed(a.seed)

    rows = []
    for code, (df, thr) in frames.items():
        s = st[code]
        clean = clean_station_frame(df, thr)
        X, yr, _, _, times = make_windows(clean, sc)
        if len(X) == 0:
            continue
        hourly = fl.hourly_labels(clean.index, ev.get(fl.district_of(s.area_id, areas), []))
        y, valid = fl.window_labels(hourly, LOOKBACK, HORIZON, PERIOD, clean.index)
        rows.append(dict(code=code, X=X, yr=yr, y=y, valid=valid, times=pd.DatetimeIndex(times),
                         pf=formula_prob(clean, s, hot, tide, tstats, len(X))))
    cat = lambda k: np.concatenate([r[k] for r in rows])  # noqa: E731
    X, yr, y, valid, pf = cat("X"), cat("yr"), cat("y"), cat("valid"), cat("pf")
    times = np.concatenate([r["times"].to_numpy() for r in rows])
    stn = np.concatenate([[r["code"]] * len(r["X"]) for r in rows])
    date = (pd.DatetimeIndex(times) + VN).normalize()

    # chia theo ngày VN: ngày có sự kiện 60/20/20 + ngày không sự kiện cùng tỉ lệ, seed cố định
    lab_dates = pd.DatetimeIndex(sorted(set(date[valid])))
    ev_dates = pd.DatetimeIndex(sorted({(t + VN).replace(hour=0, minute=0, second=0, microsecond=0)
                                        for v in ev.values() for t in v}))
    rng = np.random.default_rng(a.seed)
    split_of = {}
    for grp in (ev_dates.intersection(lab_dates), lab_dates.difference(ev_dates)):
        g = rng.permutation(np.array(grp))
        n1, n2 = int(len(g) * .6), int(len(g) * .8)
        for i, d in enumerate(g):
            split_of[pd.Timestamp(d)] = "train" if i < n1 else "val" if i < n2 else "test"
    sp = np.array([split_of.get(pd.Timestamp(d), "train") for d in date])  # ngoài giai đoạn nhãn: train (chỉ đầu mưa)
    spl = {k: sp == k for k in ("train", "val", "test")}
    info = {}
    for k, m in spl.items():
        mv = m & valid
        info[k] = {"windows": int(mv.sum()), "positive_station_hours": int(y[mv].sum()),
                   "positive_windows": int((y[mv].max(1) > 0).sum()),
                   "event_dates": sum(1 for d, s_ in split_of.items() if s_ == k and d in ev_dates),
                   "nonevent_dates": sum(1 for d, s_ in split_of.items() if s_ == k and d not in ev_dates)}
    print(json.dumps(info))

    pos_w = min(float((1 - y[spl["train"] & valid].mean()) / max(y[spl["train"] & valid].mean(), 1e-6)), 50.0)

    def weights(m):
        f = (m & valid).astype(np.float32) * (1 + (pos_w - 1) * (y.max(1) > 0))
        return [np.ones(m.sum(), np.float32), f[m]]

    res = {"split": info, "pos_weight": pos_w, "label_window_h": [fl.LABEL_BEFORE_H, fl.LABEL_AFTER_H],
           "period_utc": [str(PERIOD[0]), str(PERIOD[1])], "models": {}}
    te, va = spl["test"] & valid, spl["val"] & valid
    unit = lambda m: np.repeat((pd.Series(stn[m]) + "|" + pd.Series(date[m].astype(str))).to_numpy(), HORIZON)  # noqa: E731
    yt, yv = y[te].ravel(), y[va].ravel()

    thr_f = best_thr(yv, pf[va].ravel())
    res["formula"] = metrics(yt, pf[te].ravel(), thr_f, unit(te))
    print("formula", json.dumps(res["formula"]))
    lm = inference.load(active.artifact_path)
    res["active_gru_rain_mae"] = float(np.abs(np.expm1(np.asarray(lm.model.predict(X[te], verbose=0, batch_size=1024)))
                                              - yr[te]).mean())
    print("active gru rain mae", res["active_gru_rain_mae"])

    for cell in a.cells:
        m = build_model(cell, heads=("rain", "flood"))
        tr = spl["train"]
        h = m.fit(X[tr], [np.log1p(yr[tr]), y[tr]], sample_weight=weights(tr),
                  validation_data=(X[spl["val"]], [np.log1p(yr[spl["val"]]), y[spl["val"]]],
                                   weights(spl["val"])),
                  epochs=a.epochs, batch_size=256, verbose=2,
                  callbacks=[keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True)])
        pv, pt = m.predict(X[va], verbose=0, batch_size=1024), m.predict(X[te], verbose=0, batch_size=1024)
        mm = metrics(yt, pt[1].ravel(), best_thr(yv, pv[1].ravel()), unit(te))
        mm["rain_mae"] = float(np.abs(np.expm1(pt[0]) - yr[te]).mean())
        mm["epochs_run"] = len(h.history["loss"])
        res["models"][cell] = mm
        print(cell, json.dumps(mm))
        OUT.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print("saved", OUT)


if __name__ == "__main__":
    main()
