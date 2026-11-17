"""Camera giao thông công khai của TP.HCM: đọc danh sách và proxy ảnh (không lưu ảnh)."""

import re
import threading
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Camera, DataSource

BASE = "https://giaothong.hochiminhcity.gov.vn"
SOURCE_CODE = "HCMC_TRAFFIC"
CODE_PREFIX = "TT-"
CACHE_S = 30
_ROW = re.compile(r'\["(?P<title>[^"]*)",(?:null|"[^"]*"),"(?P<cam>[0-9a-f]{24})",')
_POINT = re.compile(r'"POINT\((?P<lon>[\d.]+) (?P<lat>[\d.]+)\)"')
_AFTER = re.compile(r'"(?:True|False)",(?:null|"[^"]*"),"(?P<status>\w+)",(?:null|"[^"]*"),(?:null|"[^"]*"|[\d.]+),(?P<name>null|"[^"]*")')
_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()


def parse_list(text: str) -> list[dict]:
    """Đọc phản hồi AjaxPro (không phải JSON chuẩn) của lớp CAMERA; bỏ camera không có toạ độ."""
    table = text[max(text.find('new Ajax.Web.DataTable([["Title"'), 0):]
    starts = list(_ROW.finditer(table))
    rows = []
    for m, nxt in zip(starts, [*starts[1:], None], strict=True):
        chunk = table[m.end(): nxt.start() if nxt else len(table)]
        pt, after = _POINT.search(chunk), _AFTER.search(chunk)
        if pt and after:
            name = after["name"].strip('"') if after["name"] != "null" else m["title"]
            rows.append({"cam_id": m["cam"], "name": name[:150], "lat": float(pt["lat"]), "lon": float(pt["lon"]),
                         "status": after["status"]})
    return rows


def source(db: Session) -> DataSource:
    src = db.scalar(select(DataSource).where(DataSource.code == SOURCE_CODE))
    if not src:
        src = DataSource(code=SOURCE_CODE, name="Cổng thông tin giao thông TP.HCM", kind="OFFICIAL", is_simulated=False,
                         url=BASE, description="Camera giao thông công khai của thành phố")
        db.add(src)
        db.flush()
    return src


def snapshot(camera: Camera, timeout: float = 10) -> bytes:
    """Ảnh mới nhất; cache ngắn để không dồn tải lên hệ thống của thành phố."""
    cam_id = camera.code.removeprefix(CODE_PREFIX)
    if not camera.code.startswith(CODE_PREFIX) or not re.fullmatch(r"[0-9a-f]{24}", cam_id):
        raise AppError(404, "NOT_FOUND", "Camera không có ảnh")
    with _lock:
        hit = _cache.get(cam_id)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    try:
        r = httpx.get(f"{BASE}/render/ImageHandler.ashx", params={"id": cam_id}, timeout=timeout,
                      headers={"User-Agent": get_settings().external_user_agent})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise AppError(502, "CAMERA_UNAVAILABLE", "Không lấy được ảnh camera") from e
    if not r.content.startswith(b"\xff\xd8"):  # chỉ chuyển tiếp ảnh JPEG
        raise AppError(502, "CAMERA_UNAVAILABLE", "Camera hiện không có ảnh")
    with _lock:
        if len(_cache) > 500:  # chặn cache tăng vô hạn
            _cache.clear()
        _cache[cam_id] = (time.monotonic(), r.content)
    return r.content
