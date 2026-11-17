# Kế hoạch triển khai (đã thực hiện)

> Lịch sử: kế hoạch ban đầu dùng MySQL và React. Từ 11/2026 hệ thống đã chuyển sang PostgreSQL/PostGIS và Streamlit (xem `requirements-matrix.md`, `testing-report.md` Đợt 6).

1. **Khảo sát**: Windows 11, Python 3.13 (TensorFlow 2.21 có sẵn), Node 24, MySQL 8.0 local, không có Docker.
2. **Nền tảng backend**: cấu hình `.env`, Geometry type MySQL (axis-order long-lat), 24 entity, schema Pydantic, bcrypt/JWT, RBAC.
3. **AI**: bộ mô phỏng mưa/triều/dòng chảy → tiền xử lý chống rò rỉ → LSTM/GRU + baseline → đánh giá → artifact + đăng ký DB;
   YOLOv8n-seg trên ảnh mô phỏng có mask; rule engine thuần có test.
4. **Nghiệp vụ**: quan trắc (kiểm tra chất lượng, nhập tệp), trạm, camera, dự báo, rủi ro, cảnh báo, thống kê, Excel, GIS, tìm kiếm, định tuyến.
5. **Controllers + main**: 86 thao tác `/api/v1`, SSE, health, header bảo mật.
6. **Migration + bootstrap**: migration sinh từ metadata, `scripts/bootstrap.py` idempotent (DB → migrate → seed → DEMO → train → backfill → chu kỳ).
7. **Frontend**: khung (API client, auth, layout, UI kit), bản đồ; trang quản trị do 2 sub-agent làm song song (analytics, ops).
8. **Kiểm thử**: pytest trên DB test riêng; E2E Playwright CLI trên ứng dụng thật; security review; sửa lỗi; tài liệu.
