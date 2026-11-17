"""Phát hiện vùng ngập trong ảnh camera: YOLOv8-seg (nếu có weights) hoặc HEURISTIC dự phòng."""

import threading
from dataclasses import dataclass

import cv2
import numpy as np

_models: dict[str, object] = {}
_lock = threading.Lock()


@dataclass
class DetectionResult:
    method: str  # YOLOV8_SEG / HEURISTIC
    flood_ratio: float
    confidence: float
    num_regions: int
    overlay: np.ndarray
    details: dict


def roi_mask(shape, roi: list | None) -> np.ndarray:
    h, w = shape[:2]
    m = np.zeros((h, w), np.uint8)
    pts = roi or [[0, 0.4], [1, 0.4], [1, 1], [0, 1]]  # mặc định: 60% phía dưới khung hình (mặt đường)
    cv2.fillPoly(m, [np.array([[int(x * w), int(y * h)] for x, y in pts], np.int32)], 1)
    return m


def _yolo(weights: str):
    with _lock:
        if weights not in _models:
            from ultralytics import YOLO

            _models[weights] = YOLO(weights)
        return _models[weights]


def _overlay(img, mask, roi):
    out = img.copy()
    color = np.zeros_like(img)
    color[:] = (255, 120, 0)  # xanh dương (BGR)
    a = (mask[..., None] > 0) * 0.5
    out = (out * (1 - a) + color * a).astype(np.uint8)
    cnts, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, cnts, -1, (0, 255, 255), 1)
    return out


def detect(img: np.ndarray, roi: list | None = None, weights: str | None = None, conf: float = 0.25) -> DetectionResult:
    rm = roi_mask(img.shape, roi)
    if weights:
        res = _yolo(weights).predict(img, imgsz=320, conf=conf, verbose=False, retina_masks=True)[0]
        mask = np.zeros(img.shape[:2], np.uint8)
        confs = []
        if res.masks is not None:
            for m in res.masks.data.cpu().numpy():
                mask |= (cv2.resize(m, (img.shape[1], img.shape[0])) > 0.5).astype(np.uint8)
            confs = res.boxes.conf.cpu().numpy().tolist()
        ratio = float((mask & rm).sum() / max(rm.sum(), 1))
        return DetectionResult("YOLOV8_SEG", round(ratio, 4), round(max(confs, default=0.0), 4), len(confs),
                               _overlay(img, mask, rm), {"box_confidences": [round(c, 3) for c in confs]})
    # Dự phòng HEURISTIC: ngưỡng màu nước đục (nâu/xám ánh vàng) trong HSV — KHÔNG phải YOLO
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (5, 40, 60), (30, 200, 200)) // 255
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _ = cv2.connectedComponents(mask)
    ratio = float((mask & rm).sum() / max(rm.sum(), 1))
    return DetectionResult("HEURISTIC", round(ratio, 4), 0.3, max(n - 1, 0), _overlay(img, mask, rm),
                           {"note": "Ước lượng theo màu, độ tin cậy thấp; chưa có trọng số YOLOv8-seg"})
