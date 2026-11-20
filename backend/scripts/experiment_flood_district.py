"""Thí nghiệm: GRU/LSTM riêng dự báo "quận có ngập trong 6 giờ tới" so với công thức flood_index.

Khác experiment_flood_head.py (gắn đầu ngập vào GRU mưa): mô hình nhỏ riêng cho ngập, nhãn theo quận và
một đầu ra/6 giờ, thêm đặc trưng triều đã lệch TIDE_LAG_H và đặc trưng tĩnh của điểm lưới (độ cao, có điểm ngập,
quận ven triều). Chia theo ngày VN (ngày có sự kiện 60/20/20). Thử thêm "kết hợp" = trung bình GRU và công thức.

Cổng chấp nhận đặt trước: chỉ đề xuất dùng nếu PR-AUC VÀ event-day recall trên test đều >= công thức.
Chỉ đọc CSDL, không đăng ký mô hình.

Chạy: PYTHONUTF8=1 .venv/Scripts/python scripts/experiment_flood_district.py [--start 2024-11-01] [--end 2026-11-15]
      [--epochs 30] [--cells gru lstm] [--out FILE]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from experiment_flood_head import best_thr, load_everything, metrics  # noqa: E402

from app.ai.forecasting import flood_district as fd  # noqa: E402
from app.ai.forecasting import flood_labels as fl  # noqa: E402
from app.ai.forecasting.flood_district import HORIZON, LOOKBACK, build  # noqa: E402
from app.ai.forecasting.preprocessing import clean_station_frame  # noqa: E402
from app.services.risk_service import TIDAL_DISTRICTS as TIDAL  # noqa: E402

VN = timedelta(hours=7)


def district_frame(clean, s, hot, tide, tstats, tidal):
    """Đặc trưng giờ của một điểm lưới + xác suất công thức theo giờ (dùng mưa quan trắc, thuận lợi cho công thức)."""
    from app.services import flood_index
    from app.services import openmeteo_service as om

    idx = clean.index
    rain = clean["rain_mm"].fillna(0).to_numpy(np.float32)
    lagged = idx - timedelta(hours=om.TIDE_LAG_H)
    tv = tide.reindex(tide.index.union(lagged)).ffill().reindex(lagged).to_numpy()
    ratio = np.array([om.tide_ratio(None if np.isnan(v) else float(v), tstats) or 0.0 for v in tv], np.float32)
    hs = s.area_id in hot
    pf = np.array([flood_index.probability(flood_index.FloodInputs(
        float(rain[i]), float(rain[max(0, i - 2): i + 1].sum()), float(ratio[i]), s.elevation_m, hs))
        for i in range(len(idx))], np.float32)
    return fd.features(rain, idx, ratio, s.elevation_m, hs, tidal), pf


def windows(feats, pf, hourly, idx, period):
    n = len(idx) - LOOKBACK - HORIZON + 1
    if n <= 0:
        return None
    X = np.stack([feats[i: i + LOOKBACK] for i in range(n)])
    tgt = np.arange(n)[:, None] + LOOKBACK + np.arange(HORIZON)
    y = hourly[tgt].max(1)  # quận có ngập trong 6 giờ tới
    p = pf[tgt].max(1)  # công thức: giờ xấu nhất trong 6 giờ tới
    t = idx.to_numpy()[tgt]
    valid = ((t >= np.datetime64(period[0])) & (t < np.datetime64(period[1]))).all(1)
    return X, y, p, valid, idx[LOOKBACK - 1: LOOKBACK - 1 + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-11-01")
    ap.add_argument("--end", default="2026-11-15")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--cells", nargs="+", default=["gru", "lstm"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("flood_district_result.json"))
    ap.add_argument("--register", action="store_true",
                    help="hiệu chỉnh Platt trên validation, lưu và kích hoạt mô hình LSTM (chỉ khi qua cổng)")
    a = ap.parse_args()
    import keras

    from app.core.database import SessionLocal

    period = (datetime.fromisoformat(a.start) - VN, datetime.fromisoformat(a.end) - VN)  # giờ VN -> UTC naive
    with SessionLocal() as db:
        frames, ev, st, areas, hot, tide, tstats, _ = load_everything(db, period)
        names = {i: n for i, n in db.execute(__import__("sqlalchemy").text(
            "select id, name from administrative_areas where level='DISTRICT'")).all()}
    keras.utils.set_random_seed(a.seed)

    parts = []
    for code, (df, thr) in frames.items():
        s = st[code]
        d = fl.district_of(s.area_id, areas)
        if d is None:
            continue
        clean = clean_station_frame(df, thr)
        feats, pf = district_frame(clean, s, hot, tide, tstats, names.get(d) in TIDAL)
        hourly = np.zeros(len(clean.index), np.float32)
        for te in ev.get(d, []):  # giờ t dương nếu có sự kiện bắt đầu trong (t, t+1]
            k = clean.index.searchsorted(pd.Timestamp(te), "left")
            hourly[max(k - 1, 0): k] = 1
        w = windows(feats, pf, hourly, clean.index, period)
        if w:
            parts.append((code, *w))
    X = np.concatenate([p[1] for p in parts])
    y = np.concatenate([p[2] for p in parts])
    pf = np.concatenate([p[3] for p in parts])
    valid = np.concatenate([p[4] for p in parts])
    times = np.concatenate([p[5].to_numpy() for p in parts])
    stn = np.concatenate([[p[0]] * len(p[1]) for p in parts])
    X, y, pf, times, stn = X[valid], y[valid], pf[valid], times[valid], stn[valid]
    date = (pd.DatetimeIndex(times) + VN).normalize()

    ev_dates = {pd.Timestamp((t + VN).date()) for v in ev.values() for t in v}
    all_dates = sorted(set(date))
    rng = np.random.default_rng(a.seed)
    split_of = {}
    for grp in ([d for d in all_dates if d in ev_dates], [d for d in all_dates if d not in ev_dates]):
        g = rng.permutation(np.array(grp, dtype=object))
        n1, n2 = int(len(g) * .6), int(len(g) * .8)
        for i, d in enumerate(g):
            split_of[d] = "train" if i < n1 else "val" if i < n2 else "test"
    sp = np.array([split_of[pd.Timestamp(d)] for d in date])
    tr, va, te = sp == "train", sp == "val", sp == "test"
    info = {k: {"windows": int(m.sum()), "positive": int(y[m].sum()),
                "event_days": sum(1 for d, s_ in split_of.items() if s_ == k and d in ev_dates)}
            for k, m in (("train", tr), ("val", va), ("test", te))}
    print(json.dumps(info))
    unit = (pd.Series(stn[te]) + "|" + pd.Series(date[te].astype(str))).to_numpy()

    res = {"period_vn": [a.start, a.end], "events": int(sum(len(v) for v in ev.values())),
           "event_days": len(ev_dates), "split": info, "models": {}}
    res["formula"] = metrics(y[te], pf[te], best_thr(y[va], pf[va]), unit)
    print("formula", json.dumps(res["formula"]))
    pos_w = min(float((1 - y[tr].mean()) / max(y[tr].mean(), 1e-6)), 100.0)
    models = {}
    for cell in a.cells:
        m = build(cell, X.shape[2])
        h = m.fit(X[tr], y[tr], validation_data=(X[va], y[va]), class_weight={0: 1.0, 1: pos_w},
                  epochs=a.epochs, batch_size=512, verbose=2,
                  callbacks=[keras.callbacks.EarlyStopping(monitor="val_pr_auc", mode="max", patience=5,
                                                           restore_best_weights=True)])
        pv = m.predict(X[va], verbose=0, batch_size=2048).ravel()
        pt = m.predict(X[te], verbose=0, batch_size=2048).ravel()
        mm = metrics(y[te], pt, best_thr(y[va], pv), unit)
        mm["epochs_run"] = len(h.history["loss"])
        hv, ht = (pv + pf[va]) / 2, (pt + pf[te]) / 2  # kết hợp: trung bình với công thức
        hy = metrics(y[te], ht, best_thr(y[va], hv), unit)
        res["models"][cell] = mm
        models[cell] = m
        res["models"][cell + "+formula"] = hy
        print(cell, json.dumps(mm))
        print(cell + "+formula", json.dumps(hy))
    f = res["formula"]
    res["gate"] = {k: bool(v["pr_auc"] >= f["pr_auc"] and (v["event_day_recall"] or 0) >= (f["event_day_recall"] or 0))
                   for k, v in res["models"].items()}
    a.out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print("gate", res["gate"], "->", a.out)
    if a.register and "lstm" in models and res["gate"].get("lstm"):
        register(models["lstm"], X[va], y[va], X[te], y[te], res, a)


def register(m, Xv, yv, Xt, yt, res, a):
    from sklearn.linear_model import LogisticRegression
    from sqlalchemy import update

    from app.core.config import get_settings
    from app.core.database import SessionLocal, utcnow
    from app.models import ModelVersion

    logit = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))  # noqa: E731
    pv = m.predict(Xv, verbose=0, batch_size=2048).ravel()
    lr = LogisticRegression().fit(logit(pv)[:, None], yv)
    pa, pb = float(lr.coef_[0][0]), float(lr.intercept_[0])
    pt = fd.calibrate(m.predict(Xt, verbose=0, batch_size=2048).ravel(), pa, pb)
    cal = {"brier_calibrated": float(((pt - yt) ** 2).mean()), "mean_prob_test": float(pt.mean()),
           "positive_rate_test": float(yt.mean())}
    version = utcnow().strftime("%Y%m%d%H%M%S")
    out = fd.save(m, get_settings().artifacts_dir / "flood_district" / version, pa, pb,
                  {"version": version, "lookback": LOOKBACK, "horizon": HORIZON, "period_vn": res["period_vn"]})
    metrics = {**res["models"]["lstm"], **cal, "formula_pr_auc": res["formula"]["pr_auc"],
               "formula_event_day_recall": res["formula"]["event_day_recall"]}
    with SessionLocal() as db:
        db.execute(update(ModelVersion).where(ModelVersion.model_type == fd.MODEL_TYPE).values(
            is_active=False, status="ARCHIVED"))
        db.add(ModelVersion(
            name="flood-district-lstm", model_type=fd.MODEL_TYPE, version=version, artifact_path=str(out),
            dataset_description=(f"{res['events']} sự kiện ngập báo chí ({res['event_days']} ngày), mưa Open-Meteo, "
                                 "triều Vũng Tàu lệch 4 giờ; nhãn: quận có ngập trong 6 giờ tới"),
            trained_on_simulated=False, metrics=metrics,
            params={"seed": a.seed, "epochs_run": res["models"]["lstm"]["epochs_run"], "platt": [pa, pb],
                    "use": "chỉ hiển thị, không vào luật cảnh báo"},
            status="DEPLOYED", is_active=True, trained_at=utcnow()))
        db.commit()
    print("đăng ký", out, cal)


if __name__ == "__main__":
    main()
