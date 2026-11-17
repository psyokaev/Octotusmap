from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from app.ai.evaluation.metrics import classification_metrics, regression_metrics, roc_auc
from app.ai.forecasting.preprocessing import (
    FEATURES,
    HORIZON,
    LOOKBACK,
    Scaler,
    chronological_split,
    clean_station_frame,
    make_windows,
    validate_schema,
)
from app.ai.forecasting.synthetic import simulate_network
from app.ai.forecasting.train import build_datasets

ST = [dict(code=f"S{i}", lat=10.75 + 0.02 * i, lon=106.65 + 0.02 * i, threshold_cm=60,
           sensitivity=5, tide_amp=25, base_cm=15) for i in range(3)]


def frames():
    sim = simulate_network(ST, datetime(2026, 8, 1), datetime(2026, 9, 15))
    return {c: (pd.DataFrame({"time": s["time"], "rain_mm": s["rain"], "water_level_cm": s["wl"]}), 60.0)
            for c, s in sim.items()}


def test_simulation_is_deterministic_and_extendable():
    a = simulate_network(ST, datetime(2026, 8, 1), datetime(2026, 8, 3))
    b = simulate_network(ST, datetime(2026, 8, 2), datetime(2026, 8, 3))
    assert np.allclose(a["S0"]["rain"][24:], b["S0"]["rain"])
    assert (a["S0"]["rain"] >= 0).all()


def test_schema_validation():
    with pytest.raises(ValueError):
        validate_schema(pd.DataFrame({"time": [1], "rain_mm": [1]}))


def test_missing_values_flagged_not_hidden():
    t = pd.date_range("2026-08-01", periods=30, freq="h")
    df = pd.DataFrame({"time": t, "rain_mm": [1.0] * 30, "water_level_cm": [20.0] * 30})
    df = df.drop(index=[5, 6])  # mất bản ghi
    df.loc[10, "rain_mm"] = -3  # giá trị âm bất hợp lý
    out = clean_station_frame(df, 60)
    assert len(out) == 30
    assert out["missing"].sum() == 3
    assert not out[FEATURES].isna().any().any()


def test_window_shapes_and_targets():
    df = clean_station_frame(frames()["S0"][0], 60)
    sc = Scaler.fit([df])
    X, yr, yw, yf, times = make_windows(df, sc)
    assert X.shape[1:] == (LOOKBACK, len(FEATURES))
    assert yr.shape[1] == yw.shape[1] == yf.shape[1] == HORIZON
    assert set(np.unique(yf)) <= {0.0, 1.0}
    # đích tại i, h=0 là giờ ngay sau cửa sổ
    assert yr[0, 0] == pytest.approx(df["rain_mm"].iloc[LOOKBACK])
    assert len(times) == len(X)


def test_no_temporal_leakage_between_splits():
    data, sc, bounds = build_datasets(frames())
    for tr_end, va_start, te_start in bounds.values():
        assert tr_end < va_start < te_start
    assert len(data["train"][0]) > len(data["test"][0]) > 0


def test_chronological_split_order():
    df = clean_station_frame(frames()["S1"][0], 60)
    tr, va, te = chronological_split(df)
    assert tr.index.max() < va.index.min() and va.index.max() < te.index.min()


def test_metrics():
    m = regression_metrics(np.zeros((4, 6)), np.ones((4, 6)))
    assert m["mae"] == 1 and m["rmse"] == 1
    c = classification_metrics(np.array([1, 0, 1, 0]), np.array([0.9, 0.1, 0.4, 0.6]))
    assert c["confusion_matrix"] == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert c["precision"] == 0.5 and c["recall"] == 0.5
    assert roc_auc(np.array([1, 0]), np.array([0.8, 0.2])) == 1.0


def test_rain_only_evaluation_picks_threshold_on_validation():
    from app.ai.forecasting.train import HEAVY_RAIN_MM, evaluate_rain

    y = np.array([[0.0] * 6, [HEAVY_RAIN_MM + 1] * 6])
    pred = np.array([[0.2] * 6, [3.0] * 6])
    m = evaluate_rain(pred, y, pred, y)
    assert m["heavy_rain"]["decision_mm"] <= 3.0 and m["heavy_rain"]["f1"] == 1.0
    assert "flood" not in m and m["rainfall"]["mae"] > 0
