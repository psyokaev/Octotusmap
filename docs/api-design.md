# Thiết kế REST API — `/api/v1`

> Sinh tự động từ OpenAPI của ứng dụng. Tài liệu tương tác: `http://127.0.0.1:8000/docs`.

## Quy ước

- Xác thực: `Authorization: Bearer <JWT>` (Streamlit dùng cách này) hoặc cookie httpOnly `ufd_token` (SameSite=Strict). Đăng xuất/đổi mật khẩu tăng `token_version` → vô hiệu token cũ.
- Phân quyền: **Công khai** (không cần đăng nhập, dữ liệu đã lọc), **USER+**, **OPERATOR+** (ADMIN, OPERATOR), **ADMIN**.
- Lỗi chuẩn: `{"error": {"code", "message", "details"}}` — 401 UNAUTHORIZED, 403 FORBIDDEN, 404 NOT_FOUND, 409 DUPLICATE/INVALID_TRANSITION, 413/415 upload, 422 VALIDATION_ERROR, 429 RATE_LIMITED, 503 dịch vụ ngoài.
- Phân trang: `page`, `size` → `{items,total,page,size}`. Sắp xếp: `sort`, `direction=asc|desc`. Thời gian: ISO 8601 UTC (`Z`).

## Danh sách endpoint

