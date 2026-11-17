from app.services.routing_service import _merge, classify_segments, dist_m, instruction, split_line

LINE = [[106.700 + i * 0.0005, 10.780] for i in range(40)]  # ~2,1 km theo hướng đông


def test_dist_m_reasonable():
    assert 54 < dist_m((106.700, 10.780), (106.7005, 10.780)) < 56


def test_split_line_keeps_continuity_and_length():
    segs = split_line(LINE)
    assert len(segs) >= 9
    assert all(a[-1] == b[0] for a, b in zip(segs, segs[1:], strict=False))
    total = sum(dist_m(p, q) for s in segs for p, q in zip(s, s[1:], strict=False))
    assert abs(total - sum(dist_m(p, q) for p, q in zip(LINE, LINE[1:], strict=False))) < 1


def test_classify_report_and_hotspot():
    segs = split_line(LINE)
    ctx = {1: (10.780, 106.70, 0.0, 0.0)}
    elev = [8.0] * len(segs)
    dry = classify_segments(segs, ctx, 0.0, elev, [], [])
    assert {s["status"] for s in dry} == {"DRY"}
    reported = classify_segments(segs, ctx, 0.0, elev, [], [(106.7001, 10.7801)])
    assert reported[0]["status"] == "REPORTED_FLOODED" and reported[-1]["status"] == "DRY"
    storm = classify_segments(segs, {1: (10.78, 106.70, 30.0, 60.0)}, 1.0, [1.5] * len(segs),
                              [(106.705, 10.780)], [])
    assert any(s["status"] == "LIKELY_FLOODED" for s in storm)


def test_merge_same_status():
    segs = [{"coords": [[0, 0], [1, 0]], "status": "DRY", "probability": 0.1, "reasons": [], "length_m": 10},
            {"coords": [[1, 0], [2, 0]], "status": "DRY", "probability": 0.2, "reasons": [], "length_m": 10},
            {"coords": [[2, 0], [3, 0]], "status": "AT_RISK", "probability": 0.4, "reasons": ["x"], "length_m": 5}]
    m = _merge(segs)
    assert [x["status"] for x in m] == ["DRY", "AT_RISK"]
    assert m[0]["coords"] == [[0, 0], [1, 0], [2, 0]] and m[0]["length_m"] == 20 and m[0]["probability"] == 0.2


def test_instruction_vietnamese():
    assert instruction({"maneuver": {"type": "turn", "modifier": "left"}, "name": "Lê Lợi"}) == "Rẽ trái vào Lê Lợi"
    assert instruction({"maneuver": {"type": "roundabout", "exit": 2}, "name": ""}) == "Vào vòng xoay, đi lối ra thứ 2"
    assert instruction({"maneuver": {"type": "depart"}, "name": "Hàm Nghi"}) == "Xuất phát trên Hàm Nghi"
    assert instruction({"maneuver": {"type": "arrive", "modifier": "right"}}).startswith("Đến nơi")


def test_classify_depth_status_and_priorities():
    from types import SimpleNamespace

    segs = split_line(LINE)
    n = len(segs)
    ctx = {1: (10.780, 106.70, 0.0, 0.0)}
    near_c = [(106.7005, 10.780)]
    tide = classify_segments(segs, ctx, 1.42, [2.0] * n, [], [], tide_centroids=near_c)
    assert tide[0]["status"] == "LIKELY_FLOODED" and any("ước ngập khoảng 40 cm" in r for r in tide[0]["reasons"])
    assert tide[-1]["status"] == "DRY"  # xa tâm phường > 1500 m
    assert {s["status"] for s in classify_segments(segs, ctx, 1.42, [2.0] * n, [], [])} == {"DRY"}  # không có tâm
    far = classify_segments(segs, ctx, 1.42, [12.0] * n, [], [], tide_centroids=near_c)
    assert {s["status"] for s in far} == {"DRY"}
    light = classify_segments(segs, {1: (10.78, 106.70, 0.0, 28.0)}, 0.0, [2.0] * n, [], [])  # 28 mm/3h -> 10 cm
    assert {s["status"] for s in light} == {"AT_RISK"}
    rep = classify_segments(segs, ctx, 1.42, [2.0] * n, [], [(106.7001, 10.7801)], tide_centroids=near_c)
    assert rep[0]["status"] == "REPORTED_FLOODED"
    sim = SimpleNamespace(longitude=LINE[-1][0], latitude=LINE[-1][1], radius_m=50, depth_cm=30)
    s2 = classify_segments(segs, ctx, 1.42, [2.0] * n, [], [], sims=[sim], tide_centroids=near_c)
    assert s2[-1]["status"] == "LIKELY_FLOODED" and s2[-1]["reasons"][0].startswith("MÔ PHỎNG")
    s3 = classify_segments(segs, ctx, 1.42, [2.0] * n, [], [(LINE[-1][0], LINE[-1][1])], sims=[sim])
    assert s3[-1]["status"] == "REPORTED_FLOODED"
