"""Khởi tạo dữ liệu nền + DEMO (idempotent — chạy lại không nhân bản)."""

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.spatial import point_wkt
from app.gis.demo_catalog import CAMERAS, STATIONS
from app.gis.importer import import_hcm_districts
from app.models import (
    AdministrativeArea,
    AlertRule,
    Camera,
    DataSource,
    HistoricalFloodEvent,
    MonitoringStation,
    Role,
    Sensor,
    SystemSetting,
    User,
    WaterLevelObservation,
)
from app.services import gis_service
from app.services.rule_engine import DEFAULT_RULE_CONFIG

log = logging.getLogger("seed")

ROLES = [("ADMIN", "Quản trị viên"), ("OPERATOR", "Cán bộ vận hành"), ("USER", "Người dùng tra cứu")]
SOURCES = [
    ("SIMULATED", "Bộ mô phỏng dữ liệu DEMO (synthetic)", "SIMULATED", True, "—", "",
     "Dữ liệu sinh tự động phục vụ trình diễn và kiểm thử; KHÔNG phải số liệu quan trắc thật."),
    ("MANUAL", "Nhập thủ công", "MANUAL", False, "", "", "Cán bộ nhập trực tiếp trên hệ thống"),
    ("IMPORT", "Nhập tệp CSV/Excel", "MANUAL", False, "", "", "Dữ liệu do người dùng tải lên"),
    ("GEOBOUNDARIES", "geoBoundaries VNM ADM2 (OCHA ROAP)", "OPEN_DATA", False, "CC BY 3.0 IGO",
     "https://www.geoboundaries.org", "Ranh giới quận/huyện năm 2020 (trước sắp xếp đơn vị hành chính 2021/2025)"),
]
SETTINGS = [
    ("map.default_center", [106.70, 10.78], "Tâm bản đồ mặc định [lon, lat]"),
    ("map.default_zoom", 11, "Mức zoom mặc định"),
    ("alerts.public_by_default", True, "Cảnh báo mới hiển thị công khai"),
    ("data.freshness_minutes", 180, "Dữ liệu cũ hơn ngưỡng này bị coi là STALE"),
    ("camera.retention_days_default", 30, "Số ngày lưu ảnh camera mặc định"),
    ("notifications.email_enabled", False, "Gửi email (cần cấu hình SMTP_HOST)"),
]


def seed_base(db: Session) -> None:
    for code, name in ROLES:
        if not db.scalar(select(Role).where(Role.code == code)):
            db.add(Role(code=code, name=name))
    for code, name, kind, sim, lic, url, desc in SOURCES:
        if not db.scalar(select(DataSource).where(DataSource.code == code)):
            db.add(DataSource(code=code, name=name, kind=kind, is_simulated=sim, license=lic, url=url,
                              description=desc))
    for k, v, d in SETTINGS:
        if not db.get(SystemSetting, k):
            db.add(SystemSetting(key=k, value=v, description=d))
    if not db.scalar(select(AlertRule.id)):
        db.add(AlertRule(version=1, name="Quy tắc mặc định (nghiên cứu/demo)", config=DEFAULT_RULE_CONFIG,
                         is_active=True, notes="Ngưỡng phục vụ nghiên cứu/demo, chưa phải ngưỡng vận hành chính thức"))
    db.commit()


def seed_areas(db: Session) -> int:
    src = db.scalar(select(DataSource).where(DataSource.code == "GEOBOUNDARIES"))
    path = get_settings().datasets_dir / "gis" / "hcm_districts_2020.geojson"
    n = import_hcm_districts(db, path, src)
    db.commit()
    return n


