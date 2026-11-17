# Báo cáo kiểm thử

## Đợt 6: chuyển PostgreSQL/PostGIS và Streamlit (12/11/2026)

Các kết quả Frontend/Vite/Playwright và MySQL ở các đợt 2–5 phía dưới là **lịch sử** của bản React/MySQL cũ.

- `pytest` backend: **123 passed** (PostgreSQL 16.4 + PostGIS 3.4.2, DB riêng `urban_flood_dss_test`). `streamlit_app/tests` (AppTest): **78 passed**.
- **Chuyển dữ liệu** MySQL → PostgreSQL bằng `scripts/migrate_mysql_to_postgres.py`: 27 bảng, số dòng khớp từng bảng; kiểm tra hình học không hợp lệ: 0; `alembic` ở revision `0001` (baseline `0001_initial_postgis_baseline`). Chạy thử trên DB tạm: 879.186 snapshot và 424.320 dòng mưa khớp, khoảng 80 giây. Script đã được sửa để kiểm tra MySQL trước và nạp trong một transaction (rollback khi lệch số dòng); bản sửa này chưa chạy lại trên dữ liệu thật.
- **Smoke trực tiếp Streamlit** trên PostgreSQL thật: 12 trang, 0 ngoại lệ.
- Rà soát giao diện sửa: XSS qua tooltip bản đồ (escape HTML), giờ mặc định theo giờ Việt Nam, trạng thái chờ gắn đúng cảnh báo, xoá tệp xuất khi đổi bộ lọc, đăng xuất xoá toàn bộ phiên, rate limit theo IP thật qua `X-Forwarded-For`.
- **YOLOv8-seg trên ảnh thật** (Kaggle "Flood Area Segmentation", 290 ảnh, 44 ảnh test): mask mAP50 **0,4503**, mAP50-95 0,207, precision 0,572, recall 0,483; mô hình mô phỏng cũ trên cùng tập 0,0085. Mô hình id 8 active, `trained_on_simulated=False`. Test: quét camera (thứ tự công bằng, ngân sách thời gian, ảnh TT- không công khai), mô hình mô phỏng không thay mô hình thật.
- **Đầu xác suất ngập GRU** (74 sự kiện): không qua cổng (PR-AUC 0,0118 so với công thức 0,0132; event-day recall 0,444 so với 0,667; 5 ngày sự kiện test). Không tích hợp.
- **Tinh chỉnh theo cụm** (2 epoch, val loss / MAE mưa): CORE 0,0801→0,0778 / 0,259→0,246; INNER 0,0835→0,0815 / 0,265→0,253; SUBURBAN 0,0775→0,0741 / 0,251→0,236. Test: `test_cluster_models`, mô hình cụm lệch nền bị bỏ qua, kích hoạt cụm sai nền trả 409 `BASE_MISMATCH`.
- Postman: collection sinh từ OpenAPI (84 path) và có test không chứa mật khẩu; 3 notebook đã chạy (mưa GRU 2 epoch MAE 0,357 so với persistence 0,457; F1 mưa to 0,041).
- **Hiệu năng** trên PostgreSQL (`scripts/benchmark.py --cycles 0`, 200 yêu cầu GET mỗi mức, một worker, 0 lỗi):

| Đồng thời | p50 (ms) | p95 (ms) | Lớn nhất (ms) | Yêu cầu/giây |
|---|---|---|---|---|
| 1 | 20,7 | 78,7 | 173,8 | 34,1 |
| 10 | 182,1 | 321,4 | 485,0 | 51,1 |
| 50 | 996,6 | 1.542,1 | 2.223,7 | 47,1 |

  So với MySQL (Đợt 5) p95 là 576 / 1.859 / 3.668 ms. Thời gian chu kỳ pipeline trên PostgreSQL chưa đo lại.
- Chưa kiểm thử: Docker, GitLab, nhiều worker; Streamlit chưa có E2E trình duyệt cho kéo thả/định vị (tính năng chưa chuyển).

