from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow
from app.core.spatial import Geometry

__all__ = [
    "Role", "User", "user_roles", "DataSource", "AdministrativeArea", "MonitoringStation",
    "Sensor", "RainfallObservation", "WaterLevelObservation", "HistoricalFloodEvent", "Camera",
    "CameraFrame", "CameraDetection", "ModelVersion", "TrainingRun", "Forecast",
    "FloodRiskSnapshot", "AlertRule", "Alert", "AlertHistory", "Notification", "ExportHistory",
    "AuditLog", "SystemSetting", "FloodHotspot", "FloodReport", "FloodSimulation", "RateLimitHit",
]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


# ---------------------------------------------------------------- auth
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # ADMIN/OPERATOR/USER
    name: Mapped[str] = mapped_column(String(100))


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(CITEXT, unique=True)  # không phân biệt hoa/thường như MySQL ci
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def role_codes(self) -> list[str]:
        return [r.code for r in self.roles]


# ---------------------------------------------------------------- GIS / sources
class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # SIMULATED/OPEN_DATA/OFFICIAL/MANUAL/IOT
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    license: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")


class AdministrativeArea(TimestampMixin, Base):
    __tablename__ = "administrative_areas"
    __table_args__ = (Index("sx_area_geom", "geom", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    level: Mapped[str] = mapped_column(String(20))  # DISTRICT/WARD
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("administrative_areas.id"))
    geom: Mapped[dict] = mapped_column(Geometry("MULTIPOLYGON"), nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)
    # 0..1, hệ số nhạy ngập tĩnh (địa hình/thoát nước); demo ước lượng từ lịch sử ngập
    susceptibility: Mapped[float] = mapped_column(Float, default=0.5)
    cluster: Mapped[str] = mapped_column(String(30), default="")  # cụm cold-start
    elevation_m: Mapped[float | None] = mapped_column(Float)  # độ cao tâm khu vực (DEM 90 m)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    source: Mapped[DataSource] = relationship(lazy="joined")


class MonitoringStation(TimestampMixin, Base):
    __tablename__ = "monitoring_stations"
    __table_args__ = (
        Index("sx_station_loc", "location", postgresql_using="gist"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_station_lat"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_station_lon"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # giữ số 0 đầu -> String
    name: Mapped[str] = mapped_column(String(150), index=True)
    station_type: Mapped[str] = mapped_column(String(20))  # RAIN/WATER_LEVEL/COMBINED
    address: Mapped[str] = mapped_column(String(255), default="")
    area_id: Mapped[int | None] = mapped_column(ForeignKey("administrative_areas.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location: Mapped[dict] = mapped_column(Geometry("POINT"), nullable=False)
    managing_unit: Mapped[str] = mapped_column(String(150), default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE/INACTIVE/MAINTENANCE
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    flood_threshold_cm: Mapped[float] = mapped_column(Float, default=60.0)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    last_observation_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    area: Mapped[AdministrativeArea | None] = relationship(lazy="joined")
    source: Mapped[DataSource] = relationship(lazy="joined")


class Sensor(Base):
    __tablename__ = "sensors"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("monitoring_stations.id", ondelete="CASCADE"))
    sensor_type: Mapped[str] = mapped_column(String(20))  # RAIN_GAUGE/WATER_LEVEL
    unit: Mapped[str] = mapped_column(String(10))
    model: Mapped[str] = mapped_column(String(100), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime)


class _ObservationMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)  # UTC
    # VALID/SUSPECT/MISSING/INTERPOLATED (INTERPOLATED = suy diễn, không phải quan trắc)
    quality_flag: Mapped[str] = mapped_column(String(15), default="VALID")
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RainfallObservation(_ObservationMixin, Base):
    __tablename__ = "rainfall_observations"
    __table_args__ = (
        UniqueConstraint("station_id", "observed_at", name="uq_rain_station_time"),
        Index("ix_rain_time", "observed_at"),
    )
    station_id: Mapped[int] = mapped_column(ForeignKey("monitoring_stations.id"))
    rainfall_mm: Mapped[float | None] = mapped_column(Float)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))


class WaterLevelObservation(_ObservationMixin, Base):
    __tablename__ = "water_level_observations"
    __table_args__ = (
        UniqueConstraint("station_id", "observed_at", name="uq_wl_station_time"),
        Index("ix_wl_time", "observed_at"),
    )
    station_id: Mapped[int] = mapped_column(ForeignKey("monitoring_stations.id"))
    water_level_cm: Mapped[float | None] = mapped_column(Float)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))


