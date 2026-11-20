"""Lấy lùi mưa vệ tinh GPM IMERG theo ngày cho 24 quận (miễn phí, cần EARTHDATA_TOKEN trong backend/.env).

Chạy lại được: chỉ lấy ngày còn thiếu. Tuần tự, nghỉ 1 s giữa các request.
Chạy: PYTHONUTF8=1 .venv/Scripts/python scripts/import_imerg.py --start 2024-11-01 [--end YYYY-MM-DD]
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services import imerg_service  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2024, 11, 1))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(2))
    a = ap.parse_args()
    token = get_settings().earthdata_token
    if not token:
        sys.exit("Thiếu EARTHDATA_TOKEN trong backend/.env")
    with SessionLocal() as db:
        days = imerg_service.missing_days(db, a.start, a.end)
        print(f"{len(days)} ngày cần lấy")
        ok = 0
        for i, d in enumerate(days):
            try:
                ok += imerg_service.ingest_day(db, d, token) > 0
            except Exception as e:  # ngày lỗi: bỏ qua, lần chạy sau lấy lại
                print("lỗi", d, str(e)[:120])
            if i % 25 == 0:
                print(i, d, "ok", ok, flush=True)
            time.sleep(1)
    print("xong", ok, "ngày")


if __name__ == "__main__":
    main()
