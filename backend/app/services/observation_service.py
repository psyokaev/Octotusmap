"""Thu thập, kiểm tra chất lượng và nhập dữ liệu quan trắc (thủ công, CSV, Excel, API)."""

import csv
import io
from datetime import UTC, datetime, timedelta

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import MonitoringStation, RainfallObservation, WaterLevelObservation

RAIN_MAX_MM_H = 200.0  # kỷ lục mưa giờ thực tế < 200mm
WL_MIN, WL_MAX = -300.0, 600.0
WL_JUMP_MAX = 150.0  # cm/giờ
VN_TZ_OFFSET = timedelta(hours=7)


def rain_flag(v: float | None) -> str:
    if v is None:
        return "MISSING"
    return "SUSPECT" if v < 0 or v > RAIN_MAX_MM_H else "VALID"


def wl_flag(v: float | None, prev: float | None = None) -> str:
    if v is None:
        return "MISSING"
    if not WL_MIN <= v <= WL_MAX or (prev is not None and abs(v - prev) > WL_JUMP_MAX):
        return "SUSPECT"
    return "VALID"


def upsert_observations(db: Session, rows: list[dict]) -> int:
    """rows: {station_id, observed_at(UTC naive), rainfall_mm?, water_level_cm?, is_simulated, source_id}.
    Trùng (station_id, observed_at) -> bỏ qua (giữ bản ghi gốc). Trả số dòng chèn mới."""
    inserted = 0
    rain = [r for r in rows if "rainfall_mm" in r]
    wl = [r for r in rows if "water_level_cm" in r]
    for model, items, key, flag in ((RainfallObservation, rain, "rainfall_mm", "rain"),
                                    (WaterLevelObservation, wl, "water_level_cm", "wl")):
        if not items:
            continue
        values = [{
            "station_id": r["station_id"], "observed_at": r["observed_at"], key: r[key],
            "quality_flag": r.get(f"{flag}_quality") or (rain_flag(r[key]) if flag == "rain" else wl_flag(r[key])),
            "is_simulated": r.get("is_simulated", False), "source_id": r["source_id"], "ingested_at": utcnow(),
        } for r in items]
        for i in range(0, len(values), 5000):
            chunk = values[i:i + 5000]
            t = model.__table__  # RETURNING chỉ trả dòng thực sự chèn -> đếm đúng (rowcount của executemany là -1)
            inserted += len(db.execute(insert(t).on_conflict_do_nothing().returning(t.c.station_id), chunk).all())
    touch_last_observation(db, {r["station_id"] for r in rows})
    return inserted


def touch_last_observation(db: Session, station_ids) -> None:
    for sid in station_ids:
        t = db.scalar(select(WaterLevelObservation.observed_at).where(WaterLevelObservation.station_id == sid)
                      .order_by(WaterLevelObservation.observed_at.desc()).limit(1))
        t2 = db.scalar(select(RainfallObservation.observed_at).where(RainfallObservation.station_id == sid)
                       .order_by(RainfallObservation.observed_at.desc()).limit(1))
        st = db.get(MonitoringStation, sid)
        if st:
            st.last_observation_at = max([x for x in (t, t2) if x], default=None)


def _parse_time(v) -> datetime:
    """Chấp nhận datetime/ISO; không có múi giờ -> hiểu là giờ Việt Nam (UTC+7)."""
    if isinstance(v, datetime):
        dt = v
    else:
        dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00").replace("/", "-"))
    if dt.tzinfo is None:
        return (dt - VN_TZ_OFFSET).replace(minute=0, second=0, microsecond=0)
    return dt.astimezone(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0)


def _num(v, unit_cm: bool = False) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    x = float(str(v).replace(",", "."))
    return x


def parse_table(filename: str, content: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    if name.endswith(".xlsx"):
        ws = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(it)]
        return [dict(zip(header, r, strict=False)) for r in it if any(c is not None for c in r)]
    raise ValueError("Chỉ hỗ trợ .csv hoặc .xlsx")


def import_observations(db: Session, rows: list[dict], station: MonitoringStation | None, source_id: int,
                        max_rows: int = 50_000) -> dict:
    """Cột: observed_at, rainfall_mm, water_level_cm (hoặc water_level_m), [station_code].
    Đơn vị m -> cm được chuẩn hoá. Dòng lỗi bị từ chối kèm lý do (không nội suy âm thầm)."""
    if len(rows) > max_rows:
        raise ValueError(f"Tối đa {max_rows} dòng mỗi lần nhập")
    codes = {s.code: s for s in db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None)))}
    out, errors, seen = [], [], set()
    dup = 0
    for i, r in enumerate(rows, start=2):
        try:
            st = station or codes.get(str(r.get("station_code", "")).strip())
            if not st:
                raise ValueError("station_code không tồn tại")
            t = _parse_time(r.get("observed_at"))
            if t > utcnow() + timedelta(hours=1):
                raise ValueError("thời gian ở tương lai")
            rain = _num(r.get("rainfall_mm"))
            wl = _num(r.get("water_level_cm"))
            if wl is None and r.get("water_level_m") not in (None, ""):
                wl = _num(r.get("water_level_m")) * 100
            if rain is None and wl is None:
                raise ValueError("không có giá trị đo")
            if (st.id, t) in seen:
                dup += 1
                continue
            seen.add((st.id, t))
            row = {"station_id": st.id, "observed_at": t, "source_id": source_id}
            if rain is not None:
                row["rainfall_mm"] = rain
            if wl is not None:
                row["water_level_cm"] = wl
            out.append(row)
        except (ValueError, TypeError) as e:
            errors.append(f"Dòng {i}: {e}")
    inserted = upsert_observations(db, out) if out else 0
    # số cặp giá trị đã gửi so với số chèn mới -> phần còn lại là trùng trong DB
    sent = sum(("rainfall_mm" in r) + ("water_level_cm" in r) for r in out)
    return {"total_rows": len(rows), "inserted": inserted, "duplicates": dup + max(sent - inserted, 0),
            "rejected": len(errors), "errors": errors[:100]}
