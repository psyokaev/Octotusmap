import pytest

from app.services.flood_index import FloodInputs, probability, reasons, status


def test_dry_weather_low_probability():
    assert probability(FloodInputs(0, 0, tide_ratio=0.2, elevation_m=6)) < 0.02


def test_heavy_rain_low_ground_hotspot_high():
    p = probability(FloodInputs(25, 50, tide_ratio=0.5, elevation_m=2, near_hotspot=True))
    assert p > 0.95 and status(p) == "LIKELY_FLOODED"


def test_monotonic_in_rain_and_elevation():
    base = probability(FloodInputs(5, 10, elevation_m=4))
    assert probability(FloodInputs(15, 30, elevation_m=4)) > base
    assert probability(FloodInputs(5, 10, elevation_m=1)) > base > probability(FloodInputs(5, 10, elevation_m=9))


def test_tide_matters_mostly_on_low_ground():
    low = probability(FloodInputs(0, 0, tide_ratio=1.2, elevation_m=1.5, near_hotspot=True)) - \
        probability(FloodInputs(0, 0, tide_ratio=0, elevation_m=1.5, near_hotspot=True))
    high = probability(FloodInputs(0, 0, tide_ratio=1.2, elevation_m=8, near_hotspot=True)) - \
        probability(FloodInputs(0, 0, tide_ratio=0, elevation_m=8, near_hotspot=True))
    assert low > high > 0


def test_missing_inputs_and_report_override():
    p = probability(FloodInputs(0, 0))
    assert 0 < p < 1
    assert status(p, reported=True) == "REPORTED_FLOODED"
    assert "Có người dân báo ngập gần đây" in reasons(FloodInputs(0, 0), reported=True)


def test_depth_helpers():
    from app.services.flood_index import rain_depth_cm, round_depth, tide_depth_cm

    assert tide_depth_cm(1.417) == pytest.approx(38.69, abs=0.01)
    assert tide_depth_cm(1.0) == 0 and tide_depth_cm(None) == 0 and tide_depth_cm(3.0) == 60
    assert round_depth(3) is None and round_depth(38.7) == 40 and round_depth(5) == 10
    assert rain_depth_cm(15) == 0 and rain_depth_cm(50) == 40 and rain_depth_cm(200) == 40


def test_reasons_with_depth():
    x = FloodInputs(0, 0, tide_ratio=1.4)
    assert "Triều cao, ước ngập khoảng 40 cm" in reasons(x, depth_cm=40, cause="TIDE")
    assert "Triều cao" in reasons(x)
