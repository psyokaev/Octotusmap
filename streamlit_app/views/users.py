"""Tài khoản (UsersPage.tsx): danh sách, tạo, sửa (vai trò, khoá, đặt lại mật khẩu), xoá có xác nhận."""
import re

import api
import auth
import streamlit as st
from common import confirm_action, fmt_dt, pager, refresh, reset_page_on_change, run_action, show_error

ROLE_VI = {"ADMIN": "Quản trị", "OPERATOR": "Cán bộ vận hành", "USER": "Người dân"}


def password_error(pw: str) -> str | None:
    if len(pw) < 10:
        return "Mật khẩu tối thiểu 10 ký tự"
    if len(pw) > 128:
        return "Mật khẩu tối đa 128 ký tự"
    if not (re.search(r"\d", pw) and re.search(r"[a-zA-Z]", pw)):
        return "Mật khẩu cần cả chữ và số"
    return None


def render() -> None:
    st.title("Người dùng")
    st.button("Thêm người dùng", type="primary", key="usr-new", on_click=lambda: st.session_state.update({"usr-form": "new"}))
    with st.container(border=True):
        c = st.columns(2)
        q = c[0].text_input("Tìm kiếm", placeholder="Tên đăng nhập, email, họ tên", key="usr-q")
        role = c[1].selectbox("Vai trò", [None, *ROLE_VI], format_func=lambda r: "Tất cả" if r is None else ROLE_VI[r], key="usr-role")
    f = {"q": q, "role": role}
    reset_page_on_change("usr-page", repr(f))
    try:
        data = api.get("/admin/users", {**f, "page": st.session_state.get("usr-page", 1), "size": 20})
    except api.ApiError as e:
        show_error(e)
        return
    items = data["items"]
    by_id = {u["id"]: u for u in items}
    form = st.session_state.get("usr-form")
    if form == "new":
        _create()
    elif form in by_id:
        _edit(by_id[form])
    if not items:
        st.info("Không có người dùng phù hợp.")
        return
    st.dataframe([{"Tên đăng nhập": u["username"], "Họ tên": u.get("full_name") or "—", "Email": u["email"],
                   "Vai trò": ", ".join(ROLE_VI.get(r, r) for r in u["role_codes"]), "Trạng thái": "Hoạt động" if u["is_active"] else "Đã khoá",
                   "Đăng nhập gần nhất": fmt_dt(u.get("last_login_at")), "Ngày tạo": fmt_dt(u.get("created_at"))} for u in items],
                 hide_index=True, width="stretch")
    pager("usr-page", data["total"], data["size"])
    pick = st.selectbox("Chọn người dùng", list(by_id), format_func=lambda i: f"{by_id[i]['username']} – {by_id[i].get('full_name') or ''}", key="usr-pick")
    u = by_id[pick]
    a = st.columns(2)
    a[0].button("Sửa", key="usr-edit", on_click=lambda: st.session_state.update({"usr-form": pick}))
    me = (auth.user() or {}).get("id")
    with a[1]:
        if u["id"] == me:
            st.caption("Không thể xoá chính mình.")
        else:
            confirm_action("usr-del", "Xoá", f"Xoá tài khoản {u['username']}? Người dùng sẽ không thể đăng nhập nữa.",
                           lambda: api.delete(f"/admin/users/{pick}"), "Đã xoá người dùng", "Xoá người dùng")


def _create() -> None:
    with st.form("usr-create-f"):
        st.subheader("Thêm người dùng")
        c = st.columns(2)
        username = c[0].text_input("Tên đăng nhập")
        full = c[1].text_input("Họ tên", max_chars=120)
        email = c[0].text_input("Email")
        pw = c[1].text_input("Mật khẩu (tối thiểu 10 ký tự, gồm chữ và số)", type="password")
        roles = st.multiselect("Vai trò", list(ROLE_VI), default=["USER"], format_func=ROLE_VI.get)
        ok = st.form_submit_button("Tạo người dùng", type="primary")
    st.button("Huỷ", key="usr-create-cancel", on_click=lambda: st.session_state.pop("usr-form", None))
    if not ok:
        return
    err = (None if re.fullmatch(r"[a-zA-Z0-9_.]{3,50}", username) else "Tên đăng nhập 3–50 ký tự: chữ, số, dấu chấm, gạch dưới"
           ) or (None if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else "Email không hợp lệ") or password_error(pw) \
        or (None if roles else "Chọn ít nhất một vai trò")
    if err:
        st.error(err)
    elif run_action(lambda: api.post("/admin/users", {"username": username, "password": pw, "email": email, "full_name": full, "roles": roles}),
                    "Đã tạo người dùng"):
        st.session_state.pop("usr-form", None)
        refresh()


def _edit(u: dict) -> None:
    with st.form("usr-edit-f"):
        st.subheader(f"Sửa người dùng {u['username']}")
        c = st.columns(2)
        full = c[0].text_input("Họ tên", value=u.get("full_name") or "", max_chars=120)
        email = c[1].text_input("Email", value=u["email"])
        pw = st.text_input("Đặt lại mật khẩu (để trống nếu giữ nguyên)", type="password")
        roles = st.multiselect("Vai trò", list(ROLE_VI), default=[r for r in u["role_codes"] if r in ROLE_VI], format_func=ROLE_VI.get)
        active = st.checkbox("Tài khoản đang hoạt động", value=u["is_active"])
        ok = st.form_submit_button("Lưu", type="primary")
    st.button("Huỷ", key="usr-edit-cancel", on_click=lambda: st.session_state.pop("usr-form", None))
    if not ok:
        return
    err = (None if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else "Email không hợp lệ") or (password_error(pw) if pw else None) \
        or (None if roles else "Chọn ít nhất một vai trò")
    if err:
        st.error(err)
        return
    body = {"email": email, "full_name": full, "roles": roles, "is_active": active, **({"new_password": pw} if pw else {})}
    if run_action(lambda: api.patch(f"/admin/users/{u['id']}", body), "Đã cập nhật người dùng"):
        st.session_state.pop("usr-form", None)
        refresh()
