import numpy as np
import pandas as pd

from app.ai.forecasting import flood_district as fd


def test_features_shape_and_calibration():
    idx = pd.date_range("2026-11-01", periods=fd.LOOKBACK, freq="h")
    f = fd.features(np.full(fd.LOOKBACK, 5.0), idx, np.full(fd.LOOKBACK, 3.0), 2.0, True, False)
    assert f.shape == (fd.LOOKBACK, 7) and f[0, 1] == 2.0  # tỉ lệ triều bị cắt về [-2, 2]
    assert np.allclose(fd.calibrate(np.array([0.5]), 1.0, 0.0), 0.5)  # Platt a=1, b=0 giữ nguyên
    assert fd.calibrate(np.array([0.9]), 1.0, -5.0)[0] < 0.1  # hệ số chặn âm kéo xác suất phồng xuống


def test_predict_without_model_is_empty(db):
    assert fd.predict(db, pd.Timestamp("2026-11-01").to_pydatetime()) == {}