class HistoricalFloodEvent(Base):
    __tablename__ = "historical_flood_events"
    __table_args__ = (Index("sx_flood_loc", "location", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("administrative_areas.id"), index=True)
    location_name: Mapped[str] = mapped_column(String(200), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location: Mapped[dict] = mapped_column(Geometry("POINT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    max_depth_cm: Mapped[float | None] = mapped_column(Float)
    cause: Mapped[str] = mapped_column(String(50), default="RAIN")  # RAIN/TIDE/RAIN_TIDE
    description: Mapped[str] = mapped_column(Text, default="")
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    area: Mapped[AdministrativeArea | None] = relationship(lazy="joined")


class Camera(TimestampMixin, Base):
    __tablename__ = "cameras"
    __table_args__ = (Index("sx_camera_loc", "location", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("administrative_areas.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location: Mapped[dict] = mapped_column(Geometry("POINT"), nullable=False)
    stream_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    roi: Mapped[list | None] = mapped_column(JSON)  # [[x,y] ...] tỉ lệ 0..1
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    area: Mapped[AdministrativeArea | None] = relationship(lazy="joined")
    source: Mapped[DataSource] = relationship(lazy="joined")


class CameraFrame(Base):
    __tablename__ = "camera_frames"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    image_path: Mapped[str] = mapped_column(String(300))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class CameraDetection(Base):
    __tablename__ = "camera_detections"
    __table_args__ = (Index("ix_det_cam_time", "camera_id", "detected_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("camera_frames.id", ondelete="CASCADE"))
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    method: Mapped[str] = mapped_column(String(20))  # YOLOV8_SEG / HEURISTIC
    flood_ratio: Mapped[float] = mapped_column(Float)  # 0..1 trong ROI
    confidence: Mapped[float] = mapped_column(Float)
    num_regions: Mapped[int] = mapped_column(Integer, default=0)
    result_image_path: Mapped[str] = mapped_column(String(300), default="")
    details: Mapped[dict | None] = mapped_column(JSON)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- AI
class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    model_type: Mapped[str] = mapped_column(String(30))  # LSTM/GRU/BASELINE/YOLOV8_SEG
    version: Mapped[str] = mapped_column(String(40))
    artifact_path: Mapped[str] = mapped_column(String(300), default="")
    dataset_description: Mapped[str] = mapped_column(Text, default="")
    trained_on_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    params: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="TRAINED")  # TRAINED/DEPLOYED/ARCHIVED/FAILED
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime)
    training_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrainingRun(Base):
    __tablename__ = "training_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    task: Mapped[str] = mapped_column(String(30))  # FORECAST/VISION
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    params: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    log: Mapped[str] = mapped_column(Text, default="")


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("station_id", "issued_at", "horizon_h", name="uq_fc_station_issue_h"),
        Index("ix_fc_issued", "issued_at"),
        CheckConstraint("flood_probability BETWEEN 0 AND 1", name="ck_fc_prob"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("monitoring_stations.id"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("administrative_areas.id"), index=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime)
    horizon_h: Mapped[int] = mapped_column(Integer)  # 1..6
    target_time: Mapped[datetime] = mapped_column(DateTime)
    rainfall_mm: Mapped[float] = mapped_column(Float)
    water_level_cm: Mapped[float | None] = mapped_column(Float)
    flood_probability: Mapped[float] = mapped_column(Float)
    data_quality: Mapped[str] = mapped_column(String(15))  # GOOD/DEGRADED/POOR
    is_cold_start: Mapped[bool] = mapped_column(Boolean, default=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class FloodRiskSnapshot(Base):
    __tablename__ = "flood_risk_snapshots"
    __table_args__ = (
        UniqueConstraint("area_id", "issued_at", "horizon_h", name="uq_risk_area_issue_h"),
        Index("ix_risk_issued", "issued_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("administrative_areas.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime)
    horizon_h: Mapped[int] = mapped_column(Integer)  # 0 = hiện tại
    risk_level: Mapped[str] = mapped_column(String(20))  # LOW/MEDIUM/HIGH/INSUFFICIENT_DATA
    score: Mapped[float] = mapped_column(Float)
    flood_probability: Mapped[float | None] = mapped_column(Float)
    rainfall_mm: Mapped[float | None] = mapped_column(Float)
    water_level_ratio: Mapped[float | None] = mapped_column(Float)
    camera_flood_ratio: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[dict | None] = mapped_column(JSON)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- alerts
class AlertRule(Base):
    """Mỗi lần sửa quy tắc tạo bản ghi version mới (lịch sử thay đổi)."""

    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_status_area", "status", "area_id"),
        Index("ix_alert_triggered", "triggered_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("administrative_areas.id"))
    risk_level: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(15), default="NEW")
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    recommendations: Mapped[list | None] = mapped_column(JSON)
    explanation: Mapped[dict | None] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    horizon_h: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # ground truth sau xác minh: CONFIRMED/FALSE_ALARM/UNVERIFIED
    verified_outcome: Mapped[str] = mapped_column(String(15), default="UNVERIFIED")
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    area: Mapped[AdministrativeArea] = relationship(lazy="joined")
    assignee: Mapped[User | None] = relationship(lazy="joined")


class AlertHistory(Base):
    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30))  # CREATED/ESCALATED/STATUS/ASSIGN/NOTE/VERIFY
    from_status: Mapped[str | None] = mapped_column(String(15))
    to_status: Mapped[str | None] = mapped_column(String(15))
    note: Mapped[str] = mapped_column(Text, default="")
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user: Mapped[User | None] = relationship(lazy="joined")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notif_user_read", "user_id", "is_read"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- system
class ExportHistory(Base):
    __tablename__ = "export_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    report_type: Mapped[str] = mapped_column(String(40))
    file_format: Mapped[str] = mapped_column(String(10))
    filters: Mapped[dict | None] = mapped_column(JSON)
    file_name: Mapped[str] = mapped_column(String(200))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_time", "created_at"), Index("ix_audit_entity", "entity_type", "entity_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str] = mapped_column(String(50), default="")
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str] = mapped_column(String(50), default="")
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str] = mapped_column(String(45), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(String(255), default="")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- điểm ngập & báo cáo người dân
class FloodHotspot(Base):
    """Điểm/tuyến ngập thường xuyên đã được công bố (mỗi điểm có nguồn)."""

    __tablename__ = "flood_hotspots"
    __table_args__ = (Index("sx_hotspot_loc", "location", postgresql_using="gist"),
                      UniqueConstraint("name", "latitude", "longitude", name="uq_hotspot"))
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    street: Mapped[str] = mapped_column(String(200), default="")
    area_id: Mapped[int | None] = mapped_column(ForeignKey("administrative_areas.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location: Mapped[dict] = mapped_column(Geometry("POINT"), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    area: Mapped[AdministrativeArea | None] = relationship(lazy="joined")


class FloodReport(Base):
    """Báo cáo ngập tại chỗ của người dùng (crowdsourcing), hết hiệu lực sau vài giờ."""

    __tablename__ = "flood_reports"
    __table_args__ = (Index("sx_report_loc", "location", postgresql_using="gist"),
                      Index("ix_report_status_exp", "status", "expires_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location: Mapped[dict] = mapped_column(Geometry("POINT"), nullable=False)
    severity: Mapped[str] = mapped_column(String(10))  # ANKLE/KNEE/DEEP
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")  # ACTIVE/EXPIRED/REJECTED
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_by: Mapped[list | None] = mapped_column(JSON)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("administrative_areas.id"))
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    user: Mapped[User | None] = relationship(lazy="joined")


class FloodSimulation(Base):
    """Ngập giả định do admin tạo để diễn tập. Không phải dữ liệu thật, không vào quan trắc/cảnh báo/thống kê."""

    __tablename__ = "flood_simulations"
    __table_args__ = (Index("sx_sim_loc", "location", postgresql_using="gist"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location: Mapped[dict] = mapped_column(Geometry("POINT"), nullable=False)
    radius_m: Mapped[int] = mapped_column(Integer)
    depth_cm: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RateLimitHit(Base):
    """Bộ đếm giới hạn tốc độ theo cửa sổ cố định, dùng chung cho mọi worker uvicorn."""
    __tablename__ = "rate_limit_hits"
    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
