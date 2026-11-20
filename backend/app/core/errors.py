import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


def NotFound(what: str = "Đối tượng"):
    return AppError(404, "NOT_FOUND", f"{what} không tồn tại")


def _body(code, message, details=None):
    return {"error": {"code": code, "message": message, "details": details}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app(_: Request, e: AppError):
        return JSONResponse(_body(e.code, e.message, e.details), status_code=e.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 429: "RATE_LIMITED"}.get(
            e.status_code, "HTTP_ERROR")
        return JSONResponse(_body(code, str(e.detail)), status_code=e.status_code,
                            headers=getattr(e, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        details = [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "Dữ liệu không hợp lệ", details), status_code=422)

    @app.exception_handler(OperationalError)
    async def _db(_: Request, e: OperationalError):
        log.error("Database unavailable: %s", e.orig)
        return JSONResponse(_body("DB_UNAVAILABLE", "Không kết nối được cơ sở dữ liệu, kiểm tra PostgreSQL"),
                            status_code=503)

    @app.exception_handler(Exception)
    async def _any(_: Request, e: Exception):
        log.exception("Unhandled error")
        return JSONResponse(_body("INTERNAL_ERROR", "Lỗi hệ thống"), status_code=500)
