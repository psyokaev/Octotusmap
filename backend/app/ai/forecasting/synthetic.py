"""Bộ sinh dữ liệu MÔ PHỎNG (SIMULATED) mưa + mực nước cho mạng trạm TP.HCM.

KHÔNG phải số liệu quan trắc thật. Dùng để chạy demo và kiểm thử pipeline khi
chưa có nguồn dữ liệu khí tượng thủy văn được cấp phép.

Mô hình vật lý đơn giản hoá:
- Mưa đối lưu: xác suất phát sinh cơn dông phụ thuộc mùa (mùa mưa 5-11) và giờ
  trong ngày (đỉnh 14-18h giờ VN), cơn dông có tâm di chuyển, cường độ suy giảm
  theo khoảng cách (Gaussian) -> các trạm gần nhau tương quan.
- Mực nước (cm, so với cao độ tham chiếu cống/kênh): thuỷ triều bán nhật triều
  (M2 12.42h) + nhật triều + chu kỳ triều cường/kém (14.77 ngày) + đáp ứng dòng
  chảy mặt (tích chập mưa với kernel trễ ~2h) + nhiễu.
- Ngập: mực nước > ngưỡng ngập của trạm.
"""

import math
from datetime import datetime, timedelta

import numpy as np

EPOCH = datetime(2026, 1, 1)  # mốc thời gian cố định (UTC) -> chuỗi xác định
VN_OFFSET_H = 7


def _season_factor(month: int) -> float:
    return {5: 0.6, 6: 0.9, 7: 0.9, 8: 1.0, 9: 1.1, 10: 1.0, 11: 0.6}.get(month, 0.12)


def _diurnal_factor(local_hour: int) -> float:
    return 0.25 + 1.6 * math.exp(-((local_hour - 16) ** 2) / 8.0)


def simulate_network(stations: list[dict], start: datetime, end: datetime, seed: int = 2026) -> dict:
    """Sinh chuỗi theo giờ [start, end) cho mọi trạm.

    stations: [{code, lat, lon, threshold_cm, sensitivity, tide_amp, base_cm}]
    Chuỗi tính từ EPOCH nên cùng seed luôn cho cùng giá trị tại cùng thời điểm
    (cho phép sinh nối tiếp theo thời gian thực).
    Trả về {code: {"time": [...], "rain": np.array, "wl": np.array}}.
    """
    rng = np.random.default_rng(seed)
    n0 = int((start - EPOCH).total_seconds() // 3600)
    n1 = int((end - EPOCH).total_seconds() // 3600)
    n = n1  # mô phỏng từ EPOCH để đảm bảo tính xác định
    lat = np.array([s["lat"] for s in stations])
    lon = np.array([s["lon"] for s in stations])
    rain = np.zeros((len(stations), n))

    storms = []
    for t in range(n):
        ts = EPOCH + timedelta(hours=t)
        lh = (ts.hour + VN_OFFSET_H) % 24
        p = 0.045 * _season_factor(ts.month) * _diurnal_factor(lh)
        if rng.random() < p:
            storms.append({
                "t0": t,
                "dur": int(rng.integers(1, 5)),
                "peak": float(rng.gamma(2.2, 11.0)),
                "clat": 10.78 + rng.normal(0, 0.09),
                "clon": 106.68 + rng.normal(0, 0.09),
                "vlat": rng.normal(0, 0.03),
                "vlon": rng.normal(0, 0.03),
                "sigma": float(rng.uniform(0.04, 0.12)),
            })
    for s in storms:
        for k in range(s["dur"] + 2):
            t = s["t0"] + k
            if t >= n:
                break
            shape = math.sin(math.pi * (k + 0.5) / (s["dur"] + 2))
            clat, clon = s["clat"] + s["vlat"] * k, s["clon"] + s["vlon"] * k
            d2 = (lat - clat) ** 2 + (lon - clon) ** 2
            rain[:, t] += s["peak"] * shape * np.exp(-d2 / (2 * s["sigma"] ** 2))
    rain *= rng.lognormal(0, 0.25, size=rain.shape)
    drizzle = (rng.random(rain.shape) < 0.02) * rng.exponential(0.6, size=rain.shape)
    rain = np.round(rain + drizzle, 1)
    rain[rain < 0.2] = 0.0

    hours = np.arange(n)
    kernel_t = np.arange(12)
    kernel = kernel_t * np.exp(-kernel_t / 1.8)
    kernel /= kernel.sum()
    out = {}
    for i, st in enumerate(stations):
        phase = rng.uniform(0, 2 * math.pi)
        spring_neap = 1 + 0.35 * np.cos(2 * math.pi * hours / (14.77 * 24) + phase / 3)
        tide = st["tide_amp"] * spring_neap * (
            np.cos(2 * math.pi * hours / 12.42 + phase) + 0.3 * np.cos(2 * math.pi * hours / 23.93 + phase / 2)
        )
        runoff = np.convolve(rain[i], kernel)[:n] * st["sensitivity"]
        wl = st["base_cm"] + tide + runoff + rng.normal(0, 1.5, n)
        out[st["code"]] = {
            "time": [EPOCH + timedelta(hours=int(h)) for h in range(n0, n1)],
            "rain": rain[i, n0:n1],
            "wl": np.round(wl[n0:n1], 1),
        }
    return out


def inject_sensor_faults(series: dict, rate: float = 0.01, seed: int = 7) -> dict:
    """Mô phỏng lỗi truyền dữ liệu: mất bản ghi (None) và giá trị bất thường."""
    rng = np.random.default_rng(seed)
    for code, s in series.items():
        n = len(s["time"])
        miss = rng.random(n) < rate
        spike = rng.random(n) < rate / 5
        s["rain_missing"] = miss
        s["wl_missing"] = rng.random(n) < rate
        s["wl_spike"] = spike
    return series
