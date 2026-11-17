from app.services.risk_service import camera_ratios

TT, MAN = "TT-" + "a" * 24, "CAM-01"


def test_traffic_camera_needs_two_high_detections_and_uses_lower():
    assert camera_ratios(TT, [0.9], 0.4) == []  # chỉ một phát hiện
    assert camera_ratios(TT, [0.9, 0.1], 0.4) == []  # phát hiện thứ hai thấp
    assert camera_ratios(TT, [0.1, 0.9, 0.9], 0.4) == []  # hai gần nhất mới tính
    assert camera_ratios(TT, [0.9, 0.5, 0.1], 0.4) == [0.5]  # lấy giá trị thấp hơn


def test_manual_camera_unchanged():
    assert camera_ratios(MAN, [0.9], 0.4) == [0.9]
    assert camera_ratios(MAN, [0.1, 0.9], 0.4) == [0.1, 0.9]
