"""Truy xuất dữ liệu dùng chung (Repository layer)."""

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, stmt: Select, page: int, size: int, sort_col=None, sort_dir: str = "desc"):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    if sort_col is not None:
        # thứ tự NULL như MySQL: ASC NULL đầu, DESC NULL cuối
        stmt = stmt.order_by(desc(sort_col).nulls_last() if sort_dir == "desc" else asc(sort_col).nulls_first())
    rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).unique().all()
    return rows, total


def like(term: str) -> str:
    """Escape ký tự đại diện của LIKE trong chuỗi người dùng nhập."""
    return "%" + term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def contains(col, term: str):
    """Chứa chuỗi, không phân biệt hoa/thường và dấu ("quan 7" khớp "Quận 7") như collation utf8mb4_unicode_ci cũ."""
    return func.unaccent(col).ilike(func.unaccent(like(term)), escape="\\")
