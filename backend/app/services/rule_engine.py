"""Hệ luật cảnh báo & hỗ trợ ra quyết định (pure functions, không phụ thuộc DB).

Ngưỡng mặc định CHỈ phục vụ nghiên cứu/demo, chưa phải ngưỡng vận hành chính thức
của cơ quan quản lý.
"""

from dataclasses import dataclass, field

LEVELS = ["LOW", "MEDIUM", "HIGH"]
RANK = {"INSUFFICIENT_DATA": -1, "LOW": 0, "MEDIUM": 1, "HIGH": 2}

DEFAULT_RULE_CONFIG: dict = {
    "weights": {"flood_probability": 0.45, "rainfall": 0.2, "water_level": 0.2, "camera": 0.1, "history": 0.05},
    "rainfall_ref_mm": 40.0,  # mưa giờ >= giá trị này -> thành phần mưa = 1
    "thresholds": {"medium": 0.35, "high": 0.6},
    "hysteresis": 0.05,
    "overrides": {"flood_probability_high": 0.8, "water_level_ratio_high": 1.0, "camera_ratio_high": 0.4},
    "min_confidence": 0.5,  # tổng trọng số các đầu vào có dữ liệu
    "freshness_max_minutes": 180,
    "alert_min_level": "MEDIUM",
    "cooldown_minutes": 60,
}

RECOMMENDATIONS = {
    "LOW": ["Tiếp tục theo dõi.", "Kiểm tra dữ liệu định kỳ."],
    "MEDIUM": [
        "Tăng cường giám sát khu vực.",
        "Kiểm tra khả năng thoát nước (cống, kênh, miệng thu).",
        "Chuẩn bị phương án ứng phó, chuẩn bị vận hành trạm bơm theo quy trình.",
    ],
    "HIGH": [
        "Ưu tiên xác minh hiện trường.",
        "Chuyển cảnh báo tới cán bộ phụ trách.",
        "Cân nhắc biện pháp điều tiết theo quy trình được phê duyệt (trạm bơm, phân luồng giao thông).",
        "Khuyến nghị hạn chế lưu thông qua khu vực trũng thấp.",
        "Thông tin tới người dân dưới dạng tham khảo, kèm nguồn và thời điểm.",
    ],
    "INSUFFICIENT_DATA": ["Không đủ dữ liệu tin cậy — kiểm tra kết nối trạm/camera trước khi ra quyết định."],
}


@dataclass
class RiskInputs:
    flood_probability: float | None = None
    rainfall_mm: float | None = None
    water_level_ratio: float | None = None  # mực nước / ngưỡng ngập, CHỈ trạm đo thật
    camera_flood_ratio: float | None = None
    history_susceptibility: float | None = None
    data_age_minutes: float | None = None
    notes: list[str] = field(default_factory=list)
    tide_ratio: float | None = None  # triều (đã trễ) so với P50/P95; chỉ vào điểm số, không ép mức HIGH
    flood_depth_cm: float | None = None  # độ sâu ngập ước tính
    report_confirmations: int | None = None  # số xác nhận của báo cáo ngập (None = không có báo cáo)
    storm_models: int | None = None  # số mô hình thời tiết báo mưa 3 giờ tới >= 10 mm (mưa dông cục bộ)


@dataclass
class RiskResult:
    level: str
    score: float
    confidence: float
    explanation: dict


def validate_config(cfg: dict) -> list[str]:
    errs = []
    w = cfg.get("weights", {})
    if set(w) != set(DEFAULT_RULE_CONFIG["weights"]):
        errs.append("weights phải gồm: " + ", ".join(DEFAULT_RULE_CONFIG["weights"]))
    if any(not isinstance(v, (int, float)) or v < 0 for v in w.values()):
        errs.append("weights phải là số không âm")
    t = cfg.get("thresholds", {})
    if not (0 < t.get("medium", -1) < t.get("high", -1) <= 1):
        errs.append("Cần 0 < thresholds.medium < thresholds.high <= 1")
    if not 0 <= cfg.get("hysteresis", -1) < 0.3:
        errs.append("hysteresis trong [0, 0.3)")
    if cfg.get("rainfall_ref_mm", 0) <= 0:
        errs.append("rainfall_ref_mm > 0")
    if cfg.get("alert_min_level") not in LEVELS:
        errs.append("alert_min_level thuộc LOW/MEDIUM/HIGH")
    return errs


def _clip(v: float) -> float:
    return max(0.0, min(1.0, v))


