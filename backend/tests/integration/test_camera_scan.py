"""Quét định kỳ camera giao thông: chọn camera, quay vòng, lỗi tải ảnh, không có model. Không dùng mạng."""

import cv2
import numpy as np
import pytest
from sqlalchemy import delete, select

from app.ai.computer_vision.detector import DetectionResult
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.spatial import point_wkt
from app.models import Camera, CameraDetection, CameraFrame, DataSource, FloodHotspot, ModelVersion, TrainingRun
from app.services import camera_service

LON, LAT = 106.5, 10.5  # xa mọi dữ liệu seed
JPEG = cv2.imencode(".jpg", np.zeros((32, 32, 3), "uint8"))[1].tobytes()


def _cam(src, i, dlat=0.0, code=None, status="ACTIVE"):
    lat = LAT + dlat
    return Camera(code=code or f"TT-{i:024x}", name=f"scan{i}", latitude=lat, longitude=LON,
                  location=point_wkt(LON, lat),
                  status=status, is_public=True, retention_days=1, source_id=src.id)


@pytest.fixture()
def world(db, tmp_path, monkeypatch):
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    hot = FloodHotspot(name="scan-hot", latitude=LAT, longitude=LON, location=point_wkt(LON, LAT), source_id=src.id)
    w = tmp_path / "w.pt"
    w.write_bytes(b"x")
    mv = ModelVersion(name="scan-test", model_type="YOLOV8_SEG", version="t", artifact_path=str(w), is_active=True)
    cams = [_cam(src, 1, 0.0009), _cam(src, 2, 0.001), _cam(src, 3, -0.001),  # ~100 m
            _cam(src, 4, 0.02),  # ~2 km: ngoài bán kính
            _cam(src, 5, 0.0005, status="INACTIVE"), _cam(src, 6, 0.0005, code="MAN-scan")]
    db.add_all([hot, mv, *cams])
    db.commit()
    prev = db.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True), ModelVersion.id != mv.id)).all()
    for m in prev:
        m.is_active = False
    db.commit()
    monkeypatch.setattr(camera_service.detector, "detect", lambda img, roi, weights: DetectionResult(
        "YOLOV8_SEG", 0.5, 0.9, 1, img, {}))
    yield cams, mv
    ids = [c.id for c in cams]
    frames = select(CameraFrame.id).where(CameraFrame.camera_id.in_(ids))
    db.execute(delete(CameraDetection).where(CameraDetection.frame_id.in_(frames)))
    db.execute(delete(CameraFrame).where(CameraFrame.camera_id.in_(ids)))
    db.execute(delete(Camera).where(Camera.id.in_(ids)))
    db.delete(hot)
    db.delete(mv)
    for m in prev:
        m.is_active = True
    db.commit()


def test_selection_radius_active_tt_only(db, world):
    cams, _ = world
    got = camera_service.scan_candidates(db, 500, 10)
    assert {c.id for c in got} == {c.id for c in cams[:3]}


def test_rotation_and_max_per_run(db, world, monkeypatch):
    cams, _ = world
    monkeypatch.setattr(get_settings(), "camera_scan_max_per_run", 2)
    monkeypatch.setattr("app.services.traffic_camera_service.snapshot", lambda c, **kw: JPEG)
    for _ in range(2):
        assert camera_service.scan_traffic_cameras(db)["scanned"] == 2
    seen = [d.camera_id for d in db.scalars(select(CameraDetection).where(
        CameraDetection.camera_id.in_([c.id for c in cams])))]
    assert set(seen) == {c.id for c in cams[:3]}  # sau hai lượt đủ cả ba camera
    assert len(seen) == 3 + 1  # lượt 2: 1 camera mới + 1 quét lại (cũ nhất)


def test_fetch_failure_is_skipped(db, world, monkeypatch):
    cams, _ = world
    bad = cams[1].code

    def snap(c, **kw):
        if c.code == bad:
            raise AppError(502, "CAMERA_UNAVAILABLE", "x")
        return JPEG

    monkeypatch.setattr("app.services.traffic_camera_service.snapshot", snap)
    assert camera_service.scan_traffic_cameras(db) == {"scanned": 2, "failed": 1, "selected": 3}


