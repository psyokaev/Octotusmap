from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.errors import register_error_handlers


def test_db_down_returns_503():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/x")
    def x():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    r = TestClient(app, raise_server_exceptions=False).get("/x")
    assert r.status_code == 503 and r.json()["error"]["code"] == "DB_UNAVAILABLE"
