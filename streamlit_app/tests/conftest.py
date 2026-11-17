"""Fixture chung: `api` giả (không gọi mạng, không chạm DB) và dữ liệu mẫu."""
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import api  # noqa: E402
from staff_data import STAFF_ROUTES  # noqa: E402

PRELUDE = f"import sys; sys.path.insert(0, {str(APP_DIR)!r})\n"
USER = {"id": 2, "username": "nguoidan", "email": "a@b.vn", "full_name": "Người Dân", "role_codes": ["USER"], "is_active": True}
OPERATOR = {**USER, "id": 3, "username": "canbo", "full_name": "Cán Bộ", "role_codes": ["OPERATOR"]}
ADMIN = {**USER, "id": 1, "username": "admin", "full_name": "Quản Trị", "role_codes": ["ADMIN"]}


def square(lon, lat, d=0.01):
    return {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}


def area(i, name, level, parent, risk, cause=None, depth=None, lon=106.6):
    return {"type": "Feature", "id": i, "geometry": square(lon + i * 0.02, 10.7), "properties": {
        "id": i, "code": f"A{i}", "name": name, "level": level, "parent_id": parent, "risk_level": risk, "score": 0.5 + i / 10,
        "flood_probability": 0.6, "cause": cause, "depth_cm": depth, "rainfall_mm": 3.0, "is_simulated": False}}


RISK_LAYERS = {"type": "FeatureCollection", "properties": {"horizon_h": 0, "issued_at": "2025-06-01T03:00:00Z"}, "features": [
    area(1, "Quận 1", "DISTRICT", None, "HIGH", "TIDE", 40),
    area(2, "Phường Bến Nghé", "WARD", 1, "HIGH", "TIDE", 40),
    area(3, "Phường Tân Định", "WARD", 1, "LOW"),
    area(4, "Quận 7", "DISTRICT", None, "LOW"),
]}
STATION_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [106.7, 10.78]},
     "properties": {"id": 5, "code": "R01", "name": "Trạm mưa 1", "station_type": "RAIN", "rainfall_mm": 6.0}}]}
FEATURES = {"stations": STATION_FC, "alerts": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None, "properties": {}}]},
            "forecast_issued_at": "2025-06-01T03:00:00Z"}
LATEST = [{"station_id": 5, "station_code": "R01", "station_name": "Trạm mưa 1", "area_id": 1, "issued_at": "2025-06-01T03:00:00",
           "model_version": "v1", "data_quality": "OK", "is_cold_start": False, "is_simulated": False,
           "points": [{"horizon_h": h, "target_time": f"2025-06-01T{3 + h:02d}:00:00Z", "rainfall_mm": h * 1.5,
                       "water_level_cm": None, "flood_probability": min(0.15 * h, 1)} for h in range(1, 7)]}]
IDENTIFY = {"lat": 10.7, "lon": 106.7, "area": {"id": 2, "name": "Phường Bến Nghé"}, "district": "Quận 1", "stations": [],
            "risk": [{"horizon_h": h, "risk_level": "HIGH" if h == 0 else "LOW", "score": 0.7, "flood_probability": 0.7, "rainfall_mm": 4.0,
                      "explanation": {"cause": "TIDE", "depth_cm": 40, "notes": ["Triều cao"], "overrides": []}} for h in range(7)],
            "history": {"events_within_1500m": 3, "last_event_at": "2024-10-01T10:00:00Z", "max_depth_cm": 35}, "issued_at": "2025-06-01T03:00:00Z"}
ALERT = {"id": 10, "code": "AL-10", "area": {"id": 1, "name": "Quận 1"}, "risk_level": "HIGH", "status": "NEW", "title": "Nguy cơ ngập cao",
         "message": "Triều cường kết hợp mưa", "recommendations": ["Tránh khu vực trũng"], "score": 0.82, "horizon_h": 2,
         "cause": "RAIN_TIDE", "depth_cm": 30, "wards": ["Phường Bến Nghé"], "is_simulated": False, "is_public": True,
         "verified_outcome": "UNVERIFIED", "assigned_to": None, "assignee_name": None, "triggered_at": "2025-06-01T03:00:00Z",
         "acknowledged_at": None, "resolved_at": None, "closed_at": None, "updated_at": "2025-06-01T03:00:00Z",
         "explanation": {"level_reason": "Xác suất cao", "confidence": 0.9, "rule_version": 3, "contributions": {"rainfall": 0.4},
                         "normalized": {"rainfall": 0.8}, "overrides": ["Triều > 1.5 m"], "notes": [], "stations": ["R01"]}}
ALERT_PUBLIC = {**ALERT, "status": "NEW", "explanation": None, "assigned_to": None, "verified_outcome": "UNVERIFIED"}
ALERT_DETAIL = {**ALERT, "history": [{"id": 1, "action": "TẠO", "from_status": None, "to_status": "NEW", "note": "", "changed_at": "2025-06-01T03:00:00Z", "username": None}]}
MODEL_STATUS = {"forecast_model": {"id": 1, "name": "LSTM-rain", "model_type": "LSTM", "version": "1", "status": "DEPLOYED", "is_active": True,
                                  "trained_on_simulated": False, "metrics": {"rainfall": {"mae": 0.512, "rmse": 0.9}}},
                "vision_model": None, "latest_issued_at": "2025-06-01T03:00:00", "last_cycle": {}, "warning": None}
