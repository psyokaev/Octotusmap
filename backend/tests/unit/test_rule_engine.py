import copy

from app.services.rule_engine import DEFAULT_RULE_CONFIG as CFG
from app.services.rule_engine import RiskInputs, evaluate, should_alert, validate_config


def full(**kw):
    base = dict(flood_probability=0.1, rainfall_mm=2, water_level_ratio=0.3, camera_flood_ratio=0.0,
                history_susceptibility=0.2, data_age_minutes=10)
    base.update(kw)
    return RiskInputs(**base)


def test_low_when_calm():
    r = evaluate(full(), CFG)
    assert r.level == "LOW" and 0 <= r.score < CFG["thresholds"]["medium"]


def test_high_when_everything_bad():
    r = evaluate(full(flood_probability=0.95, rainfall_mm=60, water_level_ratio=1.2, camera_flood_ratio=0.6), CFG)
    assert r.level == "HIGH" and r.explanation["overrides"]


def test_override_by_camera_only():
    r = evaluate(full(camera_flood_ratio=0.5), CFG)
    assert r.level == "HIGH"
    assert any("Camera" in o for o in r.explanation["overrides"])


def test_medium_band():
    r = evaluate(full(flood_probability=0.5, rainfall_mm=20, water_level_ratio=0.7), CFG)
    assert r.level == "MEDIUM"


def test_insufficient_when_missing_inputs():
    r = evaluate(RiskInputs(history_susceptibility=0.5), CFG)
    assert r.level == "INSUFFICIENT_DATA"


def test_insufficient_when_stale():
    r = evaluate(full(data_age_minutes=500), CFG)
    assert r.level == "INSUFFICIENT_DATA"


def test_hysteresis_keeps_previous_level():
    # điểm ngay dưới ngưỡng MEDIUM nhưng trong biên hysteresis -> giữ MEDIUM
    inp = full(flood_probability=0.38, rainfall_mm=12, water_level_ratio=0.45, camera_flood_ratio=0.05,
               history_susceptibility=0.3)
    plain = evaluate(inp, CFG)
    assert plain.level == "LOW" and plain.score >= CFG["thresholds"]["medium"] - CFG["hysteresis"]
    assert evaluate(inp, CFG, previous_level="MEDIUM").level == "MEDIUM"


def test_score_bounded_and_explained():
    r = evaluate(full(rainfall_mm=10_000, flood_probability=1.0), CFG)
    assert 0 <= r.score <= 1
    assert set(r.explanation["contributions"]) == set(CFG["weights"])


def test_should_alert():
    assert should_alert("HIGH", CFG) and should_alert("MEDIUM", CFG)
    assert not should_alert("LOW", CFG) and not should_alert("INSUFFICIENT_DATA", CFG)


def test_validate_config():
    assert validate_config(CFG) == []
    bad = copy.deepcopy(CFG)
    bad["thresholds"] = {"medium": 0.7, "high": 0.5}
    assert validate_config(bad)


def test_tide_ratio_alone_is_not_an_override():
    r = evaluate(full(flood_probability=0.002, water_level_ratio=None, tide_ratio=1.04), CFG)
    assert r.level != "HIGH" and not r.explanation["overrides"]
    assert evaluate(full(water_level_ratio=1.0), CFG).level == "HIGH"


def test_depth_and_report_overrides():
    r = evaluate(full(flood_depth_cm=40), CFG)
    assert r.level == "HIGH" and any("40" in o for o in r.explanation["overrides"])
    assert "40" in r.explanation["level_reason"]
    assert evaluate(full(report_confirmations=1), CFG).level == "HIGH"
    r0 = evaluate(full(report_confirmations=0), CFG)
    assert r0.level == "MEDIUM" and not r0.explanation["overrides"]
    assert "Có báo cáo ngập chưa xác nhận" in r0.explanation["notes"]


def test_old_config_without_depth_key():
    old = copy.deepcopy(CFG)
    old["overrides"].pop("flood_depth_cm_high", None)
    assert evaluate(full(flood_depth_cm=25), old).level == "HIGH"


def test_storm_signal_raises_only_to_medium():
    calm = evaluate(full(storm_models=1), CFG)
    assert calm.level == "LOW"  # 1/7 mô hình chưa đủ đồng thuận
    r = evaluate(full(storm_models=2), CFG)
    assert r.level == "MEDIUM" and "mưa dông" in r.explanation["level_reason"]
    hi = evaluate(full(storm_models=7, camera_flood_ratio=0.9), CFG)
    assert hi.level == "HIGH" and "mưa dông" not in hi.explanation["level_reason"]  # override vẫn quyết định


def test_direct_evidence_still_counts_when_model_data_stale():
    stale = dict(data_age_minutes=500, camera_flood_ratio=None)
    r = evaluate(full(**stale, report_confirmations=2), CFG)
    assert r.level == "HIGH" and "báo cáo ngập đã được xác nhận" in r.explanation["level_reason"]
    assert evaluate(full(**stale, report_confirmations=0), CFG).level == "MEDIUM"
    assert evaluate(full(data_age_minutes=500, camera_flood_ratio=0.6), CFG).level == "HIGH"
    assert evaluate(RiskInputs(report_confirmations=1), CFG).level == "HIGH"  # thiếu hẳn dữ liệu mưa/triều
    assert evaluate(full(**stale), CFG).level == "INSUFFICIENT_DATA"