## Đợt 5: đối chiếu đề cương (10/11/2026)

- `pytest`: **105 passed**. Frontend: `tsc`, `eslint` (0 lỗi), `vitest` 16 passed.
- YOLOv8 vào luồng cảnh báo: test bảo đảm ảnh gắn camera chỉ nâng đúng phường chứa camera, chỉ tính kết quả YOLOv8-seg, không dùng phát hiện quá 90 phút hoặc sau mốc đánh giá hơn 1 giờ, và từ chối phân tích camera giao thông.
- Accuracy/F1 mức rủi ro và thí nghiệm NWP: xem [ai-methodology.md](ai-methodology.md).
- **Hiệu năng** (`scripts/benchmark.py`, 200 yêu cầu GET mỗi mức, một worker, máy cá nhân, 0 lỗi):

| Đồng thời | p50 (ms) | p95 (ms) | Lớn nhất (ms) | Yêu cầu/giây |
|---|---|---|---|---|
| 1 | 36 | 576 | 699 | 7,4 |
| 10 | 143 | 1.859 | 2.144 | 25,5 |
| 50 | 1.637 | 3.668 | 4.826 | 23,1 |

  Một chu kỳ pipeline đầy đủ (Open-Meteo, 24 điểm dự báo, 346 khu vực × 7 mốc): 3,5–8,1 giây. Endpoint chậm nhất là `/gis/features` (p50 559 ms khi 1 yêu cầu).
- Chưa kiểm thử: Docker (máy không cài), tải dài hạn, chạy nhiều worker.


## Đợt 4: cảnh báo theo phường, lý do và độ sâu (07/11/2026)

- `pytest`: **95 passed**. Test mới: lệch triều 4 giờ, triều không tự ép mức Cao, độ sâu và lý do theo phường, quận lấy theo phường, báo cáo người dân (đã/chưa xác nhận), điểm ngập nặng, cập nhật cảnh báo cùng mức, người dân không thấy thông tin xử lý, gán quận khi tạo sự kiện/trạm. Test không còn ghi vào `storage/` và `artifacts/` thật.
- Frontend: `tsc`, `eslint` (0 lỗi), `vitest` 16 passed, `vite build` đạt.
- **Đối chiếu nghiệp vụ** (tính lại 14 ngày, 23/10–07/11/2026):
  - 12/12 sự kiện triều có phường được hệ thống báo Cao trong ±1 giờ, độ sâu ước 20–40 cm (báo chí ghi 20–50 cm).
  - 2 sự kiện triều nằm ngoài đa giác phường nên không đối chiếu được.
  - Mức Cao còn 23 giờ trong 6 ngày, đông nhất 64 phường cùng lúc (trước đây là cả 346 khu vực). Không dòng Cao nào thiếu lý do.
  - **0/7 sự kiện mưa ngày 04/11** được báo (lưới mưa chỉ ghi tối đa 1,0 mm/h).
  - Phường Bình Trưng Tây (cao 8 m) ở mốc +6h đã về mức Thấp.
- E2E (Edge, server tạm cổng 8001 vì cổng 8000 đang bị dự án khác chiếm): tuyến qua vùng mô phỏng hiện "0.9 km có thể ngập" với nét đỏ và chú giải 4 loại; bản đồ hiện tại chỉ tô 1 phường; 0 lỗi console.

## Đợt 3: OctotusMap, phường, camera, mô phỏng (06/11/2026)

