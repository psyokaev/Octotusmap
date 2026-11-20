# Ma trận yêu cầu

Nguồn: đề cương DACN (`Đề cương DACN NguyenQuocTu.docx`, trích tại `docs/de-cuong.txt`) và master prompt (`promt.txt`).
Trạng thái: NOT_STARTED · IN_PROGRESS · IMPLEMENTED · TESTED · BLOCKED.

## Sai khác có chủ đích so với đề cương

| Đề cương | Triển khai | Lý do |
|---|---|---|
| PostgreSQL/PostGIS | PostgreSQL 16.4 + PostGIS 3.4.2 (cài portable `E:/pgsql`) | Đúng đề cương. Từng triển khai trên MySQL 8 rồi chuyển lại (27 bảng khớp số dòng); script chuyển một lần đã xoá sau khi xong |
| Dashboard Streamlit/Plotly | Streamlit + Plotly + Folium (`streamlit_app/`) | Đúng đề cương. Bản React cũ đã xoá khỏi repo |
| YOLOv8 "phát hiện đối tượng" ước lượng diện tích | YOLOv8-**seg** | Diện tích vùng ngập cần mask, không suy được từ bounding box |
| Dữ liệu khí tượng thủy văn công khai | Open-Meteo (mô hình trên lưới), điểm ngập công bố, báo chí; không có trạm đo mưa/mực nước cống thật | Chưa có nguồn trạm đo được cấp phép; DEMO dùng dữ liệu mô phỏng có nhãn |
| LSTM dự báo xác suất ngập | LSTM/GRU dự báo mưa; xác suất ngập ước tính bằng công thức (`flood_index`) | Chưa có nhãn ngập thật để huấn luyện |
| Postman | Có: `docs/postman/OctotusMap.postman_collection.json` (sinh từ OpenAPI bằng `scripts/export_postman.py`) | Đã làm |
| Jupyter | Có: `notebooks/01_du_bao_mua_lstm.ipynb`, `02_yolov8_ngap.ipynb`, `03_danh_gia_canh_bao.ipynb` (đã chạy) | Đã làm |
| GitLab | Chưa dựng; chỉ Git cục bộ | Không có máy chủ GitLab |
| Tinh chỉnh theo cụm khu vực; LSTM xác suất ngập | Tinh chỉnh `GRU_CLUSTER` đã làm; đầu xác suất ngập thử nghiệm không đạt cổng nên không tích hợp (`scripts/experiment_flood_head.py`) | Chỉ có 74 sự kiện báo chí, chưa có nhãn ngập thật |

## Chức năng

