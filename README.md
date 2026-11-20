# OctotusMap

Hệ thống hỗ trợ ra quyết định cảnh báo sớm ngập úng đô thị TP.HCM.

Đồ án chuyên ngành — Tin học Tài nguyên và Môi trường, Trường ĐH Tài nguyên và Môi trường TP.HCM
Sinh viên: **Nguyễn Quốc Tú** (MSSV 1250080219) · GVHD: **ThS. Hà Châu Hoàng**

Web application dự báo mưa và xác suất ngập **1–6 giờ tới** bằng LSTM/GRU, phát hiện vùng ngập từ ảnh camera bằng
YOLOv8-seg, hệ luật phân loại rủi ro LOW/MEDIUM/HIGH, bản đồ GIS kiểu Google Maps, dashboard, thống kê và xuất Excel.

> **Dữ liệu**: từ 11/2026 hệ thống chạy trên dữ liệu thật từ **Open-Meteo** (mưa giờ tái phân tích + dự báo số,
> mực nước biển Vũng Tàu, độ cao DEM 90 m), **31 điểm ngập** do Phòng CSGT TP.HCM công bố (qua báo Tiền Phong, 06/10/2026)
> và **báo cáo ngập của người dùng**. Open-Meteo là dữ liệu mô hình trên lưới, không phải trạm đo tại chỗ.
> **Trạng thái ngập là ƯỚC TÍNH**, chưa được hiệu chỉnh với số liệu ngập thật. YOLOv8-seg được huấn luyện lại trên ảnh thật (Kaggle "Flood Area Segmentation", CC0, 290 ảnh; mask mAP50 0,450 trên 44 ảnh test) và áp dụng cho ảnh cán bộ tải lên;
> quét camera giao thông tự động (`CAMERA_SCAN_ENABLED`) đã cài nhưng đang tắt; bản đồ xem được ảnh camera giao thông công khai của thành phố. Đặt `DEMO_MODE=true` để quay lại chế độ mô phỏng. Xem [docs/known-limitations.md](docs/known-limitations.md).

## Công nghệ

| Lớp | Công nghệ |
|---|---|
| Backend | Python 3.13, FastAPI (MVC + Service + Repository), SQLAlchemy 2.1, Alembic, Pydantic 2 |
| CSDL | PostgreSQL 16 + PostGIS 3.4 (`geometry(POINT|MULTIPOLYGON,4326)`, GiST index) |
| AI | TensorFlow 2.21 / Keras 3 (LSTM, GRU), Ultralytics YOLOv8n-seg (PyTorch CPU), scikit-learn, OpenCV |
| Giao diện | Streamlit + Plotly + Folium (`streamlit_app/`, REST client của API FastAPI) |
| Báo cáo | OpenPyXL (Excel), CSV UTF-8 BOM |
| Bản đồ | OpenFreeMap (vector tiles OSM), ranh giới geoBoundaries (CC BY 3.0 IGO), Photon (geocode), OSRM (chỉ đường) |
| Thời gian thực | Server-Sent Events + scheduler asyncio trong tiến trình |

## Chạy nhanh trên Windows (không Docker)

Yêu cầu: Python 3.11–3.13, Node.js 20+ (chỉ để chạy `scripts/dev.mjs`), PostgreSQL 16 + PostGIS 3.4 (extension `postgis`, `citext`, `unaccent`).
Bản cài portable trên máy phát triển nằm ở `E:\pgsql`; khởi động bằng
`E:\pgsql\bin\pg_ctl -D E:\pgsql\data -l E:\pgsql\server.log -w start`.

```powershell
# 1) cấu hình
copy backend\.env.example backend\.env
#    mở backend\.env, điền POSTGRES_PASSWORD (tài khoản có quyền CREATE DATABASE)

# 2) môi trường Python
cd backend
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# 3) khởi tạo: tạo DB, migrate, seed, tải 2 năm dữ liệu Open-Meteo, huấn luyện LSTM/GRU, chu kỳ đầu
$env:PYTHONUTF8="1"; .venv\Scripts\python scripts\bootstrap.py      # ~10 phút lần đầu (CPU)

# 4) chạy API
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 5) chạy giao diện Streamlit (cửa sổ khác)
cd ..\streamlit_app; ..\backend\.venv\Scripts\python -m streamlit run app.py --server.port 5173
```

Từ lần sau, chỉ cần một lệnh ở thư mục gốc: `npm run dev`. Lệnh này tự bật PostgreSQL nếu đang tắt (mặc định `E:\pgsql`, đổi bằng biến `PG_HOME`), chạy API và giao diện, rồi mở trình duyệt ở http://localhost:5173 (`NO_BROWSER=1` để không mở).


| Thành phần | URL |
|---|---|
| Giao diện (Streamlit) | http://localhost:5173 (`npm run dev`), http://localhost:8501 (Docker) |
| API docs (OpenAPI/Swagger) | http://127.0.0.1:8000/docs |
| Health check | http://127.0.0.1:8000/health |

### Tài khoản ban đầu

`bootstrap.py` tạo `admin` (ADMIN), và khi `DEMO_MODE=true` thêm `operator` (OPERATOR) và `citizen` (USER).
Mật khẩu lấy từ `ADMIN_PASSWORD`, `OPERATOR_PASSWORD`, `DEMO_USER_PASSWORD` trong `backend/.env`; nếu để trống,
script **sinh ngẫu nhiên** (≥16 ký tự), ghi vào `.env` (đã gitignore) và in ra **một lần**. Không có mật khẩu mặc định.