- `pytest`: **78 passed**; frontend `tsc`, `eslint` (0 lỗi), `vitest`, `vite build` đạt.
- E2E (Edge, ứng dụng thật): logo/tên mới, Google Sans hiển thị dấu tiếng Việt (41); điểm ngập hiện ảnh camera thật (42); mở quận → phường, zoom hiện ranh giới và tên phường (43); admin tạo mô phỏng bằng giao diện (44).
- Mô phỏng trên tuyến thật qua API: admin 0,86 km ngập và đề xuất đổi tuyến; khách 0 km, đề xuất giữ nguyên. Không phát sinh cảnh báo (test tự động).
- Một chu kỳ pipeline với 346 khu vực: ~8 giây.
- **Lỗi nghiêm trọng tìm thấy khi migrate**: SSE giữ phiên DB suốt thời gian mở tab, chặn migration và có thể cạn pool. Đã sửa, có test.
- **Chưa kiểm chứng**: nét tô màu đoạn mô phỏng trên bản đồ khi tuyến thật đi qua vùng (đã kiểm chứng qua API, ảnh 45 không cắt vùng); nạp GeoJSON phường mới qua giao diện (chỉ có test hàm import).

## Đợt 2: dữ liệu thật + chỉ đường (06/11/2026)

- `pytest`: **69 passed** (thêm flood_index, chia đoạn tuyến, hướng dẫn rẽ, parser Open-Meteo, vòng đời báo cáo, RBAC, hết hạn, hotspot, tuyến bị đánh dấu ngập).
- Frontend: `tsc`, `eslint` (0 lỗi), `vitest` 14 passed, `vite build` đạt.
- E2E (Edge, ứng dụng thật):
  - Đăng nhập `admin`/`123`; bản đồ mới, 0 lỗi console (30-map-google-style.png).
  - Chỉ đường Bến Thành → Ung Văn Khiêm qua Photon + OSRM thật: 2 tuyến, hướng dẫn tiếng Việt (31-directions.png).
  - Gửi báo cáo ngập bằng giao diện tại điểm trên tuyến → tuyến đó ghi "0.4 km có báo cáo ngập", đoạn nét đứt tím, **đề xuất tự đổi sang tuyến còn lại** (33, 34).
  - Mobile: panel thành bottom sheet (35-mobile-directions.png).
  - 8 trang quản trị: 0 lỗi console. Excel báo cáo tổng hợp không còn sheet Camera.
- **Chưa kiểm chứng**: đoạn `AT_RISK`/`LIKELY_FLOODED` trên ứng dụng thật vì lúc kiểm thử trời không mưa (mới có unit test với mưa giả định). Luồng rain-only của `forecast_service` chỉ chạy trên DB thật, không có test tự động.

## Đợt 1: chế độ DEMO (04/11/2026)

*Lịch sử: toàn bộ Đợt 1 chạy trên MySQL và giao diện React/Vite; giữ nguyên làm hồ sơ.*

Môi trường: Windows 11, Python 3.13.16, MySQL 8.0.46, Node 24.21, Microsoft Edge (Playwright CLI 0.1.23). Ngày 04/11/2026.

## 1. Backend — pytest (`backend/tests`)

```
$ PYTHONUTF8=1 .venv/Scripts/python -m pytest -q
50 passed, 1 warning in 27.45s
```

Kiểm thử tích hợp chạy trên DB riêng `urban_flood_dss_test` (tạo mới mỗi lần: migrate → seed → 21 ngày dữ liệu mô phỏng
→ huấn luyện GRU 1 epoch → chu kỳ pipeline). Không mock MySQL.

