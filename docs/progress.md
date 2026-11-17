# Tiến độ

| Phase | Nội dung | Trạng thái | Ghi chú |
|---|---|---|---|
| 0 Research & audit | Đọc đề cương, khảo sát môi trường, audit công cụ | TESTED | `docs/de-cuong.txt`, `docs/tool-audit.md` |
| 1 Architecture | MVC, CSDL 24 bảng, API, AI, GIS, bảo mật | TESTED | `docs/architecture.md`, `docs/database-design.md`, `docs/api-design.md` |
| 2 Database & backend | PostgreSQL 16 + PostGIS (trước đó MySQL), Alembic, auth/RBAC, CRUD, 86 thao tác API | TESTED | backend 123 test pytest |
| 3 Data pipeline & AI | Mô phỏng, kiểm tra chất lượng, LSTM/GRU, YOLOv8-seg, rule engine, backfill | TESTED | `docs/ai-methodology.md` |
| 4 GIS & frontend | Bản đồ Folium trong Streamlit, lớp, tìm kiếm, mốc giờ, panel (bản React/MapLibre cũ đã thay) | TESTED | 78 test AppTest + smoke 12 trang |
| 5 Dashboard & reporting | KPI, biểu đồ, thống kê, Excel/CSV | TESTED | Excel đối chiếu SQL |
| 6 Admin & operations | Người dùng, trạm, camera, cảnh báo, thông báo, cấu hình, audit | TESTED | E2E Operator/Admin |
| 7 Test & fix | Unit, integration, E2E, security review, sửa lỗi | TESTED | `docs/testing-report.md` |
| 8 Delivery | README, CLAUDE.md, tài liệu, Docker, Postman, notebook, commit | IMPLEMENTED | Docker chưa chạy; GitLab chưa dựng |

Mốc commit: `git log --oneline`.
