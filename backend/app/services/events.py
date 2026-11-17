"""Pub/sub cho Server-Sent Events qua PostgreSQL LISTEN/NOTIFY: sự kiện phát ở worker nào cũng tới mọi worker."""

import asyncio
import json
import logging
import threading
import time

log = logging.getLogger(__name__)
CHANNEL = "octotusmap_events"


class EventBus:
    def __init__(self):
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self.listening = threading.Event()  # NOTIFY phát trước LISTEN bị PostgreSQL bỏ
        self.last_cycle: dict = {}  # chu kỳ pipeline gần nhất, đồng bộ giữa các worker qua sự kiện "cycle"

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is None:
            threading.Thread(target=self._listen, name="sse-listen", daemon=True).start()
        self._loop = loop

    def subscribe(self, staff: bool = False) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        q.staff = staff  # type: ignore[attr-defined]
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: str, data: dict, public: bool = True) -> None:
        """An toàn khi gọi từ thread nền (job). public=False -> chỉ gửi cho cán bộ."""
        if not self._loop:  # script/CLI không có server: không phát
            return
        from sqlalchemy import text

        from app.core.database import engine

        payload = json.dumps({"event": event, "data": data, "public": public}, ensure_ascii=False, default=str)
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_notify(:ch, :p)"), {"ch": CHANNEL, "p": payload})
        except Exception:  # mất sự kiện SSE không được làm hỏng nghiệp vụ đang chạy
            log.exception("pg_notify failed")

    def dispatch(self, payload: str) -> None:
        m = json.loads(payload)
        if m["event"] == "cycle":
            self.last_cycle.clear()
            self.last_cycle.update(m["data"])
        msg = f"event: {m['event']}\ndata: {json.dumps(m['data'], ensure_ascii=False)}\n\n"
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            if m["public"] or q.staff:
                self._loop.call_soon_threadsafe(_put, q, msg)

    def _listen(self) -> None:
        import psycopg

        from app.core.config import get_settings

        url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        while True:
            try:
                # keepalive: kết nối chết âm thầm thì notifies() không treo mãi
                with psycopg.connect(url, autocommit=True, connect_timeout=10, keepalives=1,
                                     keepalives_idle=30) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    self.listening.set()
                    for n in conn.notifies():
                        self.dispatch(n.payload)
            except Exception:
                self.listening.clear()
                log.exception("SSE listener mất kết nối, thử lại sau 5 s")
                time.sleep(5)


def _put(q: asyncio.Queue, msg: str) -> None:
    if not q.full():
        q.put_nowait(msg)


bus = EventBus()
