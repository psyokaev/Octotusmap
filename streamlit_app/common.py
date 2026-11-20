"""Định dạng, màu rủi ro và nguyên nhân ngập. Khớp frontend/src/lib/{risk,format}.ts và routeStyle.ts."""
from datetime import date, datetime, time, timedelta, timezone

import api
import streamlit as st
from streamlit.errors import StreamlitAPIException

VN_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh, không có giờ mùa hè

RISK = {
    "LOW": {"color": "#2E8B57", "label": "Thấp", "symbol": "●"},
    "MEDIUM": {"color": "#D99A00", "label": "Trung bình", "symbol": "▲"},
    "HIGH": {"color": "#C62828", "label": "Cao", "symbol": "◆"},
    "INSUFFICIENT_DATA": {"color": "#8A949C", "label": "Không đủ dữ liệu", "symbol": "○"},
    "NO_DATA": {"color": "#8A949C", "label": "Không có dữ liệu", "symbol": "○"},
}
RISK_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INSUFFICIENT_DATA": 0, "NO_DATA": -1}
STATUS_VI = {"NEW": "Mới", "ACKNOWLEDGED": "Đã tiếp nhận", "IN_PROGRESS": "Đang xử lý", "RESOLVED": "Đã xử lý", "CLOSED": "Đã đóng"}
CAUSE_VI = {"RAIN": "Mưa", "TIDE": "Triều cường", "RAIN_TIDE": "Mưa kết hợp triều", "OTHER": "Khác",
            "SIMULATION": "Mô phỏng"}
FLOOD_CAUSE = {
    "TIDE": "Ngập do triều", "RAIN": "Ngập do mưa", "RAIN_TIDE": "Ngập do mưa kết hợp triều", "REPORT": "Người dân báo ngập",
    "CAMERA": "Camera phát hiện ngập (mô hình thử nghiệm, tham khảo)",
    "STORM": "Nguy cơ mưa dông cục bộ (ước tính)",
    "SIMULATION": "MÔ PHỎNG: ngập giả định do admin tạo",
}
# trạng thái đoạn đường (routeStyle.ts)
STATUS = {
    "DRY": {"color": "#1A73E8", "label": "Không có dấu hiệu ngập"},
    "AT_RISK": {"color": "#F29900", "label": "Có nguy cơ ngập"},
    "LIKELY_FLOODED": {"color": "#D93025", "label": "Có thể đang ngập"},
    "REPORTED_FLOODED": {"color": "#8E24AA", "label": "Người dân báo ngập"},
}
SEVERITY = {"ANKLE": "Ngập mắt cá", "KNEE": "Ngập đầu gối", "DEEP": "Ngập sâu"}
_MD_COLOR = {"HIGH": "red", "MEDIUM": "orange", "LOW": "green"}


def risk_of(r) -> str:
    return r if r in RISK else "NO_DATA"


def risk_text(level) -> str:
    r = RISK[risk_of(level)]
    return f"{r['symbol']} {r['label']}"


def risk_md(level) -> str:
    """Nhãn màu cho st.markdown (ký hiệu hình dạng đi kèm màu, không chỉ dựa vào màu)."""
    return f":{_MD_COLOR.get(level, 'gray')}[**{risk_text(level)}**]"


def risk_badge(level) -> str:
    """Chip màu như bản React (chỉ dùng được trong nhãn/markdown của Streamlit)."""
    return f":{_MD_COLOR.get(level, 'gray')}-badge[{risk_text(level)}]"


def flood_cause(cause=None, depth_cm=None) -> str | None:
    """Nguyên nhân ngập + độ sâu ước tính (cm); None khi không có nguyên nhân."""
    phrase = FLOOD_CAUSE.get(cause) if cause else None
    if not phrase:
        return None
    if depth_cm is None:
        return phrase
    return f"{phrase}, khoảng {depth_cm:g} cm" + ("" if cause == "SIMULATION" else " (ước tính)")


def parse_dt(iso) -> datetime | None:
    if not iso:
        return None
    d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)  # backend lưu UTC


def fmt_dt(iso) -> str:
    d = parse_dt(iso)
    return d.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M") if d else "—"


def fmt_time(iso) -> str:
    d = parse_dt(iso)
    return d.astimezone(VN_TZ).strftime("%H:%M") if d else "—"


def fmt_num(v, unit: str = "") -> str:
    if v is None:
        return "—"
    s = f"{v:,.1f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return (s[:-2] if s.endswith(",0") else s) + unit


def fmt_dec(v, digits: int = 3) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def fmt_pct(v) -> str:
    return "—" if v is None else f"{round(v * 100)}%"