### Đổi mật khẩu trực tiếp trong database

```powershell
cd backend; .venv\Scripts\python scripts\set_password.py --username admin --password <mật khẩu>
```
Script này cố ý bỏ qua chính sách mật khẩu mạnh: **chỉ dùng trên máy cá nhân**, hãy đặt mật khẩu mạnh trước khi đưa hệ thống lên mạng.
Nếu cài mới từ DB trống, `ADMIN_PASSWORD` trong `.env` phải ≥10 ký tự có chữ và số.

## Nạp phường và camera

`bootstrap.py` chỉ chạy các bước này khi DB chưa có dữ liệu mưa. Với DB đang chạy, gọi trực tiếp (chạy lại an toàn):

```powershell
cd backend; .venv\Scripts\python scripts\import_wards.py
.venv\Scripts\python scripts\import_traffic_cameras.py
```
Có GeoJSON phường mới: vào Cấu hình → Vận hành → Import, chọn cấp WARD; phường tự gắn vào quận chứa tâm phường.

## Docker

```bash
cp .env.example .env    # điền POSTGRES_PASSWORD, JWT_SECRET
docker compose up --build -d
```
Compose chạy `postgis/postgis:16-3.4`, backend và dịch vụ `streamlit` (http://localhost:8501, `API_BASE=http://backend:8000/api/v1`).
*Chưa chạy thử trên máy phát triển (không cài Docker) — xem known-limitations.*

## Kiểm thử

```powershell
cd backend;  $env:PYTHONUTF8="1"; .venv\Scripts\python -m pytest -q     # unit + tích hợp PostgreSQL, DB riêng urban_flood_dss_test)
backend\.venv\Scripts\python -m pytest -q streamlit_app\tests           # giao diện Streamlit (AppTest)
```
Hiện tại: backend 123 passed, `streamlit_app/tests` 78 passed. Kết quả chi tiết: [docs/testing-report.md](docs/testing-report.md).
Bộ sưu tập Postman: `docs/postman/OctotusMap.postman_collection.json` (sinh bằng `backend/scripts/export_postman.py`); notebook trong `notebooks/`.

## Cấu trúc

```text
backend/
  app/core/          cấu hình, DB, spatial type, bảo mật (bcrypt/JWT), RBAC deps, lỗi chuẩn
  app/models/        SQLAlchemy entities (Model)
  app/schemas/       Pydantic request/response (View)
  app/controllers/   FastAPI routers /api/v1 (Controller)
  app/services/      nghiệp vụ: rule engine, cảnh báo, thống kê, Excel, GIS, định tuyến, camera…
  app/repositories/  truy vấn dùng chung
  app/ai/            forecasting (LSTM/GRU), computer_vision (YOLOv8-seg), evaluation
  app/jobs/          pipeline gần thời gian thực, bộ mô phỏng DEMO, backfill
  app/gis/           import GeoJSON → PostGIS, danh mục DEMO
  migrations/        Alembic
  scripts/bootstrap.py
  tests/             unit + integration
streamlit_app/       giao diện Streamlit: app.py, nav.py, api.py, views/, tests/
notebooks/           3 notebook đã chạy (dự báo mưa, YOLOv8 ngập, đánh giá cảnh báo)
datasets/gis/        hcm_districts_2020.geojson (geoBoundaries)
docs/                kiến trúc, CSDL, API, AI, kiểm thử, hạn chế, audit công cụ, ảnh chụp
```

## Tài liệu

[Chức năng, cách dùng, thuật toán](docs/huong-dan-chuc-nang.md) · [Kiến trúc](docs/architecture.md) · [CSDL/ERD](docs/database-design.md) · [API](docs/api-design.md) ·
[Phương pháp AI](docs/ai-methodology.md) · [Kiểm thử](docs/testing-report.md) · [Hạn chế](docs/known-limitations.md) ·
[Ma trận yêu cầu](docs/requirements-matrix.md) · [Tiến độ](docs/progress.md) · [Audit công cụ](docs/tool-audit.md)

## Nguồn dữ liệu & bản quyền

- Ranh giới quận/huyện: geoBoundaries gbOpen VNM ADM2 (OCHA ROAP, Government of Viet Nam), CC BY 3.0 IGO —
  ranh giới **năm 2020**, trước sắp xếp đơn vị hành chính 2021/2025. Có thể import ranh giới mới qua Cấu hình → Vận hành.
- Bản đồ nền: © OpenStreetMap contributors, OpenFreeMap / OpenMapTiles.
- Mưa, triều, độ cao: Open-Meteo (CC BY 4.0).
- Ảnh huấn luyện YOLOv8-seg: Kaggle "Flood Area Segmentation" (faizalkarim, CC0).
- Điểm ngập lịch sử: `datasets/gis/flood_events.csv`, mỗi dòng có URL bài báo gốc (nguồn `PRESS_VN`).
- Ranh giới phường: GADM 4.1, cấu trúc quận → phường trước 07/2025 (học thuật/phi thương mại, không phân phối lại; file không commit).
- Camera: Cổng thông tin giao thông TP.HCM (danh sách là snapshot `datasets/gis/traffic_cameras.csv`).
- Điểm ngập: Phòng CSGT TP.HCM qua báo Tiền Phong (toạ độ geocode gần đúng).
- Geocoding: Photon/komoot, dữ liệu OSM (giới hạn 1 request/giây, có cache). Định tuyến: OSRM demo server — chỉ phục vụ demo.
