"""Theo dõi ảnh camera giao thông: tự ngừng khi lỗi liên tiếp, tự bật lại, không khoá hàng loạt khi cổng sập."""

from sqlalchemy import delete, select

from app.core.errors import AppError
from app.core.spatial import point_wkt
from app.models import Camera, DataSource
from app.services import traffic_camera_service as tc

LON, LAT = 106.51, 10.51


def test_camera_health_disables_after_failures_and_restores(db, monkeypatch):
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    others = db.scalars(select(Camera).where(Camera.code.like("TT-%"), Camera.deleted_at.is_(None))).all()
    for c in others:  # chỉ kiểm tra camera của test này
        c.deleted_at = c.created_at
    cams = [Camera(code=f"TT-{0xabc000 + i:024x}", name=f"h{i}", latitude=LAT, longitude=LON,
                   location=point_wkt(LON, LAT), is_public=True, source_id=src.id) for i in range(3)]
    db.add_all(cams)
    db.commit()
    bad, good, back = cams
    back.status = "INACTIVE"
    db.commit()

    def snap(c, timeout=10):
        if c.code == bad.code:
            raise AppError(502, "CAMERA_UNAVAILABLE", "x")
        return b"\xff\xd8"
    monkeypatch.setattr(tc, "snapshot", snap)
    try:
        for _ in range(tc.FAILS_TO_DISABLE):
            r = tc.check_health(db, 10)
        assert r["checked"] == 3 and not r["outage"]
        db.refresh(bad), db.refresh(good), db.refresh(back)
        assert bad.status == "INACTIVE" and bad.snapshot_fail_count == tc.FAILS_TO_DISABLE
        assert good.status == "ACTIVE" and back.status == "ACTIVE"  # có ảnh lại -> tự bật

        good.status = "ACTIVE"
        db.commit()
        monkeypatch.setattr(tc, "snapshot", lambda c, timeout=10: (_ for _ in ()).throw(AppError(502, "X", "x")))
        r = tc.check_health(db, 10)  # cả loạt lỗi: coi là cổng sập, không khoá ai
        db.refresh(good)
        assert r["outage"] and good.status == "ACTIVE" and good.snapshot_fail_count == 0
    finally:
        db.execute(delete(Camera).where(Camera.id.in_([c.id for c in cams])))
        for c in others:
            c.deleted_at = None
        db.commit()
