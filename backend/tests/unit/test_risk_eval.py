from datetime import date, datetime

import pandas as pd

from app.ai.evaluation import risk_eval as re_
from app.services import openmeteo_service as om

STATS = (100.0, 200.0)  # ratio = (cm-100)/100; độ sâu >= 20 cm cần r >= 1.15 -> cm >= 215
D1, D2 = 1, 2
PERIOD = (date(2026, 10, 9), date(2026, 10, 12))


def run(events, level, rain=None, exposed=(D1,), capable=(D1,), calib=frozenset({date(2026, 10, 10)})):
    return re_.evaluate(events, {D1, D2}, set(exposed), set(capable), rain or {}, pd.Series(level, dtype=float),
                        STATS, om.tide_ratio, period=PERIOD, calib=set(calib))


def test_tide_lag_pushes_peak_to_next_day():
    # đỉnh 23:00 VN ngày 10/10 (16:00 UTC) -> sau lệch 4 h rơi vào ngày 11/10 (held-out)
    r = run([(D1, datetime(2026, 10, 11, 1), "TIDE")], {pd.Timestamp("2026-10-10 16:00"): 230})
    g = r["held_out/TIDE/district-day"]
    assert (g["tp"], g["fp"], g["fn"]) == (1, 0, 0) and g["positives"] == 1
    assert r["calibration/TIDE/district-day"]["positives"] == 0  # 10/10 là ngày hiệu chỉnh
    old = r["held_out/old_rule_vs_TIDE/district-day"]  # luật cũ đoán ngày 10/10 (hiệu chỉnh): held-out chỉ có fn
    assert (old["tp"], old["fp"], old["fn"]) == (0, 0, 1)


def test_exposed_vs_not_district():
    r = run([(D2, datetime(2026, 10, 11, 1), "TIDE")], {pd.Timestamp("2026-10-10 16:00"): 230})
    g = r["held_out/TIDE/district-day"]
    assert (g["tp"], g["fp"], g["fn"]) == (0, 1, 1)  # D1 dương sai, D2 không phơi nhiễm bị bỏ sót
    assert r["held_out/TIDE/city-day"]["tp"] == 1


def test_rain_case_and_calibration_split():
    rain = {D1: pd.Series({pd.Timestamp("2026-10-10 03:00"): 40.0})}  # 3 h = 40 mm -> 30 cm >= 20
    ev = [(D1, datetime(2026, 10, 10, 4), "RAIN_TIDE")]
    r = run(ev, {pd.Timestamp("2026-10-09 00:00"): 100}, rain)
    assert r["calibration/RAIN/district-day"]["tp"] == 1
    assert r["held_out/RAIN/district-day"]["positives"] == 0
    assert r["calibration/TIDE/district-day"]["fn"] == 1  # RAIN_TIDE tính cả cho truth TIDE


def test_null_area_skipped_and_all_negative_f1_zero():
    r = run([(None, datetime(2026, 10, 11, 1), "TIDE")], {pd.Timestamp("2026-10-09 00:00"): 100})
    assert r["skipped_null_area_events"] == 1
    g = r["held_out/ALL/district-day"]
    assert g["positives"] == 0 and g["f1"] == 0.0 and g["tn"] == g["n"]
