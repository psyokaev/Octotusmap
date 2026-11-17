from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(db: Session, user: User | None, action: str, entity_type: str = "", entity_id="",
          detail: dict | None = None, request: Request | None = None) -> None:
    """Ghi audit log; commit cùng transaction nghiệp vụ của caller."""
    db.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id or ""),
        detail=detail,
        ip=(request.client.host if request and request.client else ""),
    ))
