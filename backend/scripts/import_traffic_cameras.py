"""Nạp danh sách camera giao thông từ snapshot datasets/gis/traffic_cameras.csv; chạy lại không trùng.

Snapshot lấy từ trang công khai https://giaothong.hochiminhcity.gov.vn/Map.aspx. API danh sách cần phiên trình duyệt của
trang nên không gọi tự động. Muốn cập nhật: mở trang, bật lớp Camera, lưu phản hồi SearchQuery ra file rồi truyền đường dẫn
file đó làm tham số cho script này.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.core.spatial import point_wkt, valid_hcm_coordinate
    from app.models import Camera
    from app.services import gis_service
    from app.services import traffic_camera_service as tc

    path = get_settings().datasets_dir / "gis" / "traffic_cameras.csv"
    if len(sys.argv) > 1:
        rows = tc.parse_list(Path(sys.argv[1]).read_text(encoding="utf-8"))
        if not rows:
            sys.exit("Không đọc được camera nào từ file; không thay đổi dữ liệu")
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    rows = [{**r, "lat": float(r["lat"]), "lon": float(r["lon"])} for r in csv.DictReader(open(path, encoding="utf-8"))]
    with SessionLocal() as db:
        src = tc.source(db)
        existing = {c.code: c for c in db.scalars(select(Camera).where(Camera.source_id == src.id))}
        added = updated = skipped = 0
        for r in rows:
            if not valid_hcm_coordinate(r["lat"], r["lon"]):
                skipped += 1
                continue
            code = tc.CODE_PREFIX + r["cam_id"]
            status = "ACTIVE" if r["status"] == "UP" else "INACTIVE"
            c = existing.get(code)
            area = gis_service.area_at(db, r["lon"], r["lat"], "DISTRICT")  # quận để lọc/thống kê; None nếu ngoài quận
            if c:
                c.name, c.status, c.area_id = r["name"], status, area.id if area else None
                updated += 1
            else:
                db.add(Camera(code=code, name=r["name"], latitude=r["lat"], longitude=r["lon"],
                              location=point_wkt(r["lon"], r["lat"]), status=status, is_public=True,
                              retention_days=1, source_id=src.id, area_id=area.id if area else None))
                added += 1
        db.commit()
    print(f"+{added} camera, cập nhật {updated}, ngoài phạm vi {skipped}")


if __name__ == "__main__":
    main()
