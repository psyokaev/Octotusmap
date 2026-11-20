"""Client REST của backend FastAPI. Streamlit không bao giờ truy cập DB trực tiếp."""
import os
import re
import time

import httpx
import streamlit as st

DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"
TIMEOUT = 20.0
JWT_MAX_AGE_S = 480 * 60  # bằng jwt_expire_minutes của backend
_cache: dict = {}  # shortcut: cache trong tiến trình, xoá khi có thao tác ghi; đủ cho 1 worker


class ApiError(Exception):
    """Lỗi backend; `message` là thông điệp tiếng Việt của backend."""

    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def clear_cache() -> None:
    _cache.clear()


def base() -> str:
    return os.environ.get("API_BASE", DEFAULT_BASE).rstrip("/")


def root() -> str:
    b = base()
    return b[: -len("/api/v1")] if b.endswith("/api/v1") else b


def _clean(params: dict | None) -> dict:
    out = {}
    for k, v in (params or {}).items():
        if v is None or v == "" or v == []:
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else v
    return out


def _headers() -> dict:
    token = st.session_state.get("token")  # chỉ gửi đi, không bao giờ ghi log
    h = {"Authorization": f"Bearer {token}"} if token else {}
    try:  # giới hạn tần suất của backend tính theo IP người dùng, không phải IP máy chủ Streamlit
        ip = st.context.ip_address
    except Exception:  # ngoài phiên Streamlit (test, script)
        ip = None
    if ip:
        h["X-Forwarded-For"] = ip
    return h


def _err(res: httpx.Response) -> ApiError:
    try:
        e = (res.json() or {}).get("error") or {}
    except ValueError:
        e = {}
    if res.status_code == 401 and st.session_state.get("token"):  # phiên hết hạn
        st.session_state.pop("token", None)
        st.session_state.pop("user", None)
        st.session_state["auth_notice"] = "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại."
        st.session_state["cookie_clear"] = True
    return ApiError(res.status_code, e.get("code", "HTTP_ERROR"), e.get("message") or f"Lỗi {res.status_code}", e.get("details"))


def _send(method: str, url: str, **kw) -> httpx.Response:
    try:
        res = httpx.request(method, url, headers=_headers(), timeout=TIMEOUT, **kw)
    except httpx.HTTPError as e:
        raise ApiError(0, "NETWORK", "Không kết nối được máy chủ dữ liệu, thử lại sau.") from e
    if res.status_code >= 400:
        raise _err(res)
    return res


def request(method: str, path: str, *, params=None, json=None, data=None, files=None):
    res = _send(method, base() + path, params=_clean(params), json=json, data=data, files=files)
    if method != "GET":
        _cache.clear()
    return None if res.status_code == 204 or not res.content else res.json()


def get(path: str, params: dict | None = None, ttl: float = 0):
    """GET JSON; `ttl` giây > 0 thì cache theo (đường dẫn, tham số, token)."""
    if ttl <= 0:
        return request("GET", path, params=params)
    key = (path, repr(sorted(_clean(params).items())), st.session_state.get("token"))
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    val = request("GET", path, params=params)
    _cache[key] = (time.monotonic() + ttl, val)
    return val


def post(path: str, body=None, params=None):
    return request("POST", path, json=body, params=params)


def patch(path: str, body=None):
    return request("PATCH", path, json=body)


def put(path: str, body=None):
    return request("PUT", path, json=body)


def delete(path: str):
    return request("DELETE", path)


def upload(path: str, name: str, content: bytes, data: dict | None = None, field: str = "file", params: dict | None = None):
    """Tải tệp lên (multipart); `params` là query string."""
    return request("POST", path, data=data, files={field: (name, content)}, params=params)


def get_bytes(path: str, params: dict | None = None) -> bytes:
    """Nội dung nhị phân (ảnh camera)."""
    return _send("GET", base() + path, params=_clean(params)).content


def download(path: str, params: dict | None = None) -> tuple[str, bytes]:
    """Tải tệp xuất (Excel/CSV): trả (tên tệp, nội dung)."""
    res = _send("GET", base() + path, params=_clean(params))
    m = re.search(r'filename="([^"]+)"', res.headers.get("content-disposition", ""))
    return (m.group(1) if m else "bao_cao"), res.content


def health() -> dict:
    try:
        return httpx.get(root() + "/health", timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return {}
