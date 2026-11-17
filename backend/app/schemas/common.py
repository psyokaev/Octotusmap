from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer

T = TypeVar("T")


def _utc_iso(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC).isoformat().replace("+00:00", "Z")


# DATETIME trong DB là UTC naive -> trả ra ISO có 'Z'; frontend hiển thị Asia/Ho_Chi_Minh
UtcDatetime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]


def to_utc_naive(v: datetime) -> datetime:
    return v.astimezone(UTC).replace(tzinfo=None) if v.tzinfo else v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class Message(BaseModel):
    message: str
