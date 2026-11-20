"""So sánh mưa vệ tinh GPM IMERG (đo) với Open-Meteo (mô hình) theo quận-ngày, nhất là ngày có ngập do mưa.

Ngày theo UTC (như IMERG). Open-Meteo: tổng mưa giờ của điểm lưới quận trong ngày UTC đó.
Chạy: PYTHONUTF8=1 .venv/Scripts/python scripts/compare_imerg_openmeteo.py [--out FILE]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

Q = """
WITH om AS (
  SELECT COALESCE(a.parent_id, a.id) AS area_id, date(r.observed_at) AS day, sum(r.rainfall_mm) AS om_mm
  FROM rainfall_observations r JOIN monitoring_stations s ON s.id = r.station_id
  JOIN administrative_areas a ON a.id = s.area_id
  WHERE s.code LIKE 'OM-%' AND s.code <> 'OM-TIDE-VT' AND r.quality_flag <> 'SUSPECT'
  GROUP BY 1, 2 HAVING count(*) >= 20)
SELECT i.area_id, i.day, i.rain_mm AS imerg_mm, om.om_mm FROM satellite_rainfall_daily i
JOIN om ON om.area_id = i.area_id AND om.day = i.day
"""
EV = """
SELECT DISTINCT COALESCE(a.parent_id, a.id) AS area_id, date(e.started_at) AS day
FROM historical_flood_events e JOIN administrative_areas a ON a.id = e.area_id
WHERE e.is_simulated = false AND e.cause IN ('RAIN', 'RAIN_TIDE')
"""


def stats(d: pd.DataFrame) -> dict:
    return {"n": len(d), "pearson_r": round(float(np.corrcoef(d.imerg_mm, d.om_mm)[0, 1]), 3) if len(d) > 2 else None,
            "imerg_mean_mm": round(float(d.imerg_mm.mean()), 2), "om_mean_mm": round(float(d.om_mm.mean()), 2),
            "imerg_median_mm": round(float(d.imerg_mm.median()), 2), "om_median_mm": round(float(d.om_mm.median()), 2),
            **{f"share_ge_{t}mm": {"imerg": round(float((d.imerg_mm >= t).mean()), 3),
                                   "om": round(float((d.om_mm >= t).mean()), 3)} for t in (20, 50)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    with SessionLocal() as db:
        d = pd.DataFrame(db.execute(text(Q)).all(), columns=["area_id", "day", "imerg_mm", "om_mm"])
        ev = {(r[0], r[1]) for r in db.execute(text(EV)).all()}
    d["event"] = [(x, y) in ev for x, y in zip(d.area_id, d.day, strict=True)]
    res = {"all_district_days": stats(d), "rain_flood_district_days": stats(d[d.event]),
           "days": [str(d.day.min()), str(d.day.max())]}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
