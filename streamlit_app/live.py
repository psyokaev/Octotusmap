"""Cập nhật tức thì: một luồng nền nghe SSE của backend, mỗi phiên trình duyệt kiểm tra bộ đếm sự kiện mỗi 3 giây.

Trình duyệt không cần nối tới backend (chạy được cả trong Docker); luồng nghe ẩn danh nên chỉ nhận sự kiện công khai
(chu kỳ dữ liệu mới, cảnh báo công khai, báo cáo ngập).
"""
import logging
import os
import threading
import time

import api
import httpx
import streamlit as st

log = logging.getLogger(__name__)
POLL_S = 3


class _Counter:
    def __init__(self):
        self.n = 0
        self.lock = threading.Lock()

    def bump(self):
        with self.lock:
            self.n += 1


def _listen(c: _Counter) -> None:
    while True:
        try:
            with httpx.stream("GET", api.base() + "/events", timeout=httpx.Timeout(10, read=60)) as r:
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        c.bump()
        except Exception:  # backend tắt/khởi động lại: thử lại sau
            log.debug("SSE ngắt, thử lại", exc_info=True)
        time.sleep(5)


@st.cache_resource
def _counter() -> _Counter:
    c = _Counter()
    if os.environ.get("LIVE_EVENTS", "1") != "0":  # tắt trong kiểm thử
        threading.Thread(target=_listen, args=(c,), daemon=True, name="sse-listener").start()
    return c


@st.fragment(run_every=POLL_S)
def watch() -> None:
    n = _counter().n
    prev = st.session_state.get("live-n")
    st.session_state["live-n"] = n
    if prev is not None and n != prev:
        api.clear_cache()
        st.rerun(scope="app")
