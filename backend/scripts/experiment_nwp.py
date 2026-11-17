"""Thí nghiệm cô lập: dự báo số (NWP) 6 giờ tới có cải thiện GRU mưa không? Không ghi DB, không đổi production.

Chạy: PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python scripts/experiment_nwp.py
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL = sys.argv[1] if len(sys.argv) > 1 else ""  # "" = best_match (lần chạy đầu, bị rò rỉ)
SFX = f"_{MODEL}" if MODEL else ""
CACHE = ROOT / "storage" / f"nwp_cache{SFX}.csv"
OUT = Path(f"E:/Octotusmap/.superpowers/sdd/outline-gap-fixes/nwp_result{SFX}.json")
HIST_FC = "https://historical-forecast-api.open-meteo.com/v1/forecast"
SEED, EPOCHS, BATCH = 42, 8, 256


def log(*a):
    print(*a, flush=True)


def fetch_nwp(stations, start, end) -> pd.DataFrame:
    """stations: [(code, lat, lon)]. Cache dạng dài: code,time,nwp_mm."""
    if CACHE.exists():
        return pd.read_csv(CACHE, parse_dates=["time"], encoding="utf-8")
    from app.services.openmeteo_service import _get

    rows = []
    d = start.normalize()
    while d <= end:
        e = min(d + timedelta(days=179), end.normalize())
        params = {"latitude": ",".join(f"{s[1]:.4f}" for s in stations),
                  "longitude": ",".join(f"{s[2]:.4f}" for s in stations),
                  "hourly": "precipitation", "timezone": "GMT",
                  "start_date": f"{d:%Y-%m-%d}", "end_date": f"{e:%Y-%m-%d}"} | ({"models": MODEL} if MODEL else {})
        data = _get(HIST_FC, params, timeout=120)
        data = data if isinstance(data, list) else [data]
        for (code, _, _), item in zip(stations, data, strict=True):
            h = item["hourly"]
            rows += [(code, t, v) for t, v in zip(h["time"], h["precipitation"], strict=True) if v is not None]
        log(f"nwp chunk {d:%Y-%m-%d}..{e:%Y-%m-%d} rows={len(rows)}")
        d = e + timedelta(days=1)
    df = pd.DataFrame(rows, columns=["code", "time", "nwp_mm"])
    df["time"] = pd.to_datetime(df["time"])
    CACHE.parent.mkdir(exist_ok=True)
    df.to_csv(CACHE, index=False, encoding="utf-8")
    return df


def main():
    import keras
    from keras import layers

    from app.ai.evaluation.metrics import classification_metrics, roc_auc
    from app.ai.forecasting.model import build_model
    from app.ai.forecasting.preprocessing import (FEATURES, HORIZON, LOOKBACK, Scaler, apply_scaler,
                                                  chronological_split, clean_station_frame)
    from app.ai.forecasting.train import HEAVY_RAIN_MM, baseline_predictions, evaluate_rain, load_frames_from_db
    from app.core.database import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:  # chỉ SELECT
        frames, _ = load_frames_from_db(db)
        stn = {r[0]: (r[1], r[2], r[3]) for r in db.execute(text(
            "select code,latitude,longitude,area_id from monitoring_stations where deleted_at is null and station_type='RAIN'"))}
        events = db.execute(text(
            "select e.id,e.area_id,e.started_at,e.cause from historical_flood_events e "
            "where e.cause in ('RAIN','RAIN_TIDE') and e.area_id is not null")).all()
    cleaned = {c: clean_station_frame(df, thr) for c, (df, thr) in frames.items() if len(df) > 200}
    codes = sorted(cleaned)
    log("stations", len(codes))
    start = min(df.index.min() for df in cleaned.values())
    end = max(df.index.max() for df in cleaned.values())
    nwp_long = fetch_nwp([(c, stn[c][0], stn[c][1]) for c in codes], start, end)
    nwp = {c: g.drop_duplicates("time").set_index("time")["nwp_mm"] for c, g in nwp_long.groupby("code")}

    splits = {c: chronological_split(cleaned[c]) for c in codes}
    sc = Scaler.fit([s[0] for s in splits.values()])
    parts = {k: [] for k in ("train", "val", "test")}
    dropped = {k: 0 for k in parts}
    total = {k: 0 for k in parts}
    for c in codes:
        for name, seg in zip(("train", "val", "test"), splits[c], strict=True):
            n = len(seg) - LOOKBACK - HORIZON + 1
            if n <= 0:
                continue
            x = apply_scaler(seg, sc)
            idx = np.arange(n)[:, None]
            X = x[idx + np.arange(LOOKBACK)]
            tgt = idx + LOOKBACK + np.arange(HORIZON)
            yr = seg["rain_mm"].to_numpy(np.float32)[tgt]
            nw = nwp[c].reindex(seg.index).to_numpy(np.float32)[tgt]
            ok = ~np.isnan(nw).any(1)
            total[name] += n
            dropped[name] += int((~ok).sum())
            parts[name].append((X[ok], yr[ok], nw[ok]))
    D = {k: tuple(np.concatenate([p[i] for p in v]) for i in range(3)) for k, v in parts.items()}
    (Xtr, rtr, ntr), (Xva, rva, nva), (Xte, rte, nte) = D["train"], D["val"], D["test"]
    log(f"windows train={len(Xtr)} val={len(Xva)} test={len(Xte)} dropped(no NWP)={dropped} of {total}")

    for k in D:
        assert not np.isnan(D[k][2]).any() and not np.isnan(D[k][1]).any(), f"NaN in {k}"
    ltr = np.log1p(ntr)
    am, asd = float(ltr.mean()), float(ltr.std() + 1e-6)  # chỉ train
    aux = {k: ((np.log1p(D[k][2]) - am) / asd).astype(np.float32) for k in D}

    def build_nwp_model(units=48, dropout=0.1):
        h = layers.Input(shape=(LOOKBACK, len(FEATURES)), name="history")
        a = layers.Input(shape=(HORIZON,), name="nwp")
        x = layers.GRU(units, return_sequences=True, dropout=dropout)(h)
        x = layers.GRU(units // 2, dropout=dropout)(x)
        x = layers.Concatenate()([x, a])
        x = layers.Dense(64, activation="relu")(x)
        out = layers.Dense(HORIZON, activation="softplus", name="rain")(x)
        m = keras.Model([h, a], out, name="gru_nwp")
        m.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse")
        return m

    def fit(model, tr_in, va_in, te_in):
        keras.utils.set_random_seed(SEED)
        hist = model.fit(tr_in, np.log1p(rtr), validation_data=(va_in, np.log1p(rva)), epochs=EPOCHS,
                         batch_size=BATCH, verbose=0,
                         callbacks=[keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True)])
        pv = np.expm1(model.predict(va_in, verbose=0, batch_size=1024)).reshape(-1, HORIZON)
        pt = np.expm1(model.predict(te_in, verbose=0, batch_size=1024)).reshape(-1, HORIZON)
        return pv, pt, len(hist.history["loss"]), float(min(hist.history["val_loss"]))

    keras.utils.set_random_seed(SEED)
    ma = build_model("gru", heads=("rain",))
    pva, pta, ea, vla = fit(ma, Xtr, Xva, Xte)
    log("a done", ea, vla)
    keras.utils.set_random_seed(SEED)
    mb = build_nwp_model()
    pvb, ptb, eb, vlb = fit(mb, [Xtr, aux["train"]], [Xva, aux["val"]], [Xte, aux["test"]])
    log("b done", eb, vlb)

    b_pers, _, _ = baseline_predictions(Xte, sc)
    res = {}
    for name, pv, pt, ep, vl in (("a_gru_history", pva, pta, ea, vla), ("b_gru_nwp", pvb, ptb, eb, vlb),
                                 ("c_nwp_alone", nva, nte, None, None), ("d_persistence", None, b_pers, None, None)):
        m = evaluate_rain(pt, rte, pv, rva)
        # ROC-AUC thật trên mm dự báo liên tục (evaluate_rain chỉ cho AUC của quyết định nhị phân)
        m["heavy_rain"]["roc_auc_continuous"] = roc_auc((rte >= HEAVY_RAIN_MM).ravel().astype(int), pt.ravel())
        if ep:
            m["epochs_run"], m["val_loss"] = ep, vl
        res[name] = m
        hr = m["heavy_rain"]
        log(f"{name}: MAE={m['rainfall']['mae']:.3f} RMSE={m['rainfall']['rmse']:.3f} P={hr['precision']:.3f} "
            f"R={hr['recall']:.3f} F1={hr['f1']:.3f} AUC={hr['roc_auc_continuous']} thr={hr['decision_mm']}")

    # ---- Kiểm tra độc lập với tin báo chí (ngày VN, tổng 3 giờ lớn nhất) ----
    area_code = {stn[c][2]: c for c in codes}
    obs_s = {c: cleaned[c]["rain_mm"] for c in codes}
    evrows, seen = [], set()
    for _, area, st, cause in events:
        c = area_code.get(area)
        if c is None:
            continue
        vn = pd.Timestamp(st) + pd.Timedelta(hours=7)
        day = vn.normalize()
        if (c, day) in seen:
            continue
        seen.add((c, day))
        lo, hi = day - pd.Timedelta(hours=7), day + pd.Timedelta(hours=17)  # UTC của ngày VN

        def m3(s):
            w = s.reindex(pd.date_range(lo, hi - pd.Timedelta(hours=1), freq="h"))
            return None if w.isna().all() else float(w.fillna(0).rolling(3).sum().max())
        evrows.append({"station": c, "vn_date": str(day.date()), "cause": cause,
                       "obs_max3h": m3(obs_s[c]), "nwp_max3h": m3(nwp[c])})
    ev = pd.DataFrame(evrows)
    if len(ev):
        log(ev.to_string())
    cnt = {}
    for thr in (20.0, 33.3):
        cnt[str(thr)] = {"n_district_days": len(ev), "reanalysis": int((ev["obs_max3h"] >= thr).sum()),
                         "nwp": int((ev["nwp_max3h"] >= thr).sum()),
                         "nwp_only": int(((ev["nwp_max3h"] >= thr) & ~(ev["obs_max3h"] >= thr)).sum()),
                         "obs_only": int((~(ev["nwp_max3h"] >= thr) & (ev["obs_max3h"] >= thr)).sum())}
    log(json.dumps(cnt))
    OUT.write_text(json.dumps({"windows": {"train": len(Xtr), "val": len(Xva), "test": len(Xte),
                                           "dropped_no_nwp": dropped, "total_before_drop": total},
                               "heavy_rain_mm": HEAVY_RAIN_MM, "models": res, "events": evrows,
                               "event_counts": cnt}, indent=2, default=str), encoding="utf-8")
    log("saved", OUT)


if __name__ == "__main__":
    sys.exit(main())
