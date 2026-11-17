"""Khởi tạo toàn bộ hệ thống: DB -> migrations -> seed -> (DEMO) dữ liệu mô phỏng -> huấn luyện -> chu kỳ đầu.

Chạy từ thư mục backend:  .venv\\Scripts\\python scripts\\bootstrap.py [--skip-train] [--vision-epochs 15]
Idempotent: chạy lại an toàn.
"""

import argparse
import re
import secrets
import string
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _random_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.isdigit() for c in p) and any(c.isalpha() for c in p):
            return p


def _env_set(key: str, value: str) -> None:
    env = BACKEND / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    if re.search(rf"^{key}=", text, re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text += f"\n{key}={value}\n"
    env.write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-train", action="store_true")
    ap.add_argument("--forecast-epochs", type=int, default=8)
    ap.add_argument("--vision-epochs", type=int, default=15)
    a = ap.parse_args()

    env_text = (BACKEND / ".env").read_text(encoding="utf-8") if (BACKEND / ".env").exists() else ""
    vals = dict(re.findall(r"^([A-Z_]+)=(.*)$", env_text, re.M))
    created = []
    if not vals.get("JWT_SECRET"):
        _env_set("JWT_SECRET", secrets.token_urlsafe(48))
    for key, user in (("ADMIN_PASSWORD", vals.get("ADMIN_USERNAME") or "admin"), ("OPERATOR_PASSWORD", "operator"),
                      ("DEMO_USER_PASSWORD", "citizen")):
        if not vals.get(key):
            pw = _random_password()
            _env_set(key, pw)
            created.append((user, pw))

    from app.core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    from sqlalchemy import create_engine, text

    print(f"[1/7] Kết nối PostgreSQL {s.postgres_host}:{s.postgres_port} và tạo database \"{s.postgres_database}\"")
    eng = create_engine(s.server_url + "/postgres", isolation_level="AUTOCOMMIT")  # CREATE DATABASE cần autocommit
    with eng.connect() as c:
        ver = c.execute(text("SHOW server_version")).scalar()
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": s.postgres_database}).scalar():
            c.execute(text(f'CREATE DATABASE "{s.postgres_database}"'))
    print(f"      PostgreSQL {ver}")

    print("[2/7] Chạy Alembic migrations")
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")

    from app import seed
    from app.core.database import SessionLocal
    from app.models import User
    from app.services import user_service

    print("[3/7] Seed vai trò, nguồn dữ liệu, cấu hình, quy tắc cảnh báo, ranh giới hành chính")
    with SessionLocal() as db:
        seed.seed_base(db)
        print(f"      +{seed.seed_areas(db)} khu vực")
        env = dict(re.findall(r"^([A-Z_]+)=(.*)$", (BACKEND / ".env").read_text(encoding="utf-8"), re.M))
        from sqlalchemy import select

        accounts = [(s.admin_username, s.admin_email, "Quản trị hệ thống", env["ADMIN_PASSWORD"], ["ADMIN"])]
        if s.demo_mode:
            accounts += [("operator", "operator@example.com", "Cán bộ vận hành (DEMO)", env["OPERATOR_PASSWORD"],
                          ["OPERATOR"]),
                         ("citizen", "citizen@example.com", "Người dân (DEMO)", env["DEMO_USER_PASSWORD"], ["USER"])]
        for username, email, full, pw, roles in accounts:
            if not db.scalar(select(User.id).where(User.username == username)):
                user_service.create_user(db, username=username, email=email, full_name=full, password=pw,
                                         roles=roles, actor=None)

        if s.demo_mode:
            print("[4/7] DEMO: trạm/camera mô phỏng + 120 ngày dữ liệu mô phỏng")
            seed.seed_demo_assets(db)
            from app.jobs import simulator

            print(f"      +{simulator.ingest_until_now(db)} bản ghi quan trắc mô phỏng")
            print(f"      +{seed.derive_flood_history(db)} sự kiện ngập lịch sử mô phỏng")
            seed.update_susceptibility(db)
        else:
            print("[4/7] LIVE: điểm lưới Open-Meteo, điểm ngập công bố, dữ liệu mưa/triều 2 năm")
            print(f"      +{seed.seed_openmeteo_points(db)} điểm dữ liệu, +{seed.seed_hotspots(db)} điểm ngập")
            seed.update_susceptibility_from_hotspots(db)
            from app.models import RainfallObservation
            from app.services import openmeteo_service

            if not db.scalar(select(RainfallObservation.id).limit(1)):
                print(f"      +{openmeteo_service.ingest_history(db)} bản ghi Open-Meteo")
            import subprocess

            for script in ("import_wards.py", "import_traffic_cameras.py", "import_flood_events.py"):
                subprocess.run([sys.executable, str(BACKEND / "scripts" / script)], check=True)  # noqa: S603
        print("      Kiểm tra:", seed.check(db))

        from app.models import ModelVersion

        has_fc = db.scalar(select(ModelVersion.id).where(ModelVersion.is_active.is_(True),
                                                         ModelVersion.model_type.in_(["LSTM", "GRU"])))
        has_cv = db.scalar(select(ModelVersion.id).where(ModelVersion.is_active.is_(True),
                                                         ModelVersion.model_type == "YOLOV8_SEG"))
        if a.skip_train:
            print("[5/7] Bỏ qua huấn luyện (--skip-train)")
        else:
            if not has_fc:
                print("[5/7] Huấn luyện LSTM/GRU dự báo mưa & xác suất ngập")
                from app.ai.forecasting.train import train_and_register as tf

                tf(db, epochs=a.forecast_epochs)
            if not has_cv and s.camera_enabled:
                print("[6/7] Huấn luyện YOLOv8-seg phát hiện vùng ngập (dataset mô phỏng)")
                from app.ai.computer_vision.train import train_and_register as tv

                tv(db, epochs=a.vision_epochs)

    if s.demo_mode and not a.skip_train:
        from app.jobs.backfill import backfill

        print("[6b] DEMO: chạy lại pipeline cho 14 ngày mô phỏng gần nhất (lịch sử dự báo/cảnh báo)")
        with SessionLocal() as db:
            print(f"      {backfill(db)} chu kỳ giờ")

    print("[7/7] Chạy chu kỳ đầu: dự báo -> rule engine -> cảnh báo")
    from app.jobs.pipeline import run_cycle

    out = run_cycle()
    print("      ", {k: v for k, v in out.items() if k != "forecast"})
    print("\nHoàn tất. Tài khoản ban đầu:")
    for u, pw in created:
        print(f"   {u:10s} mật khẩu: {pw}   (chỉ hiển thị lần này; lưu trong backend/.env)")
    if not created:
        print("   Mật khẩu lấy từ backend/.env (ADMIN_PASSWORD / OPERATOR_PASSWORD / DEMO_USER_PASSWORD)")


if __name__ == "__main__":
    main()
