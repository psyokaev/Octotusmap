import time
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings

ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int, token_version: int) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "tv": token_version, "iat": now,
               "exp": now + timedelta(minutes=s.jwt_expire_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGO)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
    except jwt.PyJWTError:
        return None


def password_policy_error(pw: str) -> str | None:
    if len(pw) < 10:
        return "Mật khẩu tối thiểu 10 ký tự"
    if not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        return "Mật khẩu phải có cả chữ và số"
    return None


class RateLimiter:
    """Giới hạn tốc độ lưu trong PostgreSQL nên đúng khi chạy nhiều worker.

    shortcut: cửa sổ cố định, ở ranh giới cửa sổ có thể lọt tới 2x limit; đổi sang sliding log nếu cần chặt hơn.
    """

    def __init__(self, limit: int, window_s: int, name: str = ""):
        self.limit, self.window, self.name = limit, window_s, name  # name tách khoá giữa các limiter

    def _start(self) -> datetime:
        return datetime.fromtimestamp(int(time.time()) // self.window * self.window, UTC).replace(tzinfo=None)

    def blocked(self, key: str) -> bool:
        """Đã hết hạn mức chưa, KHÔNG tính thêm lần này (dùng với record() khi chỉ đếm lần thất bại)."""
        from sqlalchemy import select

        from app.core.database import engine
        from app.models import RateLimitHit

        with engine.connect() as conn:
            n = conn.scalar(select(RateLimitHit.hits).where(RateLimitHit.key == f"{self.name}:{key}"[:300],
                                                            RateLimitHit.window_start == self._start()))
        return (n or 0) >= self.limit

    def record(self, key: str) -> None:
        self.allow(key)

    def allow(self, key: str) -> bool:
        from sqlalchemy.dialects.postgresql import insert

        from app.core.database import engine
        from app.models import RateLimitHit

        start = self._start()
        stmt = insert(RateLimitHit).values(key=f"{self.name}:{key}"[:300], window_start=start, hits=1)
        stmt = stmt.on_conflict_do_update(index_elements=["key", "window_start"],
                                          set_={"hits": RateLimitHit.hits + 1}).returning(RateLimitHit.hits)
        with engine.begin() as conn:
            return conn.execute(stmt).scalar_one() <= self.limit


login_limiter = RateLimiter(limit=10, window_s=60, name="login")  # theo IP + tài khoản
login_ip_limiter = RateLimiter(limit=30, window_s=60, name="login_ip")  # theo IP, chặn thử lần lượt nhiều tài khoản
# chỉ đếm lần SAI theo tài khoản, không phụ thuộc IP: X-Forwarded-For giả không vượt qua được.
# Đánh đổi: kẻ biết tên tài khoản có thể cố tình nhập sai để khoá tài khoản đó tối đa 15 phút.
login_account_limiter = RateLimiter(limit=20, window_s=900, name="login_account")
password_change_limiter = RateLimiter(limit=10, window_s=900, name="password_change")  # theo id người dùng