def seed_demo_assets(db: Session) -> None:
    sim = db.scalar(select(DataSource).where(DataSource.code == "SIMULATED"))
    for code, name, typ, addr, lat, lon, thr, *_ in STATIONS:
        if db.scalar(select(MonitoringStation.id).where(MonitoringStation.code == code)):
            continue
        area = gis_service.nearest_area(db, lon, lat, level="DISTRICT")
        st = MonitoringStation(code=code, name=name, station_type=typ, address=addr, latitude=lat, longitude=lon,
                               location=point_wkt(lon, lat), area_id=area.id if area else None,
                               managing_unit="DEMO — đơn vị giả định", flood_threshold_cm=thr, source_id=sim.id,
                               notes="Trạm hư cấu phục vụ demo; dữ liệu mô phỏng")
        db.add(st)
        db.flush()
        for t, u in (("RAIN_GAUGE", "mm"), ("WATER_LEVEL", "cm")):
            if typ == "COMBINED" or (t == "RAIN_GAUGE") == (typ == "RAIN"):
                db.add(Sensor(station_id=st.id, sensor_type=t, unit=u, model="DEMO"))
    for code, name, lat, lon, _ref, public in CAMERAS:
        if db.scalar(select(Camera.id).where(Camera.code == code)):
            continue
        area = gis_service.nearest_area(db, lon, lat, level="DISTRICT")
        db.add(Camera(code=code, name=name, latitude=lat, longitude=lon, location=point_wkt(lon, lat),
                      area_id=area.id if area else None, is_public=public, source_id=sim.id,
                      roi=[[0, 0.45], [1, 0.45], [1, 1], [0, 1]]))
    db.commit()


def derive_flood_history(db: Session) -> int:
    """Sự kiện ngập lịch sử MÔ PHỎNG = các đợt mực nước vượt ngưỡng trong chuỗi mô phỏng."""
    sim = db.scalar(select(DataSource).where(DataSource.code == "SIMULATED"))
    if db.scalar(select(func.count()).select_from(HistoricalFloodEvent).where(HistoricalFloodEvent.is_simulated)):
        return 0
    n = 0
    for st in db.scalars(select(MonitoringStation).where(MonitoringStation.source_id == sim.id)):
        rows = db.execute(select(WaterLevelObservation.observed_at, WaterLevelObservation.water_level_cm)
                          .where(WaterLevelObservation.station_id == st.id,
                                 WaterLevelObservation.quality_flag == "VALID")
                          .order_by(WaterLevelObservation.observed_at)).all()
        run = []
        for t, w in rows + [(None, None)]:
            if w is not None and w > st.flood_threshold_cm and (not run or t - run[-1][0] <= timedelta(hours=2)):
                run.append((t, w))
                continue
            if len(run) >= 1:
                depth = max(x[1] for x in run) - st.flood_threshold_cm
                db.add(HistoricalFloodEvent(
                    area_id=st.area_id, location_name=st.address, latitude=st.latitude, longitude=st.longitude,
                    location=point_wkt(st.longitude, st.latitude), started_at=run[0][0],
                    ended_at=run[-1][0] + timedelta(hours=1), max_depth_cm=round(depth, 1), cause="RAIN_TIDE",
                    description=f"Sự kiện MÔ PHỎNG suy ra từ mực nước trạm {st.code} vượt ngưỡng",
                    is_simulated=True, source_id=sim.id))
                n += 1
            run = [(t, w)] if w is not None and w > st.flood_threshold_cm else []
    db.commit()
    return n


def update_susceptibility(db: Session) -> None:
    counts = dict(db.execute(select(HistoricalFloodEvent.area_id, func.count())
                             .group_by(HistoricalFloodEvent.area_id)).all())
    mx = max(counts.values(), default=0)
    for a in db.scalars(select(AdministrativeArea)):
        c = counts.get(a.id, 0)
        a.susceptibility = round(0.15 + 0.85 * c / mx, 3) if mx and c else 0.2
    db.commit()


def check(db: Session) -> dict:
    out = {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in
           (Role, User, DataSource, AdministrativeArea, MonitoringStation, Camera, HistoricalFloodEvent, AlertRule)}
    out["water_level_observations"] = db.scalar(select(func.count()).select_from(WaterLevelObservation))
    assert out["roles"] == 3 and out["administrative_areas"] >= 24, out
    return out




