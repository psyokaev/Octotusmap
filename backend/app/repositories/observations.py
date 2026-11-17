from datetime import datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import RainfallObservation as R
from app.models import WaterLevelObservation as W


def latest_values(db: Session, station_ids: list[int] | None = None, as_of: datetime | None = None) -> dict[int, dict]:
    """{station_id: {rain, rain_at, wl, wl_at}} — bản ghi hợp lệ mới nhất (tính đến as_of nếu có)."""
    out: dict[int, dict] = {}
    for model, col, key in ((R, R.rainfall_mm, "rain"), (W, W.water_level_cm, "wl")):
        sub = (select(model.station_id, func.max(model.observed_at).label("t"))
               .where(model.quality_flag == "VALID").group_by(model.station_id))
        if station_ids is not None:
            sub = sub.where(model.station_id.in_(station_ids))
        if as_of is not None:
            sub = sub.where(model.observed_at <= as_of)
        sub = sub.subquery()
        rows = db.execute(select(model.station_id, model.observed_at, col)
                          .join(sub, (model.station_id == sub.c.station_id) & (model.observed_at == sub.c.t))).all()
        for sid, t, v in rows:
            out.setdefault(sid, {})[key] = v
            out[sid][f"{key}_at"] = t
    return out


def series(db: Session, station_id: int, start: datetime, end: datetime) -> pd.DataFrame:
    """Chuỗi giờ (time, rain_mm, water_level_cm, rain_q, wl_q, sim) — loại bản ghi SUSPECT khỏi giá trị."""
    r = db.execute(select(R.observed_at, R.rainfall_mm, R.quality_flag, R.is_simulated)
                   .where(R.station_id == station_id, R.observed_at >= start, R.observed_at <= end)).all()
    w = db.execute(select(W.observed_at, W.water_level_cm, W.quality_flag, W.is_simulated)
                   .where(W.station_id == station_id, W.observed_at >= start, W.observed_at <= end)).all()
    dr = pd.DataFrame(r, columns=["time", "rain_mm", "rain_q", "sim_r"])
    dw = pd.DataFrame(w, columns=["time", "water_level_cm", "wl_q", "sim_w"])
    df = dr.merge(dw, on="time", how="outer").sort_values("time").reset_index(drop=True)
    df.loc[df["rain_q"] == "SUSPECT", "rain_mm"] = None
    df.loc[df["wl_q"] == "SUSPECT", "water_level_cm"] = None
    df["sim"] = df["sim_r"].fillna(False).astype(bool) | df["sim_w"].fillna(False).astype(bool)
    return df.drop(columns=["sim_r", "sim_w"])


def latest_time(db: Session) -> datetime | None:
    return db.scalar(select(func.max(W.observed_at)))
