"""Chuyển Kaggle "Flood Area Segmentation" (mask nhị phân) sang YOLO-seg, chia train/val/test 70/15/15 (seed cố định).

Chạy từ thư mục khác dữ liệu: python -I scripts/prepare_flood_area_real.py
"""

import random
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2] / "datasets" / "vision" / "flood_area_real"
MAX_SIDE, MIN_AREA = 640, 0.002  # thu nhỏ ảnh; bỏ vùng < 0.2% khung hình (nhiễu mask)


def mask_to_label(mask, min_area: float = MIN_AREA) -> str:
    """Mask nhị phân -> các dòng 'class x1 y1 x2 y2 ...' (toạ độ chuẩn hoá), mỗi vùng ngoài một dòng."""
    h, w = mask.shape[:2]
    cnts, _ = cv2.findContours((mask > 127).astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lines = []
    for c in cnts:
        if cv2.contourArea(c) < min_area * w * h:
            continue
        c = cv2.approxPolyDP(c, 0.003 * cv2.arcLength(c, True), True).reshape(-1, 2)
        if len(c) >= 3:
            lines.append("0 " + " ".join(f"{x / w:.5f} {y / h:.5f}" for x, y in c))
    return "\n".join(lines) + ("\n" if lines else "")


def main() -> None:
    raw = ROOT / "raw"
    names = sorted(p.stem for p in (raw / "Image").glob("*.jpg"))
    random.Random(42).shuffle(names)
    n = len(names)
    cut = {"train": names[: int(n * .7)], "val": names[int(n * .7): int(n * .85)], "test": names[int(n * .85):]}
    for split, items in cut.items():
        (ROOT / "images" / split).mkdir(parents=True, exist_ok=True)
        (ROOT / "labels" / split).mkdir(parents=True, exist_ok=True)
        for s in items:
            img, m = cv2.imread(str(raw / "Image" / f"{s}.jpg")), cv2.imread(str(raw / "Mask" / f"{s}.png"), 0)
            if img is None or m is None:
                continue
            k = MAX_SIDE / max(img.shape[:2])
            if k < 1:
                img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
                m = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(str(ROOT / "images" / split / f"{s}.jpg"), img)
            (ROOT / "labels" / split / f"{s}.txt").write_text(mask_to_label(m), encoding="utf-8")
    (ROOT / "data.yaml").write_text(
        f"# Kaggle Flood Area Segmentation (faizalkarim, CC0) - ảnh THẬT, mask -> polygon\npath: {ROOT.as_posix()}\n"
        "train: images/train\nval: images/val\ntest: images/test\nnames:\n  0: flood_water\n", encoding="utf-8")
    print({k: len(v) for k, v in cut.items()})


if __name__ == "__main__":
    main()
