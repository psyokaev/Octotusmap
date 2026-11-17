"""Huấn luyện / đánh giá YOLOv8-seg phát hiện vùng nước ngập.

Chạy: python -m app.ai.computer_vision.train --epochs 15
Mặc định dùng dataset MÔ PHỎNG (datasets/vision/synthetic). Để dùng ảnh thật, truyền
--data đến data.yaml của bộ ảnh đã gán nhãn polygon (Roboflow/CVAT xuất YOLO-seg).
"""

import argparse
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.ai.computer_vision.synthetic import generate_dataset


def evaluate(weights: str, data_yaml: Path, split: str = "test", imgsz: int = 320) -> dict:
    """Đo mAP/precision/recall (mask) của một trọng số trên tập `split` của data.yaml."""
    from ultralytics import YOLO

    m = YOLO(weights).val(data=str(data_yaml), split=split, imgsz=imgsz, device="cpu", workers=0, plots=False,
                          verbose=False)
    return {"box_map50": float(m.box.map50), "box_map50_95": float(m.box.map),
            "mask_map50": float(m.seg.map50), "mask_map50_95": float(m.seg.map),
            "precision": float(m.seg.mp), "recall": float(m.seg.mr)}


def train(data_yaml: Path, out_dir: Path, epochs: int = 15, imgsz: int = 320, log=print) -> dict:
    from ultralytics import YOLO

    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / "yolov8n-seg.pt"
    model = YOLO(str(base) if base.exists() else "yolov8n-seg.pt")  # tải trọng số COCO để fine-tune
    t0 = time.time()
    version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    model.train(data=str(data_yaml), epochs=epochs, imgsz=imgsz, batch=16, device="cpu", workers=0,
                project=str(out_dir / "runs"), name=version, exist_ok=True, plots=False, verbose=False,
                seed=0, deterministic=True)
    secs = time.time() - t0
    run_dir = out_dir / "runs" / version
    best = run_dir / "weights" / "best.pt"
    final = YOLO(str(best))
    m = final.val(data=str(data_yaml), imgsz=imgsz, device="cpu", workers=0, plots=False, verbose=False)
    metrics = {
        "box_map50": float(m.box.map50), "box_map50_95": float(m.box.map),
        "mask_map50": float(m.seg.map50), "mask_map50_95": float(m.seg.map),
        "precision": float(m.box.mp), "recall": float(m.box.mr),
    }
    dest = out_dir / f"yolov8n-seg-{version}"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(best, dest / "best.pt")
    log(f"YOLOv8-seg {version}: {metrics} ({secs:.0f}s)")
    return {"version": version, "weights": str(dest / "best.pt"), "metrics": metrics, "seconds": secs,
            "params": {"epochs": epochs, "imgsz": imgsz, "base": "yolov8n-seg (COCO)"}}


REAL_DESCRIPTION = ("Kaggle 'Flood Area Segmentation' (faizalkarim, CC0): 290 ảnh lũ THẬT có mask, "
                    "chuyển polygon YOLO-seg, chia 70/15/15")


def train_and_register(db, epochs: int = 15, data_yaml: Path | None = None, log=print, imgsz: int = 320,
                       description: str = REAL_DESCRIPTION) -> dict:
    """Ảnh thật (data_yaml): đo trên tập test, chỉ kích hoạt nếu mask mAP50 vượt mô hình đang dùng."""
    from app.core.config import get_settings
    from app.core.database import utcnow
    from app.models import ModelVersion, TrainingRun

    s = get_settings()
    simulated = data_yaml is None
    if simulated:
        data_yaml = generate_dataset(s.datasets_dir / "vision" / "synthetic")
    run = TrainingRun(task="VISION", params={"epochs": epochs, "data": str(data_yaml)})
    db.add(run)
    db.commit()
    try:
        res = train(data_yaml, s.artifacts_dir / "vision", epochs, imgsz, log=log)
    except Exception as e:
        run.status, run.finished_at, run.log = "FAILED", utcnow(), repr(e)
        db.commit()
        raise
    activate, old_test = True, None
    if not simulated:
        res["val_metrics"], res["metrics"] = res["metrics"], evaluate(res["weights"], data_yaml, "test", imgsz)
        old = db.scalar(select(ModelVersion).where(ModelVersion.model_type == "YOLOV8_SEG",
                                                   ModelVersion.is_active.is_(True)))
        if old and Path(old.artifact_path).exists():
            old_test = res["old_test_metrics"] = evaluate(old.artifact_path, data_yaml, "test", imgsz)
            activate = res["metrics"]["mask_map50"] > old_test["mask_map50"]
        res["activated"] = activate
        res["params"] |= {"eval_split": "test", "old_test_metrics": old_test, "val_metrics": res["val_metrics"]}
        log(f"test mới={res['metrics']} cũ={old_test} -> kích hoạt={activate}")
    if simulated:  # mô hình huấn luyện trên ảnh mô phỏng không bao giờ thay mô hình ảnh thật đang dùng
        real_active = db.scalar(select(ModelVersion.id).where(
            ModelVersion.model_type == "YOLOV8_SEG", ModelVersion.is_active.is_(True),
            ModelVersion.trained_on_simulated.is_(False)).limit(1))
        if real_active:
            activate = res["activated"] = False
            log("Mô hình mô phỏng không thay mô hình ảnh thật đang dùng -> không kích hoạt")
    if activate:
        db.query(ModelVersion).filter(ModelVersion.model_type == "YOLOV8_SEG").update(
            {"is_active": False, "status": "ARCHIVED"})
    mv = ModelVersion(
        name="flood-yolov8n-seg", model_type="YOLOV8_SEG", version=res["version"], artifact_path=res["weights"],
        dataset_description=("Ảnh đường phố MÔ PHỎNG (SIMULATED) sinh tự động, nhãn polygon vùng nước"
                             if simulated else description),
        trained_on_simulated=simulated, metrics=res["metrics"], params=res["params"],
        status="DEPLOYED" if activate else "TRAINED", is_active=activate, trained_at=utcnow(),
        training_seconds=res["seconds"])
    db.add(mv)
    db.flush()
    run.model_version_id, run.status, run.finished_at, run.metrics = mv.id, "SUCCESS", utcnow(), res["metrics"]
    db.commit()
    return res


if __name__ == "__main__":
    from app.core.database import SessionLocal

    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--data", type=Path, default=None)
    ap.add_argument("--imgsz", type=int, default=320)
    a = ap.parse_args()
    with SessionLocal() as sess:
        print(train_and_register(sess, a.epochs, a.data, imgsz=a.imgsz)["metrics"])
