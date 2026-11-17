"""Quản lý camera, lưu khung hình, chạy phát hiện ngập (YOLOv8-seg/HEURISTIC)."""

import logging
import secrets
import time
from datetime import timedelta
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.ai.computer_vision import detector
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import AppError, NotFound
from app.core.spatial import point_wkt, valid_hcm_coordinate
from app.models import Camera, CameraDetection, CameraFrame, DataSource, FloodHotspot, ModelVersion, User
from app.schemas.views import CameraBase, CameraOut, CameraUpdate, DetectionOut
from app.services import gis_service
from app.services.audit_service import audit

log = logging.getLogger("app.camera")
SCAN_BUDGET_S = 60  # tổng thời gian tối đa mỗi lượt quét
SCAN_FETCH_TIMEOUT_S = 5  # mỗi ảnh khi quét (proxy công khai vẫn dùng timeout mặc định)
_last_attempt: dict[int, float] = {}  # cam_id -> monotonic; camera lỗi không được chiếm lượt của camera khác
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png"}


def media_root() -> Path:
    p = get_settings().storage_dir / "camera"
    p.mkdir(parents=True, exist_ok=True)
    return p


def active_vision_model(db: Session) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True),
                                                ModelVersion.model_type == "YOLOV8_SEG").limit(1))


def detection_out(d: CameraDetection, frame: CameraFrame | None = None) -> DetectionOut:
    o = DetectionOut.model_validate(d)
    o.image_url = f"/api/v1/cameras/media/{d.frame_id}/input"
    o.result_image_url = f"/api/v1/cameras/media/{d.frame_id}/result"
    return o


def latest_detection(db: Session, camera_id: int) -> CameraDetection | None:
    return db.scalar(select(CameraDetection).where(CameraDetection.camera_id == camera_id)
                     .order_by(CameraDetection.detected_at.desc()).limit(1))


def to_out(db: Session, c: Camera, staff: bool = True) -> CameraOut:
    o = CameraOut.model_validate(c)
    if not staff:
        o.stream_url = ""  # URL nguồn camera có thể chứa thông tin truy cập -> chỉ cán bộ xem
    d = latest_detection(db, c.id)
    o.latest_detection = detection_out(d) if d else None
    return o


def get(db: Session, cid: int) -> Camera:
    c = db.get(Camera, cid)
    if not c or c.deleted_at:
        raise NotFound("Camera")
    return c


def create(db: Session, data: CameraBase, user: User, request=None) -> Camera:
    if not valid_hcm_coordinate(data.latitude, data.longitude):
        raise AppError(422, "OUT_OF_AREA", "Toạ độ nằm ngoài phạm vi TP.HCM")
    if db.scalar(select(Camera.id).where(Camera.code == data.code)):
        raise AppError(409, "DUPLICATE", f"Mã camera {data.code} đã tồn tại")
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    area = gis_service.nearest_area(db, data.longitude, data.latitude, level="DISTRICT")
    c = Camera(**data.model_dump(), location=point_wkt(data.longitude, data.latitude),
               area_id=area.id if area else None, source_id=src.id)
    db.add(c)
    db.flush()
    audit(db, user, "CAMERA_CREATE", "camera", c.id, {"code": c.code}, request)
    db.commit()
    return c


def update(db: Session, cid: int, data: CameraUpdate, user: User, request=None) -> Camera:
    c = get(db, cid)
    ch = data.model_dump(exclude_unset=True)
    for k, v in ch.items():
        setattr(c, k, v)
    if "latitude" in ch or "longitude" in ch:
        if not valid_hcm_coordinate(c.latitude, c.longitude):
            raise AppError(422, "OUT_OF_AREA", "Toạ độ nằm ngoài phạm vi TP.HCM")
        c.location = point_wkt(c.longitude, c.latitude)
        area = gis_service.nearest_area(db, c.longitude, c.latitude, level="DISTRICT")
        c.area_id = area.id if area else None
    audit(db, user, "CAMERA_UPDATE", "camera", c.id, ch, request)
    db.commit()
    db.refresh(c)
    return c


def soft_delete(db: Session, cid: int, user: User, request=None) -> None:
    c = get(db, cid)
    c.deleted_at, c.status = utcnow(), "INACTIVE"
    c.code = f"{c.code}~{c.id}"[:30]
    audit(db, user, "CAMERA_DELETE", "camera", c.id, None, request)
    db.commit()


def decode_upload(filename: str, content: bytes) -> np.ndarray:
    max_b = get_settings().max_upload_mb * 1024 * 1024
    if Path(filename or "").suffix.lower() not in ALLOWED_IMAGE:
        raise AppError(415, "UNSUPPORTED_MEDIA", "Chỉ nhận ảnh JPG/PNG")
    if len(content) > max_b:
        raise AppError(413, "TOO_LARGE", f"Ảnh tối đa {get_settings().max_upload_mb} MB")
    img = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)  # xác thực nội dung thực là ảnh
    if img is None:
        raise AppError(415, "INVALID_IMAGE", "Tệp không phải ảnh hợp lệ")
    h, w = img.shape[:2]
    if max(h, w) > 1280:  # giới hạn kích thước xử lý
        s = 1280 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)))
    return img


