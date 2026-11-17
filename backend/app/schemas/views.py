"""View layer: hợp đồng request/response của REST API."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORM, UtcDatetime

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA"]
AlertStatus = Literal["NEW", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CLOSED"]


# ------------------------------------------------------------ auth / users
class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.]+$")
    email: EmailStr
    full_name: str = Field(default="", max_length=120)
    password: str = Field(min_length=10, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class UserOut(ORM):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    role_codes: list[str]
    last_login_at: UtcDatetime | None
    created_at: UtcDatetime


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(RegisterIn):
    roles: list[Literal["ADMIN", "OPERATOR", "USER"]] = ["USER"]


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    roles: list[Literal["ADMIN", "OPERATOR", "USER"]] | None = None
    new_password: str | None = Field(default=None, min_length=10, max_length=128)


# ------------------------------------------------------------ sources / areas
class DataSourceOut(ORM):
    id: int
    code: str
    name: str
    kind: str
    is_simulated: bool
    license: str
    url: str


class AreaOut(ORM):
    id: int
    code: str
    name: str
    level: str
    centroid_lat: float
    centroid_lon: float
    susceptibility: float
    cluster: str


# ------------------------------------------------------------ stations
StationType = Literal["RAIN", "WATER_LEVEL", "COMBINED"]
StationStatus = Literal["ACTIVE", "INACTIVE", "MAINTENANCE"]


class StationBase(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=2, max_length=150)
    station_type: StationType
    address: str = Field(default="", max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    managing_unit: str = Field(default="", max_length=150)
    status: StationStatus = "ACTIVE"
    interval_minutes: int = Field(default=60, ge=1, le=1440)
    flood_threshold_cm: float = Field(default=60, gt=0, le=1000)
    notes: str = Field(default="", max_length=2000)


class StationCreate(StationBase):
    source_code: str = "MANUAL"


class StationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    station_type: StationType | None = None
    address: str | None = Field(default=None, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    managing_unit: str | None = Field(default=None, max_length=150)
    status: StationStatus | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    flood_threshold_cm: float | None = Field(default=None, gt=0, le=1000)
    notes: str | None = Field(default=None, max_length=2000)


class StationOut(ORM):
    id: int
    code: str
    name: str
    station_type: str
    address: str
    latitude: float
    longitude: float
    managing_unit: str
    status: str
    interval_minutes: int
    flood_threshold_cm: float
    notes: str
    area: AreaOut | None
    source: DataSourceOut
    last_observation_at: UtcDatetime | None
    connection_status: str = "UNKNOWN"  # ONLINE/OFFLINE/NO_DATA (tính toán)
    data_status: str = "DEMO"  # DEMO/LIVE/STALE/UNAVAILABLE
    latest_rainfall_mm: float | None = None
    latest_water_level_cm: float | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ObservationOut(BaseModel):
    observed_at: UtcDatetime
    rainfall_mm: float | None = None
    water_level_cm: float | None = None
    rain_quality: str | None = None
    wl_quality: str | None = None
    is_simulated: bool


class ObservationIn(BaseModel):
    observed_at: UtcDatetime
    rainfall_mm: float | None = Field(default=None, ge=0, le=500)
    water_level_cm: float | None = Field(default=None, ge=-500, le=2000)


class ImportReport(BaseModel):
    total_rows: int
    inserted: int
    duplicates: int
    rejected: int
    errors: list[str]


# ------------------------------------------------------------ cameras
def _check_stream_url(v: str | None) -> str | None:
    if v and not v.startswith(("http://", "https://", "rtsp://")):
        raise ValueError("URL nguồn camera phải bắt đầu bằng http(s):// hoặc rtsp://")
    return v


class CameraBase(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=2, max_length=150)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    stream_url: str = Field(default="", max_length=500)
    status: Literal["ACTIVE", "INACTIVE", "MAINTENANCE"] = "ACTIVE"
    is_public: bool = False
    retention_days: int = Field(default=30, ge=1, le=365)
    roi: list[list[float]] | None = None

    _url = field_validator("stream_url")(lambda v: _check_stream_url(v))

    @field_validator("roi")
    @classmethod
    def _roi(cls, v):
        if v is not None and (len(v) < 3 or any(len(p) != 2 or not all(0 <= c <= 1 for c in p) for p in v)):
            raise ValueError("ROI là đa giác >=3 điểm, toạ độ tỉ lệ 0..1")
        return v


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    stream_url: str | None = Field(default=None, max_length=500)
    status: Literal["ACTIVE", "INACTIVE", "MAINTENANCE"] | None = None
    is_public: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=365)

    _url = field_validator("stream_url")(lambda v: _check_stream_url(v))


class DetectionOut(ORM):
    id: int
    camera_id: int | None
    detected_at: UtcDatetime
    method: str
    flood_ratio: float
    confidence: float
    num_regions: int
    is_simulated: bool
    image_url: str = ""
    result_image_url: str = ""
    details: dict | None = None


class CameraOut(ORM):
    id: int
    code: str
    name: str
    latitude: float
    longitude: float
    stream_url: str
    status: str
    is_public: bool
    retention_days: int
    roi: list | None
    area: AreaOut | None
    source: DataSourceOut
    latest_detection: DetectionOut | None = None


# ------------------------------------------------------------ forecasts / risk
class ForecastPoint(BaseModel):
    horizon_h: int
    target_time: UtcDatetime
    rainfall_mm: float
    water_level_cm: float | None
    flood_probability: float


class StationForecast(BaseModel):
    station_id: int
    station_code: str
    station_name: str
    area_id: int | None
    issued_at: UtcDatetime
    model_version: str | None
    data_quality: str
    is_cold_start: bool
    is_simulated: bool
    points: list[ForecastPoint]


class RiskOut(BaseModel):
    area_id: int
    area_name: str
    horizon_h: int
    issued_at: UtcDatetime
    risk_level: RiskLevel
    score: float
    flood_probability: float | None
    rainfall_mm: float | None
    water_level_ratio: float | None
    camera_flood_ratio: float | None
    explanation: dict | None
    is_simulated: bool


class ModelVersionOut(ORM):
    id: int
    name: str
    model_type: str
    version: str
    status: str
    is_active: bool
    trained_on_simulated: bool
    dataset_description: str
    metrics: dict | None
    params: dict | None
    trained_at: UtcDatetime | None
    training_seconds: float | None
    created_at: UtcDatetime


# ------------------------------------------------------------ alerts
class AlertOut(ORM):
    id: int
    code: str
    area: AreaOut
    risk_level: str
    status: str
    title: str
    message: str
    recommendations: list | None
    explanation: dict | None
    cause: str | None = None
    depth_cm: int | None = None
    wards: list[str] = Field(default_factory=list)
    score: float
    horizon_h: int
    is_simulated: bool
    is_public: bool
    verified_outcome: str
    assigned_to: int | None
    assignee_name: str | None = None
    triggered_at: UtcDatetime
    acknowledged_at: UtcDatetime | None
    resolved_at: UtcDatetime | None
    closed_at: UtcDatetime | None
    updated_at: UtcDatetime


class AlertHistoryOut(ORM):
    id: int
    action: str
    from_status: str | None
    to_status: str | None
    note: str
    changed_at: UtcDatetime
    username: str | None = None


class AlertDetailOut(AlertOut):
    history: list[AlertHistoryOut]


class AlertStatusIn(BaseModel):
    status: AlertStatus
    note: str = Field(default="", max_length=2000)


class AlertAssignIn(BaseModel):
    user_id: int | None
    note: str = Field(default="", max_length=2000)


class AlertNoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class AlertVerifyIn(BaseModel):
    outcome: Literal["CONFIRMED", "FALSE_ALARM", "UNVERIFIED"]
    note: str = Field(default="", max_length=2000)


class NotificationOut(ORM):
    id: int
    alert_id: int | None
    title: str
    body: str
    level: str
    is_read: bool
    created_at: UtcDatetime


# ------------------------------------------------------------ history
class FloodEventOut(ORM):
    id: int
    location_name: str
    latitude: float
    longitude: float
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    max_depth_cm: float | None
    cause: str
    description: str
    is_simulated: bool
    area: AreaOut | None


class FloodEventIn(BaseModel):
    location_name: str = Field(min_length=2, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    started_at: UtcDatetime
    ended_at: UtcDatetime | None = None
    max_depth_cm: float | None = Field(default=None, ge=0, le=500)
    cause: Literal["RAIN", "TIDE", "RAIN_TIDE", "OTHER"] = "RAIN"
    description: str = Field(default="", max_length=2000)


# ------------------------------------------------------------ admin
class RuleOut(ORM):
    id: int
    version: int
    name: str
    config: dict
    is_active: bool
    notes: str
    created_at: UtcDatetime


class RuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    config: dict
    notes: str = Field(default="", max_length=2000)


class SettingOut(ORM):
    key: str
    value: dict | list | str | int | float | bool | None
    description: str
    updated_at: UtcDatetime


class SettingIn(BaseModel):
    value: dict | list | str | int | float | bool | None


class AuditOut(ORM):
    id: int
    username: str
    action: str
    entity_type: str
    entity_id: str
    detail: dict | None
    ip: str
    created_at: UtcDatetime
