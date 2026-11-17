"""Đặt lại mật khẩu một tài khoản trực tiếp trong database (công cụ quản trị cục bộ).

Chạy từ thư mục backend:  .venv\\Scripts\\python scripts\\set_password.py --username admin --password 123
Cố ý BỎ QUA chính sách mật khẩu mạnh — chỉ dùng cho demo trên máy cá nhân.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    a = ap.parse_args()

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.security import hash_password, password_policy_error
    from app.models import User
    from app.services.audit_service import audit

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == a.username, User.deleted_at.is_(None)))
        if not u:
            sys.exit(f"Không tìm thấy tài khoản {a.username}")
        u.password_hash = hash_password(a.password)
        u.token_version += 1  # đăng xuất mọi phiên cũ
        u.is_active = True
        audit(db, None, "PASSWORD_RESET_CLI", "user", u.id, {"username": u.username})
        db.commit()
    weak = password_policy_error(a.password)
    print(f"Đã đặt lại mật khẩu cho '{a.username}'.")
    if weak:
        print(f"CẢNH BÁO: mật khẩu yếu ({weak}). Chỉ dùng trên máy cá nhân, không đưa lên mạng.")


if __name__ == "__main__":
    main()
