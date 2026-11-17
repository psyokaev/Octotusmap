from fastapi import APIRouter, HTTPException, Request, Response

from app.core.config import get_settings
from app.core.deps import COOKIE_NAME, DB, CurrentUser, OptionalUser
from app.core.errors import AppError
from app.core.security import (
    login_account_limiter,
    login_ip_limiter,
    login_limiter,
    password_change_limiter,
)
from app.schemas.views import ChangePasswordIn, LoginIn, LoginOut, RegisterIn, UserOut
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["Auth"])


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict", secure=s.cookie_secure,
                    max_age=s.jwt_expire_minutes * 60, path="/")


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response, db: DB):
    ip = request.client.host if request.client else "?"
    account = body.username.strip().lower()
    limited = not (login_limiter.allow(f"{ip}:{body.username}") and login_ip_limiter.allow(ip))
    if limited or login_account_limiter.blocked(account):
        raise HTTPException(429, "Quá nhiều lần đăng nhập, thử lại sau ít phút")
    try:
        user, token = user_service.authenticate(db, body.username, body.password, request)
    except AppError:
        login_account_limiter.record(account)  # đăng nhập đúng không làm tốn hạn mức của chủ tài khoản
        raise
    _set_cookie(response, token)
    return LoginOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
def logout(user: CurrentUser, request: Request, response: Response, db: DB):
    user_service.logout(db, user, request)
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/session", response_model=UserOut | None)
def session(user: OptionalUser):
    """Phiên hiện tại hoặc null (khách) — tránh lỗi 401 khi trang công khai kiểm tra đăng nhập."""
    return user


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: DB):
    ip = request.client.host if request.client else "?"
    if not login_limiter.allow(f"register:{ip}"):
        raise HTTPException(429, "Quá nhiều yêu cầu")
    return user_service.create_user(db, **body.model_dump(), roles=["USER"], actor=None, request=request)


@router.post("/change-password", response_model=LoginOut)
def change_password(body: ChangePasswordIn, user: CurrentUser, request: Request, response: Response, db: DB):
    if not password_change_limiter.allow(str(user.id)):
        raise HTTPException(429, "Quá nhiều lần thử mật khẩu, thử lại sau ít phút")
    token = user_service.change_password(db, user, body.current_password, body.new_password, request)
    _set_cookie(response, token)
    return LoginOut(access_token=token, user=UserOut.model_validate(user))