def test_no_active_model_skips_scan(db, world, monkeypatch):
    _, mv = world
    mv.is_active = False
    db.commit()
    monkeypatch.setattr("app.services.traffic_camera_service.snapshot", lambda c, **kw: pytest.fail("không tải"))
    assert camera_service.scan_traffic_cameras(db) == {"skipped": "NO_ACTIVE_MODEL"}


def test_scan_media_not_public(client, operator, db, world, monkeypatch):
    cams, _ = world
    monkeypatch.setattr("app.services.traffic_camera_service.snapshot", lambda c, **kw: JPEG)
    camera_service.scan_traffic_cameras(db)
    from fastapi.testclient import TestClient

    anon = TestClient(client.app)  # client dùng chung có thể đang giữ cookie đăng nhập của test khác
    fid = db.scalar(select(CameraFrame.id).where(CameraFrame.camera_id == cams[0].id))
    assert anon.get(f"/api/v1/cameras/media/{fid}/result").status_code == 403
    assert anon.get(f"/api/v1/cameras/{cams[0].id}/detections").status_code == 403
    assert client.get(f"/api/v1/cameras/media/{fid}/result", headers=operator).status_code == 200
    assert anon.get(f"/api/v1/cameras/{cams[0].id}").json()["latest_detection"] is None
    assert client.get(f"/api/v1/cameras/{cams[0].id}", headers=operator).json()["latest_detection"] is not None


def test_failing_cameras_do_not_starve_others(db, world, monkeypatch):
    cams, _ = world
    monkeypatch.setattr(get_settings(), "camera_scan_max_per_run", 1)
    bad = {cams[0].code, cams[1].code}

    def snap(c, **kw):
        if c.code in bad:
            raise AppError(502, "CAMERA_UNAVAILABLE", "x")
        return JPEG

    monkeypatch.setattr("app.services.traffic_camera_service.snapshot", snap)
    out = [camera_service.scan_traffic_cameras(db) for _ in range(3)]
    assert [o["scanned"] for o in out] == [0, 0, 1]  # hai lượt lỗi rồi tới camera tốt


def test_scan_budget_stops_run(db, world, monkeypatch):
    monkeypatch.setattr(camera_service, "SCAN_BUDGET_S", -1)
    monkeypatch.setattr("app.services.traffic_camera_service.snapshot", lambda c, **kw: pytest.fail("quá ngân sách"))
    assert camera_service.scan_traffic_cameras(db)["timed_out"] is True


def test_simulated_vision_never_replaces_real_active(db, tmp_path, monkeypatch):
    from app.ai.computer_vision import train as cv

    real = ModelVersion(name="real-v", model_type="YOLOV8_SEG", version="r", artifact_path=str(tmp_path / "r.pt"),
                        trained_on_simulated=False, is_active=True)
    prev = db.scalars(select(ModelVersion).where(ModelVersion.model_type == "YOLOV8_SEG",
                                                 ModelVersion.is_active.is_(True))).all()
    for m in prev:
        m.is_active = False
    db.add(real)
    db.commit()
    monkeypatch.setattr(cv, "generate_dataset", lambda d: tmp_path / "d.yaml")
    monkeypatch.setattr(cv, "train", lambda *a, **k: {"version": "sim1", "weights": "s.pt", "metrics": {},
                                                     "seconds": 1, "params": {}})
    res = cv.train_and_register(db, epochs=1, log=lambda *_: None)
    new = db.scalar(select(ModelVersion).where(ModelVersion.version == "sim1"))
    db.refresh(real)
    ok = real.is_active and not new.is_active and res["activated"] is False
    db.execute(delete(TrainingRun).where(TrainingRun.model_version_id == new.id))
    db.delete(new)
    db.delete(real)
    for m in prev:
        m.is_active = True
    db.commit()
    assert ok
