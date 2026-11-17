"""THÍ NGHIỆM cô lập: tín hiệu Open-Meteo miễn phí nào bắt được ngập do mưa cục bộ? Không ghi DB, không đổi production.

So sánh theo đơn vị quận-ngày (ngày giờ VN) với tin ngập báo chí (historical_flood_events, cause RAIN/RAIN_TIDE):
  - best_match: CAPE, lifted_index, convective_inhibition, precipitation_probability, showers
  - MAX mưa 3 giờ trên nhiều model (ecmwf_ifs025, gfs_seamless, icon_seamless, jma_seamless, cma_grapes_global,
    ukmo_seamless, meteofrance_seamless)
  - MAX mưa 3 giờ best_match trên lưới 3x3 (±0,1°) quanh điểm quận
Nguồn: historical-forecast-api (ghép giờ đầu của mỗi lần chạy model: dự báo hạn rất ngắn, gần với phân tích,
KHÔNG phải bản dự báo phát trước 3 giờ). Nhãn âm là giả định (không có tin = không ngập).
Cache ở thư mục tham số 1 (mặc định thư mục tạm hệ thống), không ghi storage/.

Chạy: cd backend; $env:PYTHONUTF8="1"; $env:PYTHONPATH="."
      .venv\\Scripts\\python scripts\\experiment_convective.py [cache_dir]
"""

import json
import sys
import tempfile
import time
from datetime import timedelta
from itertools import product
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path(sys.argv[1] if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "octotusmap_convective")
HIST_FC = "https://historical-forecast-api.open-meteo.com/v1/forecast"
START, END = pd.Timestamp("2024-11-04"), pd.Timestamp("2026-11-10")
CHUNK_DAYS, PAUSE_S = 90, 15
BM_VARS = ["precipitation", "showers", "precipitation_probability", "cape", "lifted_index", "convective_inhibition"]
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "jma_seamless", "cma_grapes_global", "ukmo_seamless",
          "meteofrance_seamless"]
OFFS = (-0.1, 0.0, 0.1)
VN = pd.Timedelta(hours=7)
DRY = {12, 1, 2, 3, 4}


def log(*a):
    print(*a, flush=True)


def fetch(kind: str, points: list[tuple[str, float, float]], hourly: list[str], models: list[str] | None = None):
    """Dạng dài: key,time,<cột>. Mỗi khúc 90 ngày một request gộp mọi điểm, cache từng khúc."""
    from app.services.openmeteo_service import _get

    CACHE.mkdir(parents=True, exist_ok=True)
    out, d = [], START
    while d <= END:
        e = min(d + timedelta(days=CHUNK_DAYS - 1), END)
        f = CACHE / f"{kind}_{d:%Y%m%d}_{e:%Y%m%d}.csv"
        if not f.exists():
            params = {"latitude": ",".join(f"{p[1]:.4f}" for p in points),
                      "longitude": ",".join(f"{p[2]:.4f}" for p in points),
                      "hourly": ",".join(hourly), "timezone": "GMT",
                      "start_date": f"{d:%Y-%m-%d}", "end_date": f"{e:%Y-%m-%d}"} | (
                {"models": ",".join(models)} if models else {})
            for i in range(6):
                try:
                    data = _get(HIST_FC, params, timeout=180)
                    break
                except httpx.HTTPStatusError as ex:  # 429: hết hạn mức phút/giờ, chờ rồi thử lại
                    if ex.response.status_code != 429 or i == 5:
                        raise
                    log("429:", ex.response.text[:120], "-> chờ 70 s")
                    time.sleep(70)
            data = data if isinstance(data, list) else [data]
            frames = []
            for (key, _, _), item in zip(points, data, strict=True):
                h = pd.DataFrame(item["hourly"])
                h.insert(0, "key", key)
                frames.append(h)
            pd.concat(frames).to_csv(f, index=False, encoding="utf-8")
            log(f"{kind} {d:%Y-%m-%d}..{e:%Y-%m-%d} tải xong")
            time.sleep(PAUSE_S)
        out.append(pd.read_csv(f, encoding="utf-8"))
        d = e + timedelta(days=1)
    df = pd.concat(out)
    df["time"] = pd.to_datetime(df["time"])
    return df