# ------------------------------------------------------------------ dữ liệu thật (Open-Meteo, điểm ngập công bố)
def seed_openmeteo_points(db: Session) -> int:
    """24 điểm lưới mưa tại tâm quận/huyện + 1 trạm triều Vũng Tàu; kèm độ cao DEM."""
    from app.services import openmeteo_service as om

    src = om.source(db)
    areas = list(db.scalars(select(AdministrativeArea).where(AdministrativeArea.level == "DISTRICT")
                            .order_by(AdministrativeArea.id)))
    elev = om.elevations([(a.centroid_lat, a.centroid_lon) for a in areas] + [om.TIDE_POINT])
    n = 0
    for a, e in zip(areas, elev, strict=False):
        if e is not None:  # dịch vụ lỗi không được xoá độ cao đã có
            a.elevation_m = e
        code = "OM-" + a.code.removeprefix("HCM-")[:27]
        if db.scalar(select(MonitoringStation.id).where(MonitoringStation.code == code)):
            continue
        db.add(MonitoringStation(
            code=code, name=f"Điểm lưới mưa Open-Meteo – {a.name}", station_type="RAIN", address=a.name,
            latitude=a.centroid_lat, longitude=a.centroid_lon, location=point_wkt(a.centroid_lon, a.centroid_lat),
            area_id=a.id, managing_unit="Open-Meteo (mô hình)", interval_minutes=60, elevation_m=e,
            source_id=src.id, notes="Mưa giờ từ mô hình khí tượng tại tâm khu vực, không phải trạm đo tại chỗ"))
        n += 1
    if not db.scalar(select(MonitoringStation.id).where(MonitoringStation.code == om.TIDE_CODE)):
        lat, lon = om.TIDE_POINT
        db.add(MonitoringStation(
            code=om.TIDE_CODE, name="Mực nước biển Vũng Tàu (mô hình Open-Meteo Marine)", station_type="WATER_LEVEL",
            address="Cửa biển Vũng Tàu", latitude=lat, longitude=lon, location=point_wkt(lon, lat),
            managing_unit="Open-Meteo (mô hình)", interval_minutes=60, flood_threshold_cm=110, elevation_m=elev[-1],
            source_id=src.id, notes="Mực nước biển so với mực nước biển trung bình (cm); đại diện triều cường"))
        n += 1
    db.commit()
    return n


def seed_hotspots(db: Session) -> int:
    import csv

    from app.models import FloodHotspot

    path = get_settings().datasets_dir / "gis" / "flood_hotspots.csv"
    if not path.exists():
        return 0
    src = db.scalar(select(DataSource).where(DataSource.code == "PC08_TIENPHONG"))
    if not src:
        src = DataSource(code="PC08_TIENPHONG", name="Phòng CSGT Công an TP.HCM (qua báo Tiền Phong, 06/10/2026)",
                         kind="OFFICIAL", is_simulated=False, url="https://tienphong.vn",
                         description="Danh sách điểm có nguy cơ ngập do mưa lớn/triều cường; toạ độ geocode gần đúng")
        db.add(src)
        db.flush()
    n = 0
    for r in csv.DictReader(open(path, encoding="utf-8")):
        lat, lon = float(r["lat"]), float(r["lon"])
        if db.scalar(select(FloodHotspot.id).where(FloodHotspot.name == r["name"])):
            continue
        area = gis_service.nearest_area(db, lon, lat)
        db.add(FloodHotspot(name=r["name"], street=r["street"], latitude=lat, longitude=lon,
                            location=point_wkt(lon, lat), area_id=area.id if area else None,
                            source_url=r["source_url"],
                            note=" ".join(x for x in (("Do triều cường." if r["cause"] == "TIDE" else "Do mưa lớn."),
                                                      r["note"]) if x),
                            source_id=src.id))
        n += 1
    db.commit()
    return n


def update_susceptibility_from_hotspots(db: Session) -> None:
    from app.models import FloodHotspot

    counts = dict(db.execute(select(FloodHotspot.area_id, func.count()).group_by(FloodHotspot.area_id)).all())
    areas = list(db.scalars(select(AdministrativeArea)))
    for a in areas:  # cộng dồn số điểm ngập của phường lên quận
        if a.parent_id and a.id in counts:
            counts[a.parent_id] = counts.get(a.parent_id, 0) + counts[a.id]
    mx = max(counts.values(), default=0)
    for a in areas:
        c = counts.get(a.id, 0)
        a.susceptibility = round(0.2 + 0.7 * c / mx, 3) if mx and c else 0.2
    db.commit()


def assign_hotspots_to_wards(db: Session) -> int:
    from app.models import FloodHotspot

    n = 0
    for h in db.scalars(select(FloodHotspot)):
        ward = gis_service.area_at(db, h.longitude, h.latitude, "WARD")
        if ward and h.area_id != ward.id:
            h.area_id = ward.id
            n += 1
    db.commit()
    return n