| Yêu cầu | Trạng thái | Code | Test |
|---|---|---|---|
| Backend FastAPI RESTful, MVC | TESTED | `backend/app/{models,schemas,controllers,services,repositories}` | tests/integration |
| Thu thập & tiền xử lý mưa (mm)/mực nước (cm) | TESTED | `services/observation_service.py`, `jobs/simulator.py` | test_import_csv_dedup_and_rejects |
| Nhập CSV/Excel, chuẩn hoá m→cm, múi giờ VN→UTC, dedup, outlier | TESTED | `observation_service.import_observations` | như trên |
| LSTM/GRU dự báo mưa + xác suất ngập 1–6h | TESTED | `ai/forecasting/*`, `services/forecast_service.py` | test_forecasting.py, test_forecast_contract |
| Cold-start trạm mới (mượn trạm lân cận cùng cụm) | TESTED | `forecast_service.run_inference` | test_cold_start_new_station, test_cold_start_prefers_same_cluster |
| Tinh chỉnh mô hình theo cụm khu vực (`GRU_CLUSTER`, chỉ dùng khi nền khớp mô hình active) | TESTED | `ai/forecasting/train.py --finetune-clusters`, `forecast_service.cluster_models` | test_cluster_models, test_stale_cluster_model_ignored_and_newest_wins |
| Metrics MAE/RMSE/P/R/F1/Brier/AUC, confusion matrix | TESTED | `ai/evaluation/metrics.py` | test_metrics |
| Accuracy/F1 phân loại mức rủi ro so với sự kiện báo chí, tách tập hiệu chỉnh | TESTED | `ai/evaluation/risk_eval.py`, `scripts/evaluate_risk.py` | test_risk_eval |
| Đo hiệu năng gần thời gian thực | TESTED | `scripts/benchmark.py` | testing-report Đợt 5, Đợt 6 |
| YOLOv8-seg huấn luyện trên ảnh thật (mask mAP50 0,450, 44 ảnh test) + tỉ lệ diện tích ngập trong ROI, đưa vào cảnh báo cho ảnh cán bộ tải lên | TESTED | `ai/computer_vision/*`, `services/camera_service.py` | test_camera_analyze..., test_simulated_vision_never_replaces_real_active |
| Quét tự động camera giao thông bằng YOLOv8-seg (`CAMERA_SCAN_ENABLED`, 15 phút, tối đa 20 camera/lần, 2 lần liên tiếp) | IMPLEMENTED (đang TẮT ở .env thật) | `camera_service.scan_traffic_cameras` | test_scan_* |
| Rule engine LOW/MEDIUM/HIGH/không đủ dữ liệu, trọng số, version, hysteresis, giải thích | TESTED | `services/rule_engine.py`, `risk_service.py` | test_rule_engine.py |
| Khuyến nghị theo mức | IMPLEMENTED | `rule_engine.RECOMMENDATIONS` | E2E (panel cảnh báo) |
| Cảnh báo: chống lặp, escalate, cooldown, trạng thái NEW→CLOSED, phân công, ghi chú, xác minh, audit | TESTED | `services/alert_service.py`, `controllers/alerts.py` | test_alert_workflow, test_alert_dedup, E2E #15 |
| Thông báo trong web + SSE | IMPLEMENTED | `controllers/misc.py`, `services/events.py`, `streamlit_app/views/notifications.py` (Streamlit hỏi lại 60 s, không dùng SSE) | AppTest |
| Email SMTP (tuỳ chọn) | NOT_STARTED | — | — |
| GIS: ranh giới, vùng nguy cơ, điểm ngập, trạm mưa/mực nước, camera, cảnh báo, heatmap, tuyến, dự báo theo mốc | TESTED | `controllers/gis.py`, `streamlit_app/views/map.py`, `map_layers.py` | test_geojson_layers, AppTest, smoke 12 trang |
| Bản đồ Folium: tìm kiếm (chọn từ danh sách), zoom, panel chi tiết, chỉ đường; chưa có kéo thả điểm A/B, "vị trí của tôi", nền tối | IMPLEMENTED | `streamlit_app/views/map.py` | AppTest, smoke 12 trang |
| Tìm kiếm: đường (Photon; Nominatim bị chặn ở mạng này), phường/quận, trạm, camera, điểm ngập, toạ độ | TESTED | `services/search_service.py` | AppTest |
| Hỗ trợ di chuyển (tuyến tránh vùng nguy cơ, có giới hạn) | TESTED | `services/routing_service.py` | kiểm thử API OSRM thật |
| Dashboard KPI + biểu đồ + bộ lọc | TESTED | `streamlit_app/views/dashboard.py` | AppTest |
| Thống kê 10 nhóm, bảng phân trang/sắp xếp/tìm kiếm | IMPLEMENTED | `services/statistics_service.py`, `streamlit_app/views/statistics.py` | test_statistics_match_sql |
| Xuất Excel (OpenPyXL) theo bộ lọc + CSV | TESTED | `services/export_service.py` | test_excel_*, E2E #19–20 |
| CRUD trạm (xoá mềm, import, lịch sử, biểu đồ, bất thường, kết nối) | TESTED | `controllers/stations.py`, `streamlit_app/views/stations.py` | test_station_*, AppTest |
| CRUD camera, upload, retention, quyền xem | TESTED | `controllers/cameras.py`, `streamlit_app/views/cameras.py` | test_camera_*, test_public_* |
| Lịch sử ngập | IMPLEMENTED | `controllers/history.py`, `streamlit_app/views/history.py` | AppTest |
| Quản lý mô hình (version, metrics, kích hoạt, huấn luyện lại) | IMPLEMENTED | `controllers/admin.py`, `streamlit_app/views/models.py` | AppTest |
| Tài khoản & RBAC ADMIN/OPERATOR/USER, đăng ký, đổi mật khẩu | TESTED | `core/deps.py`, `services/user_service.py` | test_rbac_roles, test_me_and_logout... |
| Cấu hình hệ thống, audit log, nguồn dữ liệu | IMPLEMENTED | `controllers/admin.py`, `streamlit_app/views/settings.py` | AppTest |
| DEMO/LIVE/STALE/UNAVAILABLE, nhãn mô phỏng | TESTED | `station_service.data_status`, `is_simulated` | test_station_list_filters... |
| PostgreSQL tự tạo DB, migrations (baseline `0001_initial_postgis_baseline`), FK, index GiST, seed idempotent | TESTED | `scripts/bootstrap.py`, `migrations/` | test_seed_idempotent, test_foreign_keys... |
| Docker Compose (postgis/postgis:16-3.4, backend, streamlit) + Dockerfile | IMPLEMENTED (chưa chạy) | `docker-compose.yml`, `streamlit_app/Dockerfile` | BLOCKED: máy không có Docker |
| Chạy một lệnh | IMPLEMENTED | `npm run dev` (`scripts/dev.mjs`, tự bật PostgreSQL) | — |
| Responsive / dark mode | IMPLEMENTED | Streamlit tự co giãn và theo theme; không còn E2E mobile của bản React | — |

## Phần chưa đạt đề cương

Không có trạm đo mưa/mực nước (chỉ dữ liệu mô hình Open-Meteo; mưa trong DB khớp Open-Meteo best-match 99,9%); F1 mưa to khoảng 6%; recall mưa-ngập 0/25 trên sự kiện độc lập; xác suất ngập bằng LSTM không được dùng; Docker chưa chạy; chưa có GitLab; một worker, không HA.
