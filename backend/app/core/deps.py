from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models import User

COOKIE_NAME = "ufd_token"

DB = Annotated[Session, Depends(get_db)]


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.cookies.get(COOKIE_NAME)


def get_optional_user(request: Request, db: DB) -> User | None:
    tok = _token(request)
    if not tok:
        return None
    payload = decode_token(tok)
    if not payload:
        return None
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or user.deleted_at or user.token_version != payload.get("tv"):
        return None
    return user


def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if not user:
        raise HTTPException(401, "Chưa đăng nhập hoặc phiên đã hết hạn")
    return user


def require_roles(*roles: str):
    def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if not set(roles) & set(user.role_codes):
            raise HTTPException(403, "Không có quyền thực hiện thao tác này")
        return user

    return checker


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
Operator = Annotated[User, Depends(require_roles("ADMIN", "OPERATOR"))]
Admin = Annotated[User, Depends(require_roles("ADMIN"))]


def is_staff(user: User | None) -> bool:
    return bool(user and {"ADMIN", "OPERATOR"} & set(user.role_codes))


PUBLIC_EXPLANATION_KEYS = ("cause", "depth_cm", "wards", "wards_total", "lstm_flood_6h")


def explanation_for(ex: dict | None, user: User | None) -> dict | None:
    """Người dân chỉ thấy nguyên nhân/độ sâu/phường; trọng số, đầu vào, mã trạm là nội bộ."""
    if ex is None or is_staff(user):
        return ex
    return {k: ex[k] for k in PUBLIC_EXPLANATION_KEYS if k in ex}