def day_set(mask: pd.Series) -> set:
    """mask: MultiIndex (code, time UTC) -> tập (code, ngày VN) có ít nhất một giờ True."""
    m = mask[mask.fillna(False).astype(bool)]
    return {(c, (t + VN).date()) for c, t in m.index}


def main():
    from sqlalchemy import text

    from app.core.database import SessionLocal

    with SessionLocal() as db:  # chỉ SELECT
        stn = db.execute(text("select s.code,s.latitude,s.longitude,s.area_id from monitoring_stations s "
                              "where s.deleted_at is null and s.station_type='RAIN' order by 1")).all()
        events = db.execute(text("select e.area_id,e.started_at,e.cause from historical_flood_events e "
                                 "where not e.is_simulated and e.cause in ('RAIN','RAIN_TIDE')")).all()
        obs = pd.DataFrame(db.execute(text(
            "select s.code, o.observed_at as time, o.rainfall_mm as obs from rainfall_observations o "
            "join monitoring_stations s on s.id=o.station_id where not o.is_simulated and o.quality_flag='VALID' "
            "and s.station_type='RAIN' and s.deleted_at is null")).all(), columns=["code", "time", "obs"])
    code_of = {a: c for c, _, _, a in stn}
    pts = [(c, la, lo) for c, la, lo, _ in stn]
    assert len(pts) == 24, len(pts)

    bm = fetch("bm", pts, BM_VARS).rename(columns={"key": "code"}).set_index(["code", "time"]).sort_index()
    mm = fetch("models", pts, ["precipitation"], MODELS).rename(columns={"key": "code"}).set_index(
        ["code", "time"]).sort_index()
    grid = [(f"{c}|{i}|{j}", la + dy, lo + dx) for (c, la, lo), (i, dy), (j, dx)
            in product(pts, enumerate(OFFS), enumerate(OFFS))]
    nb = pd.concat([fetch(f"grid3x3b{b}", grid[b * 24:(b + 1) * 24], ["precipitation"]) for b in range(9)])
    nb["code"] = nb["key"].str.split("|").str[0]

    def roll3(s: pd.Series, how="sum") -> pd.Series:
        """s: MultiIndex (key, time) -> cửa sổ 3 giờ kết thúc tại time, cùng MultiIndex."""
        w = s.unstack(0).asfreq("h")
        return getattr(w.rolling(3, min_periods=1), how)().stack().swaplevel().sort_index()

    p3 = roll3(bm["precipitation"])
    sh3 = roll3(bm["showers"])
    prob3 = roll3(bm["precipitation_probability"], "max")
    cape3 = roll3(bm["cape"], "max")
    li3 = roll3(bm["lifted_index"], "min")
    cin3 = roll3(bm["convective_inhibition"], "min")
    mcols = [f"precipitation_{m}" for m in MODELS]
    m3 = pd.concat({m: roll3(mm[f"precipitation_{m}"]) for m in MODELS}, axis=1)
    mmax3 = m3.max(axis=1)
    nb3 = roll3(nb.set_index(["key", "time"])["precipitation"])
    nb3 = nb3.groupby([nb3.index.get_level_values(0).str.split("|").str[0], nb3.index.get_level_values(1)]).max()
    o = obs.assign(time=pd.to_datetime(obs["time"])).groupby(["code", "time"])["obs"].max()
    o3 = roll3(o)
    log("models non-null giờ:", {c: int(mm[c].notna().sum()) for c in mcols})

    rules = {}
    for t in (20, 33.3):
        rules[f"DB mưa (best_match archive) P3h>={t}"] = o3 >= t
    for t in (5, 10, 20):
        rules[f"best_match historical-fc P3h>={t}"] = p3 >= t
    for t in (1, 3, 5):
        rules[f"showers 3h>={t}"] = sh3 >= t
    for t in (70, 80, 90):
        rules[f"precip_prob max3h>={t}"] = prob3 >= t
    for c, p in product((1500, 2000, 2500, 3000), (60, 70, 80, 90)):
        rules[f"CAPE max3h>={c} & prob>={p}"] = (cape3 >= c) & (prob3 >= p)
    for li, p in product((-4, -5, -6), (70, 80)):
        rules[f"LI min3h<={li} & prob>={p}"] = (li3 <= li) & (prob3 >= p)
    for c, p in product((2000, 2500), (70, 80)):
        rules[f"CAPE>={c} & CIN<=25 & prob>={p}"] = (cape3 >= c) & (cin3 <= 25) & (prob3 >= p)
    for t in (5, 10, 20, 33.3):
        rules[f"MAX {len(MODELS)} model P3h>={t}"] = mmax3 >= t
    for k, t in product((2, 3), (5, 10)):
        rules[f">={k} model P3h>={t}"] = (m3 >= t).sum(axis=1) >= k
    for t in (5, 10, 20, 33.3):
        rules[f"MAX lưới 3x3 P3h>={t}"] = nb3 >= t
    for c, t in product((2000,), (5, 10)):
        rules[f"CAPE>={c} & prob>=70 & MAXmodel P3h>={t}"] = (cape3 >= c) & (prob3 >= 70) & (
            mmax3.reindex(cape3.index) >= t)

    days = pd.date_range(START, END - pd.Timedelta(days=1), freq="D").date
    dry_days = [d for d in days if d.month in DRY]
    truth = {}
    for g, causes in (("RAIN", {"RAIN"}), ("RAIN+RAIN_TIDE", {"RAIN", "RAIN_TIDE"})):
        truth[g] = {(code_of[a], (pd.Timestamp(t) + VN).date()) for a, t, cause in events
                    if a in code_of and cause in causes and START.date() <= (pd.Timestamp(t) + VN).date() < END.date()}
    skipped = sum(1 for a, _, _ in events if a not in code_of)
    log(f"sự kiện mưa={len(events)} thiếu quận={skipped} quận-ngày RAIN={len(truth['RAIN'])} "
        f"RAIN+RAIN_TIDE={len(truth['RAIN+RAIN_TIDE'])} ngày={len(days)} mùa khô={len(dry_days)}")

    res = []
    for name, mask in rules.items():
        pred = {u for u in day_set(mask) if u[1] in set(days)}
        row = {"rule": name, "rate_all": len(pred) / (24 * len(days)),
               "rate_dry": sum(1 for u in pred if u[1].month in DRY) / (24 * len(dry_days)),
               "rate_wet": sum(1 for u in pred if u[1].month not in DRY) / (24 * (len(days) - len(dry_days)))}
        for g, tr in truth.items():
            row[f"recall_{g}"] = len(tr & pred) / len(tr)
            row[f"hit_{g}"] = len(tr & pred)
            city = {d for _, d in pred}
            row[f"cityday_recall_{g}"] = len({d for _, d in tr} & city) / len({d for _, d in tr})
        res.append(row)
    df = pd.DataFrame(res)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    log(df.round(3).to_string(index=False))

    # Giá trị từng sự kiện để soi
    detail = []
    for c, d in sorted(truth["RAIN+RAIN_TIDE"], key=lambda u: (u[1], u[0])):
        lo = pd.Timestamp(d) - VN
        sl = slice(lo, lo + pd.Timedelta(hours=23))

        def mx(s, c=c, sl=sl):
            try:
                return round(float(s.loc[c].loc[sl].max()), 1)
            except KeyError:
                return None
        detail.append({"code": c, "vn_date": str(d), "obs_p3": mx(o3), "bm_p3": mx(p3), "sh3": mx(sh3),
                       "prob": mx(prob3), "cape": mx(cape3), "li_neg_max": mx(-li3),  # = -(LI nhỏ nhất)
                       "mmax_p3": mx(mmax3),
                       "nb_p3": mx(nb3)})
    log(pd.DataFrame(detail).to_string(index=False))
    (CACHE / "result.json").write_text(json.dumps({"rules": res, "events": detail}, indent=2, default=str),
                                       encoding="utf-8")
    log("saved", CACHE / "result.json")


if __name__ == "__main__":
    sys.exit(main())
