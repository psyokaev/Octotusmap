"""Dữ liệu mẫu cho các trang cán bộ/quản trị (khớp schema backend)."""


def _series(n=3):
    return [{"bucket": f"2025-06-0{i + 1}", "sum": 2.0 + i, "avg": 1.0 + i, "max": 3.0 + i, "count": 10} for i in range(n)]


OVERVIEW = {"stations_total": 8, "stations_online": 6, "stations_offline": 2, "cameras_total": 3, "areas_total": 22, "areas_low": 15, "areas_medium": 4,
            "areas_high": 2, "areas_insufficient": 1, "alerts_active": 5, "alerts_in_range": 12, "alerts_handled": 7, "rainfall_avg_mm": 1.2,
            "water_level_max_cm": 88.0, "latest_forecast_at": "2025-06-01T03:00:00", "valid_data_ratio": 0.93, "generated_at": "2025-06-01T03:00:00"}
ALERT_STATS = {"total": 12, "by_time": [{"bucket": "2025-06-01", "LOW": 1, "MEDIUM": 2, "HIGH": 3, "total": 6}], "by_area": [{"area": "Quận 1", "count": 6}],
               "by_level": {"HIGH": 3}, "by_status": {"NEW": 4, "RESOLVED": 8}, "verification": {"CONFIRMED": 2, "FALSE_ALARM": 1}, "precision_verified": 0.66,
               "avg_minutes_to_ack": 12.0, "avg_minutes_to_resolve": 55.0}
RISK_STATS = {"trend": [{"bucket": "2025-06-01", "LOW": 5, "MEDIUM": 2, "HIGH": 1, "INSUFFICIENT_DATA": 0, "avg_score": 0.4}], "current": {"LOW": 15, "HIGH": 2}}
FC_METRICS = {"rainfall": {"mae": 0.5, "rmse": 0.9}, "flood": {"f1": 0.7, "precision": 0.8, "recall": 0.6}}
PERF = {"models": [{"id": 1, "name": "LSTM-rain", "type": "LSTM", "version": "1", "active": True, "trained_on_simulated": False, "metrics": FC_METRICS},
                   {"id": 2, "name": "YOLO", "type": "YOLOV8_SEG", "version": "1", "active": True, "trained_on_simulated": True, "metrics": {"mask_map50": 0.5}}],
        "online_rainfall_skill": [{"horizon_h": 1, "mae": 0.4, "rmse": 0.7, "n": 20}], "alert_verification": {"CONFIRMED": 2}}
STATION = {"id": 5, "code": "R01", "name": "Trạm mưa 1", "station_type": "COMBINED", "address": "Q1", "latitude": 10.78, "longitude": 106.7, "managing_unit": "TT",
           "status": "ACTIVE", "interval_minutes": 60, "flood_threshold_cm": 60.0, "notes": "", "area": {"id": 1, "code": "A1", "name": "Quận 1", "level": "DISTRICT"},
           "last_observation_at": "2025-06-01T03:00:00Z", "connection_status": "ONLINE", "data_status": "REAL", "latest_rainfall_mm": 1.5,
           "latest_water_level_cm": 40.0, "updated_at": "2025-06-01T03:00:00Z"}
DETECTION = {"id": 9, "camera_id": 4, "detected_at": "2025-06-01T03:00:00Z", "method": "HEURISTIC", "flood_ratio": 0.3, "confidence": 0.7,
             "num_regions": 2, "is_simulated": True, "image_url": "/api/v1/cameras/media/1/input",
             "result_image_url": "/api/v1/cameras/media/1/result", "details": None}
CAMERA = {"id": 4, "code": "CAM1", "name": "Camera 1", "latitude": 10.78, "longitude": 106.7, "stream_url": "", "status": "ACTIVE", "is_public": False,
          "retention_days": 30, "roi": None, "area": None, "source": {"is_simulated": True, "name": "SIM"}, "latest_detection": DETECTION}
MODEL = {"id": 1, "name": "LSTM-rain", "model_type": "LSTM", "version": "1", "status": "DEPLOYED", "is_active": True, "trained_on_simulated": False,
         "dataset_description": "Open-Meteo", "metrics": {**FC_METRICS, "flood": {**FC_METRICS["flood"], "confusion_matrix": {"tp": 1, "fp": 2, "fn": 3, "tn": 4}}},
         "params": {"epochs": 8}, "trained_at": "2025-06-01T03:00:00Z", "training_seconds": 12.0, "created_at": "2025-06-01T03:00:00Z"}
MODEL_OLD = {**MODEL, "id": 3, "version": "0", "status": "ARCHIVED", "is_active": False}
RULE_CFG = {"weights": {"flood_probability": 0.4, "rainfall": 0.3, "water_level": 0.2, "camera": 0.05, "history": 0.05}, "rainfall_ref_mm": 20,
            "thresholds": {"medium": 0.4, "high": 0.7}, "hysteresis": 0.05,
            "overrides": {"flood_probability_high": 0.85, "water_level_ratio_high": 1.0, "camera_ratio_high": 0.5}, "min_confidence": 0.5,
            "freshness_max_minutes": 180, "alert_min_level": "MEDIUM", "cooldown_minutes": 60}
