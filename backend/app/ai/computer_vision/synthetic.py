"""Sinh ảnh cảnh đường phố MÔ PHỎNG có vùng nước ngập + nhãn segmentation (YOLO format).

Đây là dữ liệu SIMULATED để kiểm chứng pipeline huấn luyện/suy luận YOLOv8-seg khi
chưa có bộ ảnh camera ngập thật đã gán nhãn. Mô hình huấn luyện trên dữ liệu này
KHÔNG được coi là đã kiểm chứng trên camera thực tế.

Chạy: python -m app.ai.computer_vision.synthetic --n 240
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

W, H = 320, 240
CLASS_NAMES = ["flood_water"]


def _layout(rng: np.random.Generator) -> dict:
    return {
        "sky": rng.integers(150, 230, 3).tolist(),
        "buildings": [(int(x), int(rng.integers(20, 90)), int(rng.integers(30, 70)),
                       rng.integers(60, 200, 3).tolist()) for x in np.sort(rng.integers(0, W, 7))],
        "horizon": int(rng.integers(85, 115)),
        "road_top": (int(rng.integers(120, 150)), int(rng.integers(170, 200))),
        "road_grey": int(rng.integers(70, 120)),
        "cars": [(int(rng.integers(20, W - 60)), int(rng.integers(150, 210)), rng.integers(30, 230, 3).tolist())
                 for _ in range(int(rng.integers(0, 4)))],
    }


def render(layout: dict, water_level: float, rng: np.random.Generator):
    """Vẽ cảnh; water_level 0..1 (0 = khô). Trả (ảnh BGR, polygon nước [(x,y)...] hoặc None)."""
    img = np.zeros((H, W, 3), np.uint8)
    hz = layout["horizon"]
    for y in range(hz):
        img[y] = np.array(layout["sky"]) * (0.7 + 0.3 * y / hz)
    for x, top, bw, color in layout["buildings"]:
        cv2.rectangle(img, (x, top), (min(x + bw, W - 1), hz), color, -1)
        for wy in range(top + 6, hz - 6, 12):
            for wx in range(x + 4, min(x + bw, W) - 6, 10):
                cv2.rectangle(img, (wx, wy), (wx + 4, wy + 5), (210, 220, 230), -1)
    img[hz:] = (60, 120, 70)  # vỉa hè / cây xanh
    l, r = layout["road_top"]
    g = layout["road_grey"]
    road = np.array([[l, hz], [r, hz], [W, H], [0, H]], np.int32)
    cv2.fillPoly(img, [road], (g, g, g + 5))
    for y in range(hz + 8, H, 22):
        cx = int((l + r) / 2 + (y - hz) * 0)
        cv2.line(img, (cx, y), (cx, min(y + 10, H)), (230, 230, 230), 2)
    for x, y, c in layout["cars"]:
        cv2.rectangle(img, (x, y - 18), (x + 46, y), c, -1)
        cv2.circle(img, (x + 10, y), 5, (20, 20, 20), -1)
        cv2.circle(img, (x + 36, y), 5, (20, 20, 20), -1)

    poly = None
    if water_level > 0.03:
        top = int(H - water_level * (H - hz) * 0.95)
        xs = np.linspace(0, W, 14)
        edge = [(int(x), int(np.clip(top + rng.normal(0, 4) + 6 * np.sin(x / 25), hz, H - 2))) for x in xs]
        poly = np.array(edge + [(W, H), (0, H)], np.int32)
        mask = np.zeros((H, W), np.uint8)
        cv2.fillPoly(mask, [poly], 255)
        water = np.empty_like(img)
        water[:] = (rng.integers(60, 95), rng.integers(95, 130), rng.integers(120, 160))  # nâu đục (BGR)
        noise = rng.normal(0, 9, (H, W, 1))
        ripples = (8 * np.sin(np.arange(H)[:, None] / 2.5 + rng.uniform(0, 6))).astype(np.float32)[..., None]
        reflect = cv2.flip(img, 0)
        water = np.clip(0.65 * water + 0.2 * reflect + noise + ripples, 0, 255).astype(np.uint8)
        a = (mask[..., None] / 255.0) * 0.92
        img = (img * (1 - a) + water * a).astype(np.uint8)
        poly = [(int(x), int(y)) for x, y in poly]
    img = np.clip(img + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    return img, poly


def yolo_seg_label(poly) -> str:
    coords = " ".join(f"{x / W:.5f} {y / H:.5f}" for x, y in poly)
    return f"0 {coords}\n"


def generate_dataset(root: Path, n: int = 240, seed: int = 11, val_frac: float = 0.2) -> Path:
    rng = np.random.default_rng(seed)
    for split in ("train", "val"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)
    for i in range(n):
        split = "val" if i < n * val_frac else "train"
        level = 0.0 if rng.random() < 0.2 else float(rng.uniform(0.08, 0.9))
        img, poly = render(_layout(rng), level, rng)
        cv2.imwrite(str(root / "images" / split / f"img_{i:04d}.jpg"), img)
        (root / "labels" / split / f"img_{i:04d}.txt").write_text(yolo_seg_label(poly) if poly else "", encoding="utf-8")
    yaml = root / "data.yaml"
    yaml.write_text(
        f"# SIMULATED dataset — sinh tự động, không phải ảnh camera thật\n"
        f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: flood_water\n", encoding="utf-8")
    return yaml


def camera_frame(camera_code: str, water_level: float, tick: int):
    """Khung hình DEMO cho camera: bố cục cố định theo camera, mực nước theo dữ liệu mô phỏng."""
    seed = sum(map(ord, camera_code))
    layout = _layout(np.random.default_rng(seed))
    img, _ = render(layout, water_level, np.random.default_rng(seed * 1000 + tick))
    cv2.putText(img, f"DEMO/SIMULATED {camera_code}", (6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return img


if __name__ == "__main__":
    from app.core.config import get_settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=240)
    a = ap.parse_args()
    print(generate_dataset(get_settings().datasets_dir / "vision" / "synthetic", a.n))