FC_RISK = [{"area_id": 1, "area_name": "Quận 1", "horizon_h": 0, "issued_at": "2025-06-01T03:00:00", "risk_level": "HIGH", "score": 0.82,
            "flood_probability": 0.7, "rainfall_mm": 5.0, "water_level_ratio": None, "camera_flood_ratio": None, "is_simulated": False,
            "explanation": {"cause": "TIDE", "depth_cm": 40}},
           {"area_id": 4, "area_name": "Quận 7", "horizon_h": 0, "issued_at": "2025-06-01T03:00:00", "risk_level": "LOW", "score": 0.1,
            "flood_probability": 0.1, "rainfall_mm": 0.0, "water_level_ratio": None, "camera_flood_ratio": None, "is_simulated": False,
            "explanation": None}]
EVENT = {"id": 7, "location_name": "Đường Nguyễn Hữu Cảnh", "latitude": 10.79, "longitude": 106.72, "started_at": "2024-10-14T01:00:00Z",
         "ended_at": None, "max_depth_cm": 40, "cause": "TIDE", "description": "Ngập do triều", "is_simulated": False, "area": {"id": 1, "name": "Quận 1"}}
ROUTE = {"routes": [{"index": 0, "distance_m": 5200, "duration_s": 900, "geometry": {"type": "LineString", "coordinates": [[106.7, 10.78], [106.71, 10.79]]},
                     "segments": [{"geometry": {"type": "LineString", "coordinates": [[106.7, 10.78], [106.71, 10.79]]}, "status": "LIKELY_FLOODED",
                                   "probability": 0.8, "length_m": 300, "reasons": ["Triều cao"]}],
                     "summary": {"km_by_status": {"DRY": 4.9, "AT_RISK": 0, "LIKELY_FLOODED": 0.3, "REPORTED_FLOODED": 0}, "flooded_km": 0.3,
                                 "at_risk_km": 0, "max_probability": 0.8},
                     "steps": [{"instruction": "Đi thẳng", "name": "A", "distance_m": 200, "duration_s": 30, "location": [106.7, 10.78]}]}],
         "recommended_index": 0, "data_time": "2025-06-01T03:00:00Z", "active_reports": 1, "disclaimer": "Chỉ mang tính tham khảo.",
         "attribution": "OSRM", "elevation_missing_ratio": 0}


class FakeApi:
    """Thay các hàm HTTP của api.py bằng bảng đường dẫn -> dữ liệu (giá trị có thể là hàm hoặc Exception)."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.routes: dict = {**STAFF_ROUTES,
            "/gis/areas": [{"id": 1, "code": "A1", "name": "Quận 1", "level": "DISTRICT"}],
            "/gis/risk-layers": RISK_LAYERS, "/gis/features": FEATURES, "/forecasts/latest": LATEST, "/gis/hotspots": [],
            "/reports/active": [{"id": 3, "latitude": 10.78, "longitude": 106.7, "severity": "KNEE", "note": "Nước tới gối", "status": "ACTIVE",
                                 "confirmations": 2, "reported_at": "2025-06-01T03:00:00Z", "expires_at": "2025-06-01T06:00:00Z", "reporter": "nguoidan"}],
            "/gis/identify": IDENTIFY, "/search": {"results": [{"type": "area", "id": 1, "label": "Quận 1", "lat": 10.78, "lon": 106.7}], "attribution": ""},
            "/alerts": {"items": [ALERT], "total": 1, "page": 1, "size": 20}, "/alerts/10": ALERT_DETAIL, "/alerts/assignees": [OPERATOR],
            "/forecasts/model-status": MODEL_STATUS, "/forecasts/risk": FC_RISK,
            "/history/events": {"items": [EVENT], "total": 1, "page": 1, "size": 20},
            "/statistics/flood-events": {"by_time": [{"bucket": "2024-10", "count": 2, "max_depth_cm": 40}], "by_area": [], "total": 2},
            "/notifications": {"items": [], "total": 0, "unread": 0}, "/admin/simulations": [],
        }

    def _find(self, path):
        if path not in self.routes:
            raise AssertionError(f"Chưa giả lập {path}")
        v = self.routes[path]
        if isinstance(v, Exception):
            raise v
        return v

    def get(self, path, params=None, ttl=0):
        self.calls.append(("GET", path, params))
        return self._find(path)

    def _write(self, method):
        def fn(path, body=None, params=None):
            self.calls.append((method, path, body if body is not None else params))
            return self.routes.get(f"{method} {path}")
        return fn

    def _upload(self, path, name, content, data=None, field="file", params=None):
        self.calls.append(("UPLOAD", path, {"name": name, "data": data, "params": params}))
        return self.routes.get(f"POST {path}")

    def _download(self, path, params=None):
        self.calls.append(("DOWNLOAD", path, params))
        return ("bao_cao.xlsx", b"xlsx")

    def install(self, mp):
        mp.setattr(api, "get", self.get)
        mp.setattr(api, "post", self._write("POST"))
        mp.setattr(api, "patch", self._write("PATCH"))
        mp.setattr(api, "put", self._write("PUT"))
        mp.setattr(api, "delete", lambda path: self.calls.append(("DELETE", path, None)))
        mp.setattr(api, "upload", self._upload)
        mp.setattr(api, "get_bytes", lambda path, params=None: (_ for _ in ()).throw(api.ApiError(404, "NOT_FOUND", "Không có ảnh")))
        mp.setattr(api, "health", lambda: {"camera_enabled": False})
        mp.setattr(api, "download", self._download)


@pytest.fixture
def fake(monkeypatch):
    f = FakeApi()
    f.install(monkeypatch)
    return f


def run_view(module: str, user: dict | None = None, timeout: int = 30):
    """Chạy `views.<module>.render()` trong AppTest với phiên của `user` (None = khách)."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(PRELUDE + f"from views import {module}\n{module}.render()\n", default_timeout=timeout)
    if user:
        at.session_state["user"], at.session_state["token"] = user, "test-token"
    return at.run()
