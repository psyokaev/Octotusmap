from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_name: str = "OctotusMap"
    environment: str = "development"
    demo_mode: bool = True
    camera_enabled: bool = True
    camera_scan_enabled: bool = False  # quét định kỳ camera giao thông gần điểm ngập (cần mạng + YOLO đang dùng)
    camera_scan_interval_minutes: int = 15
    camera_scan_max_per_run: int = 20
    camera_scan_radius_m: int = 500
    earthdata_token: str = ""  # NASA Earthdata (miễn phí) để tải mưa vệ tinh GPM IMERG; trống = không lấy
    camera_health_per_cycle: int = 8  # số camera giao thông kiểm tra ảnh mỗi chu kỳ (0 = tắt)
    traffic_camera_base: str = "https://giaothong.hochiminhcity.gov.vn"  # đổi khi thành phố đổi địa chỉ

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_database: str = "urban_flood_dss"

    jwt_secret: str = Field(default="", description="Bắt buộc đặt trong .env")
    jwt_expire_minutes: int = 480
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    admin_username: str = "admin"
    admin_email: str = "admin@example.com"
    admin_password: str = ""  # trống -> sinh ngẫu nhiên, in ra 1 lần

    storage_dir: Path = BACKEND_DIR / "storage"
    artifacts_dir: Path = BACKEND_DIR / "app" / "ai" / "artifacts"
    datasets_dir: Path = PROJECT_DIR / "datasets"

    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 300
    max_upload_mb: int = 8

    geocoder_url: str = "https://photon.komoot.io"  # Photon (OSM); Nominatim bị chặn ở mạng triển khai
    osrm_url: str = "https://router.project-osrm.org"
    external_user_agent: str = "UrbanFloodDSS-HCMC/1.0 (student project)"

    smtp_host: str = ""

    @property
    def database_url(self) -> str:
        return self.server_url + f"/{self.postgres_database}"

    @property
    def server_url(self) -> str:
        from urllib.parse import quote_plus

        return (
            f"postgresql+psycopg://{self.postgres_user}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
