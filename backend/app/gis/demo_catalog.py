"""Danh mục trạm & camera DEMO.

Vị trí đặt gần các điểm ngập được báo chí nhắc đến thường xuyên tại TP.HCM (toạ độ xấp xỉ),
nhưng BẢN THÂN TRẠM/CAMERA LÀ HƯ CẤU — dữ liệu sinh bởi bộ mô phỏng, gắn nhãn SIMULATED.
"""

# code, tên, loại, địa chỉ, lat, lon, ngưỡng ngập (cm), sensitivity, tide_amp, base_cm
STATIONS = [
    ("DM001", "Trạm DEMO Nguyễn Hữu Cảnh", "COMBINED", "Nguyễn Hữu Cảnh, Bình Thạnh", 10.7905, 106.7180, 60, 6.5, 28, 18),
    ("DM002", "Trạm DEMO Huỳnh Tấn Phát", "COMBINED", "Huỳnh Tấn Phát, Quận 7", 10.7330, 106.7290, 65, 6.0, 30, 20),
    ("DM003", "Trạm DEMO Kinh Dương Vương", "COMBINED", "Kinh Dương Vương, Bình Tân", 10.7480, 106.6230, 60, 5.5, 20, 14),
    ("DM004", "Trạm DEMO Đinh Bộ Lĩnh", "COMBINED", "Đinh Bộ Lĩnh, Bình Thạnh", 10.8075, 106.7100, 60, 5.8, 26, 15),
    ("DM005", "Trạm DEMO Phan Anh", "RAIN", "Phan Anh, Tân Phú", 10.7860, 106.6160, 55, 5.0, 18, 12),
    ("DM006", "Trạm DEMO Nguyễn Văn Quá", "COMBINED", "Nguyễn Văn Quá, Quận 12", 10.8470, 106.6330, 60, 5.2, 19, 12),
    ("DM007", "Trạm DEMO Quang Trung", "COMBINED", "Quang Trung, Gò Vấp", 10.8370, 106.6620, 60, 4.8, 20, 13),
    ("DM008", "Trạm DEMO Lê Văn Lương", "WATER_LEVEL", "Lê Văn Lương, Nhà Bè", 10.7020, 106.7020, 70, 6.8, 32, 22),
    ("DM009", "Trạm DEMO Thảo Điền", "COMBINED", "Thảo Điền, Quận 2 (TP Thủ Đức)", 10.8030, 106.7350, 65, 5.5, 30, 18),
    ("DM010", "Trạm DEMO Võ Văn Ngân", "COMBINED", "Võ Văn Ngân, Thủ Đức", 10.8500, 106.7700, 60, 4.5, 22, 12),
    ("DM011", "Trạm DEMO Đường Ba Tháng Hai", "RAIN", "Ba Tháng Hai, Quận 10", 10.7680, 106.6670, 55, 4.2, 15, 10),
    ("DM012", "Trạm DEMO Hồ Học Lãm", "COMBINED", "Hồ Học Lãm, Bình Tân", 10.7280, 106.6100, 60, 5.6, 21, 14),
    ("DM013", "Trạm DEMO Bến Vân Đồn", "WATER_LEVEL", "Bến Vân Đồn, Quận 4", 10.7600, 106.6980, 70, 5.0, 32, 24),
    ("DM014", "Trạm DEMO Phạm Thế Hiển", "COMBINED", "Phạm Thế Hiển, Quận 8", 10.7390, 106.6520, 65, 5.8, 28, 20),
    ("DM015", "Trạm DEMO Tân Kỳ Tân Quý", "COMBINED", "Tân Kỳ Tân Quý, Bình Tân", 10.8000, 106.6050, 55, 4.6, 16, 10),
    ("DM016", "Trạm DEMO Trường Chinh", "RAIN", "Trường Chinh, Tân Bình", 10.8020, 106.6430, 55, 4.0, 15, 10),
    ("DM017", "Trạm DEMO Lò Gốm", "COMBINED", "Lò Gốm, Quận 6", 10.7470, 106.6400, 60, 5.2, 22, 14),
    ("DM018", "Trạm DEMO Nguyễn Duy Trinh", "COMBINED", "Nguyễn Duy Trinh, Quận 9", 10.7960, 106.7900, 65, 4.6, 24, 14),
]

# code, tên, lat, lon, trạm tham chiếu mực nước (mô phỏng), công khai
CAMERAS = [
    ("CAM01", "Camera DEMO Nguyễn Hữu Cảnh", 10.7900, 106.7190, "DM001", True),
    ("CAM02", "Camera DEMO Huỳnh Tấn Phát", 10.7340, 106.7280, "DM002", True),
    ("CAM03", "Camera DEMO Kinh Dương Vương", 10.7485, 106.6240, "DM003", False),
    ("CAM04", "Camera DEMO Đinh Bộ Lĩnh", 10.8070, 106.7110, "DM004", True),
    ("CAM05", "Camera DEMO Lê Văn Lương", 10.7030, 106.7030, "DM008", False),
    ("CAM06", "Camera DEMO Thảo Điền", 10.8025, 106.7340, "DM009", True),
    ("CAM07", "Camera DEMO Phạm Thế Hiển", 10.7395, 106.6530, "DM014", False),
    ("CAM08", "Camera DEMO Quang Trung", 10.8365, 106.6610, "DM007", False),
]
