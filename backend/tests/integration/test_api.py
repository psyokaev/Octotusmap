"""Kiểm thử tích hợp API + PostgreSQL/PostGIS (auth, RBAC, CRUD, GIS, AI, cảnh báo, thống kê, Excel)."""

import io
from datetime import UTC, datetime, timedelta

import cv2
import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select, text, update

from app.models import Alert, MonitoringStation, RainfallObservation

pytestmark = pytest.mark.db
API = "/api/v1"


def iso(dt):
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ hệ thống & auth
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"] is True


def test_login_failure_is_generic(client):
    r = client.post(f"{API}/auth/login", json={"username": "admin_t", "password": "wrong-password1"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    r2 = client.post(f"{API}/auth/login", json={"username": "nobody_xx", "password": "wrong-password1"})
    assert r2.json()["error"]["message"] == r.json()["error"]["message"]


def test_me_and_logout_invalidates_token(client):
    r = client.post(f"{API}/auth/login", json={"username": "citizen_t", "password": "UserPass1234"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.cookies.clear()
    assert client.get(f"{API}/auth/me", headers=h).json()["role_codes"] == ["USER"]
    assert client.post(f"{API}/auth/logout", headers=h).status_code == 204
    client.cookies.clear()
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401


def test_password_hashed_not_plaintext(db):
    from app.models import User

    u = db.scalar(select(User).where(User.username == "admin_t"))
    assert u.password_hash.startswith("$2") and "AdminPass123" not in u.password_hash


def test_register_validation(client):
    r = client.post(f"{API}/auth/register", json={"username": "x", "email": "bad", "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------------ RBAC
@pytest.mark.parametrize("path", ["/statistics/overview", "/admin/users", "/exports/excel"])
def test_anonymous_blocked(client, path):
    client.cookies.clear()
    assert client.get(API + path).status_code == 401


def test_rbac_roles(client, citizen, operator, admin):
    assert client.get(f"{API}/statistics/overview", headers=citizen).status_code == 403
    assert client.get(f"{API}/statistics/overview", headers=operator).status_code == 200
    assert client.get(f"{API}/admin/users", headers=operator).status_code == 403
    assert client.get(f"{API}/admin/users", headers=admin).status_code == 200
    assert client.post(f"{API}/stations", headers=citizen, json={}).status_code == 403


# ------------------------------------------------------------------ trạm & GIS
STATION = {"code": "T001", "name": "Trạm test Bến Thành", "station_type": "COMBINED", "latitude": 10.7725,
           "longitude": 106.6980, "flood_threshold_cm": 50}


def test_station_crud_and_spatial_area(client, operator, db):
    r = client.post(f"{API}/stations", headers=operator, json=STATION)
    assert r.status_code == 201, r.text
    st = r.json()
    assert st["area"]["name"] == "Quận 1"  # ST_Contains với thứ tự lon/lat đúng
    assert client.post(f"{API}/stations", headers=operator, json=STATION).status_code == 409
    bad = {**STATION, "code": "T002", "latitude": 21.0, "longitude": 105.8}
    assert client.post(f"{API}/stations", headers=operator, json=bad).json()["error"]["code"] == "OUT_OF_AREA"
    r = client.patch(f"{API}/stations/{st['id']}", headers=operator, json={"name": "Trạm test đã sửa"})
    assert r.json()["name"] == "Trạm test đã sửa"
    loc = db.execute(text("SELECT ST_X(location), ST_Y(location) FROM monitoring_stations WHERE id=:i"),
                     {"i": st["id"]}).one()
    assert loc[0] == pytest.approx(106.698) and loc[1] == pytest.approx(10.7725)  # PostGIS: X=lon, Y=lat
    assert client.delete(f"{API}/stations/{st['id']}", headers=operator).status_code == 204
    assert client.get(f"{API}/stations/{st['id']}").status_code == 404


def test_station_validation(client, operator):
    r = client.post(f"{API}/stations", headers=operator, json={**STATION, "code": "bad code!", "latitude": 200})
    assert r.status_code == 422
    locs = {tuple(d["loc"][-1:]) for d in r.json()["error"]["details"]}
    assert ("code",) in locs and ("latitude",) in locs


def test_station_list_filters_and_pagination(client):
    r = client.get(f"{API}/stations", params={"size": 5, "page": 1, "station_type": "RAIN"}).json()
    assert r["total"] >= 1 and all(s["station_type"] == "RAIN" for s in r["items"])
    assert all(s["data_status"] == "DEMO" for s in r["items"])


def test_identify_point(client):
    r = client.get(f"{API}/gis/identify", params={"lat": 10.7725, "lon": 106.698})
    d = r.json()
    assert d["area"]["name"] == "Quận 1" and len(d["risk"]) == 7 and d["stations"]


def test_geojson_layers(client):
    g = client.get(f"{API}/gis/risk-layers", params={"horizon": 3}).json()
    assert len(g["features"]) == 24
    lon, lat = g["features"][0]["geometry"]["coordinates"][0][0][0][:2]
    assert 106 < lon < 107.2 and 10.3 < lat < 11.3  # GeoJSON lon/lat
    f = client.get(f"{API}/gis/features").json()
    assert f["stations"]["features"] and f["cameras"]["features"]


def test_public_hides_private_cameras(client, operator):
    client.cookies.clear()
    pub = client.get(f"{API}/cameras").json()
    staff = client.get(f"{API}/cameras", headers=operator).json()
    assert all(c["is_public"] for c in pub) and len(staff) > len(pub)


# ------------------------------------------------------------------ nhập dữ liệu
def test_import_csv_dedup_and_rejects(client, operator, db):
    sid = db.scalar(select(MonitoringStation.id).where(MonitoringStation.code == "DM011"))
    t = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%dT%H:00:00")
    csv = (f"observed_at,rainfall_mm,water_level_cm\n{t},5.5,\n{t},5.5,\nkhông-phải-ngày,1,\n"
           f"{t[:-8]}23:00:00,-4,\n").encode()
    r = client.post(f"{API}/stations/{sid}/observations/import", headers=operator,
                    files={"file": ("obs.csv", csv, "text/csv")})
    rep = r.json()
    assert rep["total_rows"] == 4 and rep["inserted"] == 2 and rep["duplicates"] == 1 and rep["rejected"] == 1
    db.rollback()  # kết thúc snapshot REPEATABLE READ để thấy dữ liệu API vừa ghi
    neg = db.scalar(select(RainfallObservation.quality_flag).where(RainfallObservation.station_id == sid,
                                                                   RainfallObservation.rainfall_mm == -4))
    assert neg == "SUSPECT"
    again = client.post(f"{API}/stations/{sid}/observations/import", headers=operator,
                        files={"file": ("obs.csv", csv, "text/csv")}).json()
    assert again["inserted"] == 0


# ------------------------------------------------------------------ AI dự báo & rủi ro
def test_forecast_contract(client):
    fc = client.get(f"{API}/forecasts/latest").json()
    assert fc
    for s in fc:
        assert [p["horizon_h"] for p in s["points"]] == [1, 2, 3, 4, 5, 6]
        for p in s["points"]:
            assert 0 <= p["flood_probability"] <= 1 and p["rainfall_mm"] >= 0
        assert s["is_simulated"] is True
    st = client.get(f"{API}/forecasts/model-status").json()
    assert st["forecast_model"]["trained_on_simulated"] and st["warning"]


def test_risk_levels_valid(client, operator):
    rows = client.get(f"{API}/forecasts/risk", params={"horizon": 2}, headers=operator).json()
    assert len(rows) == 24
    assert {r["risk_level"] for r in rows} <= {"LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA"}
    assert all(r["explanation"]["contributions"] is not None for r in rows if r["risk_level"] != "INSUFFICIENT_DATA")


def test_cold_start_new_station(client, operator, db):
    from app.jobs.pipeline import run_cycle

    r = client.post(f"{API}/stations", headers=operator, json={**STATION, "code": "T900", "name": "Trạm mới"})
    sid = r.json()["id"]
    run_cycle()
    fc = client.get(f"{API}/stations/{sid}/forecast").json()
    assert fc["points"] and fc["points"][0]["is_cold_start"] is True
    assert fc["points"][0]["data_quality"] == "POOR"


def test_order_donors_same_cluster_first():
    from app.services.forecast_service import order_donors

    cl = {1: "CORE", 2: "SUBURBAN", 3: "SUBURBAN"}
    assert order_donors([1, 2, 3], cl, "SUBURBAN") == [2, 3, 1]
    assert order_donors([1, 2, 3], cl, "") == [1, 2, 3]


def test_cold_start_prefers_same_cluster(client, operator, db, monkeypatch):
    from app.jobs.pipeline import run_cycle
    from app.models import MonitoringStation
    from app.services import forecast_service, gis_service

    run_cycle()
    areas = gis_service.area_geometries(db)
    sts = list(db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None),
                                                          MonitoringStation.area_id.is_not(None))))
    near = sts[0]
    far = next(s for s in sts if forecast_service._cluster(areas, s.area_id)
               != forecast_service._cluster(areas, near.area_id))
    r = client.post(f"{API}/stations", headers=operator,
                    json={**STATION, "code": "T901", "name": "Trạm cụm", "latitude": far.latitude, "longitude": far.longitude})
    sid = r.json()["id"]
    assert r.status_code == 201, r.text
    db.rollback()  # kết thúc snapshot cũ để thấy trạm mới
    new = db.get(MonitoringStation, sid)
    new.area_id = far.area_id  # cùng cụm với `far`, khác cụm với `near`
    db.commit()
    monkeypatch.setattr(gis_service, "nearest_stations", lambda *a, **k: [(near.id, 100.0), (far.id, 200.0)])
    info = forecast_service.run_inference(db)
    assert info["cold_start_donors"]["T901"] == {"donor": far.code, "same_cluster": True}


# ------------------------------------------------------------------ cảnh báo
def _make_alert(db):
    from app.models import AdministrativeArea

    area = db.scalar(select(AdministrativeArea).where(AdministrativeArea.name == "Quận 3"))
    a = Alert(code=f"T-{datetime.now(UTC).timestamp()}", area_id=area.id, risk_level="HIGH", status="NEW",
              title="[HIGH] Quận 3", message="test", score=0.9, horizon_h=1, is_simulated=True)
    db.add(a)
    db.commit()
    return a.id


def test_alert_workflow(client, operator, citizen, db):
    aid = _make_alert(db)
    assert client.post(f"{API}/alerts/{aid}/acknowledge", headers=citizen).status_code == 403
    r = client.post(f"{API}/alerts/{aid}/acknowledge", headers=operator)
    assert r.json()["status"] == "ACKNOWLEDGED" and r.json()["acknowledged_at"]
    assert client.post(f"{API}/alerts/{aid}/status", headers=operator,
                       json={"status": "NEW"}).json()["error"]["code"] == "INVALID_TRANSITION"
    assert client.post(f"{API}/alerts/{aid}/status", headers=operator, json={"status": "RESOLVED",
                                                                              "note": "đã bơm"}).status_code == 200
    assert client.post(f"{API}/alerts/{aid}/verify", headers=operator,
                       json={"outcome": "CONFIRMED"}).json()["verified_outcome"] == "CONFIRMED"
    d = client.get(f"{API}/alerts/{aid}", headers=operator).json()
    assert [h["action"] for h in d["history"]] == ["STATUS", "STATUS", "VERIFY"]
    client.cookies.clear()
    assert client.get(f"{API}/alerts/{aid}").status_code == 403  # đã xử lý -> không còn công khai


def test_alert_dedup(db):
    from app.repositories.observations import latest_time
    from app.services import alert_service

    issued = latest_time(db)
    alert_service.process(db, issued)
    n1 = db.scalar(select(func.count()).select_from(Alert))
    out = alert_service.process(db, issued)
    assert out["created"] == 0 and db.scalar(select(func.count()).select_from(Alert)) == n1
    open_per_area = db.execute(select(Alert.area_id, func.count()).where(
        Alert.status.in_(["NEW", "ACKNOWLEDGED", "IN_PROGRESS"])).group_by(Alert.area_id)).all()
    assert all(c == 1 for _, c in open_per_area)


def test_rule_version_validation(client, admin):
    from app.services.rule_engine import DEFAULT_RULE_CONFIG

    bad = {**DEFAULT_RULE_CONFIG, "thresholds": {"medium": 0.9, "high": 0.2}}
    assert client.post(f"{API}/admin/rules", headers=admin, json={"name": "x", "config": bad}).status_code == 422
    r = client.post(f"{API}/admin/rules", headers=admin, json={"name": "v2", "config": DEFAULT_RULE_CONFIG})
    assert r.status_code == 201 and r.json()["version"] >= 2 and r.json()["is_active"]


# ------------------------------------------------------------------ thống kê & Excel
def _range():
    end = datetime.now(UTC).replace(tzinfo=None)
    return end - timedelta(days=7), end


def test_statistics_match_sql(client, operator, db):
    start, end = _range()
    o = client.get(f"{API}/statistics/overview", headers=operator,
                   params={"date_from": iso(start), "date_to": iso(end)}).json()
    assert o["stations_total"] == db.scalar(select(func.count()).select_from(MonitoringStation)
                                            .where(MonitoringStation.deleted_at.is_(None)))
    sid = db.scalar(select(MonitoringStation.id).where(MonitoringStation.code == "DM001"))
    r = client.get(f"{API}/statistics/rainfall", headers=operator,
                   params={"date_from": iso(start), "date_to": iso(end), "station_id": sid, "group": "day"}).json()
    sql_sum = db.scalar(select(func.sum(RainfallObservation.rainfall_mm)).where(
        RainfallObservation.station_id == sid, RainfallObservation.observed_at >= start,
        RainfallObservation.observed_at < end, RainfallObservation.quality_flag == "VALID")) or 0
    assert sum(x["sum"] or 0 for x in r["series"]) == pytest.approx(sql_sum, abs=0.05)


def test_excel_export_matches_filter(client, operator, db):
    start, end = _range()
    sid = db.scalar(select(MonitoringStation.id).where(MonitoringStation.code == "DM002"))
    r = client.get(f"{API}/exports/excel", headers=operator,
                   params={"report": "rainfall", "date_from": iso(start), "date_to": iso(end), "station_id": sid})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Tong_quan", "Luong_mua", "Nguon_du_lieu"]
    ws = wb["Luong_mua"]
    assert ws["A1"].value.startswith("Báo cáo lượng mưa")
    header_row = next(i for i in range(1, 15) if ws.cell(i, 1).value == "Thời gian (giờ VN)")
    data = [r for r in ws.iter_rows(min_row=header_row + 1, values_only=True) if r[0]]
    expected = db.scalar(select(func.count()).select_from(RainfallObservation).where(
        RainfallObservation.station_id == sid, RainfallObservation.observed_at >= start,
        RainfallObservation.observed_at < end))
    assert len(data) == expected
    assert {row[1] for row in data} == {"DM002"}
    assert ws.freeze_panes and ws.auto_filter.ref
    assert ws.cell(header_row + 1, 1).number_format == "dd/mm/yyyy hh:mm"


def test_excel_formula_injection_and_leading_zero(client, operator, admin):
    client.post(f"{API}/stations", headers=operator, json={**STATION, "code": "007", "name": "=HYPERLINK(\"x\")",
                                                            "latitude": 10.78, "longitude": 106.70})
    r = client.get(f"{API}/exports/excel", headers=admin, params={"report": "stations"})
    ws = load_workbook(io.BytesIO(r.content))["Tram_quan_trac"]
    vals = [(row[0], row[1]) for row in ws.iter_rows(values_only=True)]
    assert ("007", "'=HYPERLINK(\"x\")") in vals


def test_full_report_has_all_sheets(client, admin):
    r = client.get(f"{API}/exports/excel", headers=admin, params={"report": "full"})
    names = load_workbook(io.BytesIO(r.content)).sheetnames
    assert names[0] == "Tong_quan" and "Danh_gia_mo_hinh" in names and "Canh_bao_ngap" in names


def test_csv_export(client, operator):
    r = client.get(f"{API}/exports/csv", headers=operator, params={"kind": "water_level"})
    assert r.status_code == 200 and r.content.startswith("﻿".encode())


# ------------------------------------------------------------------ camera
def test_camera_analyze_and_upload_guard(client, operator):
    from app.ai.computer_vision.synthetic import camera_frame

    ok, buf = cv2.imencode(".jpg", camera_frame("CAMX", 0.6, 1))
    r = client.post(f"{API}/cameras/analyze", headers=operator, files={"file": ("a.jpg", buf.tobytes(), "image/jpeg")})
    assert r.status_code == 201, r.text
    d = r.json()
    assert 0 <= d["flood_ratio"] <= 1 and d["method"] in ("YOLOV8_SEG", "HEURISTIC")
    img = client.get(d["result_image_url"], headers=operator)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    client.cookies.clear()
    assert client.get(d["image_url"]).status_code == 403  # ảnh upload không gắn camera công khai
    bad = client.post(f"{API}/cameras/analyze", headers=operator, files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 415
    exe = client.post(f"{API}/cameras/analyze", headers=operator, files={"file": ("x.exe", b"MZ", "application/x")})
    assert exe.status_code == 415


def test_analyze_rejects_traffic_camera(client, operator, db):
    from app.core.spatial import point_wkt
    from app.models import Camera, DataSource

    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    cam = Camera(code="TT-" + "a" * 24, name="tt", latitude=10.7, longitude=106.7, location=point_wkt(106.7, 10.7),
                 status="ACTIVE", is_public=True, retention_days=1, source_id=src.id)
    db.add(cam)
    db.commit()
    try:
        ok, buf = cv2.imencode(".jpg", __import__("numpy").zeros((32, 32, 3), "uint8"))
        r = client.post(f"{API}/cameras/analyze", headers=operator, data={"camera_id": cam.id},
                        files={"file": ("a.jpg", buf.tobytes(), "image/jpeg")})
        assert r.status_code == 422 and r.json()["error"]["code"] == "TRAFFIC_CAMERA_NOT_ANALYZED"
    finally:
        db.delete(cam)
        db.commit()


# ------------------------------------------------------------------ DB
def test_seed_idempotent(db):
    from app import seed

    before = seed.check(db)
    seed.seed_base(db)
    seed.seed_areas(db)
    seed.seed_demo_assets(db)
    assert seed.derive_flood_history(db) == 0
    after = seed.check(db)
    assert before == after


def test_foreign_keys_and_spatial_index(db):
    fks = db.execute(text("SELECT COUNT(*) FROM information_schema.referential_constraints "
                          "WHERE constraint_schema = 'public'")).scalar()
    assert fks >= 30
    sp = db.execute(text("SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public' "
                         "AND indexdef LIKE '%USING gist%'")).scalar()
    assert sp == 7


def test_transaction_rollback(db):
    from sqlalchemy.exc import IntegrityError

    n = db.scalar(select(func.count()).select_from(MonitoringStation))
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO monitoring_stations (code, name, station_type, address, latitude, longitude, "
                        "location, managing_unit, status, interval_minutes, flood_threshold_cm, source_id, notes, "
                        "created_at, updated_at) VALUES ('DM001','x','RAIN','',10.8,106.7,"
                        "ST_GeomFromText('POINT(106.7 10.8)',4326),'','ACTIVE',60,50,1,'',"
                        "NOW(),NOW())"))
    db.rollback()
    assert db.scalar(select(func.count()).select_from(MonitoringStation)) == n


def test_public_responses_hide_internal_fields(client, operator, db):
    from app.models import Camera

    cam = db.scalar(select(Camera).where(Camera.is_public.is_(True)).limit(1))
    client.patch(f"{API}/cameras/{cam.id}", headers=operator, json={"stream_url": "rtsp://user:pw@10.0.0.5/live"})
    client.cookies.clear()
    assert client.get(f"{API}/cameras/{cam.id}").json()["stream_url"] == ""
    assert client.get(f"{API}/cameras/{cam.id}", headers=operator).json()["stream_url"].startswith("rtsp://")
    aid = _make_alert(db)
    client.post(f"{API}/alerts/{aid}/assign", headers=operator, json={"user_id": None, "note": "x"})
    client.cookies.clear()
    pub = client.get(f"{API}/alerts/{aid}").json()
    assert pub["assigned_to"] is None and pub["explanation"] is None and pub["history"] == []


def test_dict_endpoints_emit_utc_z(client, operator):
    d = client.get(f"{API}/gis/identify", params={"lat": 10.7725, "lon": 106.698}).json()
    assert d["issued_at"].endswith("Z")
    o = client.get(f"{API}/statistics/overview", headers=operator).json()
    assert o["generated_at"].endswith("Z") and o["latest_forecast_at"].endswith("Z")


# ------------------------------------------------------------------ báo cáo ngập, điểm ngập, chỉ đường
def _report(client, headers, **kw):
    body = {"latitude": 10.7938, "longitude": 106.708, "severity": "KNEE", "note": "test", **kw}
    return client.post(f"{API}/reports", headers=headers, json=body)


def test_report_lifecycle_and_rbac(client, citizen, operator, db):
    client.cookies.clear()
    assert _report(client, {}).status_code == 401
    assert _report(client, citizen, latitude=21.0, longitude=105.8).json()["error"]["code"] == "OUT_OF_AREA"
    r = _report(client, citizen)
    assert r.status_code == 201 and r.json()["reporter"] is None
    rid = r.json()["id"]
    client.cookies.clear()
    pub = client.get(f"{API}/reports/active").json()
    assert any(x["id"] == rid and x["reporter"] is None for x in pub)
    assert client.post(f"{API}/reports/{rid}/confirm", headers=citizen).status_code == 409  # không tự xác nhận
    assert client.post(f"{API}/reports/{rid}/confirm", headers=operator).json()["confirmations"] == 1
    assert client.post(f"{API}/reports/{rid}/confirm", headers=operator).status_code == 409
    assert client.post(f"{API}/reports/{rid}/reject", headers=citizen).status_code == 403
    assert client.post(f"{API}/reports/{rid}/reject", headers=operator).json()["status"] == "REJECTED"
    client.cookies.clear()
    assert all(x["id"] != rid for x in client.get(f"{API}/reports/active").json())


def test_report_expires(client, operator, db):
    from app.core.database import utcnow
    from app.models import FloodReport
    from app.services import report_service

    rid = _report(client, operator, latitude=10.80, longitude=106.70).json()["id"]
    db.rollback()
    r = db.get(FloodReport, rid)
    r.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert report_service.expire(db) >= 1
    db.refresh(r)
    assert r.status == "EXPIRED"


def test_hotspots_seed_idempotent_and_public(client, db):
    from app import seed

    assert seed.seed_hotspots(db) >= 30
    assert seed.seed_hotspots(db) == 0
    client.cookies.clear()
    rows = client.get(f"{API}/gis/hotspots").json()
    assert rows and all(x["source_url"].startswith("https://") for x in rows)


def test_route_flags_reported_segment(client, operator, monkeypatch):
    from app.services import openmeteo_service as om
    from app.services import routing_service as rs

    line = [[106.70 + i * 0.0005, 10.85] for i in range(20)]
    osrm = {"code": "Ok", "routes": [{"distance": 1000, "duration": 120, "geometry": {"type": "LineString", "coordinates": line},
                                      "legs": [{"steps": [{"name": "Lê Lợi", "distance": 1000, "duration": 120,
                                                           "maneuver": {"type": "depart", "location": line[0]}}]}]}]}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return osrm

    monkeypatch.setattr(rs.httpx, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(om, "elevations", lambda coords: [8.0] * len(coords))
    body = {"start": line[0], "end": line[-1], "horizon_h": 0}
    client.cookies.clear()
    before = client.post(f"{API}/routing/route", json=body).json()["routes"][0]
    assert before["summary"]["km_by_status"]["REPORTED_FLOODED"] == 0 and before["steps"][0]["instruction"].startswith("Xuất phát")
    assert _report(client, operator, latitude=10.85, longitude=106.7045).status_code == 201
    client.cookies.clear()
    after = client.post(f"{API}/routing/route", json=body).json()["routes"][0]
    assert after["summary"]["km_by_status"]["REPORTED_FLOODED"] > 0
    assert any(s["status"] == "REPORTED_FLOODED" and s["reasons"] for s in after["segments"])
    bad = client.post(f"{API}/routing/route", json={**body, "end": [105.8, 21.0]})
    assert bad.status_code == 422


def test_route_flags_missing_elevation(client, monkeypatch):
    from app.services import openmeteo_service as om
    from app.services import routing_service as rs

    line = [[106.70 + i * 0.0005, 10.86] for i in range(10)]
    osrm = {"code": "Ok", "routes": [{"distance": 500, "duration": 60, "geometry": {"type": "LineString", "coordinates": line},
                                      "legs": [{"steps": []}]}]}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return osrm

    monkeypatch.setattr(rs.httpx, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(om, "elevations", lambda coords: [None] * len(coords))
    r = client.post(f"{API}/routing/route", json={"start": line[0], "end": line[-1], "horizon_h": 0})
    assert r.json()["elevation_missing_ratio"] == 1.0


def test_sse_does_not_hold_db_session():
    import inspect

    from app.controllers.misc import events

    # stream sống lâu không được nhận session/người dùng qua dependency (giữ kết nối DB suốt thời gian mở tab)
    assert list(inspect.signature(events).parameters) == ["request"]


# ------------------------------------------------------------------ mô phỏng, phường, camera giao thông
SIM = {"latitude": 10.87, "longitude": 106.7045, "radius_m": 300, "depth_cm": 40}


def test_simulation_rbac_and_validation(client, admin, operator, citizen):
    client.cookies.clear()
    assert client.get(f"{API}/admin/simulations").status_code == 401
    for h in (operator, citizen):
        assert client.post(f"{API}/admin/simulations", headers=h, json=SIM).status_code == 403
    assert client.post(f"{API}/admin/simulations", headers=admin, json={**SIM, "radius_m": 50}).status_code == 422
    assert client.post(f"{API}/admin/simulations", headers=admin, json={**SIM, "latitude": 21.0, "longitude": 105.8}).status_code == 422


def test_simulation_only_affects_admin_route_and_no_alerts(client, admin, citizen, db, monkeypatch):
    from app.services import openmeteo_service as om
    from app.services import routing_service as rs

    line = [[106.70 + i * 0.0005, 10.87] for i in range(20)]
    osrm = {"code": "Ok", "routes": [{"distance": 1000, "duration": 120, "geometry": {"type": "LineString", "coordinates": line},
                                      "legs": [{"steps": []}]}]}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return osrm

    monkeypatch.setattr(rs.httpx, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(om, "elevations", lambda coords: [8.0] * len(coords))
    alerts_before = db.scalar(select(func.count()).select_from(Alert))
    sid = client.post(f"{API}/admin/simulations", headers=admin, json=SIM).json()["id"]
    body = {"start": line[0], "end": line[-1], "horizon_h": 0}
    r_admin = client.post(f"{API}/routing/route", headers=admin, json=body).json()["routes"][0]
    assert r_admin["summary"]["km_by_status"]["LIKELY_FLOODED"] > 0 and r_admin["summary"]["flooded_km"] > 0
    assert "SIMULATED_FLOOD" not in {s["status"] for s in r_admin["segments"]}
    assert any("MÔ PHỎNG" in x for s in r_admin["segments"] for x in s["reasons"])
    r_user = client.post(f"{API}/routing/route", headers=citizen, json=body).json()["routes"][0]
    assert not any("MÔ PHỎNG" in x for s in r_user["segments"] for x in s["reasons"])
    client.cookies.clear()
    r_guest = client.post(f"{API}/routing/route", json=body).json()["routes"][0]
    assert not any("MÔ PHỎNG" in x for s in r_guest["segments"] for x in s["reasons"])
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Alert)) == alerts_before
    assert client.delete(f"{API}/admin/simulations/{sid}", headers=admin).status_code == 204
    assert client.delete(f"{API}/admin/simulations", headers=admin).status_code == 204


def test_latest_values_as_of_ignores_later_observations(client, db):
    from app.repositories import observations as obs_repo

    sid, v = next((k, x) for k, x in obs_repo.latest_values(db).items() if x.get("rain_at"))
    cut = v["rain_at"] - timedelta(hours=3)
    assert obs_repo.latest_values(db, [sid], cut)[sid]["rain_at"] <= cut


def test_backfill_without_alerts_skips_alert_processing(client, db, monkeypatch):
    from app.jobs import backfill as bf

    calls = []
    monkeypatch.setattr(bf.obs_repo, "latest_time", lambda _: datetime(2000, 1, 2))  # trước mọi snapshot đã có
    monkeypatch.setattr(bf.forecast_service, "active_model", lambda _: True)
    monkeypatch.setattr(bf.forecast_service, "run_inference", lambda _, t: calls.append(t))
    monkeypatch.setattr(bf.risk_service, "evaluate_all", lambda _, t: None)
    monkeypatch.setattr(bf.alert_service, "process", lambda *a, **k: pytest.fail("không được tạo cảnh báo"))
    monkeypatch.setattr(bf, "_auto_close", lambda *a: pytest.fail("không được đóng cảnh báo"))
    assert bf.backfill(db, days=1, alerts=False) == 26 == len(calls)  # [end-1d-1h, end] gồm cả hai đầu
    assert calls[0] == datetime(1999, 12, 31, 23) and calls[-1] == datetime(2000, 1, 2)


def test_backfill_force_reruns_when_snapshots_exist(client, db, monkeypatch):
    from app.jobs import backfill as bf
    from app.models import FloodRiskSnapshot

    calls = []
    have = db.scalar(select(func.min(FloodRiskSnapshot.issued_at)))
    assert have is not None  # đã có snapshot
    end = have + timedelta(days=1)
    monkeypatch.setattr(bf.obs_repo, "latest_time", lambda _: end)
    monkeypatch.setattr(bf.forecast_service, "active_model", lambda _: True)
    monkeypatch.setattr(bf.forecast_service, "run_inference", lambda _, t: calls.append(t))
    monkeypatch.setattr(bf.risk_service, "evaluate_all", lambda _, t: None)
    assert bf.backfill(db, days=1, alerts=False) == 0
    assert bf.backfill(db, days=1, alerts=False, force=True) == 26 and calls[-1] == end


def test_ward_hierarchy_and_alerts_only_for_district(client, db):
    from app.gis.importer import import_geojson
    from app.models import AdministrativeArea, DataSource, FloodRiskSnapshot
    from app.repositories.observations import latest_time
    from app.services import alert_service, risk_service

    q1 = db.scalar(select(AdministrativeArea).where(AdministrativeArea.name == "Quận 1"))
    lat, lon = q1.centroid_lat, q1.centroid_lon
    d = 0.001
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    data = {"features": [{"properties": {"name": "Phường Thử", "code": "W-TEST"}, "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    assert import_geojson(db, data, src) == 1
    db.commit()
    ward = db.scalar(select(AdministrativeArea).where(AdministrativeArea.code == "W-TEST"))
    assert ward.parent_id == q1.id
    client.cookies.clear()
    r = client.get(f"{API}/gis/identify", params={"lat": lat, "lon": lon}).json()
    assert r["area"]["name"] == "Phường Thử" and r["district"] == "Quận 1"
    assert all(a["level"] == "DISTRICT" for a in client.get(f"{API}/gis/areas").json())
    assert [a["name"] for a in client.get(f"{API}/gis/areas", params={"level": "WARD", "parent_id": q1.id}).json()] == ["Phường Thử"]
    issued = latest_time(db)
    risk_service.evaluate_all(db, issued)
    assert db.scalar(select(FloodRiskSnapshot).where(FloodRiskSnapshot.area_id == ward.id, FloodRiskSnapshot.issued_at == issued))
    db.add(FloodRiskSnapshot(area_id=ward.id, issued_at=issued, horizon_h=9, risk_level="HIGH", score=1.0))
    db.commit()
    alert_service.process(db, issued)
    assert not db.scalar(select(Alert).where(Alert.area_id == ward.id))
    # dọn để không ảnh hưởng test đếm 24 khu vực
    db.execute(text("DELETE FROM flood_risk_snapshots WHERE area_id=:i"), {"i": ward.id})
    db.delete(ward)
    db.commit()


def test_traffic_snapshot_proxy(client, db, monkeypatch):
    from app.core.spatial import point_wkt
    from app.models import Camera
    from app.services import traffic_camera_service as tc

    src = tc.source(db)
    cam = Camera(code="TT-662b86c41afb9c00172dd31c", name="Cam thử", latitude=10.8, longitude=106.7,
                 location=point_wkt(106.7, 10.8), is_public=True, source_id=src.id)
    db.add(cam)
    db.commit()
    calls = []

    class Resp:
        content = b"\xff\xd8jpeg"

        def raise_for_status(self):
            pass

    def fake(url, params=None, **k):
        calls.append((url, params))
        return Resp()

    monkeypatch.setattr(tc.httpx, "get", fake)
    tc._cache.clear()
    client.cookies.clear()
    for _ in range(2):
        r = client.get(f"{API}/cameras/{cam.id}/snapshot")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert calls == [(f"{tc.BASE}/render/ImageHandler.ashx", {"id": "662b86c41afb9c00172dd31c"})]  # cache + host cố định
    assert all(c["code"] != cam.code for c in client.get(f"{API}/cameras").json())
    tc._cache.clear()

    def boom(*a, **k):
        raise tc.httpx.ConnectTimeout("x")

    monkeypatch.setattr(tc.httpx, "get", boom)
    assert client.get(f"{API}/cameras/{cam.id}/snapshot").status_code == 502
    assert client.get(f"{API}/cameras/999999/snapshot").status_code == 404
    db.delete(cam)
    db.commit()

# ------------------------------------------------------------------ ngập do triều / độ sâu / báo cáo
class _Box:
    """Trạng thái dùng chung của test: issued, danh sách hàng tạo thêm để dọn."""

    def __init__(self, db, issued):
        self.db, self.issued, self.areas, self.rows = db, issued, [], []

    def ward(self, parent_name, code, name, dlon, elev):
        from app.gis.importer import import_geojson
        from app.models import AdministrativeArea, DataSource

        parent = self.db.scalar(select(AdministrativeArea).where(AdministrativeArea.name == parent_name))
        src = self.db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
        d, lon, lat = 0.0005, parent.centroid_lon + dlon, parent.centroid_lat
        ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
        data = {"features": [{"properties": {"name": name, "code": code},
                              "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
        assert import_geojson(self.db, data, src) == 1
        w = self.db.scalar(select(AdministrativeArea).where(AdministrativeArea.code == code))
        assert w.parent_id == parent.id
        w.elevation_m = elev
        self.db.commit()
        self.areas.append(w.id)
        return w

    def add(self, table, obj):
        self.db.add(obj)
        self.db.commit()
        self.rows.append((table, obj.id))
        return obj

    def snap(self, area, h=0):
        from app.models import FloodRiskSnapshot

        return self.db.scalar(select(FloodRiskSnapshot).where(
            FloodRiskSnapshot.area_id == area.id, FloodRiskSnapshot.issued_at == self.issued,
            FloodRiskSnapshot.horizon_h == h))


@pytest.fixture
def box(db, monkeypatch):
    """Dọn sạch sau test: hàng tạo thêm, cảnh báo/lịch sử/thông báo mới, khôi phục cảnh báo cũ và snapshot gốc."""
    from app.models import AlertHistory, Notification
    from app.repositories.observations import latest_time
    from app.services import risk_service

    cols = ("message", "explanation", "score", "horizon_h", "risk_level", "title", "recommendations", "status",
            "closed_at", "resolved_at")
    saved = {a.id: {c: getattr(a, c) for c in cols} for a in db.scalars(select(Alert))}
    mh = db.scalar(select(func.max(AlertHistory.id))) or 0
    mn = db.scalar(select(func.max(Notification.id))) or 0
    b = _Box(db, latest_time(db))
    yield b
    db.rollback()
    monkeypatch.undo()
    db.execute(text("DELETE FROM alert_history WHERE id>:h"), {"h": mh})
    db.execute(text("DELETE FROM notifications WHERE id>:n"), {"n": mn})
    db.execute(text("DELETE FROM alerts WHERE id>:a"), {"a": max(saved, default=0)})
    for aid, vals in saved.items():
        db.execute(update(Alert).where(Alert.id == aid).values(**vals))
    db.execute(text("DELETE FROM flood_risk_snapshots WHERE issued_at >= '2029-01-01'"))
    for table, rid in reversed(b.rows):
        db.execute(text(f"DELETE FROM {table} WHERE id=:i"), {"i": rid})
    for i in b.areas:
        db.execute(text("DELETE FROM flood_risk_snapshots WHERE area_id=:i"), {"i": i})
        db.execute(text("DELETE FROM administrative_areas WHERE id=:i"), {"i": i})
    db.commit()
    if b.issued:
        risk_service.evaluate_all(db, b.issued)  # trả snapshot về trạng thái do pipeline tạo


def _close_open_alerts(db, area_name):
    """Đóng tạm cảnh báo mở có sẵn của quận để test không phụ thuộc (box khôi phục sau)."""
    from app.models import AdministrativeArea

    aid = db.scalar(select(AdministrativeArea.id).where(AdministrativeArea.name == area_name))
    for a in db.scalars(select(Alert).where(Alert.area_id == aid, Alert.status.in_(("NEW", "ACKNOWLEDGED",
                                                                                   "IN_PROGRESS")))):
        a.status, a.closed_at = "CLOSED", datetime(2000, 1, 1)
    db.commit()
    return aid


def _no_station_water(monkeypatch):
    """Bỏ mực nước trạm mô phỏng (DEMO): nó dao động theo giờ chạy test và có lúc vượt ngưỡng, ép mức Cao."""
    from dataclasses import replace

    from app.services import risk_service

    orig = risk_service.evaluate
    monkeypatch.setattr(risk_service, "evaluate", lambda inp, cfg, prev=None: orig(replace(inp, water_level_ratio=None), cfg, prev))


def test_tide_depth_rollup_by_horizon_and_alert_message(client, db, box, monkeypatch):
    from app.models import AdministrativeArea
    from app.services import alert_service, risk_service
    from app.services import openmeteo_service as om
    _no_station_water(monkeypatch)

    issued = box.issued
    hot_t = issued + timedelta(hours=2)  # mock tide_at theo t: chỉ mốc +2h có triều cao
    monkeypatch.setattr(om, "tide_stats", lambda _db: (0.0, 100.0))
    monkeypatch.setattr(om, "tide_at", lambda _db, t: 142.0 if t == hot_t else 10.0)
    q7, q1 = (db.scalar(select(AdministrativeArea).where(AdministrativeArea.name == n)) for n in ("Quận 7", "Quận 1"))
    low, high = box.ward("Quận 7", "W-T1", "Phường Thấp", 0, 2.0), box.ward("Quận 7", "W-T2", "Phường Cao", 0.002, 20.0)
    q1w = box.ward("Quận 1", "W-T3", "Phường Thấp Q1", 0, 2.0)
    exposed = risk_service.tide_exposed_wards(db)
    assert low.id in exposed and high.id not in exposed and q1w.id not in exposed
    risk_service.evaluate_all(db, issued)

    s = box.snap(low, 2)
    assert s.risk_level == "HIGH" and s.explanation["cause"] == "TIDE" and s.explanation["depth_cm"] == 40
    assert box.snap(high, 2).explanation["cause"] is None
    d7 = box.snap(q7, 2)
    assert d7.risk_level == "HIGH" and d7.explanation["depth_cm"] == 40
    assert d7.explanation["wards"] == ["Phường Thấp"] and d7.explanation["wards_total"] == 1
    for h in (0, 3):  # triều đã hạ: không còn độ sâu/override ở phường và quận
        for a in (low, q7):
            e = box.snap(a, h).explanation
            assert e["cause"] is None and e["depth_cm"] is None
            assert not any("ngập khoảng" in o for o in e["overrides"])
    for h in (0, 2, 3):  # quận không ven triều
        ex = box.snap(q1w, h).explanation
        assert ex["cause"] is None and ex["inputs"]["tide_ratio"] == 0.0
        assert box.snap(q1, h).explanation["cause"] != "TIDE"
    assert box.snap(q1, 2).risk_level != "HIGH"

    _close_open_alerts(db, "Quận 7")
    alert_service.process(db, issued)
    a = db.scalar(select(Alert).where(Alert.area_id == q7.id, Alert.status == "NEW").order_by(Alert.id.desc()))
    assert a.title.startswith("[CAO]") and "Ngập do triều" in a.message and "40 cm" in a.message
    assert "Phường Thấp" in a.message and "Phường Thấp" in a.explanation["wards"]
    client.cookies.clear()
    mine = next(i for i in client.get(f"{API}/alerts").json()["items"] if i["id"] == a.id)
    assert mine["cause"] == "TIDE" and mine["depth_cm"] == 40 and mine["wards"] == ["Phường Thấp"]
    assert mine["explanation"] is None


def test_severe_hotspot_wards_filters(db, box):
    from app.core.spatial import point_wkt
    from app.models import DataSource, FloodHotspot, HistoricalFloodEvent
    from app.services import risk_service

    issued = datetime(2026, 10, 28, 12)
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    ok, future, shallow, far = (box.ward("Quận 7", f"W-S{i}", f"Phường S{i}", 0.001 * i, 5.0) for i in range(4))
    base = [(10.50, 106.50), (10.50, 106.60), (10.50, 106.70), (10.50, 106.80)]
    for w, (lat, lon), start, depth, off in zip(
            (ok, future, shallow, far), base,
            (datetime(2026, 10, 27), datetime(2026, 10, 29), datetime(2026, 10, 27), datetime(2026, 10, 27)),
            (40, 40, 10, 40), (0.003, 0.003, 0.003, 0.02), strict=True):  # 0.003 độ ~ 330 m; 0.02 độ ~ 2,2 km
        box.add("flood_hotspots", FloodHotspot(name=f"Điểm {w.code}", latitude=lat, longitude=lon, area_id=w.id,
                                               location=point_wkt(lon, lat), source_id=src.id))
        box.add("historical_flood_events", HistoricalFloodEvent(
            location_name=f"Sự kiện {w.code}", latitude=lat + off, longitude=lon, location=point_wkt(lon, lat + off),
            started_at=start, max_depth_cm=depth, cause="RAIN", source_id=src.id))
    got = risk_service.severe_hotspot_wards(db, issued)
    assert ok.id in got and not ({future.id, shallow.id, far.id} & got)


def test_reports_in_evaluate_all(db, box, monkeypatch):
    from app.core.spatial import point_wkt
    from app.models import FloodReport
    from app.services import openmeteo_service as om
    from app.services import risk_service

    monkeypatch.setattr(om, "tide_stats", lambda _db: None)
    monkeypatch.setattr(om, "tide_at", lambda _db, _t: None)
    issued = box.issued
    conf = box.ward("Quận 3", "W-R1", "Phường R1", 0, 20.0)
    unconf, expired, later = (box.ward("Quận 1", f"W-R{i}", f"Phường R{i}", 0.001 * i, 20.0) for i in (2, 3, 4))

    def rep(w, confirmations=0, expires=timedelta(hours=3), reported=timedelta(minutes=-10)):
        box.add("flood_reports", FloodReport(
            latitude=w.centroid_lat, longitude=w.centroid_lon, location=point_wkt(w.centroid_lon, w.centroid_lat),
            severity="KNEE", status="ACTIVE", confirmations=confirmations, area_id=w.id,
            reported_at=issued + reported, expires_at=issued + expires))

    rep(conf, 1)
    rep(unconf, 0)
    rep(expired, 2, expires=timedelta(minutes=-1))  # hết hạn trước issued
    rep(later, 2, reported=timedelta(hours=2))  # báo cáo sau issued + 1h
    risk_service.evaluate_all(db, issued)
    for h in (0, 1):
        s = box.snap(conf, h)
        assert s.risk_level == "HIGH" and s.explanation["cause"] == "REPORT" and s.explanation["depth_cm"] == 40
        assert "Có báo cáo ngập đã được xác nhận" in s.explanation["overrides"]
        u = box.snap(unconf, h)
        assert u.risk_level == "MEDIUM" and not u.explanation["overrides"] and u.explanation["depth_cm"] is None
        assert "Có báo cáo ngập chưa xác nhận" in u.explanation["notes"] and u.explanation["cause"] == "REPORT"
    for w in (expired, later):
        e = box.snap(w, 0).explanation
        assert e["cause"] is None and e["inputs"]["report_confirmations"] is None
    assert box.snap(conf, 2).explanation["cause"] is None  # báo cáo chỉ áp dụng h <= 1
    from app.models import AdministrativeArea
    q1 = db.scalar(select(AdministrativeArea).where(AdministrativeArea.name == "Quận 1"))
    d = box.snap(q1, 0).explanation
    assert d["cause"] == "REPORT" and not d["wards"]  # R2 chưa xác nhận, không có độ sâu
    assert d["inputs"]["report_confirmations"] is None and box.snap(q1, 0).risk_level not in ("MEDIUM", "HIGH")


def test_camera_detection_is_ward_level(db, box, monkeypatch):
    from app.core.spatial import point_wkt
    from app.models import AdministrativeArea, Camera, CameraDetection, CameraFrame, DataSource
    from app.services import gis_service, risk_service
    from app.services import openmeteo_service as om
    _no_station_water(monkeypatch)

    monkeypatch.setattr(om, "tide_stats", lambda _db: None)
    monkeypatch.setattr(om, "tide_at", lambda _db, _t: None)
    issued = box.issued
    q7 = db.scalar(select(AdministrativeArea).where(AdministrativeArea.name == "Quận 7"))
    a, b = box.ward("Quận 7", "W-C1", "Phường C1", 0, 20.0), box.ward("Quận 7", "W-C2", "Phường C2", 0.002, 20.0)
    assert gis_service.area_at(db, a.centroid_lon, a.centroid_lat, "DISTRICT").id == q7.id  # phép gán area_id của script nạp camera
    assert gis_service.area_at(db, 0.0, 0.0, "DISTRICT") is None
    src = db.scalar(select(DataSource).where(DataSource.code == "MANUAL"))
    cam = box.add("cameras", Camera(code="CAM-WARD-T", name="t", latitude=a.centroid_lat, longitude=a.centroid_lon,
                                    location=point_wkt(a.centroid_lon, a.centroid_lat), status="ACTIVE",
                                    is_public=False, retention_days=1, source_id=src.id, area_id=None))
    fr = box.add("camera_frames", CameraFrame(camera_id=cam.id, captured_at=issued, image_path="x"))
    det = box.add("camera_detections", CameraDetection(
        frame_id=fr.id, camera_id=cam.id, detected_at=issued - timedelta(minutes=10), method="YOLOV8_SEG",
        flood_ratio=0.6, confidence=0.9))
    risk_service.evaluate_all(db, issued)
    for h in (0, 1):
        s = box.snap(a, h)
        assert s.risk_level == "HIGH" and s.explanation["cause"] == "CAMERA" and s.explanation["depth_cm"] is None
        assert box.snap(b, h).risk_level != "HIGH" and box.snap(b, h).explanation["cause"] is None
        d = box.snap(q7, h)
        assert d.risk_level == "HIGH" and d.explanation["cause"] == "CAMERA" and d.explanation["wards"] == ["Phường C1"]
    assert box.snap(a, 2).explanation["cause"] is None and box.snap(a, 2).risk_level != "HIGH"
    from app.models import FloodReport  # báo cáo chưa xác nhận không che nguyên nhân camera
    box.add("flood_reports", FloodReport(
        latitude=a.centroid_lat, longitude=a.centroid_lon, location=point_wkt(a.centroid_lon, a.centroid_lat),
        severity="KNEE", status="ACTIVE", confirmations=0, area_id=a.id,
        reported_at=issued - timedelta(minutes=10), expires_at=issued + timedelta(hours=3)))
    risk_service.evaluate_all(db, issued)
    assert box.snap(a, 0).explanation["cause"] == "CAMERA"
    d = box.snap(q7, 0).explanation
    assert d["cause"] == "CAMERA" and d["wards"] == ["Phường C1"]
    det.detected_at = issued - timedelta(minutes=120)  # quá 90 phút: bỏ qua
    db.commit()
    risk_service.evaluate_all(db, issued)
    assert box.snap(a, 0).explanation["cause"] == "REPORT" and box.snap(q7, 0).explanation["cause"] != "CAMERA"
    for method, when in (("HEURISTIC", issued - timedelta(minutes=10)), ("YOLOV8_SEG", issued + timedelta(minutes=90))):
        det.method, det.detected_at = method, when  # heuristic hoặc muộn hơn issued_at + 1 h: bỏ qua
        db.commit()
        risk_service.evaluate_all(db, issued)
        assert box.snap(a, 0).explanation["cause"] == "REPORT", method


def test_open_alert_refresh_same_level_only(db, box):
    from app.models import AdministrativeArea, AlertHistory, FloodRiskSnapshot, Notification
    from app.services import alert_service

    aid = _close_open_alerts(db, "Quận 7")
    t1, t2, t3 = (datetime(2030, 1, 1, h) for h in (0, 1, 2))

    def snap(t, level, depth):
        db.add(FloodRiskSnapshot(area_id=aid, issued_at=t, horizon_h=0, risk_level=level, score=0.9,
                                 explanation={"cause": "TIDE", "depth_cm": depth, "wards": ["Phường A"]}))
        db.commit()
        alert_service.process(db, t)
        return db.scalar(select(Alert).where(Alert.area_id == aid, Alert.status == "NEW").order_by(Alert.id.desc()))

    a = snap(t1, "HIGH", 40)
    assert "40 cm" in a.message
    hist = lambda: db.scalar(select(func.count()).select_from(AlertHistory).where(AlertHistory.alert_id == a.id))  # noqa: E731
    notes = lambda: db.scalar(select(func.count()).select_from(Notification).where(Notification.alert_id == a.id))  # noqa: E731
    h0, n0 = hist(), notes()
    a.title = "[CŨ]"
    db.commit()
    a = snap(t2, "HIGH", 70)  # cùng mức, nội dung đổi -> làm mới lặng lẽ
    assert a.title == "[CAO] Quận 7"
    assert "70 cm" in a.message and a.explanation["depth_cm"] == 70 and (hist(), notes()) == (h0, n0)
    msg = a.message
    a = snap(t3, "MEDIUM", 10)  # thấp hơn: giữ nguyên
    assert a.risk_level == "HIGH" and a.message == msg and a.explanation["depth_cm"] == 70
    assert db.get(AdministrativeArea, aid).name == "Quận 7"


# ------------------------------------------------------------------ phường trong DB test: gán quận, ẩn thông tin xử lý
def test_event_and_station_in_ward_attach_to_district(client, db, box, operator):
    from app.models import AdministrativeArea

    w = box.ward("Quận 1", "W-D1", "Phường D1", 0, 3.0)
    q1 = db.get(AdministrativeArea, w.parent_id)
    body = {"location_name": "Điểm ngập trong phường", "latitude": w.centroid_lat, "longitude": w.centroid_lon,
            "started_at": "2026-01-01T00:00:00Z"}
    r = client.post(f"{API}/history/events", headers=operator, json=body)
    assert r.status_code == 201, r.text
    box.rows.append(("historical_flood_events", r.json()["id"]))
    assert r.json()["area"]["level"] == "DISTRICT"
    got = client.get(f"{API}/history/events", params={"area_id": q1.id, "size": 200}).json()["items"]
    assert r.json()["id"] in [e["id"] for e in got]
    r = client.post(f"{API}/stations", headers=operator, json={
        **STATION, "code": "T-WARD", "latitude": w.centroid_lat, "longitude": w.centroid_lon})
    assert r.status_code == 201, r.text
    box.rows.append(("monitoring_stations", r.json()["id"]))
    assert r.json()["area"]["id"] == q1.id and r.json()["area"]["level"] == "DISTRICT"


def test_citizen_alert_hides_handling_info(client, operator, citizen, db):
    aid = _make_alert(db)
    client.post(f"{API}/alerts/{aid}/acknowledge", headers=operator)
    staff = client.get(f"{API}/alerts/{aid}", headers=operator).json()
    assert staff["status"] == "ACKNOWLEDGED" and staff["acknowledged_at"]
    feat = lambda hdr: next(f["properties"] for f in client.get(  # noqa: E731
        f"{API}/gis/features", headers=hdr).json()["alerts"]["features"] if f["properties"]["id"] == aid)
    assert feat(operator)["status"] == "ACKNOWLEDGED"
    for hdr in (citizen, {}):
        client.cookies.clear()
        assert feat(hdr)["status"] == "NEW"
        d = client.get(f"{API}/alerts/{aid}", headers=hdr).json()
        assert d["status"] == "NEW" and d["updated_at"] == d["triggered_at"]
        assert d["acknowledged_at"] is d["resolved_at"] is d["closed_at"] is None
        items = client.get(f"{API}/alerts", headers=hdr, params={"status": "CLOSED", "sort": "status",
                                                                  "size": 200}).json()["items"]
        row = next(i for i in items if i["id"] == aid)  # status=CLOSED bị bỏ qua
        assert row["status"] == "NEW" and row["acknowledged_at"] is None
    st = client.get(f"{API}/alerts", headers=operator, params={"status": "CLOSED", "size": 200}).json()["items"]
    assert aid not in [i["id"] for i in st]
    db.execute(text("DELETE FROM alert_history WHERE alert_id=:i"), {"i": aid})
    db.execute(text("DELETE FROM alerts WHERE id=:i"), {"i": aid})
    db.commit()


def test_openmeteo_points_only_for_districts(db, box, monkeypatch):
    from app.models import MonitoringStation
    from app.seed import seed_openmeteo_points
    from app.services import openmeteo_service as om

    monkeypatch.setattr(om, "elevations", lambda pts: [None] * len(pts))
    w = box.ward("Quận 1", "W-OM1", "Phường OM1", 0, 3.0)
    top = db.scalar(select(func.max(MonitoringStation.id))) or 0
    try:
        seed_openmeteo_points(db)
        assert not db.scalar(select(MonitoringStation.id).where(MonitoringStation.area_id == w.id))
    finally:  # trạm OM mới tạo (nếu DB test chưa có) được dọn
        db.execute(text("DELETE FROM monitoring_stations WHERE id>:t"), {"t": top})
        db.commit()


# ------------------------------------------------------------------ ngữ nghĩa MySQL được giữ trên PostgreSQL
def test_search_is_case_and_accent_insensitive(db):
    from app.models import AdministrativeArea
    from app.repositories.base import contains

    def names(q):
        return {a.name for a in db.scalars(select(AdministrativeArea).where(contains(AdministrativeArea.name, q)))}

    assert "Quận 1" in names("quan 1") and names("quan 1") == names("QUẬN 1") == names("quận 1")
    assert names("100%") == set() and names("_") == set()  # ký tự đại diện LIKE được escape


def test_username_email_case_insensitive(client, db):
    from app.core.errors import AppError
    from app.services import user_service

    assert client.post(f"{API}/auth/login", json={"username": "ADMIN_T", "password": "AdminPass123"}).status_code == 200
    with pytest.raises(AppError) as e:
        user_service.create_user(db, username="Admin_T", email="x@example.com", full_name="x", password="Passw0rdxx",  # noqa: S106
                                 roles=["USER"], actor=None)
    assert e.value.status == 409
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):  # ràng buộc UNIQUE của CSDL cũng không phân biệt hoa/thường
        db.execute(text("INSERT INTO users (username, email, full_name, password_hash, is_active, token_version, "
                        "created_at, updated_at) VALUES ('CITIZEN_T','c@example.com','','x',true,0,NOW(),NOW())"))
    db.rollback()


def test_spatial_lon_lat_order(db):
    """PostGIS lưu (lon, lat): điểm giữa Quận 1 nằm trong Quận 1, đảo trục thì không; khoảng cách đúng mét."""
    from app.services import gis_service

    a = gis_service.area_at(db, 106.698, 10.7725, "DISTRICT")
    assert a is not None and a.name == "Quận 1"
    assert gis_service.area_at(db, 10.7725, 106.698) is None  # lat/lon đảo -> ngoài mọi khu vực
    d = db.scalar(select(func.ST_DistanceSphere(func.ST_GeomFromText("POINT(106.698 10.7725)", 4326),
                                                func.ST_GeomFromText("POINT(106.698 10.7815)", 4326))))
    assert d == pytest.approx(1000, rel=0.02)  # 0,009 độ vĩ ~ 1 km


def test_risk_explanation_is_limited_for_citizens(client, operator, citizen):
    pub = {"cause", "depth_cm", "wards", "wards_total"}
    staff = client.get(f"{API}/forecasts/risk", headers=operator).json()
    assert staff and any(set(r["explanation"] or {}) - pub for r in staff)
    for hdr in (citizen, {}):
        client.cookies.clear()  # cookie phiên từ lần đăng nhập trước sẽ biến lời gọi ẩn danh thành cán bộ
        for r in client.get(f"{API}/forecasts/risk", headers=hdr).json():
            assert set(r["explanation"] or {}) <= pub
        aid = staff[0]["area_id"]
        for r in client.get(f"{API}/gis/areas/{aid}", headers=hdr).json()["risk"]:
            assert set(r["explanation"] or {}) <= pub


def test_login_account_limit_ignores_ip(client, monkeypatch):
    from app.core import security
    from app.controllers import auth
    monkeypatch.setattr(auth, "login_account_limiter", security.RateLimiter(limit=2, window_s=60))
    codes = [client.post(f"{API}/auth/login", json={"username": "Khong_Ton_Tai", "password": "sai"},
                         headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(3)]
    assert codes[-1] == 429 and 429 not in codes[:2]  # IP khác nhau vẫn chung một hạn mức theo tài khoản


def test_successful_logins_do_not_use_account_limit(client, monkeypatch):
    from app.core import security
    from app.controllers import auth
    from tests.conftest import PASSWORDS
    monkeypatch.setattr(auth, "login_account_limiter", security.RateLimiter(limit=2, window_s=60, name="t_ok"))
    ok = [client.post(f"{API}/auth/login", json={"username": "citizen_t", "password": PASSWORDS["citizen_t"]},
                      headers={"X-Forwarded-For": f"10.1.0.{i}"}).status_code for i in range(4)]
    client.cookies.clear()
    assert ok == [200] * 4


def test_change_password_is_rate_limited(client, citizen, monkeypatch):
    from app.core import security
    from app.controllers import auth
    monkeypatch.setattr(auth, "password_change_limiter", security.RateLimiter(limit=2, window_s=60))
    body = {"current_password": "sai-mat-khau", "new_password": "MatKhauMoi12345"}
    codes = [client.post(f"{API}/auth/change-password", json=body, headers=citizen).status_code for _ in range(3)]
    assert codes == [400, 400, 429]


def test_simulation_reaches_staff_pages_until_cleared(client, admin, operator, citizen, db):
    sim = {**SIM, "radius_m": 2000, "depth_cm": 40}
    client.delete(f"{API}/admin/simulations", headers=admin)
    assert client.post(f"{API}/admin/simulations", headers=admin, json=sim).status_code == 201
    alerts_before = db.scalar(select(func.count()).select_from(Alert))

    def seen(hdr):
        client.cookies.clear()
        layers = client.get(f"{API}/gis/risk-layers", headers=hdr).json()["features"]
        al = client.get(f"{API}/alerts", headers=hdr).json()["items"]
        ev = client.get(f"{API}/history/events", headers=hdr).json()["items"]
        rk = client.get(f"{API}/forecasts/risk", headers=hdr).json()
        return ({f["id"] for f in layers if f["properties"].get("cause") == "SIMULATION"},
                [a for a in al if a["is_simulated"] and a["id"] < 0], [e for e in ev if e["id"] < 0],
                [r for r in rk if (r["explanation"] or {}).get("cause") == "SIMULATION"])

    areas, alerts, events, risk = seen(operator)
    assert areas and alerts and events and risk
    assert alerts[0]["title"].startswith("[MÔ PHỎNG]") and alerts[0]["cause"] == "SIMULATION" and alerts[0]["depth_cm"] == 40
    assert risk[0]["risk_level"] == "HIGH" and risk[0]["is_simulated"]
    assert client.get(f"{API}/alerts/{alerts[0]['id']}", headers=operator).json()["history"] == []
    ov = client.get(f"{API}/statistics/overview", headers=operator).json()
    assert ov["simulation"]["districts"] == len(alerts) and ov["areas_high"] >= len(alerts)
    assert client.get(f"{API}/statistics/overview", headers=operator, params={"data_type": "REAL"}).json().get("simulation") is None
    assert client.get(f"{API}/statistics/alerts", headers=operator).json()["simulated"] == len(alerts)
    assert [s["id"] for s in client.get(f"{API}/gis/simulations", headers=operator).json()]
    for hdr in (citizen, {}):  # người dân/khách không bao giờ thấy mô phỏng
        assert seen(hdr) == (set(), [], [], [])
        client.cookies.clear()
        assert client.get(f"{API}/alerts/{alerts[0]['id']}", headers=hdr).status_code == 404
    assert client.get(f"{API}/gis/simulations", headers=citizen).status_code == 403
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Alert)) == alerts_before  # không ghi vào bảng thật

    assert client.delete(f"{API}/admin/simulations", headers=admin).status_code == 204
    assert seen(operator) == (set(), [], [], [])  # tắt mô phỏng là hết tham chiếu
    assert client.get(f"{API}/alerts/{alerts[0]['id']}", headers=operator).status_code == 404


def test_pdf_summary_report_staff_only(client, operator, citizen):
    r = client.get(f"{API}/exports/pdf", headers=operator)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert ".pdf" in r.headers["content-disposition"]
    client.cookies.clear()
    assert client.get(f"{API}/exports/pdf", headers=citizen).status_code == 403
    assert client.get(f"{API}/exports/pdf").status_code == 401


def test_satellite_rainfall_series_staff_only(client, operator, citizen, db):
    from datetime import date

    from app.models import AdministrativeArea, SatelliteRainfallDaily

    q1 = db.scalar(select(AdministrativeArea).where(AdministrativeArea.name == "Quận 1"))
    row = SatelliteRainfallDaily(area_id=q1.id, day=date(2030, 1, 5), rain_mm=12.5, product="TEST")
    db.add(row)
    db.commit()
    try:
        r = client.get(f"{API}/statistics/satellite-rainfall", headers=operator,
                       params={"date_from": "2030-01-04T00:00:00Z", "date_to": "2030-01-07T00:00:00Z"}).json()
        assert r == [{"day": "2030-01-05", "imerg_mm": 12.5, "model_mm": None}]
        client.cookies.clear()
        assert client.get(f"{API}/statistics/satellite-rainfall", headers=citizen).status_code == 403
    finally:
        db.delete(row)
        db.commit()
