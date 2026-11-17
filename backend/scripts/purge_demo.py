"""Xoá toàn bộ dữ liệu MÔ PHỎNG (DEMO) để chuyển sang dữ liệu thật. Sao lưu DB trước khi chạy.

Chạy từ thư mục backend:  .venv\\Scripts\\python scripts\\purge_demo.py --yes
Giữ lại: tài khoản, vai trò, ranh giới hành chính, nguồn dữ liệu, quy tắc, cấu hình, audit log, mô hình YOLO.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SIM_STATIONS = ("SELECT id FROM monitoring_stations WHERE source_id IN (SELECT id FROM data_sources WHERE is_simulated) "
                "OR code LIKE 'E2E%' OR code LIKE '007%'")
STEPS = [
    "DELETE FROM notifications",
    "DELETE FROM alert_history WHERE alert_id IN (SELECT id FROM alerts WHERE is_simulated)",
    "DELETE FROM alerts WHERE is_simulated",
    "DELETE FROM flood_risk_snapshots",  # toàn bộ snapshot hiện có sinh từ dữ liệu mô phỏng
    "DELETE FROM forecasts WHERE is_simulated OR station_id IN (" + SIM_STATIONS + ")",
    "DELETE FROM camera_detections",
    "DELETE FROM camera_frames",
    "DELETE FROM cameras WHERE source_id IN (SELECT id FROM data_sources WHERE is_simulated)",
    "DELETE FROM rainfall_observations WHERE is_simulated OR station_id IN (" + SIM_STATIONS + ")",
    "DELETE FROM water_level_observations WHERE is_simulated OR station_id IN (" + SIM_STATIONS + ")",
    "DELETE FROM historical_flood_events WHERE is_simulated",
    "DELETE FROM sensors WHERE station_id IN (" + SIM_STATIONS + ")",
    "DELETE FROM monitoring_stations WHERE id IN (SELECT id FROM (" + SIM_STATIONS + ") x)",
    "DELETE FROM training_runs WHERE model_version_id IN (SELECT id FROM model_versions WHERE trained_on_simulated "
    "AND model_type IN ('LSTM','GRU','BASELINE')) OR (task='FORECAST')",
    "DELETE FROM model_versions WHERE trained_on_simulated AND model_type IN ('LSTM','GRU','BASELINE')",
    "UPDATE administrative_areas SET susceptibility=0.2",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="xác nhận xoá")
    if not ap.parse_args().yes:
        sys.exit("Thêm --yes để xác nhận (đã sao lưu DB chưa?)")
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.database import engine

    if not get_settings().demo_mode:  # DB đang chạy dữ liệu thật: không xoá
        sys.exit("DEMO_MODE=false: từ chối xoá dữ liệu. Chỉ chạy script này khi DEMO_MODE=true.")
    with engine.begin() as c:  # một transaction: lỗi giữa chừng -> rollback toàn bộ
        for sql in STEPS:
            n = c.execute(text(sql)).rowcount
            print(f"{n:>8}  {sql[:90]}")
        left = c.execute(text("SELECT (SELECT COUNT(*) FROM rainfall_observations WHERE is_simulated)"
                              " + (SELECT COUNT(*) FROM water_level_observations WHERE is_simulated)")).scalar()
        assert left == 0, left
    shutil.rmtree(get_settings().storage_dir / "camera", ignore_errors=True)
    print("Đã xoá dữ liệu mô phỏng. Đặt DEMO_MODE=false trong .env rồi chạy scripts/bootstrap.py.")


if __name__ == "__main__":
    main()