def evaluate(inp: RiskInputs, cfg: dict, previous_level: str | None = None) -> RiskResult:
    w = cfg["weights"]
    wl = inp.water_level_ratio if inp.water_level_ratio is not None else inp.tide_ratio
    comps = {
        "flood_probability": inp.flood_probability,
        "rainfall": None if inp.rainfall_mm is None else _clip(inp.rainfall_mm / cfg["rainfall_ref_mm"]),
        "water_level": None if wl is None else _clip(wl),
        "camera": inp.camera_flood_ratio if inp.camera_flood_ratio is None else _clip(inp.camera_flood_ratio / 0.5),
        "history": inp.history_susceptibility,
    }
    avail = {k: v for k, v in comps.items() if v is not None}
    total_w = sum(w.values()) or 1.0
    confidence = sum(w[k] for k in avail) / total_w
    contributions = {k: round(w[k] * v, 4) for k, v in avail.items()}
    score = sum(contributions.values()) / max(sum(w[k] for k in avail), 1e-9) if avail else 0.0

    expl = {
        "inputs": {k: (None if v is None else round(v, 4)) for k, v in vars(inp).items() if k != "notes"},
        "normalized": {k: (None if v is None else round(v, 4)) for k, v in comps.items()},
        "contributions": contributions,
        "confidence": round(confidence, 3),
        "overrides": [],
        "notes": list(inp.notes),
    }

    stale = inp.data_age_minutes is not None and inp.data_age_minutes > cfg["freshness_max_minutes"]
    if confidence < cfg["min_confidence"] or stale:
        if stale:
            expl["notes"].append(f"Dữ liệu cũ {inp.data_age_minutes:.0f} phút (> {cfg['freshness_max_minutes']})")
        else:
            expl["notes"].append("Độ tin cậy dữ liệu thấp: thiếu đầu vào quan trọng")
        return RiskResult("INSUFFICIENT_DATA", round(score, 4), confidence, expl)

    th = cfg["thresholds"]
    level = "HIGH" if score >= th["high"] else "MEDIUM" if score >= th["medium"] else "LOW"

    ov = cfg["overrides"]
    if inp.flood_probability is not None and inp.flood_probability >= ov["flood_probability_high"]:
        expl["overrides"].append(f"Xác suất ngập {inp.flood_probability:.0%} >= {ov['flood_probability_high']:.0%}")
    if inp.water_level_ratio is not None and inp.water_level_ratio >= ov["water_level_ratio_high"]:
        expl["overrides"].append("Mực nước đạt/vượt ngưỡng ngập")
    if inp.camera_flood_ratio is not None and inp.camera_flood_ratio >= ov["camera_ratio_high"]:
        expl["overrides"].append(f"Camera phát hiện {inp.camera_flood_ratio:.0%} diện tích ROI bị ngập")
    if inp.flood_depth_cm is not None and inp.flood_depth_cm >= ov.get("flood_depth_cm_high", 20):
        expl["overrides"].append(f"Ước ngập khoảng {max(10, round(inp.flood_depth_cm / 10) * 10)} cm")
    if inp.report_confirmations:
        expl["overrides"].append("Có báo cáo ngập đã được xác nhận")
    if expl["overrides"]:
        level = "HIGH"
    elif inp.report_confirmations == 0:
        expl["notes"].append("Có báo cáo ngập chưa xác nhận")
        level = level if RANK[level] >= RANK["MEDIUM"] else "MEDIUM"
    storm = None
    if not expl["overrides"] and inp.storm_models and inp.storm_models >= cfg.get("storm_min_models", 2):
        storm = (f"Nguy cơ mưa dông cục bộ: {inp.storm_models}/7 mô hình thời tiết báo mưa 3 giờ tới "
                 ">= 10 mm (ước tính)")
        expl["notes"].append(storm)
        if RANK[level] < RANK["MEDIUM"]:  # chỉ nâng tới Trung bình: tín hiệu đo trên ít sự kiện
            level = "MEDIUM"
        else:
            storm = None

    # hysteresis: chỉ hạ mức khi điểm giảm rõ dưới ngưỡng của mức trước
    if previous_level in ("MEDIUM", "HIGH") and RANK[level] < RANK[previous_level] and not expl["overrides"]:
        keep = th[previous_level.lower()] - cfg["hysteresis"]
        if score >= keep:
            expl["notes"].append(f"Giữ mức {previous_level} (hysteresis: điểm {score:.2f} >= {keep:.2f})")
            level = previous_level

    expl["level_reason"] = (
        "Mức do: " + "; ".join(expl["overrides"]) if expl["overrides"]
        else f"Mức do: {storm}" if storm and level == "MEDIUM"
        else f"Điểm rủi ro {score:.2f} (ngưỡng MEDIUM {th['medium']}, HIGH {th['high']})")
    return RiskResult(level, round(score, 4), confidence, expl)


def should_alert(level: str, cfg: dict) -> bool:
    return RANK.get(level, -1) >= RANK[cfg["alert_min_level"]]
