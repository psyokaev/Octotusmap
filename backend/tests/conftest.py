"""Fixtures tích hợp: DB test riêng `urban_flood_dss_test`, migrate + seed DEMO rút gọn + mô hình nhỏ."""

import atexit
import os
import shutil
import tempfile

os.environ["POSTGRES_DATABASE"] = "urban_flood_dss_test"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DEMO_MODE"] = "true"
os.environ["CAMERA_ENABLED"] = "true"
for _k in ("STORAGE_DIR", "ARTIFACTS_DIR"):  # test không được ghi vào thư mục thật
    _d = tempfile.mkdtemp(prefix=f"octo_{_k.lower()}_")
    os.environ[_k] = _d
    atexit.register(shutil.rmtree, _d, ignore_errors=True)
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

import pytest  # noqa: E402

PASSWORDS = {"admin_t": "AdminPass123", "operator_t": "OperPass1234", "citizen_t": "UserPass1234"}


def _db_available() -> str | None:
    from sqlalchemy import create_engine, text

    from app.core.config import get_settings

    try:
        with create_engine(get_settings().server_url + "/postgres").connect() as c:
            c.execute(text("SELECT 1"))
        return None
    except Exception as e:  # báo lý do skip thay vì lỗi mù
        return f"PostgreSQL không kết nối được ({type(e).__name__}); điền POSTGRES_PASSWORD trong backend/.env"


@pytest.fixture(scope="session")
def db_ready():
    reason = _db_available()
    if reason:
        pytest.skip(reason)
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from app.core.config import BACKEND_DIR, get_settings

    s = get_settings()
    with create_engine(s.server_url + "/postgres", isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{s.postgres_database}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{s.postgres_database}"'))
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")

    from app import seed
    from app.ai.forecasting.train import train_and_register
    from app.core.database import SessionLocal
    from app.jobs import simulator
    from app.jobs.pipeline import run_cycle
    from app.services import user_service

    with SessionLocal() as db:
        seed.seed_base(db)
        seed.seed_areas(db)
        for u, roles in (("admin_t", ["ADMIN"]), ("operator_t", ["OPERATOR"]), ("citizen_t", ["USER"])):
            user_service.create_user(db, username=u, email=f"{u}@example.com", full_name=u, password=PASSWORDS[u],
                                     roles=roles, actor=None)
        seed.seed_demo_assets(db)
        simulator.ingest_until_now(db, history_days=21)
        seed.derive_flood_history(db)
        seed.update_susceptibility(db)
        train_and_register(db, cells=("gru",), epochs=1, log=lambda *_: None)
    run_cycle()
    return True


@pytest.fixture(scope="session")
def client(db_ready):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _token(client, user):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": PASSWORDS[user]})
    assert r.status_code == 200, r.text
    client.cookies.clear()  # chỉ dùng Bearer trong test để tách vai trò
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _token(client, "admin_t")


@pytest.fixture(scope="session")
def operator(client):
    return _token(client, "operator_t")


@pytest.fixture(scope="session")
def citizen(client):
    return _token(client, "citizen_t")


@pytest.fixture()
def db(db_ready):
    from app.core.database import SessionLocal

    with SessionLocal() as s:
        yield s
