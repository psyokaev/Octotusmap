"""Thí nghiệm: đo báo động giả của YOLOv8-seg đang active trên camera giao thông TP.HCM (TT-).

Lấy ảnh camera TT- ACTIVE (ưu tiên camera trong 500 m quanh flood_hotspots, rồi thêm ngẫu nhiên),
mỗi camera 2 ảnh cách nhau >= 60 s, chạy đúng detector.detect như scan_traffic_cameras (ROI camera,
conf mặc định), ghi tỉ lệ ngập. Chỉ đọc CSDL; ảnh + CSV ghi vào thư mục OUT (không ghi storage/).
Tuần tự, nghỉ ~1 s giữa các request, dùng User-Agent cấu hình như production.

Chạy: PYTHONUTF8=1 .venv/Scripts/python scripts/experiment_camera_fp.py [--n 150] [--out DIR]
"""

import argparse
import csv
import hashlib
import random
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import exists, func, select  # noqa: E402

from app.ai.computer_vision import detector  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models import Camera, FloodHotspot  # noqa: E402
from app.services import camera_service, traffic_camera_service as tc  # noqa: E402

OUT = Path(tempfile.gettempdir()) / "octotusmap_camera_fp"  # không ghi storage/
PAUSE_S, GAP_S, RADIUS_M = 1.0, 60.0, 500


def pick(db, n: int) -> list[tuple[Camera, bool]]:
    base = select(Camera).where(Camera.deleted_at.is_(None), Camera.status == "ACTIVE", Camera.code.like("TT-%"))
    near = exists().where(func.ST_DistanceSphere(Camera.__table__.c.location, FloodHotspot.__table__.c.location) <= RADIUS_M)
    close = list(db.scalars(base.where(near).order_by(Camera.id)))
    rest = list(db.scalars(base.where(~near).order_by(Camera.id)))
    random.Random(42).shuffle(rest)
    return [(c, True) for c in close[:n]] + [(c, False) for c in rest[: max(n - len(close), 0)]]


def shot(cam, weights, tag: str) -> dict:
    row = {"t": time.strftime("%H:%M:%S"), "ok": 0, "ratio": "", "conf": "", "regions": "", "mean": "", "gray": "",
           "md5": "", "err": ""}
    try:
        raw = tc.snapshot(cam)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("ảnh không giải mã được")
        res = detector.detect(img, cam.roi, weights)  # giống camera_service.analyze
        b, g, r = (img[..., i].astype(int) for i in range(3))
        stem = f"{cam.code}_{tag}"
        cv2.imwrite(str(OUT / "img" / f"{stem}.jpg"), img)
        cv2.imwrite(str(OUT / "img" / f"{stem}_result.jpg"), res.overlay)
        row |= {"ok": 1, "ratio": res.flood_ratio, "conf": res.confidence, "regions": res.num_regions,
                "mean": round(float(img.mean()), 1),
                "gray": int(max(np.abs(b - g).mean(), np.abs(g - r).mean()) < 3),  # ảnh hồng ngoại ban đêm
                "md5": hashlib.md5(raw).hexdigest()[:10]}
    except Exception as e:  # camera lỗi chỉ ghi lại, không dừng thí nghiệm
        row["err"] = f"{type(e).__name__}: {getattr(e, 'message', e)}"[:120]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    globals()["OUT"] = a.out
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    mv = camera_service.active_vision_model(db)
    assert mv and Path(mv.artifact_path).exists(), "không có mô hình YOLOv8-seg active"
    print("model", mv.name, mv.version, mv.artifact_path)
    cams = pick(db, a.n)
    db.close()  # chỉ đọc; không giữ kết nối trong lúc tải ảnh
    print(f"{len(cams)} camera ({sum(n for _, n in cams)} gần điểm ngập)")
    first_at, rows = {}, {}
    for k in (1, 2):
        for i, (cam, near) in enumerate(cams):
            if k == 2:
                wait = GAP_S - (time.monotonic() - first_at[cam.id])
                if wait > 0:
                    time.sleep(wait)
            else:
                first_at[cam.id] = time.monotonic()
            r = shot(cam, mv.artifact_path, str(k))
            rows.setdefault(cam.id, {"code": cam.code, "name": cam.name, "lon": cam.longitude, "lat": cam.latitude,
                                     "near_hotspot": int(near), "roi": cam.roi})
            rows[cam.id] |= {f"{key}{k}": v for key, v in r.items()}
            print(k, i, cam.code, r["ratio"] if r["ok"] else r["err"], flush=True)
            time.sleep(PAUSE_S)
    with open(OUT / "results.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(rows.values()))))
        w.writeheader()
        w.writerows(rows.values())
    print("ghi", OUT / "results.csv")


if __name__ == "__main__":
    main()
