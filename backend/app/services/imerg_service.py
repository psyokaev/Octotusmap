"""Mưa vệ tinh GPM IMERG (NASA, miễn phí, cần token Earthdata) theo ngày cho 24 quận.

Dùng bản Late run theo ngày (GPM_3IMERGDL.07, trễ ~1–2 ngày, ngày theo UTC), cắt sẵn ô lưới TP.HCM qua OPeNDAP:
mỗi ngày đúng một request nhỏ. Mỗi quận lấy ô 0,1° chứa tâm quận.
"""

import logging
import re
from datetime import date, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AdministrativeArea, SatelliteRainfallDaily

log = logging.getLogger(__name__)
PRODUCT = "GPM_3IMERGDL.07"
BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDL.07"
LON0, LAT0, STEP = -179.95, -89.95, 0.1
BOX = (106.35, 107.05, 10.35, 11.15)  # lon min/max, lat min/max (TP.HCM)


def _idx(v: float, origin: float) -> int:
    return int(round((v - origin) / STEP))


def parse_ascii(text: str) -> dict[tuple[float, float], float]:
    """Phản hồi .ascii của OPeNDAP -> {(lon, lat): mm/ngày}; bỏ giá trị thiếu (âm)."""
    lats = [float(x) for x in re.search(r"precipitation\.lat, (.+)", text).group(1).split(",")]
    out = {}
    for m in re.finditer(r"precipitation\.lon=([\d.]+)\], (.+)", text):
        lon = float(m.group(1))
        for lat, v in zip(lats, m.group(2).split(","), strict=True):
            if float(v) >= 0:
                out[(round(lon, 2), round(lat, 2))] = float(v)
    return out


_names: dict[str, dict[str, str]] = {}  # "YYYY/MM" -> {YYYYMMDD: tên file}


def _file_name(day: date, token: str, timeout: float) -> str:
    """Tên file của ngày: NASA đổi hậu tố phiên bản (V07B -> V07C từ 03/03/2026), nên đọc danh sách tháng."""
    key = f"{day:%Y}/{day:%m}"
    if day.strftime("%Y%m%d") not in _names.get(key, {}):
        r = httpx.get(f"{BASE}/{key}/contents.html", headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
                      follow_redirects=True)
        r.raise_for_status()
        _names[key] = {m.group(1): m.group(0) for m in re.finditer(
            r"3B-DAY-L\.MS\.MRG\.3IMERG\.(\d{8})-S000000-E235959\.V\w+\.nc4", r.text)}
    name = _names[key].get(day.strftime("%Y%m%d"))
    if not name:
        raise ValueError(f"IMERG chưa có ngày {day}")
    return name


def fetch_day(day: date, token: str, timeout: float = 60) -> dict[tuple[float, float], float]:
    i0, i1 = _idx(BOX[0], LON0), _idx(BOX[1], LON0)
    j0, j1 = _idx(BOX[2], LAT0), _idx(BOX[3], LAT0)
    url = (f"{BASE}/{day:%Y}/{day:%m}/{_file_name(day, token, timeout)}.ascii"
           f"?precipitation[0:0][{i0}:{i1}][{j0}:{j1}]")
    r = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    if "precipitation.lat" not in r.text:  # trang đăng nhập/lỗi thay vì dữ liệu
        raise ValueError("IMERG không trả dữ liệu (token sai hoặc ngày chưa có)")
    return parse_ascii(r.text)


def district_cells(db: Session) -> dict[int, tuple[float, float]]:
    """Quận -> ô lưới (lon, lat) chứa tâm quận."""
    snap = lambda v, o: round(o + _idx(v, o) * STEP, 2)  # noqa: E731
    return {a.id: (snap(a.centroid_lon, LON0), snap(a.centroid_lat, LAT0))
            for a in db.scalars(select(AdministrativeArea).where(AdministrativeArea.level == "DISTRICT"))}


def ingest_day(db: Session, day: date, token: str) -> int:
    grid = fetch_day(day, token)
    rows = [{"area_id": aid, "day": day, "rain_mm": grid[cell], "product": PRODUCT}
            for aid, cell in district_cells(db).items() if cell in grid]
    if rows:
        db.execute(insert(SatelliteRainfallDaily).values(rows).on_conflict_do_nothing(
            constraint="uq_satrain_area_day"))
        db.commit()
    return len(rows)


def missing_days(db: Session, start: date, end: date) -> list[date]:
    have = set(db.scalars(select(SatelliteRainfallDaily.day).where(
        SatelliteRainfallDaily.day >= start, SatelliteRainfallDaily.day <= end,
        SatelliteRainfallDaily.product == PRODUCT).distinct()))
    return [start + timedelta(d) for d in range((end - start).days + 1) if start + timedelta(d) not in have]


def ingest_recent(db: Session, today: date, days: int = 7) -> dict:
    """Bù các ngày còn thiếu trong `days` ngày gần nhất (ngày chưa phát hành thì để lần sau)."""
    token = get_settings().earthdata_token
    if not token:
        return {"skipped": "chưa có EARTHDATA_TOKEN"}
    out = {"days": 0, "rows": 0}
    for d in missing_days(db, today - timedelta(days), today - timedelta(1)):
        try:
            out["rows"] += ingest_day(db, d, token)
            out["days"] += 1
        except (httpx.HTTPError, ValueError) as e:
            log.info("IMERG %s chưa có: %s", d, e)
    return out