RULES = [{"id": 2, "version": 2, "name": "Quy tắc v2", "config": RULE_CFG, "is_active": True, "notes": "", "created_at": "2025-06-01T03:00:00Z"},
         {"id": 1, "version": 1, "name": "Quy tắc v1", "config": RULE_CFG, "is_active": False, "notes": "gốc", "created_at": "2025-05-01T03:00:00Z"}]
USERS = [{"id": 1, "username": "admin", "email": "a@b.vn", "full_name": "Quản Trị", "role_codes": ["ADMIN"], "is_active": True,
          "last_login_at": None, "created_at": "2025-06-01T03:00:00Z"},
         {"id": 2, "username": "nguoidan", "email": "nd@b.vn", "full_name": "Người Dân", "role_codes": ["USER"], "is_active": True,
          "last_login_at": None, "created_at": "2025-06-01T03:00:00Z"}]

STAFF_ROUTES = {
    "/stations": {"items": [STATION], "total": 1, "page": 1, "size": 20},
    "/statistics/overview": OVERVIEW,
    "/statistics/satellite-rainfall": [{"day": "2025-06-01", "imerg_mm": 12.5, "model_mm": 8.1}],
    "/statistics/rainfall": {"series": _series(), "unit": "mm", "by_station": [
        {"station_id": 5, "code": "R01", "name": "Trạm mưa 1", "sum": 9.0, "avg": 3.0, "max": 5.0, "count": 30}]},
    "/statistics/water-level": {"series": _series(), "by_station": [], "unit": "cm"},
    "/statistics/observations": {"items": [{"observed_at": "2025-06-01T03:00:00", "station_code": "R01", "station_name": "Trạm mưa 1", "area": "Quận 1",
                                            "value": 2.5, "quality": "VALID", "is_simulated": False}], "total": 1, "page": 1, "size": 50},
    "/statistics/alerts": ALERT_STATS, "/statistics/risk": RISK_STATS, "/statistics/model-performance": PERF,
    "/statistics/cameras": [{"id": 4, "code": "CAM1", "name": "Camera 1", "status": "ACTIVE", "area": None, "is_public": False, "is_simulated": True,
                             "detections": 3, "max_flood_ratio": 0.5, "avg_flood_ratio": 0.3, "last_detection_at": "2025-06-01T03:00:00"}],
    "/statistics/stations": [{"id": 5, "code": "R01", "name": "Trạm mưa 1", "type": "COMBINED", "status": "ACTIVE", "connection": "ONLINE", "area": "Quận 1",
                              "area_id": 1, "last_observation_at": "2025-06-01T03:00:00", "source": "OPEN_METEO", "is_simulated": False,
                              "managing_unit": "TT", "interval_minutes": 60, "flood_threshold_cm": 60}],
    "/statistics/data-quality": [{"kind": "rainfall", "code": "R01", "name": "Trạm mưa 1", "total": 100, "valid_ratio": 0.9, "SUSPECT": 5}],
    "/statistics/alert-handling": [{"action": "STATUS", "to_status": "RESOLVED", "count": 4}],
    "/stations/5/observations": [{"observed_at": "2025-06-01T03:00:00Z", "rainfall_mm": 2.0, "water_level_cm": 40.0}],
    "/stations/5/quality": {"rainfall": {"VALID": 90, "SUSPECT": 5, "MISSING": 5}, "water_level": {"VALID": 95}, "expected_records": 168,
                            "completeness": 0.9, "delay_minutes": 20},
    "/stations/5/forecast": {"station_id": 5, "station_code": "R01", "issued_at": "2025-06-01T03:00:00Z", "is_simulated": False, "points": [
        {"horizon_h": 1, "target_time": "2025-06-01T04:00:00Z", "rainfall_mm": 1.0, "water_level_cm": None, "flood_probability": 0.2,
         "data_quality": "OK", "is_cold_start": False}]},
    "/cameras": [CAMERA], "/cameras/4/detections": {"items": [DETECTION], "total": 1, "page": 1, "size": 10},
    "/admin/models": [MODEL, MODEL_OLD],
    "/admin/training-runs": [{"id": 1, "task": "FORECAST", "status": "SUCCESS", "started_at": "2025-06-01T03:00:00Z", "finished_at": "2025-06-01T03:05:00Z",
                              "params": {"epochs": 8}, "model_version_id": 1, "log": "xong"}],
    "/admin/users": {"items": USERS, "total": 2, "page": 1, "size": 20},
    "/admin/rules": RULES,
    "/admin/settings": [{"key": "alert.default", "value": {"a": 1}, "description": "mô tả", "updated_at": "2025-06-01T03:00:00Z"}],
    "/admin/audit-logs": {"items": [{"id": 1, "username": "admin", "action": "LOGIN", "entity_type": "user", "entity_id": "1", "detail": {"x": 1},
                                     "ip": "1.2.3.4", "created_at": "2025-06-01T03:00:00Z"}], "total": 1, "page": 1, "size": 50},
    "/admin/data-sources": [{"id": 1, "code": "OPEN_METEO", "name": "Open-Meteo", "kind": "WEATHER", "is_simulated": False, "license": "CC",
                             "url": "https://open-meteo.com"}],
    "POST /admin/rules": {}, "POST /admin/rules/1/activate": {}, "POST /admin/users": {}, "PATCH /admin/users/2": {},
    "POST /admin/jobs/run-cycle": {"ok": True}, "POST /admin/models/3/activate": {}, "POST /admin/models/train": {"message": "ok"},
}
