from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError, NotFound
from app.core.security import create_token, hash_password, password_policy_error, verify_password
from app.models import Role, User
from app.repositories.base import contains, paginate
from app.services.audit_service import audit

DUMMY_HASH = hash_password("timing-equaliser-not-a-password-1")


def _check_policy(pw: str) -> None:
    err = password_policy_error(pw)
    if err:
        raise AppError(422, "WEAK_PASSWORD", err)


def roles_by_code(db: Session, codes: list[str]) -> list[Role]:
    return list(db.scalars(select(Role).where(Role.code.in_(codes))))


def authenticate(db: Session, username: str, password: str, request=None) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.username == username, User.deleted_at.is_(None)))
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)  # chống dò user qua thời gian
    if not user or not ok or not user.is_active:
        audit(db, user, "LOGIN_FAILED", "user", user.id if user else "", {"username": username[:50]}, request)
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu")
    user.last_login_at = utcnow()
    audit(db, user, "LOGIN", "user", user.id, None, request)
    db.commit()
    return user, create_token(user.id, user.token_version)


def logout(db: Session, user: User, request=None) -> None:
    user.token_version += 1  # vô hiệu mọi token đã phát
    audit(db, user, "LOGOUT", "user", user.id, None, request)
    db.commit()


def create_user(db: Session, *, username, email, full_name, password, roles, actor: User | None, request=None) -> User:
    _check_policy(password)
    if db.scalar(select(User.id).where(or_(User.username == username, User.email == email))):
        raise AppError(409, "DUPLICATE", "Tên đăng nhập hoặc email đã được sử dụng")
    u = User(username=username, email=email, full_name=full_name, password_hash=hash_password(password),
             roles=roles_by_code(db, roles))
    db.add(u)
    db.flush()
    audit(db, actor or u, "USER_CREATE", "user", u.id, {"username": username, "roles": roles}, request)
    db.commit()
    return u


def change_password(db: Session, user: User, current: str, new: str, request=None) -> str:
    if not verify_password(current, user.password_hash):
        audit(db, user, "PASSWORD_CHANGE_FAILED", "user", user.id, None, request)
        db.commit()
        raise AppError(400, "WRONG_PASSWORD", "Mật khẩu hiện tại không đúng")
    _check_policy(new)
    user.password_hash = hash_password(new)
    user.token_version += 1
    audit(db, user, "PASSWORD_CHANGE", "user", user.id, None, request)
    db.commit()
    return create_token(user.id, user.token_version)


def get(db: Session, uid: int) -> User:
    u = db.get(User, uid)
    if not u or u.deleted_at:
        raise NotFound("Người dùng")
    return u


def list_users(db: Session, q, role, page, size):
    stmt = select(User).where(User.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(contains(User.username, q), contains(User.email, q), contains(User.full_name, q)))
    if role:
        stmt = stmt.where(User.roles.any(Role.code == role))
    return paginate(db, stmt, page, size, User.id, "asc")


def update_user(db: Session, uid: int, data, actor: User, request=None) -> User:
    u = get(db, uid)
    ch = data.model_dump(exclude_unset=True)
    if u.id == actor.id and (ch.get("is_active") is False or ("roles" in ch and "ADMIN" not in ch["roles"])):
        raise AppError(409, "SELF_LOCKOUT", "Không thể tự khoá hoặc tự gỡ quyền ADMIN của chính mình")
    if "email" in ch and db.scalar(select(User.id).where(User.email == ch["email"], User.id != uid)):
        raise AppError(409, "DUPLICATE", "Email đã được sử dụng")
    if ch.get("new_password"):
        _check_policy(ch["new_password"])
        u.password_hash = hash_password(ch["new_password"])
        u.token_version += 1
    if "roles" in ch:
        u.roles = roles_by_code(db, ch["roles"])
        u.token_version += 1
    for k in ("email", "full_name", "is_active"):
        if k in ch:
            setattr(u, k, ch[k])
    if ch.get("is_active") is False:
        u.token_version += 1
    audit(db, actor, "USER_UPDATE", "user", u.id, {k: v for k, v in ch.items() if k != "new_password"}, request)
    db.commit()
    return u


def soft_delete(db: Session, uid: int, actor: User, request=None) -> None:
    u = get(db, uid)
    if u.id == actor.id:
        raise AppError(409, "SELF_LOCKOUT", "Không thể xoá chính mình")
    u.deleted_at, u.is_active = utcnow(), False
    u.token_version += 1
    u.username = f"{u.username}~{u.id}"[:50]
    u.email = f"deleted+{u.id}@invalid"
    audit(db, actor, "USER_DELETE", "user", u.id, None, request)
    db.commit()
