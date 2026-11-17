from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import DB, Operator, OptionalUser, is_staff
from app.core.errors import AppError, NotFound
from app.models import Camera, CameraDetection, CameraFrame
from app.repositories.base import paginate
from app.schemas.common import Page
from app.schemas.views import CameraBase, CameraOut, CameraUpdate, DetectionOut
from app.core.security import RateLimiter
from app.services import camera_service
from app.services import traffic_camera_service as tc
from app.services.audit_service import audit

router = APIRouter(prefix="/cameras", tags=["Cameras"])
snapshot_limiter = RateLimiter(limit=60, window_s=60, name="snapshot")


def _visible(c: Camera, user) -> bool:
    return c.is_public or is_staff(user)


def _media_visible(c: Camera, user) -> bool:
    """Ảnh/kết quả quét của camera giao thông (TT-) chỉ cán bộ xem, dù camera công khai."""
    return is_staff(user) or (c.is_public and not c.code.startswith(tc.CODE_PREFIX))


@router.get("", response_model=list[CameraOut])
def list_cameras(db: DB, user: OptionalUser):
    stmt = select(Camera).where(Camera.deleted_at.is_(None), Camera.code.not_like(tc.CODE_PREFIX + "%")).order_by(Camera.code)
    if not is_staff(user):
        stmt = stmt.where(Camera.is_public.is_(True))
    return [camera_service.to_out(db, c, is_staff(user)) for c in db.scalars(stmt)]


@router.post("", response_model=CameraOut, status_code=201)
def create_camera(body: CameraBase, user: Operator, request: Request, db: DB):
    return camera_service.to_out(db, camera_service.create(db, body, user, request))


@router.post("/analyze", response_model=DetectionOut, status_code=201)
async def analyze(user: Operator, request: Request, db: DB, file: UploadFile = File(...),
                  camera_id: int | None = Form(None)):
    """Phân tích ảnh tải lên (YOLOv8-seg nếu có trọng số, ngược lại HEURISTIC)."""
    cam = camera_service.get(db, camera_id) if camera_id else None
    if cam and cam.code.startswith(tc.CODE_PREFIX):
        raise AppError(422, "TRAFFIC_CAMERA_NOT_ANALYZED", "Camera giao thông không được phân tích bằng mô hình")
    content = await file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    img = camera_service.decode_upload(file.filename or "", content)
    det = camera_service.analyze(db, img, cam, user)
    audit(db, user, "CAMERA_ANALYZE", "camera", camera_id or "", {"detection_id": det.id}, request)
    db.commit()
    return camera_service.detection_out(det)


@router.get("/media/{frame_id}/{kind}")
def media(frame_id: int, kind: Literal["input", "result"], db: DB, user: OptionalUser):
    """Ảnh camera chỉ phục vụ qua API có kiểm tra quyền (không mở thư mục tĩnh)."""
    f = db.get(CameraFrame, frame_id)
    if not f:
        raise NotFound("Ảnh")
    cam = db.get(Camera, f.camera_id) if f.camera_id else None
    if (cam and not _media_visible(cam, user)) or (not cam and not is_staff(user)):
        raise HTTPException(403, "Không có quyền xem ảnh này")
    path = Path(f.image_path)
    if kind == "result":
        d = db.scalar(select(CameraDetection).where(CameraDetection.frame_id == f.id).limit(1))
        path = Path(d.result_image_path) if d else path
    root = get_settings().storage_dir.resolve()
    if not path.resolve().is_relative_to(root) or not path.exists():
        raise NotFound("Ảnh")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/{cid}/snapshot")
def traffic_snapshot(cid: int, request: Request, db: DB):
    """Ảnh mới nhất của camera giao thông công khai (proxy, không lưu)."""
    c = camera_service.get(db, cid)
    if not c.is_public or not snapshot_limiter.allow(request.client.host if request.client else "?"):
        raise HTTPException(429 if c.is_public else 403, "Không lấy được ảnh lúc này")
    return Response(tc.snapshot(c), media_type="image/jpeg", headers={"Cache-Control": f"public, max-age={tc.CACHE_S}"})


@router.get("/{cid}", response_model=CameraOut)
def get_camera(cid: int, db: DB, user: OptionalUser):
    c = camera_service.get(db, cid)
    if not _visible(c, user):
        raise HTTPException(403, "Camera không công khai")
    out = camera_service.to_out(db, c, is_staff(user))
    if not _media_visible(c, user):
        out.latest_detection = None  # kết quả phát hiện kèm URL ảnh: cùng quyền với ảnh
    return out


@router.patch("/{cid}", response_model=CameraOut)
def update_camera(cid: int, body: CameraUpdate, user: Operator, request: Request, db: DB):
    return camera_service.to_out(db, camera_service.update(db, cid, body, user, request))


@router.delete("/{cid}", status_code=204)
def delete_camera(cid: int, user: Operator, request: Request, db: DB):
    camera_service.soft_delete(db, cid, user, request)


@router.get("/{cid}/detections", response_model=Page[DetectionOut])
def detections(cid: int, db: DB, user: OptionalUser, page: int = Query(1, ge=1), size: int = Query(20, le=100)):
    c = camera_service.get(db, cid)
    if not _media_visible(c, user):
        raise HTTPException(403, "Camera không công khai")
    rows, total = paginate(db, select(CameraDetection).where(CameraDetection.camera_id == cid), page, size,
                           CameraDetection.detected_at, "desc")
    return Page(items=[camera_service.detection_out(d) for d in rows], total=total, page=page, size=size)
