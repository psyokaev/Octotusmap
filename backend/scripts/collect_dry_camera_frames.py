"""Thu ảnh camera giao thông TP.HCM lúc trời KHÔ làm ảnh nền (không có nước) để giảm báo giả của YOLOv8-seg.

- Chỉ chạy khi mưa 6 giờ qua của mọi điểm lưới <= 0,2 mm/h (dữ liệu trong CSDL), nếu không thì dừng.
- Chia theo CAMERA (không trùng camera giữa train/val/test) để đo báo giả trên camera chưa từng thấy.
- Ảnh không có file nhãn = ảnh nền trong YOLO. Ghi datasets/vision/hcm_dry/{images/<split>,meta.csv}
  và datasets/vision/flood_hcm/data.yaml (ảnh lũ Kaggle + ảnh nền TP.HCM). Chạy lại được (ban ngày/ban đêm) để thêm ảnh.
- Tuần tự, nghỉ 1 s giữa các request, dùng proxy/cache có sẵn (traffic_camera_service.snapshot).

Chạy: PYTHONUTF8=1 .venv/Scripts/python scripts/collect_dry_camera_frames.py [--n 300]
"""

import argparse
import csv
import random
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal, utcnow  # noqa: E402
from app.models import Camera, RainfallObservation  # noqa: E402
from app.services import traffic_camera_service as tc  # noqa: E402

DRY_MAX_MM, PAUSE_S = 0.2, 1.0
SPLITS = (("train", 0.7), ("val", 0.15), ("test", 0.15))


def split_of(code: str) -> str:
    """Tách theo camera, cố định qua các lần chạy (cùng camera luôn cùng tập)."""
    x = random.Random(code).random()
    acc = 0.0
    for name, frac in SPLITS:
        acc += frac
        if x < acc:
            return name
    return SPLITS[-1][0]


def write_yaml(root: Path) -> Path:
    y = root / "flood_hcm" / "data.yaml"
    y.parent.mkdir(parents=True, exist_ok=True)
    real, dry = (root / "flood_area_real").as_posix(), (root / "hcm_dry").as_posix()
    y.write_text(
        "# Ảnh lũ thật Kaggle (có nhãn) + ảnh camera TP.HCM lúc khô (ảnh nền, không nhãn)\n"
        + "".join(f"{s}:\n  - {real}/images/{s}\n  - {dry}/images/{s}\n" for s, _ in SPLITS)
        + "names:\n  0: flood_water\n", encoding="utf-8")
    return y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    a = ap.parse_args()
    root = get_settings().datasets_dir / "vision"
    out = root / "hcm_dry"
    with SessionLocal() as db:
        wet = db.scalar(select(func.max(RainfallObservation.rainfall_mm)).where(
            RainfallObservation.observed_at >= utcnow() - timedelta(hours=6)))
        if wet is None or wet > DRY_MAX_MM:
            sys.exit(f"Không thu: mưa 6 giờ qua lớn nhất {wet} mm/h (cần <= {DRY_MAX_MM})")
        cams = list(db.scalars(select(Camera).where(Camera.deleted_at.is_(None), Camera.status == "ACTIVE",
                                                    Camera.code.like(tc.CODE_PREFIX + "%")).order_by(Camera.id)))
    random.Random(int(time.time())).shuffle(cams)
    stamp = time.strftime("%Y%m%d%H%M")
    out.mkdir(parents=True, exist_ok=True)
    meta = out / "meta.csv"
    new = not meta.exists()
    ok = 0
    with open(meta, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["file", "split", "camera", "name", "taken_local", "rain_max_6h_mm"])
        for cam in cams[: a.n]:
            s = split_of(cam.code)
            try:
                raw = tc.snapshot(cam)
            except Exception as e:  # camera lỗi: bỏ qua
                print("lỗi", cam.code, getattr(e, "message", e))
                time.sleep(PAUSE_S)
                continue
            d = out / "images" / s
            d.mkdir(parents=True, exist_ok=True)
            name = f"{cam.code}_{stamp}.jpg"
            (d / name).write_bytes(raw)
            w.writerow([name, s, cam.code, cam.name, time.strftime("%Y-%m-%d %H:%M"), wet])
            ok += 1
            time.sleep(PAUSE_S)
    print(f"thu {ok} ảnh khô vào {out}; data.yaml: {write_yaml(root)}")


if __name__ == "__main__":
    main()
