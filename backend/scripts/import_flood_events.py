"""Nạp các trận ngập có nguồn báo chí từ datasets/gis/flood_events.csv; chạy lại không trùng.

Mỗi dòng phải có URL bài gốc. Độ sâu chỉ điền khi bài nêu số. Toạ độ geocode gần đúng (Photon), không phải khảo sát.
"""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
VN_OFFSET = timedelta(hours=7)


def main() -> None:
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.core.spatial import point_wkt, valid_hcm_coordinate
    from app.models import DataSource, HistoricalFloodEvent
    from app.services import gis_service

    path = get_settings().datasets_dir / "gis" / "flood_events.csv"
    with SessionLocal() as db, open(path, encoding="utf-8") as f:
        src = db.scalar(select(DataSource).where(DataSource.code == "PRESS_VN"))
        if not src:
            src = DataSource(code="PRESS_VN", name="Báo chí trong nước", kind="NEWS", is_simulated=False,
                             description="Tin ngập đã đăng báo; toạ độ geocode gần đúng, độ sâu chỉ có khi bài nêu số")
            db.add(src)
            db.flush()
        n = 0
        for r in csv.DictReader(f):
            lat, lon = float(r["lat"]), float(r["lon"])
            if not r["source_url"] or not valid_hcm_coordinate(lat, lon):
                sys.exit(f"Dòng không hợp lệ: {r['location_name']}")
            started = datetime.fromisoformat(r["started_at_vn"]) - VN_OFFSET
            if db.scalar(select(HistoricalFloodEvent.id).where(HistoricalFloodEvent.location_name == r["location_name"],
                                                               HistoricalFloodEvent.started_at == started)):
                continue
            # bộ lọc khu vực và thống kê chỉ theo quận; điểm ngoài ranh giới quận để trống, không gán đại
            area = gis_service.area_at(db, lon, lat, level="DISTRICT")
            db.add(HistoricalFloodEvent(
                location_name=r["location_name"], latitude=lat, longitude=lon, location=point_wkt(lon, lat),
                started_at=started, max_depth_cm=float(r["max_depth_cm"]) if r["max_depth_cm"] else None,
                cause=r["cause"], description=f"{r['description']} Nguồn: {r['source_url']}",
                area_id=area.id if area else None, source_id=src.id, is_simulated=False))
            n += 1
        db.commit()
    print(f"+{n} sự kiện ngập từ báo chí")


if __name__ == "__main__":
    main()