def analyze(db: Session, img: np.ndarray, camera: Camera | None, user: User | None,
            is_simulated: bool = False) -> CameraDetection:
    """Lưu ảnh (tên file ngẫu nhiên, không dùng tên người dùng gửi), chạy model, lưu kết quả."""
    mv = active_vision_model(db)
    weights = mv.artifact_path if mv and Path(mv.artifact_path).exists() else None
    res = detector.detect(img, camera.roi if camera else None, weights)
    folder = media_root() / (camera.code if camera else "uploads")
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{utcnow():%Y%m%d%H%M%S}_{secrets.token_hex(4)}"
    cv2.imwrite(str(folder / f"{stem}.jpg"), img)
    cv2.imwrite(str(folder / f"{stem}_result.jpg"), res.overlay)
    frame = CameraFrame(camera_id=camera.id if camera else None, image_path=str(folder / f"{stem}.jpg"),
                        uploaded_by=user.id if user else None, is_simulated=is_simulated)
    db.add(frame)
    db.flush()
    det = CameraDetection(frame_id=frame.id, camera_id=frame.camera_id, model_version_id=mv.id if mv and weights else None,
                          method=res.method, flood_ratio=res.flood_ratio, confidence=res.confidence,
                          num_regions=res.num_regions, result_image_path=str(folder / f"{stem}_result.jpg"),
                          details={**res.details, "model": f"{mv.name}:{mv.version}" if mv and weights else None,
                                   "trained_on_simulated": mv.trained_on_simulated if mv else None},
                          is_simulated=is_simulated)
    db.add(det)
    db.commit()
    return det


def purge_expired(db: Session) -> int:
    """Chính sách lưu trữ: xoá ảnh quá hạn retention_days của từng camera."""
    n = 0
    for c in db.scalars(select(Camera).where(Camera.id.in_(select(CameraFrame.camera_id).distinct()))):
        cutoff = utcnow() - timedelta(days=c.retention_days)
        for f in db.scalars(select(CameraFrame).where(CameraFrame.camera_id == c.id, CameraFrame.captured_at < cutoff)):
            for d in db.scalars(select(CameraDetection).where(CameraDetection.frame_id == f.id)):
                Path(d.result_image_path).unlink(missing_ok=True)
            Path(f.image_path).unlink(missing_ok=True)
            db.delete(f)
            n += 1
    db.commit()
    return n


def scan_candidates(db: Session, radius_m: int, limit: int) -> list[Camera]:
    """Camera TT- ACTIVE gần điểm ngập; thử lâu nhất (hoặc chưa thử) trước -> quay vòng công bằng, kể cả khi lỗi."""
    cam_loc, hot_loc = Camera.__table__.c.location, FloodHotspot.__table__.c.location
    last = (select(CameraFrame.camera_id, func.max(CameraFrame.captured_at).label("t"))
            .group_by(CameraFrame.camera_id).subquery())
    near = exists().where(func.ST_DistanceSphere(cam_loc, hot_loc) <= radius_m)
    stmt = (select(Camera).outerjoin(last, last.c.camera_id == Camera.id)
            .where(Camera.deleted_at.is_(None), Camera.status == "ACTIVE", Camera.code.like("TT-%"), near)
            .order_by(last.c.t.asc().nulls_first(), Camera.id))
    return sorted(db.scalars(stmt), key=lambda c: _last_attempt.get(c.id, -1.0))[:limit]  # sort ổn định


def scan_traffic_cameras(db: Session) -> dict:
    """Quét ảnh camera giao thông gần điểm ngập bằng YOLOv8-seg đang dùng; lỗi một camera chỉ bỏ qua camera đó."""
    from app.services import traffic_camera_service as tc

    mv = active_vision_model(db)
    if not mv or not Path(mv.artifact_path).exists():
        return {"skipped": "NO_ACTIVE_MODEL"}
    s = get_settings()
    done = failed = 0
    cams = scan_candidates(db, s.camera_scan_radius_m, s.camera_scan_max_per_run)
    t0, timed_out = time.monotonic(), False
    for cam in cams:
        if time.monotonic() - t0 > SCAN_BUDGET_S:
            timed_out = True
            break
        _last_attempt[cam.id] = time.monotonic()  # ghi trước khi thử
        try:
            raw = tc.snapshot(cam, timeout=SCAN_FETCH_TIMEOUT_S)
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("ảnh không giải mã được")
            analyze(db, img, cam, None)
            done += 1
        except Exception as e:  # mạng/camera hỏng -> bỏ qua, chu kỳ sau thử lại
            db.rollback()
            failed += 1
            log.warning("Quét camera %s lỗi: %s", cam.code, e)
    return {"scanned": done, "failed": failed, "selected": len(cams)} | ({"timed_out": True} if timed_out else {})
