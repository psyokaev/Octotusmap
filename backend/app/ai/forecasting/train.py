"""Huấn luyện & đánh giá mô hình dự báo mưa / mực nước / xác suất ngập 1-6h.

Chạy:  python -m app.ai.forecasting.train --models lstm gru --epochs 8
Quy trình: load -> validate -> làm sạch/missing -> chia theo thời gian -> scaler (fit train)
-> sliding windows -> baseline -> LSTM/GRU -> đánh giá test -> lưu artifact + metadata -> đăng ký DB.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.ai.evaluation.metrics import best_f1_threshold, classification_metrics, regression_metrics
from app.ai.forecasting.preprocessing import (
    FEATURES,
    HORIZON,
    LOOKBACK,
    Scaler,
    chronological_split,
    clean_station_frame,
    make_windows,
)


def build_datasets(frames: dict[str, tuple[pd.DataFrame, float]]):
    """frames: {station_code: (df[time, rain_mm, water_level_cm], threshold_cm)}"""
    cleaned = {c: clean_station_frame(df, thr) for c, (df, thr) in frames.items() if len(df) > 200}
    splits = {c: chronological_split(df) for c, df in cleaned.items()}
    scaler = Scaler.fit([s[0] for s in splits.values()])  # chỉ tập train
    parts: dict[str, list] = {"train": [], "val": [], "test": []}
    boundaries = {}
    for code, (tr, va, te) in splits.items():
        boundaries[code] = (str(tr.index.max()), str(va.index.min()), str(te.index.min()))
        for name, seg in zip(("train", "val", "test"), (tr, va, te), strict=True):
            X, yr, yw, yf, _ = make_windows(seg, scaler)
            parts[name].append((X, yr, yw, yf))
    data = {k: tuple(np.concatenate([p[i] for p in v]) for i in range(4)) for k, v in parts.items()}
    return data, scaler, boundaries


def baseline_predictions(X: np.ndarray, sc: Scaler):
    """Persistence: mưa & mực nước 6h tới = giá trị giờ cuối; ngập = đang ngập."""
    last = X[:, -1, :]
    rain_last = np.expm1(last[:, 0] * sc.rain_std + sc.rain_mean)
    wl_last = last[:, 1] * sc.wl_std + sc.wl_mean
    rain = np.repeat(rain_last[:, None], HORIZON, 1)
    wl = np.repeat(wl_last[:, None], HORIZON, 1)
    return rain, wl, (wl > 0).astype(float)


def evaluate_rain(pred_rain, y_rain, pred_val, rva) -> dict:
    """Hồi quy mưa + phát hiện mưa to (ngưỡng quyết định chọn trên validation nếu có)."""
    thr = HEAVY_RAIN_MM
    if pred_val is not None:
        cands = np.linspace(1.0, 8.0, 15)
        thr = float(max(cands, key=lambda t: classification_metrics(rva >= HEAVY_RAIN_MM, pred_val >= t)["f1"]))
    return {"rainfall": regression_metrics(y_rain, pred_rain),
            "heavy_rain": {**classification_metrics(y_rain >= HEAVY_RAIN_MM, pred_rain >= thr),
                           "event_mm": HEAVY_RAIN_MM, "decision_mm": thr},
            "n_samples": len(y_rain)}


def evaluate(pred_rain, pred_wl, prob, y_rain, y_wl, y_flood, threshold) -> dict:
    return {
        "rainfall": regression_metrics(y_rain, pred_rain),
        "water_level": regression_metrics(y_wl, pred_wl),
        "flood": classification_metrics(y_flood, prob, threshold),
        "n_samples": len(y_rain),
    }


HEAVY_RAIN_MM = 5.0  # ngưỡng "mưa to" theo giờ để đánh giá khả năng phát hiện


def _as_dict(model, X, heads):
    out = model.predict(X, verbose=0, batch_size=1024)
    return dict(zip(heads, out if len(heads) > 1 else [out], strict=True))


def train_models(frames, out_dir: Path, cells=("lstm", "gru"), epochs=8, batch=256, seed=42, log=print,
                 heads=("rain", "wl", "flood")):
    import keras

    keras.utils.set_random_seed(seed)
    from app.ai.forecasting.model import build_model

    data, sc, boundaries = build_datasets(frames)
    Xtr, rtr, wtr, ftr = data["train"]
    Xva, rva, wva, fva = data["val"]
    Xte, rte, wte, fte = data["test"]
    log(f"windows train={len(Xtr)} val={len(Xva)} test={len(Xte)} flood_rate_train={ftr.mean():.4f}")

    b_rain, b_wl, b_flood = baseline_predictions(Xte, sc)
    results = {"baseline_persistence": evaluate(b_rain, b_wl, b_flood, rte, wte, fte, 0.5)}
    rain_only = "flood" not in heads
    if rain_only:
        clim = np.full_like(rte, float(rtr.mean()))
        results = {"baseline_persistence": evaluate_rain(b_rain, rte, None, rva=None),
                   "baseline_climatology": evaluate_rain(clim, rte, None, rva=None)}
    trained = {}
    for cell in cells:
        t0 = time.time()
        model = build_model(cell, heads=heads)
        def y(r, w, f):
            d = {"rain": np.log1p(r), "wl": (w - sc.wl_mean) / sc.wl_std, "flood": f}
            return d[heads[0]] if len(heads) == 1 else {k: d[k] for k in heads}  # Keras: 1 đầu ra nhận mảng
        hist = model.fit(
            Xtr, y(rtr, wtr, ftr), validation_data=(Xva, y(rva, wva, fva)),
            epochs=epochs, batch_size=batch, verbose=0,
            callbacks=[keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True)],
        )
        secs = time.time() - t0
        pva, pte = _as_dict(model, Xva, heads), _as_dict(model, Xte, heads)
        if rain_only:
            thr = None
            metrics = evaluate_rain(np.expm1(pte["rain"]), rte, np.expm1(pva["rain"]), rva)
        else:
            thr = best_f1_threshold(fva, pva["flood"])  # chọn ngưỡng trên validation
            metrics = evaluate(np.expm1(pte["rain"]), pte["wl"] * sc.wl_std + sc.wl_mean, pte["flood"], rte, wte,
                               fte, thr)
        metrics["val_loss"] = float(min(hist.history["val_loss"]))
        metrics["epochs_run"] = len(hist.history["loss"])
        results[cell] = metrics
        trained[cell] = (model, thr, secs, metrics)
        f1 = metrics["heavy_rain" if rain_only else "flood"]["f1"]
        log(f"{cell}: val_loss={metrics['val_loss']:.4f} rain_MAE={metrics['rainfall']['mae']:.3f} "
            f"F1={f1:.3f} ({secs:.1f}s)")

    version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    saved = []
    for cell, (model, thr, secs, metrics) in trained.items():
        d = out_dir / "forecast" / f"{cell}-{version}"
        d.mkdir(parents=True, exist_ok=True)
        model.save(d / "model.keras")
        sc.save(d / "scaler.json")
        meta = {
            "cell": cell, "version": version, "lookback": LOOKBACK, "horizon": HORIZON,
            "features": FEATURES, "flood_threshold": thr, "metrics": metrics,
            "baseline": results["baseline_persistence"], "split_boundaries": boundaries, "heads": list(heads),
            "epochs": epochs, "seed": seed, "training_seconds": secs,
        }
        (d / "metadata.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        saved.append({"cell": cell, "dir": d, "metrics": metrics, "threshold": thr, "seconds": secs,
                      "params": {"epochs": epochs, "batch": batch, "seed": seed, "units": 48,
                                 "lookback": LOOKBACK, "horizon": HORIZON}})
    return {"version": version, "results": results, "saved": saved}


def load_frames_from_db(db, min_rows: int = 200):
    from sqlalchemy import select

    from app.models import MonitoringStation, RainfallObservation, WaterLevelObservation

    frames, simulated = {}, False
    from app.services.openmeteo_service import TIDE_CODE

    tide_st = db.scalar(select(MonitoringStation).where(MonitoringStation.code == TIDE_CODE))
    tide = (db.execute(select(WaterLevelObservation.observed_at, WaterLevelObservation.water_level_cm)
                       .where(WaterLevelObservation.station_id == tide_st.id)).all() if tide_st else [])
    tide_p95 = float(np.percentile([t[1] for t in tide], 95)) if tide else None
    for st in db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None))):
        r = db.execute(select(RainfallObservation.observed_at, RainfallObservation.rainfall_mm,
                              RainfallObservation.is_simulated)
                       .where(RainfallObservation.station_id == st.id)
                       .where(RainfallObservation.quality_flag != "SUSPECT")).all()
        w = db.execute(select(WaterLevelObservation.observed_at, WaterLevelObservation.water_level_cm)
                       .where(WaterLevelObservation.station_id == st.id)
                       .where(WaterLevelObservation.quality_flag != "SUSPECT")).all()
        threshold = st.flood_threshold_cm
        if len(w) < min_rows and tide and st.station_type == "RAIN":
            w, threshold = tide, tide_p95  # điểm lưới mưa: dùng triều chung (tương đối với mức triều cường P95)
        if len(r) < min_rows or len(w) < min_rows:
            continue
        simulated |= any(x[2] for x in r)
        df = pd.DataFrame(r, columns=["time", "rain_mm", "sim"]).drop(columns="sim").merge(
            pd.DataFrame(w, columns=["time", "water_level_cm"]), on="time", how="outer").sort_values("time")
        frames[st.code] = (df, threshold)
    return frames, simulated


def train_and_register(db, cells=("lstm", "gru"), epochs=8, log=print) -> dict:
    """Huấn luyện từ dữ liệu trong CSDL, đăng ký model_versions/training_runs, kích hoạt mô hình tốt nhất."""
    from app.core.config import get_settings
    from app.core.database import utcnow
    from app.models import ModelVersion, TrainingRun

    frames, simulated = load_frames_from_db(db)
    if not frames:
        raise RuntimeError("Không đủ dữ liệu quan trắc để huấn luyện")
    run = TrainingRun(task="FORECAST", params={"cells": list(cells), "epochs": epochs})
    db.add(run)
    db.commit()
    try:
        heads = ("rain", "wl", "flood") if simulated else ("rain",)  # dữ liệu thật chưa có nhãn ngập
        res = train_models(frames, get_settings().artifacts_dir, cells, epochs, log=log, heads=heads)
    except Exception as e:
        run.status, run.finished_at, run.log = "FAILED", utcnow(), repr(e)
        db.commit()
        raise
    desc = (f"{len(frames)} trạm, dữ liệu {'MÔ PHỎNG (SIMULATED)' if simulated else 'thật Open-Meteo (mưa giờ tái phân tích, triều Marine)'}; "
            "chia train/val/test 70/15/15 theo thời gian")
    best = min(res["saved"], key=lambda s: s["metrics"]["val_loss"])
    db.add(ModelVersion(
        name="baseline-persistence", model_type="BASELINE", version=res["version"],
        dataset_description=desc, trained_on_simulated=simulated,
        metrics=res["results"]["baseline_persistence"], status="TRAINED", trained_at=utcnow(),
        params={"baselines": res["results"]}))
    for s in res["saved"]:
        is_best = s is best
        if is_best:
            db.query(ModelVersion).filter(ModelVersion.model_type.in_(["LSTM", "GRU"])).update(
                {"is_active": False, "status": "ARCHIVED"})
        mv = ModelVersion(
            name=f"flood-{s['cell']}", model_type=s["cell"].upper(), version=res["version"],
            artifact_path=str(s["dir"]), dataset_description=desc, trained_on_simulated=simulated,
            metrics=s["metrics"], params={**s["params"], "flood_threshold": s["threshold"]},
            status="DEPLOYED" if is_best else "TRAINED", is_active=is_best,
            trained_at=utcnow(), training_seconds=s["seconds"])
        db.add(mv)
        db.flush()
        if is_best:
            run.model_version_id = mv.id
    run.status, run.finished_at, run.metrics = "SUCCESS", utcnow(), res["results"]
    db.commit()
    return res


FINETUNE_LR = 1e-4


def _fit_eval(base_dir: str, frames, epochs: int, batch: int = 256):
    """Tinh chỉnh bản sao của mô hình gốc trên `frames`; trả (model, val của gốc, val sau tinh chỉnh)."""
    import keras

    from app.ai.forecasting.inference import load

    base = load(base_dir)
    heads, sc = base.heads, base.scaler
    parts = {"train": [], "val": []}
    for df, thr in frames.values():
        tr, va, _ = chronological_split(clean_station_frame(df, thr))
        for k, seg in (("train", tr), ("val", va)):
            parts[k].append(make_windows(seg, sc)[:4])

    def stack(k):
        X, r, w, f = (np.concatenate([p[i] for p in parts[k]]) for i in range(4))
        d = {"rain": np.log1p(r), "wl": (w - sc.wl_mean) / sc.wl_std, "flood": f}
        return X, (d[heads[0]] if len(heads) == 1 else {h: d[h] for h in heads}), r

    Xtr, ytr, _ = stack("train")
    Xva, yva, rva = stack("val")

    def score(m):
        loss = m.evaluate(Xva, yva, verbose=0, batch_size=1024)
        loss = float(loss[0] if isinstance(loss, list) else loss)
        pr = np.expm1(_as_dict(m, Xva, heads)["rain"])
        return {"val_loss": loss, "rain_mae": float(np.mean(np.abs(pr - rva))), "n_val": len(Xva)}

    model = keras.models.load_model(Path(base_dir) / "model.keras")  # bản sao riêng, không đụng cache suy luận
    model.optimizer.learning_rate.assign(FINETUNE_LR)
    base_score = score(model)
    model.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=epochs, batch_size=batch, verbose=0,
              callbacks=[keras.callbacks.EarlyStopping(patience=2, restore_best_weights=True)])
    return model, base_score, score(model)


def _cluster_of_codes(db) -> dict[str, str]:
    from sqlalchemy import select

    from app.models import MonitoringStation
    from app.services import forecast_service as fs
    from app.services import gis_service

    areas = gis_service.area_geometries(db)
    return {c: fs._cluster(areas, a) for c, a in db.execute(
        select(MonitoringStation.code, MonitoringStation.area_id)).all()}


def finetune_clusters(db, epochs: int = 2, log=print) -> dict:
    """Tinh chỉnh mô hình gốc đang hoạt động theo từng cụm (CORE/INNER/SUBURBAN); chỉ giữ bản tốt hơn trên validation.
    Tinh chỉnh dần: chạy lại lệnh này (CLI/huấn luyện admin) khi dữ liệu tích lũy thêm; không có bộ lập lịch."""
    import shutil

    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.database import utcnow
    from app.models import ModelVersion, TrainingRun
    from app.services import forecast_service as fs

    base = fs.active_model(db)
    if not base:
        raise RuntimeError("Chưa có mô hình gốc đang hoạt động")
    frames, simulated = load_frames_from_db(db)
    cluster_of = _cluster_of_codes(db)
    run = TrainingRun(task="FORECAST", params={"finetune_clusters": True, "epochs": epochs, "base_model_id": base.id})
    db.add(run)
    db.commit()
    version, out, results = datetime.now(UTC).strftime("%Y%m%d%H%M%S"), [], {}
    try:
        for cluster in sorted({c for c in cluster_of.values() if c}):
            sub = {c: f for c, f in frames.items() if cluster_of.get(c) == cluster}
            if not sub:
                continue
            t0 = time.time()
            model, b, n = _fit_eval(base.artifact_path, sub, epochs)
            kept = n["val_loss"] < b["val_loss"]
            results[cluster] = {"base": b, "finetuned": n, "kept": kept, "stations": len(sub)}
            log(f"{cluster}: val_loss base={b['val_loss']:.4f} ft={n['val_loss']:.4f} "
                f"rain_MAE base={b['rain_mae']:.3f} ft={n['rain_mae']:.3f} kept={kept}")
            if not kept:
                continue
            d = get_settings().artifacts_dir / "forecast" / f"{base.model_type.lower()}-{cluster}-{version}"
            d.mkdir(parents=True, exist_ok=True)
            model.save(d / "model.keras")
            src = Path(base.artifact_path)
            shutil.copy(src / "scaler.json", d / "scaler.json")  # scaler của mô hình gốc
            meta = json.loads((src / "metadata.json").read_text(encoding="utf-8"))
            (d / "metadata.json").write_text(json.dumps({**meta, "cluster": cluster, "base_model_id": base.id,
                                                         "metrics": results[cluster]}, indent=2), encoding="utf-8")
            out.append((cluster, d, results[cluster], time.time() - t0))
        for cluster, d, r, secs in out:
            for old in db.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True),
                                                             ModelVersion.model_type == f"{base.model_type}_CLUSTER")):
                if (old.params or {}).get("cluster") == cluster:
                    old.is_active, old.status = False, "ARCHIVED"
            db.add(ModelVersion(
                name=f"flood-{base.model_type.lower()}-{cluster}", model_type=f"{base.model_type}_CLUSTER",
                version=version, artifact_path=str(d), trained_on_simulated=simulated, metrics=r,
                dataset_description=f"Tinh chỉnh từ mô hình {base.name}:{base.version} trên các trạm cụm {cluster}",
                params={"cluster": cluster, "base_model_id": base.id, "epochs": epochs, "learning_rate": FINETUNE_LR,
                        "flood_threshold": base.params.get("flood_threshold") if base.params else None},
                status="DEPLOYED", is_active=True, trained_at=utcnow(), training_seconds=secs))
        run.status, run.finished_at, run.metrics = "SUCCESS", utcnow(), results
        db.commit()
    except Exception as e:
        db.rollback()
        run.status, run.finished_at, run.log = "FAILED", utcnow(), repr(e)
        db.commit()
        raise
    return results


if __name__ == "__main__":
    from app.core.database import SessionLocal

    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["lstm", "gru"])
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--finetune-clusters", action="store_true")
    a = ap.parse_args()
    with SessionLocal() as s:
        if a.finetune_clusters:
            print(json.dumps(finetune_clusters(s, a.epochs), indent=2))
            raise SystemExit
        out = train_and_register(s, tuple(a.models), a.epochs)
    print(json.dumps({k: {"f1": v.get("flood", v.get("heavy_rain"))["f1"], "rain_mae": v["rainfall"]["mae"]}
                      for k, v in out["results"].items()}, indent=2))