| Method | Path | Mô tả | Tham số |
|---|---|---|---|
| GET | `/api/v1/admin/audit-logs` | Audit Logs | q, action, page, size |
| GET | `/api/v1/admin/data-sources` | Data Sources |  |
| POST | `/api/v1/admin/jobs/run-cycle` | Run Cycle |  |
| GET | `/api/v1/admin/models` | Models |  |
| POST | `/api/v1/admin/models/train` | Huấn luyện chạy nền; theo dõi qua /admin/training-runs. | task, epochs |
| POST | `/api/v1/admin/models/{mid}/activate` | Activate Model |  |
| GET | `/api/v1/admin/rules` | Rules |  |
| POST | `/api/v1/admin/rules` | Create Rule |  |
| POST | `/api/v1/admin/rules/{rid}/activate` | Activate Rule |  |
| GET | `/api/v1/admin/settings` | Settings |  |
| PUT | `/api/v1/admin/settings/{key}` | Put Setting |  |
| GET | `/api/v1/admin/training-runs` | Training Runs |  |
| GET | `/api/v1/admin/users` | Users | q, role, page, size |
| POST | `/api/v1/admin/users` | Create User |  |
| PATCH | `/api/v1/admin/users/{uid}` | Update User |  |
| DELETE | `/api/v1/admin/users/{uid}` | Delete User |  |
| GET | `/api/v1/alerts` | Người dùng công khai chỉ thấy cảnh báo công khai đang hoạt động. | status, level, area_id, q, date_from, date_to, page, size, sort, direction |
| GET | `/api/v1/alerts/assignees` | Assignees |  |
| GET | `/api/v1/alerts/{aid}` | Detail |  |
| POST | `/api/v1/alerts/{aid}/acknowledge` | Acknowledge |  |
| POST | `/api/v1/alerts/{aid}/assign` | Assign |  |
| POST | `/api/v1/alerts/{aid}/notes` | Note |  |
| POST | `/api/v1/alerts/{aid}/status` | Set Status |  |
| POST | `/api/v1/alerts/{aid}/verify` | Verify |  |
| POST | `/api/v1/auth/change-password` | Change Password |  |
| POST | `/api/v1/auth/login` | Login |  |
| POST | `/api/v1/auth/logout` | Logout |  |
| GET | `/api/v1/auth/me` | Me |  |
| POST | `/api/v1/auth/register` | Register |  |
| GET | `/api/v1/auth/session` | Phiên hiện tại hoặc null (khách) — tránh lỗi 401 khi trang công khai kiểm tra đăng nhập. |  |
| GET | `/api/v1/cameras` | List Cameras |  |
| POST | `/api/v1/cameras` | Create Camera |  |
| POST | `/api/v1/cameras/analyze` | Phân tích ảnh tải lên (YOLOv8-seg nếu có trọng số, ngược lại HEURISTIC). |  |
| GET | `/api/v1/cameras/media/{frame_id}/{kind}` | Ảnh camera chỉ phục vụ qua API có kiểm tra quyền (không mở thư mục tĩnh). |  |
| GET | `/api/v1/cameras/{cid}` | Get Camera |  |
| PATCH | `/api/v1/cameras/{cid}` | Update Camera |  |
| DELETE | `/api/v1/cameras/{cid}` | Delete Camera |  |
| GET | `/api/v1/cameras/{cid}/detections` | Detections | page, size |
| GET | `/api/v1/events` | Server-Sent Events: 'alert' (cảnh báo mới/thay đổi), 'cycle' (dữ liệu dự báo mới). |  |
| GET | `/api/v1/exports/csv` | Csv Export | kind, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/exports/excel` | Excel | report, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/exports/history` | History | page, size |
| GET | `/api/v1/forecasts` | Các lần phát hành gần nhất của một trạm. | station_id, limit |
| GET | `/api/v1/forecasts/area/{aid}` | Area Forecast |  |
| GET | `/api/v1/forecasts/latest` | Latest | area_id |
| GET | `/api/v1/forecasts/model-status` | Model Status |  |
| GET | `/api/v1/forecasts/risk` | Risk | horizon |
| GET | `/api/v1/gis/areas` | Areas |  |
| GET | `/api/v1/gis/areas/{aid}` | Area Detail |  |
| GET | `/api/v1/gis/features` | Lớp điểm: trạm (mưa/mực nước), camera, điểm ngập lịch sử, cảnh báo đang hoạt động. | horizon |
| GET | `/api/v1/gis/geojson` | Ranh giới hành chính (GeoJSON, lon/lat, WGS84). |  |
| GET | `/api/v1/gis/identify` | Thông tin tại điểm click: khu vực, trạm gần nhất, rủi ro 0–6h, lịch sử ngập, camera. | lat, lon |
| POST | `/api/v1/gis/import` | Import Boundaries | level, name_field, code_field, source_name |
| GET | `/api/v1/gis/risk-layers` | Risk Layers | horizon |
| GET | `/api/v1/history/events` | Events | q, area_id, date_from, date_to, min_depth, page, size, sort, direction |
| POST | `/api/v1/history/events` | Create Event |  |
| DELETE | `/api/v1/history/events/{eid}` | Delete Event |  |
| GET | `/api/v1/notifications` | Notifications | unread_only, page, size |
| POST | `/api/v1/notifications/read-all` | Read All |  |
| POST | `/api/v1/notifications/{nid}/read` | Read |  |
| POST | `/api/v1/routing/route` | Route |  |
| GET | `/api/v1/search` | Search | q, geocode |
| GET | `/api/v1/stations` | List Stations | q, station_type, status, area_id, connection, page, size, sort, direction |
| POST | `/api/v1/stations` | Create Station |  |
| POST | `/api/v1/stations/import` | CSV/XLSX với cột station_code, observed_at, rainfall_mm, water_level_cm/water_level_m. |  |
| GET | `/api/v1/stations/{sid}` | Get Station |  |
| PATCH | `/api/v1/stations/{sid}` | Update Station |  |
| DELETE | `/api/v1/stations/{sid}` | Delete Station |  |
| GET | `/api/v1/stations/{sid}/forecast` | Station Forecast |  |
| GET | `/api/v1/stations/{sid}/observations` | Observations | date_from, date_to |
| POST | `/api/v1/stations/{sid}/observations` | Add Observation |  |
| POST | `/api/v1/stations/{sid}/observations/import` | Import Station |  |
| GET | `/api/v1/stations/{sid}/quality` | Quality | days |
| GET | `/api/v1/statistics/alert-handling` | Alert Handling | date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/alerts` | Alerts | group, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/cameras` | Cameras | date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/data-quality` | Data Quality | date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/flood-events` | Flood Events | group, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/model-performance` | Model Performance | date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/observations` | Bảng dữ liệu chi tiết có phân trang (mới nhất trước). | kind, page, size, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/overview` | Overview | date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/rainfall` | Rainfall | group, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/risk` | Risk | group, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/api/v1/statistics/stations` | Stations |  |
| GET | `/api/v1/statistics/water-level` | Water Level | group, date_from, date_to, area_id, station_id, risk_level, data_type |
| GET | `/health` | Health |  |
