"""Trạng thái dùng chung giữa các worker uvicorn nằm trong PostgreSQL, không trong bộ nhớ tiến trình."""

import json
import time

from sqlalchemy import text


def test_rate_limit_shared_between_instances(client):
    from app.core.security import RateLimiter

    a, b = RateLimiter(3, 60, name="t_shared"), RateLimiter(3, 60, name="t_shared")  # như 2 worker
    assert [a.allow("k"), b.allow("k"), a.allow("k"), b.allow("k")] == [True, True, True, False]
    assert RateLimiter(3, 60, name="t_other").allow("k")  # limiter khác tên không đếm chung


def test_events_go_through_postgres_notify(client):
    from app.services.events import bus

    assert bus.listening.wait(10)
    q = bus.subscribe(staff=False)
    try:
        bus.publish("cycle", {"seconds": 1.5, "issued_at": None, "alerts": 0})
        bus.publish("alert", {"id": 1}, public=False)  # nội bộ: khách không nhận
        deadline, got = time.time() + 10, []
        while time.time() < deadline and not got:
            time.sleep(0.1)
            while not q.empty():
                got.append(q.get_nowait())
        assert got and got[0].startswith("event: cycle")
        assert json.loads(got[0].split("data: ", 1)[1])["seconds"] == 1.5
        time.sleep(0.5)
        assert q.empty() and bus.last_cycle["seconds"] == 1.5
    finally:
        bus.unsubscribe(q)


def test_only_one_scheduler_leader(client):
    from app.core.database import engine
    from app.jobs import pipeline

    assert pipeline.is_leader()
    other = engine.connect().execution_options(isolation_level="AUTOCOMMIT")  # worker thứ hai
    try:
        assert other.execute(text("SELECT pg_try_advisory_lock(7340, 1)")).scalar() is False
        pipeline._leader.invalidate()  # worker giữ lịch chết: đóng hẳn kết nối -> PostgreSQL nhả khoá
        pipeline._leader = None
        assert other.execute(text("SELECT pg_try_advisory_lock(7340, 1)")).scalar() is True
        other.execute(text("SELECT pg_advisory_unlock(7340, 1)"))
    finally:
        other.close()
