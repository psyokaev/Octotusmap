"""Chỉ số ngập ƯỚC TÍNH (không học từ nhãn) cho một vị trí/đoạn đường.

Chưa có dữ liệu ngập thực đo để huấn luyện, nên xác suất ngập được ước tính bằng mô hình logistic
có hệ số minh bạch, cấu hình được:
    z = bias + a·mưa_1h + b·mưa_3h + c·triều_cao·hệ_số_trũng + d·(độ_cao_tham_chiếu − độ_cao) + e·gần_điểm_ngập
Hệ số mặc định chọn theo kinh nghiệm định tính (mưa >~ 40–50 mm/2–3h thường gây ngập điểm trũng TP.HCM),
CHƯA được hiệu chỉnh với số liệu ngập thật — chỉ phục vụ tham khảo.

Độ sâu ngập (tide_depth_cm/rain_depth_cm) chỉ dựa trên 3 mốc độ sâu từ báo chí của 2 đợt triều, không có mốc cho
mưa: mọi giá trị là ƯỚC TÍNH.
"""

import math
from dataclasses import dataclass

DEFAULT_COEF = {
    "bias": -5.0, "rain_1h": 0.22, "rain_3h": 0.07, "tide": 1.5, "elevation": 0.35, "ref_elevation_m": 4.0,
    "hotspot": 1.2, "tide_low_elevation_m": 8.0, "severe_hotspot": 0.8,
}
LIKELY, AT_RISK = 0.6, 0.3
TIDE_FLOOD_RATIO, LOW_ELEVATION_M = 1.15, 8.0
SEVERITY_CM = {"ANKLE": 10, "KNEE": 40, "DEEP": 70}


def tide_depth_cm(r: float | None) -> float:
    return 0.0 if r is None or r < TIDE_FLOOD_RATIO else min(60.0, 20 + 70 * (r - TIDE_FLOOD_RATIO))


def rain_depth_cm(rain_3h: float) -> float:
    return min(40.0, 1.5 * max(0.0, rain_3h - 20))


def round_depth(cm: float) -> int | None:
    return None if cm < 5 else max(10, int(round(cm / 10) * 10))


@dataclass
class FloodInputs:
    rain_1h_mm: float
    rain_3h_mm: float
    tide_ratio: float | None = None  # (triều − P50) / (P95 − P50); 1 ≈ triều cường
    elevation_m: float | None = None
    near_hotspot: bool = False
    severe_hotspot: bool = False


def probability(x: FloodInputs, coef: dict | None = None) -> float:
    c = {**DEFAULT_COEF, **(coef or {})}
    z = c["bias"] + c["rain_1h"] * max(x.rain_1h_mm, 0) + c["rain_3h"] * max(x.rain_3h_mm, 0)
    if x.tide_ratio is not None:
        low = x.elevation_m is None or x.elevation_m < c["tide_low_elevation_m"]
        z += c["tide"] * min(max(x.tide_ratio, 0.0), 1.5) * (1.0 if low else 0.3)
    if x.elevation_m is not None:
        z += c["elevation"] * min(max(c["ref_elevation_m"] - x.elevation_m, -6.0), 4.0)
    if x.near_hotspot:
        z += c["hotspot"]
    if x.severe_hotspot:
        z += c["severe_hotspot"]
    return 1 / (1 + math.exp(-z))


def status(p: float, reported: bool = False) -> str:
    if reported:
        return "REPORTED_FLOODED"
    return "LIKELY_FLOODED" if p >= LIKELY else "AT_RISK" if p >= AT_RISK else "DRY"


def reasons(x: FloodInputs, reported: bool = False, depth_cm: int | None = None, cause: str | None = None) -> list[str]:
    """cause ("TIDE"/"RAIN") cho biết nguyên nhân tạo ra depth_cm để ghi độ sâu vào đúng cụm từ."""
    r = []
    d = f", ước ngập khoảng {depth_cm} cm" if depth_cm else ""
    dt, dr = (d, "") if cause == "TIDE" else ("", d) if cause == "RAIN" else (d, d)
    if reported:
        r.append("Có người dân báo ngập gần đây")
    if x.rain_1h_mm >= 10 or x.rain_3h_mm >= 25:
        r.append(f"Mưa lớn: {x.rain_1h_mm:.1f} mm/h, {x.rain_3h_mm:.0f} mm/3h{dr}")
    elif x.rain_1h_mm >= 2:
        r.append(f"Đang mưa {x.rain_1h_mm:.1f} mm/h")
    if x.tide_ratio is not None and x.tide_ratio >= 0.8:
        r.append("Triều cao" + dt)
    if x.elevation_m is not None and x.elevation_m < 3:
        r.append(f"Địa hình thấp ({x.elevation_m:.0f} m)")
    if x.near_hotspot:
        r.append("Gần điểm ngập thường xuyên")
    return r