| Nhóm | Test tiêu biểu |
|---|---|
| Auth | đăng nhập sai trả thông báo chung (chống dò user), logout vô hiệu token, mật khẩu lưu bcrypt, validate đăng ký |
| RBAC | khách 401, USER 403, OPERATOR được thống kê nhưng không được quản trị, ADMIN được quản trị |
| CRUD trạm | tạo/sửa/xoá mềm, trùng mã 409, ngoài TP.HCM 422, lỗi validate trả chi tiết từng trường |
| GIS | trạm tự gán **Quận 1** bằng `ST_Contains`; kiểm tra thứ tự trục lon/lat trong MySQL; GeoJSON 24 khu vực đúng lon/lat; identify điểm |
| Nhập dữ liệu | CSV: 2 chèn, 1 trùng, 1 từ chối; giá trị âm gắn `SUSPECT`; nhập lại không nhân bản |
| AI dự báo | 6 horizon, xác suất ∈ [0,1], mưa ≥ 0, cờ mô phỏng, cảnh báo "huấn luyện trên dữ liệu mô phỏng"; **cold-start** trạm mới |
| AI tiền xử lý (unit) | schema, missing được gắn cờ, kích thước cửa sổ, **không rò rỉ thời gian**, metrics MAE/RMSE/P/R/AUC |
| Rule engine (unit) | LOW/MEDIUM/HIGH, override camera, INSUFFICIENT_DATA (thiếu/cũ), **hysteresis**, giới hạn điểm, validate cấu hình |
| Cảnh báo | quy trình trạng thái hợp lệ/không hợp lệ, xác minh, lịch sử; **chống lặp** (chạy 2 lần không tạo thêm, 1 cảnh báo mở/khu vực) |
| Thống kê | tổng trạm và tổng mưa theo ngày **khớp truy vấn SQL trực tiếp** |
| Excel | đúng sheet, tiêu đề, **số dòng = COUNT SQL theo bộ lọc**, đúng trạm lọc, freeze/autofilter, định dạng ngày; **formula injection** bị vô hiệu; mã `007` giữ số 0 |
| Camera | upload phân tích, ảnh kết quả qua API có kiểm quyền, khách bị 403, file không phải ảnh/`.exe` bị 415 |
| Riêng tư | người dân không thấy `stream_url`, người phụ trách, giải thích nội bộ |
| DB | seed **idempotent**, ≥30 foreign key, 4 SPATIAL index, **rollback** khi vi phạm unique |
| Thời gian | endpoint dạng dict xuất ISO có `Z` |

Lint: `ruff check app` sạch (F, E9).

## 2. Frontend

```
npx tsc -b --noEmit        -> 0 lỗi
npx eslint src             -> 0 lỗi, 1 cảnh báo (react-refresh trong Layout.tsx)
npm test (vitest)          -> 10 passed (format/redirect an toàn, helpers analytics/ops)
npm run build              -> build thành công
```

## 3. E2E — Playwright CLI trên ứng dụng thật (backend :8000 + Vite :5173, Edge)

Ảnh chụp trong [docs/screenshots](screenshots/).