def fmt_duration(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m} phút" if m < 60 else f"{m // 60} giờ {m % 60} phút"


def fmt_distance(meters: float) -> str:
    return f"{round(meters / 10) * 10} m" if meters < 1000 else f"{meters / 1000:.1f} km"


def _utc_iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def vn_date_to_iso(d: date | None, end: bool = False) -> str | None:
    """Ngày VN -> ISO UTC; end = đầu ngày hôm sau (khoảng [from, to))."""
    if not d:
        return None
    return _utc_iso(datetime.combine(d, time.min, tzinfo=VN_TZ) + (timedelta(days=1) if end else timedelta()))


def vn_local_to_iso(d: date, t: time) -> str:
    return _utc_iso(datetime.combine(d, t, tzinfo=VN_TZ))


_MD_SPECIAL = set(r"\`*_{}[]()<>#+-.!|~$&")


def esc_md(s) -> str:
    """Văn bản người dùng nhập -> Markdown an toàn (không dựng ảnh/liên kết tải từ ngoài)."""
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in str(s))


def err_text(e: Exception) -> str:
    """Thông báo lỗi kèm chi tiết validation (422)."""
    if not isinstance(e, api.ApiError):
        return "Đã có lỗi xảy ra"
    parts = []
    for x in e.details if isinstance(e.details, list) else []:
        parts.append(x if isinstance(x, str) else f"{'.'.join(str(p) for p in x.get('loc', []) if p != 'body')}: {x.get('msg', '')}")
    return f"{e.message} — {'; '.join(parts)}" if parts else e.message


def show_error(e: Exception) -> None:
    st.error(err_text(e))


def refresh() -> None:
    """Vẽ lại fragment đang chạy; ngoài lần chạy fragment (tải trang đầu, AppTest) thì vẽ lại cả trang."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def run_action(fn, ok: str) -> bool:
    """Chạy thao tác ghi, báo kết quả bằng toast/lỗi. True nếu thành công."""
    try:
        fn()
    except api.ApiError as e:
        show_error(e)
        return False
    st.toast(ok)
    return True


def sim_badge(on: bool = True) -> str:
    return ":orange[**Mô phỏng**]" if on else ""


def areas() -> list[dict]:
    try:
        return api.get("/gis/areas", ttl=300) or []
    except api.ApiError:
        return []


def area_select(label: str, key: str) -> int | None:
    opts = {"Tất cả khu vực": None} | {a["name"]: a["id"] for a in areas()}
    return opts[st.selectbox(label, list(opts), key=key)]


def pager(key: str, total: int, size: int) -> int:
    """Phân trang trước/sau; trả về trang hiện tại (từ 1)."""
    pages = max(1, -(-total // size))
    page = min(max(st.session_state.get(key, 1), 1), pages)
    st.session_state[key] = page

    def go(delta: int):
        st.session_state[key] = page + delta

    c1, c2, c3 = st.columns([1, 2, 1])
    c1.button("‹ Trước", key=f"{key}-prev", disabled=page <= 1, on_click=go, args=(-1,))
    c2.caption(f"Trang {page}/{pages} · {total} bản ghi")
    c3.button("Sau ›", key=f"{key}-next", disabled=page >= pages, on_click=go, args=(1,))
    return page


def reset_page_on_change(key: str, signature) -> None:
    """Đổi bộ lọc thì về trang 1."""
    if st.session_state.get(f"{key}-sig") != signature:
        st.session_state[f"{key}-sig"] = signature
        st.session_state[key] = 1


def camera_enabled() -> bool:
    """Camera chỉ hiện khi backend bật CAMERA_ENABLED (đọc một lần mỗi phiên)."""
    if "_camera_enabled" not in st.session_state:
        st.session_state["_camera_enabled"] = bool(api.health().get("camera_enabled"))
    return st.session_state["_camera_enabled"]


def confirm_pending(key: str, text: str, fn, ok: str, confirm_label: str = "Xác nhận") -> None:
    """Hộp xác nhận kiểu `Confirm` của bản React: có `st.session_state[key]` thì hỏi lại, đồng ý mới gọi fn(payload)."""
    if key not in st.session_state:
        return
    payload = st.session_state[key]
    st.warning(text)
    c1, c2 = st.columns(2)
    if c1.button(confirm_label, key=f"{key}-ok", type="primary"):
        st.session_state.pop(key)
        if run_action(lambda: fn(payload), ok):
            refresh()
    c2.button("Huỷ", key=f"{key}-no", on_click=lambda: st.session_state.pop(key, None))


def confirm_action(key: str, label: str, text: str, fn, ok: str, confirm_label: str | None = None, disabled: bool = False) -> None:
    """Nút hai bước: bấm -> hỏi lại -> thực hiện fn()."""
    st.button(label, key=key, disabled=disabled, on_click=lambda: st.session_state.__setitem__(f"{key}-p", True))
    confirm_pending(f"{key}-p", text, lambda _: fn(), ok, confirm_label or label)
