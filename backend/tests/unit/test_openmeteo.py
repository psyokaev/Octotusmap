from datetime import datetime

from app.services import openmeteo_service as om


def test_series_parses_and_skips_nulls():
    item = {"hourly": {"time": ["2026-09-01T00:00", "2026-09-01T01:00"], "precipitation": [1.5, None]}}
    assert om._series(item, "precipitation") == [(datetime(2026, 9, 1, 0, 0), 1.5)]


def test_fetch_rain_uses_archive_and_multi_point(monkeypatch):
    calls = {}

    def fake(url, params, tries=3):
        calls.update(url=url, params=params)
        return [{"hourly": {"time": ["2026-01-01T00:00"], "precipitation": [2.0]}}] * 2

    monkeypatch.setattr(om, "_get", fake)
    out = om.fetch_rain([(10.1, 106.1), (10.2, 106.2)], datetime(2026, 1, 1), datetime(2026, 1, 2))
    assert calls["url"] == om.ARCHIVE and calls["params"]["latitude"] == "10.1000,10.2000"
    assert len(out) == 2 and out[0][0][1] == 2.0


def test_tide_converted_to_cm(monkeypatch):
    monkeypatch.setattr(om, "_get", lambda *a, **k: {"hourly": {"time": ["2026-01-01T00:00"], "sea_level_height_msl": [1.25]}})
    assert om.fetch_tide()[0][1] == 125.0


def test_tide_ratio():
    assert om.tide_ratio(150, (50, 150)) == 1.0
    assert om.tide_ratio(None, (50, 150)) is None
    assert om.tide_ratio(100, None) is None


def test_elevations_fail_soft_without_retry(monkeypatch):
    import httpx

    calls = []

    def fake(url, params, tries=3, timeout=60):
        calls.append((tries, timeout))
        raise httpx.ConnectTimeout("x")

    monkeypatch.setattr(om, "_get", fake)
    assert om.elevations([(10.111, 106.111)]) == [None]
    assert calls == [(1, 5)]


def test_elevation_cache_eviction_keeps_requested_points(monkeypatch):
    monkeypatch.setattr(om, "_elev_cache", {(float(i), 0.0): 1.0 for i in range(200_001)} | {(10.5, 106.5): 7.0})
    monkeypatch.setattr(om, "_get", lambda *a, **k: {"elevation": [7.0]})
    assert om.elevations([(10.5, 106.5)]) == [7.0]


def test_parse_traffic_camera_rows_with_numeric_angle():
    from app.services.traffic_camera_service import parse_list

    geo = 'new Ajax.Web.DataTable([["GeoId","System.Object"]],[["g","POINT(106.69 10.79)",null]])'
    text = ('{"value":[new Ajax.Web.DataTable([["Title","System.Object"]],['
            f'["A",null,"662b86c41afb9c00172dd31c","A",{geo},null,"tth",null,"True",null,"UP","True",null,"Đường A",null],'
            f'["B",null,"5a6065c58576340017d06615","B",{geo},null,"tth",null,"True",null,"NOT_IMAGE","False","315","Đường B",null]'
            '])]}')
    rows = parse_list(text.replace("new Ajax.Web.DataTable([[\"Title\"", 'new Ajax.Web.DataTable([["Title"'))
    assert [r["name"] for r in rows] == ["Đường A", "Đường B"]
    assert rows[1]["status"] == "NOT_IMAGE" and rows[0]["lon"] == 106.69


def test_tide_at_is_lagged(monkeypatch):
    from datetime import timedelta

    t = datetime(2026, 10, 27, 12)
    monkeypatch.setitem(om._forecast_cache, "tide", [(t - timedelta(hours=om.TIDE_LAG_H), 123.0)])
    assert om.tide_at(None, t) == 123.0


def test_storm_model_counts_sums_next_three_hours(monkeypatch):
    t0 = datetime(2026, 11, 4, 8)
    times = [f"2026-11-04T{h:02d}:00" for h in range(8, 13)]  # 08..12; cửa sổ là 09, 10, 11
    hourly = {"time": times, "precipitation_ecmwf_ifs025": [50, 4, 4, 4, 50],  # 12 mm trong cửa sổ
              "precipitation_gfs_seamless": [0, 3, 3, 3, 0],  # 9 mm: dưới 10
              "precipitation_icon_seamless": [0, 10, None, 0, 0]}  # thiếu giờ coi là 0
    monkeypatch.setattr(om, "_get", lambda url, params, **kw: [{"hourly": hourly}, {"hourly": {"time": times}}])
    assert om.storm_model_counts([(10.8, 106.7), (10.7, 106.6)], t0) == [2, 0]