| # | Luồng | Kết quả | Bằng chứng |
|---|---|---|---|
| 1 | Truy cập trang chủ (khách) | ✅ bản đồ, 24 khu vực, trạm, nhãn DEMO | 01-map-public.png |
| 2 | Đăng nhập Admin | ✅ chuyển tới /dashboard | 04-dashboard-admin.png |
| 3 | Đăng nhập Operator | ✅ | 07-alerts-operator.png |
| 4 | Quyền User (citizen) | ✅ trang cán bộ hiển thị "không có quyền", menu cán bộ ẩn | — |
| 5–6 | Mở bản đồ, zoom/pan | ✅ (mousewheel, flyTo khi chọn kết quả tìm kiếm) | 02-search-station-detail.png |
| 7 | Bật/tắt lớp | ✅ tắt ranh giới + vùng nguy cơ, bật heatmap | 03-horizon3-layers.png |
| 8–9 | Chọn trạm, panel chi tiết | ✅ biểu đồ 48h + dự báo + ngưỡng, bảng 6h | 02-search-station-detail.png |
| 10 | Time slider | ✅ chọn +3h gọi `/gis/risk-layers?horizon=3`, `/gis/features?horizon=3` | log requests |
| 11–13 | Dashboard, đổi bộ lọc, biểu đồ | ✅ đổi 30 ngày → gọi lại `/statistics/overview` với khoảng mới | 05-dashboard-charts.png |
| 14–15 | Danh sách cảnh báo, Operator xử lý | ✅ Mới → Đã tiếp nhận → Đang xử lý (có hộp xác nhận) → xác minh; lịch sử ghi đủ | 08-alert-processing.png |
| 16 | Tạo/sửa trạm | ✅ validate 4 lỗi tiếng Việt; tạo E2E01 tự gán Quận 1; sửa ngưỡng 60→45 | 09-station-created.png |
| 17 | Xem dự báo | ✅ trang Dự báo AI hiển thị mô hình, chỉ số, cảnh báo mô phỏng, biểu đồ 6h | 20-forecasts.png |
| 18 | Phân tích camera bằng fixture | ✅ YOLOv8-seg: tỉ lệ ngập 53%, độ tin cậy 96%, ảnh vào/ra | 10-camera-yolo.png |
| 19–20 | Xuất Excel + kiểm file | ✅ `bao_cao_rainfall_*.xlsx`: 2.661 dòng = COUNT SQL cùng khoảng; header, freeze A10, AutoFilter, định dạng dd/mm/yyyy hh:mm | openpyxl |
| 21 | Mobile 390×844 | ✅ panel thu gọn, bottom sheet chi tiết khu vực | 11/12/13-mobile-*.png |
| 22 | Console errors | ✅ 0 lỗi trên mọi trang đã mở (sau khi thêm `/auth/session`) | console |
| 23 | Lỗi API | ✅ validate 422 hiển thị theo trường; lỗi định tuyến/ngoài vùng trả thông báo rõ | — |
| 24 | Truy cập trái phép | ✅ khách → `/login?next=…`; citizen gọi API quản trị/thống kê/tạo trạm: 403/403/403 | — |
| 25 | Refresh giữ trạng thái | ✅ reload /dashboard vẫn đăng nhập (cookie httpOnly) | — |

Định tuyến tránh ngập (API thật OSRM): 2 tuyến, mỗi tuyến liệt kê khu vực đi qua (`ST_Intersects`) và điểm phơi nhiễm.

Kịch bản sinh cảnh báo cho E2E: tạo quy tắc v2 ngưỡng thấp (kiểm thử version hoá quy tắc) → 13 cảnh báo → xử lý → kích
hoạt lại v1.

## 4. Lỗi phát hiện & đã sửa trong vòng kiểm thử

| Lỗi | Nguyên nhân gốc | Sửa |
|---|---|---|
| Bootstrap lỗi `rowcount` | SQLAlchemy 2.1 coi `insert(Model)` là ORM bulk | `insert(Model.__table__)` |
| GeoJSON trả chuỗi | `column_expression` bọc ST_AsGeoJSON làm mất result processor | kiểu kết quả `_GeoJSON` |
| Test nhập CSV không thấy bản ghi | session REPEATABLE READ giữ snapshot cũ | kết thúc transaction trước truy vấn (lỗi test) |
| Giờ hiển thị lệch 7h ở panel bản đồ | endpoint dạng dict xuất datetime thiếu `Z` | encoder datetime toàn cục + test |
| 401 trong console khi khách mở trang | `/auth/me` trả 401 cho khách | `/auth/session` trả `null` |
| Danh sách khu vực xếp "Không đủ dữ liệu" lên đầu | sắp xếp theo điểm | sắp theo mức rủi ro rồi điểm |
| Nút lớp bản đồ bị che / menu xuống dòng / panel che bản đồ trên mobile | bố cục | đổi vị trí, nowrap, thu gọn mặc định trên mobile |
| (Security review) open redirect, lộ `stream_url`/người phụ trách, SSE nội bộ gửi cho khách | thiếu lọc theo vai trò | `safeNext`, ẩn trường theo `is_staff`, lọc kênh SSE + test |
| Ghi file UTF-8 lỗi trên Windows | mặc định cp1252 | `encoding="utf-8"` |

## 5. Chưa kiểm chứng

- `docker compose up` (máy không có Docker).
- Bộ test Playwright tự động chạy CI (E2E thực hiện tương tác qua CLI).
- Độ chính xác AI với dữ liệu quan trắc/camera thật.
