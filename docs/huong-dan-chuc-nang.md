# OctotusMap: chức năng, cách sử dụng, thuật toán và cơ chế

Tài liệu mô tả hệ thống đúng theo code tại ngày 09/11/2026. Mọi hằng số dưới đây có thể tra trong file được ghi kèm.

Giao diện là ứng dụng **Streamlit** (cổng 8501) gọi REST API của backend (cổng 8000); các mục "trang `/…`" dưới đây là tên trang trong thanh điều hướng bên trái. Một số thao tác của bản React cũ chưa có trong Streamlit (xem [mục 7](#7-hạn-chế-cần-biết)).

Hệ thống chạy trên dữ liệu thật ở chế độ LIVE (`DEMO_MODE=false`). Mọi kết quả về ngập, gồm xác suất và độ sâu, đều là **ước tính** và chỉ để tham khảo.

**Mục lục**

1. [Hệ thống hoạt động thế nào](#1-hệ-thống-hoạt-động-thế-nào)
2. [Vai trò và quyền](#2-vai-trò-và-quyền)
3. [Hướng dẫn sử dụng từng chức năng](#3-hướng-dẫn-sử-dụng-từng-chức-năng)
4. [Thuật toán](#4-thuật-toán)
5. [Cơ chế hệ thống](#5-cơ-chế-hệ-thống)
6. [Vận hành](#6-vận-hành)
7. [Hạn chế cần biết](#7-hạn-chế-cần-biết)

---

## 1. Hệ thống hoạt động thế nào

Cứ 5 phút (`SCHEDULER_INTERVAL_SECONDS=300`), một chu kỳ xử lý chạy trong tiến trình backend (`jobs/pipeline.py::run_cycle`):

```text
Open-Meteo: mưa giờ + mực nước biển Vũng Tàu
        │  lưu vào rainfall_observations, water_level_observations
        ▼
Hết hạn báo cáo ngập quá 3 giờ
        ▼
GRU dự báo mưa 6 giờ tới cho 24 điểm lưới  ──► forecasts
        ▼
Đánh giá 346 khu vực × 7 mốc (0 đến +6 giờ) ──► flood_risk_snapshots
   phường trước, quận lấy theo phường xấu nhất
        ▼
Sinh hoặc cập nhật cảnh báo cấp quận ──► alerts, notifications
        ▼
Đẩy sự kiện qua SSE (backend); giao diện Streamlit hỏi lại mỗi 60 giây
```

Dữ liệu đầu vào:

| Dữ liệu | Nguồn | Ghi chú |
|---|---|---|
| Mưa theo giờ | Open-Meteo, 24 điểm lưới tại tâm quận/huyện | Dữ liệu mô hình trên lưới, không phải trạm đo tại chỗ |
| Mực nước biển | Open-Meteo Marine, cửa biển Vũng Tàu | Dùng làm đại diện triều |
| Độ cao | Open-Meteo Elevation (DEM 90 m) | Mỗi phường là một mẫu tại tâm phường |
| Điểm ngập thường xuyên | Phòng CSGT TP.HCM qua báo Tiền Phong | 31 điểm, toạ độ geocode gần đúng |
| Lịch sử ngập | Báo chí (`datasets/gis/flood_events.csv`) | Mỗi dòng có URL bài gốc |
| Báo cáo ngập | Người dùng gửi trên bản đồ | Có hiệu lực 3 giờ |
| Ranh giới | geoBoundaries (24 quận/huyện), GADM (322 phường/xã) | Cấu trúc trước 07/2025 |
| Camera giao thông | Cổng giao thông TP.HCM | Snapshot 796 camera, chỉ xem ảnh |

---

## 2. Vai trò và quyền

Quyền được kiểm tra ở backend (`core/deps.py`), giao diện chỉ ẩn bớt nút.

| Chức năng | Khách | Người dân (USER) | Cán bộ (OPERATOR) | Quản trị (ADMIN) |
|---|:-:|:-:|:-:|:-:|
| Bản đồ, tìm kiếm, chỉ đường | ✓ | ✓ | ✓ | ✓ |
| Xem cảnh báo công khai đang mở | ✓ | ✓ | ✓ | ✓ |
| Dự báo, lịch sử ngập (xem) | ✓ | ✓ | ✓ | ✓ |
| Gửi và xác nhận báo cáo ngập | | ✓ | ✓ | ✓ |
| Nhận thông báo cảnh báo trong web | | | ✓ | ✓ |
| Từ chối báo cáo ngập | | | ✓ | ✓ |
| Tổng quan, Thống kê, xuất Excel/CSV | | | ✓ | ✓ |
| Trạm quan trắc, Camera (quản lý) | | | ✓ | ✓ |
| Xử lý cảnh báo, xem cảnh báo đã đóng | | | ✓ | ✓ |
| Thêm/xoá sự kiện ngập lịch sử | | | ✓ | ✓ |
| Mô hình AI, Tài khoản, Cấu hình | | | | ✓ |
| Mô phỏng ngập | | | | ✓ |

Người dân và khách **không** thấy: người phụ trách, trạng thái và các mốc xử lý cảnh báo, kết quả xác minh, phần giải thích điểm số của cảnh báo, `stream_url` của camera, các sự kiện SSE nội bộ. Họ vẫn thấy lý do ngập, độ sâu ước tính và danh sách phường.

---

## 3. Hướng dẫn sử dụng từng chức năng

### 3.1 Đăng nhập và tài khoản

- **Đăng ký:** tên đăng nhập 3–50 ký tự (chữ, số, `_`, `.`), mật khẩu tối thiểu 10 ký tự. Tài khoản mới có vai trò USER.
- **Đăng nhập:** token lưu trong phiên Streamlit (`st.session_state`), hết hạn sau 480 phút; tải lại trang thì phải đăng nhập lại. Giới hạn 10 lần thử mỗi phút.
- **Đổi mật khẩu:** cần nhập đúng mật khẩu hiện tại.

### 3.2 Bản đồ (trang chủ `/`)

**Đọc bản đồ**

- Phường được tô theo mức rủi ro: **Thấp** xanh rất nhạt, **Trung bình** và **Cao** đậm hơn; quận chỉ có đường viền. Phường và viền quận luôn cùng hiện (không đổi theo mức zoom).
- Số cảnh báo đang mở hiện ở bảng "Tình hiện tại"; bản Streamlit không vẽ ký hiệu `◆`/`▲` trên bản đồ.
- Ô chọn **thời điểm** (Nay, +1h … +6h) đổi bản đồ sang mốc đó.
- Danh sách **"Tình hình hiện tại"** xếp quận theo mức rủi ro; mở rộng dòng quận để xem từng phường.
- Các công tắc lớp: Nguy cơ ngập, Mưa, Điểm ngập thường xuyên, Báo cáo ngập, Camera, Ranh giới. Chú thích lớp nằm dưới bản đồ.

**Xem chi tiết một vị trí:** bấm vào bản đồ. Cột bên phải (mục "Chi tiết") hiện phường, mức rủi ro, câu lý do (ví dụ *"Ngập do triều, khoảng 40 cm (ước tính)"*), xác suất, lượng mưa, mức rủi ro 7 mốc, khuyến nghị và số trận ngập trong bán kính 1,5 km.

**Tìm kiếm:** gõ tên đường, quận, trạm, điểm ngập, hoặc toạ độ dạng `10.77, 106.70` rồi nhấn Enter; chọn một kết quả trong danh sách và bấm "Chọn".

**Chỉ đường**

1. Mở mục "Chỉ đường" ở cột bên phải.
2. Chọn điểm đi và điểm đến bằng ô tìm kiếm hoặc bấm lên bản đồ (chưa kéo thả được điểm, chưa có "Vị trí của tôi"); có nút đổi chiều và xoá.
3. Chọn thời điểm khởi hành: Bây giờ hoặc sau 1–6 giờ.
4. So sánh tối đa 3 tuyến. Mỗi tuyến ghi thời gian, quãng đường và số km có thể ngập. Tuyến đề xuất được đánh dấu.
5. Mục "Đoạn cần chú ý" liệt kê đoạn nguy hiểm và lý do; xem lý do từng đoạn.

| Nét đường | Ý nghĩa |
|---|---|
| Xanh liền | Không có dấu hiệu ngập |
| Cam đứt | Có nguy cơ ngập |
| Đỏ đứt | Có thể đang ngập |
| Tím đứt | Người dân báo ngập |

**Báo ngập:** đăng nhập, bấm vào vị trí, mở mục "Báo cáo ngập", chọn mức (mắt cá, đầu gối, sâu) và gửi. Người khác có thể bấm xác nhận. Cán bộ có thể từ chối báo cáo sai. Xem cơ chế ở [mục 4.8](#48-báo-cáo-ngập-của-người-dân).

**Mô phỏng ngập (admin):** mở mục "Mô phỏng", bấm bản đồ chọn tâm, đặt bán kính 100–2000 m và độ sâu 1–300 cm, rồi "Tạo vùng ngập". Chỉ tuyến của tài khoản admin bị ảnh hưởng; đoạn đi qua vùng này hiện nét đỏ, lý do ghi "MÔ PHỎNG: ngập X cm". Dữ liệu mô phỏng không ghi vào quan trắc, cảnh báo hay thống kê.

### 3.3 Cảnh báo (`/alerts`)

- Lọc theo mức, khu vực, ngày; sắp xếp theo thời gian hoặc mức.
- Mỗi cảnh báo ghi lý do, độ sâu ước tính và các phường bị ảnh hưởng. Chi tiết hiện ngay dưới danh sách.
- Người dân chỉ thấy cảnh báo công khai đang mở.

**Quy trình của cán bộ:**

```text
NEW ──► ACKNOWLEDGED ──► IN_PROGRESS ──► RESOLVED ──► CLOSED
 └──────────────┴───────────────┴──────────────────────▲
                        RESOLVED có thể quay lại IN_PROGRESS
```

Trong chi tiết cảnh báo, cán bộ có thể: tiếp nhận, đổi trạng thái (có bước xác nhận), phân công cán bộ, thêm ghi chú, ghi kết quả xác minh thực địa (`CONFIRMED`, `FALSE_ALARM`, `UNVERIFIED`). Mọi thao tác được lưu vào lịch sử cảnh báo. Có thể xuất danh sách ra Excel (bấm "Chuẩn bị" rồi bấm nút tải).

### 3.4 Dự báo AI (`/forecasts`)

- Thông tin mô hình đang dùng và chỉ số đánh giá.
- Chọn trạm để xem biểu đồ mưa và xác suất ngập 6 giờ tới.
- Bảng theo trạm: mỗi ô là lượng mưa (mm) và xác suất ngập ở từng mốc +1h…+6h.
- Bảng xếp hạng khu vực theo mức nguy cơ, có cột **Lý do**.

### 3.5 Lịch sử ngập (`/history`)

- Lọc theo địa điểm, mô tả, khu vực, ngày, độ sâu tối thiểu. Sắp xếp bằng ô "Sắp xếp theo" và hướng.
- Cán bộ thấy thêm biểu đồ số trận theo tháng, thêm được sự kiện mới và xoá sự kiện.
- **Thêm sự kiện:** nhập địa điểm, vĩ độ, kinh độ trong TP.HCM, thời gian theo giờ Việt Nam, độ sâu, nguyên nhân (mưa, triều cường, kết hợp, khác) và mô tả.

### 3.6 Tổng quan (`/dashboard`, cán bộ)

Các thẻ KPI (trạm, khu vực theo mức, cảnh báo đang mở, mưa, mực nước, tỉ lệ dữ liệu hợp lệ) cùng biểu đồ mưa, mực nước, dự báo, cảnh báo và xu hướng nguy cơ. Bộ lọc ở đầu trang.

"Khu vực nguy cơ … hiện tại" chỉ tính mốc hiện tại, còn "Cảnh báo đang mở" gồm cả cảnh báo cho 6 giờ tới, nên hai số có thể khác nhau.

### 3.7 Thống kê (`/statistics`, cán bộ)

Các tab (xuất tệp cần hai lần bấm: chuẩn bị rồi tải): Lượng mưa, Mực nước, Nguy cơ ngập, Lịch sử cảnh báo, Sự kiện ngập lịch sử, Hiệu quả dự báo, Trạm quan trắc, Dữ liệu thiếu/lỗi, Hoạt động xử lý cảnh báo (tab Camera chỉ hiện khi bật camera).

- Bộ lọc: khoảng thời gian (mặc định 7 ngày, tối đa 3700 ngày), khu vực, trạm, mức, loại dữ liệu; nhóm theo giờ, ngày, tháng, năm.
- Xuất **Excel** theo 9 loại báo cáo (tổng hợp, mưa, mực nước, dự báo, cảnh báo, lịch sử, trạm, camera, mô hình), hoặc **CSV** mưa và mực nước.

### 3.8 Trạm quan trắc (`/stations`, cán bộ)

- Danh sách trạm, lọc theo trạng thái kết nối. **ONLINE** khi bản ghi mới nhất không cũ quá 2 lần chu kỳ đo + 15 phút.
- Thêm, sửa, xoá mềm trạm. Mỗi trạm có lịch sử quan trắc, biểu đồ, thống kê chất lượng.
- **Nhập dữ liệu:** tệp `.csv` hoặc `.xlsx`, tối đa 50.000 dòng, các cột:

| Cột | Bắt buộc | Ghi chú |
|---|---|---|
| `station_code` | Khi nhập nhiều trạm | Không cần nếu nhập trong trang của một trạm |
| `observed_at` | Có | Không có múi giờ thì hiểu là giờ Việt Nam |
| `rainfall_mm` | Một trong hai | |
| `water_level_cm` hoặc `water_level_m` | Một trong hai | Đơn vị mét được đổi sang cm |

Kết quả nhập báo số dòng thêm mới, số dòng trùng, và lý do từng dòng lỗi.

### 3.9 Camera (`/cameras`, cán bộ)

Bản đồ có thể xem ảnh camera giao thông công khai (proxy qua backend, cache 30 giây); YOLO không chạy trên ảnh này.

**Đưa ảnh vào cảnh báo:** cán bộ tạo một camera tại điểm cần theo dõi, chọn "Phân tích ảnh", chọn camera đó và tải ảnh lên (`.jpg`, `.jpeg`, `.png`). Nếu YOLOv8 thấy từ 40% vùng quan sát bị ngập, **chỉ phường chứa camera** lên mức Cao trong 90 phút (mốc hiện tại và +1h), với lý do "Camera phát hiện ngập (mô hình thử nghiệm, tham khảo)". Ảnh không gắn camera chỉ để xem thử. Mô hình được huấn luyện trên ảnh mô phỏng, nên cần xác minh trước khi tin.

### 3.10 Mô hình AI (`/models`, admin)

Xem các phiên bản mô hình, chỉ số, kích hoạt phiên bản khác, huấn luyện lại, xem lịch sử huấn luyện.

### 3.11 Tài khoản (`/users`, admin)

Tạo, sửa, khoá tài khoản; gán vai trò ADMIN, OPERATOR, USER.

### 3.12 Cấu hình (`/settings`, admin)

| Tab | Nội dung |
|---|---|
| Quy tắc cảnh báo | Xem các phiên bản; sửa trọng số và ngưỡng rồi lưu thành **phiên bản mới**, có hiệu lực ngay. Có thể kích hoạt lại bản cũ |
| Cấu hình hệ thống | Các tham số dạng khoá–giá trị |
| Nhật ký | Audit log các thao tác quan trọng |
| Nguồn dữ liệu | Danh sách nguồn và giấy phép |
| Vận hành | Chạy chu kỳ xử lý ngay; nhập ranh giới hành chính GeoJSON |

---

## 4. Thuật toán

### 4.1 Thu thập và kiểm tra dữ liệu

File: `services/openmeteo_service.py`, `services/observation_service.py`.

- Mỗi chu kỳ lấy lại 3 ngày gần nhất và chèn với `INSERT IGNORE`, nên chạy lại không tạo trùng.
- Giờ đã qua được lưu làm quan trắc. Các giờ tới của triều giữ trong bộ nhớ để làm dự báo triều.
- Gắn cờ `SUSPECT` (không dùng làm giá trị) khi: mưa < 0 hoặc > 200 mm/h; mực nước ngoài [−300, 600] cm; hoặc mực nước đổi quá 150 cm/giờ.
- Khi nhập tệp: dòng có thời gian ở tương lai hơn 1 giờ hoặc thiếu cả hai giá trị đo bị từ chối kèm lý do, không nội suy âm thầm.

### 4.2 Dự báo mưa bằng LSTM/GRU

File: `ai/forecasting/`.

| Thành phần | Giá trị |
|---|---|
| Đầu vào | 24 giờ gần nhất, 5 đặc trưng: `log1p(mưa)`, mực nước tương đối, sin và cos của giờ, cờ thiếu dữ liệu |
| Mạng | 2 lớp LSTM hoặc GRU (48 rồi 24 đơn vị, dropout 0,1), Dense 64 |
| Đầu ra | 6 giá trị mưa cho +1h…+6h, kích hoạt softplus. Ở LIVE chỉ dự báo mưa |
| Hàm mất mát, tối ưu | MSE trên `log1p(mưa)`, Adam 0,001, dừng sớm sau 3 epoch không cải thiện |
| Chia dữ liệu | 70/15/15 theo thời gian, chuẩn hoá chỉ học từ tập train |
| Chọn mô hình | Bản có `val_loss` nhỏ nhất được kích hoạt |
| So sánh | Baseline persistence và khí hậu |

**Thiếu dữ liệu:** thời điểm thiếu được đánh dấu bằng cờ `missing`. Cold-start ưu tiên trạm cùng cụm (CORE, INNER, SUBURBAN), sau đó tới trạm gần nhất. Trạm thiếu quá 50% lấy chuỗi của trạm lân cận trong 15 km và ghi chất lượng `POOR` (cold-start).

Kết quả đo được ở [ai-methodology.md](ai-methodology.md): MAE khoảng 0,37 mm, tốt hơn baseline, nhưng **yếu với mưa to** (F1 khoảng 6%).

### 4.3 Xác suất ngập ước tính

File: `services/flood_index.py`. Chưa có nhãn ngập thật nên không học được; đây là công thức logistic với hệ số chọn định tính:

```text
z = −5 + 0,22·mưa_1h + 0,07·mưa_3h
    + 1,5·min(max(r, 0), 1,5)·k          (k = 1 nếu độ cao < 8 m, ngược lại 0,3)
    + 0,35·min(max(4 − độ_cao, −6), 4)
    + 1,2 nếu gần điểm ngập
    + 0,8 nếu là điểm ngập nặng

xác suất = 1 / (1 + e^(−z))
```

**Ví dụ:** mưa 15 mm/h, 35 mm/3h, r = 0,5, độ cao 3 m, có điểm ngập: z = 3,05, xác suất khoảng 95,5%.

`r` là tỉ lệ triều, xem mục tiếp theo. Điểm ngập nặng là điểm nằm trong 500 m của một trận ngập lịch sử sâu từ 30 cm.

### 4.4 Triều: độ trễ và phạm vi ảnh hưởng

```text
r = (mực nước − P50) / (P95 − P50)
```

P50 và P95 là trung vị và phân vị 95 của mực nước biển trong 1 năm gần nhất (hiện khoảng 100 và 196 cm). r = 1 tương ứng mức triều cao thường gặp.

**Độ trễ 4 giờ** (`TIDE_LAG_H`): ngập đường phố TP.HCM xảy ra muộn hơn đỉnh triều Vũng Tàu. Ngày 27/10/2026, Vũng Tàu đạt đỉnh lúc 14:00, còn đường phố ngập từ 16:30 đến khoảng 19:00. Con số 4 giờ rút ra từ 7 mốc báo chí (khoảng hợp lý 3–5 giờ). Khi cần triều tại thời điểm t, hệ thống lấy giá trị Vũng Tàu tại t − 4 giờ.

**Phường bị triều** (`tide_exposed_wards`, hiện 64 phường): độ cao dưới 8 m và thuộc Quận 7, Nhà Bè, Cần Giờ, Quận 8, Quận 4, Quận 2, Bình Thạnh, Thủ Đức; cộng các phường có điểm ngập do triều cường. Phường ngoài danh sách này có tỉ lệ triều bằng 0.

### 4.5 Độ sâu và lý do ngập

| Nguồn | Công thức | Áp dụng cho |
|---|---|---|
| Triều | r ≥ 1,15 thì `min(60, 20 + 70·(r − 1,15))` cm, ngược lại 0 | Phường bị triều |
| Mưa | `min(40, 1,5·max(0, mưa_3h − 20))` cm | Phường dưới 8 m hoặc có điểm ngập |
| Báo cáo đã xác nhận | Mắt cá 10, đầu gối 40, sâu 70 cm | Phường có báo cáo, mốc 0 và +1h |

- Độ sâu của phường là giá trị lớn nhất trong 3 nguồn, làm tròn 10 cm. Dưới 5 cm thì không ghi con số.
- **Lý do:** `REPORT` (người dân báo), `RAIN_TIDE` (cả hai), `TIDE` (triều), `RAIN` (mưa).

**Kiểm tra với thực tế:** r = 1,417 (27/10/2026) cho khoảng 39 cm, báo chí ghi 20–50 cm. r = 1,19 (10/10/2026) cho khoảng 23 cm, báo chí ghi khoảng 50 cm. Công thức chỉ có 3 mốc độ sâu của 2 đợt triều; riêng mưa chưa có mốc kiểm chứng.

### 4.6 Phân loại mức rủi ro

File: `services/rule_engine.py` (hàm thuần, không phụ thuộc DB), `services/risk_service.py`.

**Bước 1: Tính điểm.** Mỗi đầu vào đưa về [0, 1], tổng có trọng số rồi chia cho tổng trọng số của đầu vào có dữ liệu:

| Thành phần | Trọng số | Cách chuẩn hoá |
|---|---|---|
| Xác suất ngập | 0,45 | Giữ nguyên |
| Mưa | 0,20 | mưa / 40 mm, cắt tại 1 |
| Mực nước | 0,20 | Trạm đo thật; nếu không có thì dùng tỉ lệ triều, cắt về [0, 1] |
| Camera | 0,10 | tỉ lệ ngập / 0,5, cắt tại 1 (mốc 0 và +1h) |
| Lịch sử | 0,05 | Độ nhạy ngập của khu vực |

**Bước 2: Kiểm tra dữ liệu.** Nếu tổng trọng số có dữ liệu dưới 0,5, hoặc dữ liệu cũ quá 180 phút, kết quả là "Không đủ dữ liệu".

**Bước 3: Xếp mức theo điểm.** Từ 0,6 là Cao, từ 0,35 là Trung bình, còn lại Thấp.

**Bước 4: Ép mức Cao** nếu có một trong các điều kiện:

- Xác suất ngập từ 80%
- Trạm đo thật báo mực nước đạt ngưỡng
- Camera thấy từ 40% vùng quan sát bị ngập
- Độ sâu ước tính từ 20 cm
- Báo cáo ngập đã có người xác nhận

Báo cáo chưa xác nhận chỉ nâng phường lên tối thiểu Trung bình.

**Bước 5: Chống dao động (hysteresis).** Khi không có điều kiện ép, mức chỉ hạ nếu điểm giảm dưới ngưỡng của mức trước trừ 0,05.

**Cấp phường và quận:** phường được tính trước. Quận lấy độ sâu, lý do và số xác nhận của phường xấu nhất, kèm danh sách phường có độ sâu (nhiều nhất 8 tên, sâu nhất trước). Báo cáo chưa xác nhận không được đẩy lên quận.

**Ví dụ:** phường Tân Phong (Q7) lúc r = 1,417: độ sâu 38,7 cm, từ 20 cm nên mức Cao, câu lý do là "Ngập do triều, khoảng 40 cm (ước tính)". Phường Bình Trưng Tây (cao 8 m) không thuộc diện bị triều, nên cùng mức triều vẫn là Thấp nếu không có mưa.

Quy tắc lưu theo phiên bản trong `alert_rules` và không sửa đè: mỗi lần lưu tạo phiên bản mới.

### 4.7 Sinh và cập nhật cảnh báo

File: `services/alert_service.py`.

- Chỉ tạo cảnh báo cấp quận, từ mức Trung bình trở lên, lấy mức xấu nhất trong 7 mốc (cùng mức thì lấy mốc sớm nhất).
- **Mỗi quận tối đa một cảnh báo mở.** Mức cao hơn thì nâng mức và báo lại. Cùng mức thì chỉ cập nhật nội dung, không báo lại. Mức thấp hơn thì giữ nguyên.
- **Chống lặp:** sau khi xử lý xong, cùng quận và cùng mức không tạo cảnh báo mới trong 60 phút.
- Cảnh báo không tự đóng ở LIVE; cán bộ phải xử lý.

### 4.8 Báo cáo ngập của người dân

File: `services/report_service.py`.

| Quy định | Giá trị |
|---|---|
| Hiệu lực | 3 giờ; mỗi lần xác nhận bảo đảm còn ít nhất 1 giờ |
| Giới hạn gửi | 5 báo cáo / 10 phút / tài khoản |
| Xác nhận | Người khác đã đăng nhập, mỗi người một lần, không tự xác nhận |
| Từ chối | Chỉ cán bộ |

### 4.9 Chỉ đường và đánh giá ngập từng đoạn

File: `services/routing_service.py`.

1. OSRM trả tối đa 3 tuyến, khoảng cách tối đa 80 km.
2. Chia mỗi tuyến thành các đoạn khoảng 200 m. Lấy độ cao tại điểm giữa đoạn.
3. Với mỗi đoạn, tính xác suất và độ sâu từ mưa của điểm lưới gần nhất, triều, độ cao, điểm ngập trong 150 m, báo cáo trong 100 m. Triều chỉ tính khi đoạn dưới 8 m và cách tâm một phường bị triều không quá 1,5 km.
4. Xếp trạng thái theo thứ tự ưu tiên:

| Trạng thái | Điều kiện |
|---|---|
| Người dân báo ngập | Có báo cáo còn hiệu lực trong 100 m |
| Có thể đang ngập | Độ sâu từ 20 cm, xác suất từ 60%, hoặc đi qua vùng mô phỏng |
| Có nguy cơ ngập | Có độ sâu ước tính, hoặc xác suất từ 30% |
| Không có dấu hiệu | Còn lại |

5. **Tuyến đề xuất:** ít km ngập nhất, rồi ít đoạn nguy cơ (quá 0,5 km), rồi nhanh nhất. Giới hạn 30 yêu cầu/phút/IP.

### 4.10 Nhận diện ngập qua camera

File: `ai/computer_vision/`.

- YOLOv8n-seg phân đoạn vùng nước (ảnh 320 px, ngưỡng tin cậy 0,25), tính tỉ lệ diện tích ngập trong vùng quan sát (mặc định 60% phía dưới ảnh).
- Không có trọng số mô hình thì dùng dự phòng theo ngưỡng màu HSV.
- Mô hình đang dùng (id 8) huấn luyện trên ảnh thật (Kaggle "Flood Area Segmentation", 290 ảnh); trên 44 ảnh test mask mAP50 0,4503, precision 0,572, recall 0,483. Vẫn chỉ là tham khảo vì không phải ảnh camera giao thông TP.HCM.
- Quét tự động camera giao thông (`CAMERA_SCAN_ENABLED`, 15 phút/lần, tối đa 20 camera, bán kính 500 m quanh điểm ngập, cần 2 lần phát hiện liên tiếp) đã cài nhưng đang **tắt**; ảnh và kết quả camera `TT-` chỉ cán bộ thấy.

### 4.11 Tính lại dữ liệu quá khứ

`jobs/backfill.py` chạy lại dự báo và đánh giá rủi ro cho từng giờ trong N ngày, chỉ dùng dữ liệu tới mốc đó. Ở LIVE dùng `alerts=False` để không dựng cảnh báo chưa từng phát. Đây là số **tính lại**, không phải bản đã phát hành khi đó.

---

## 5. Cơ chế hệ thống

| Cơ chế | Cách hoạt động |
|---|---|
| Kiến trúc | MVC: `models`, `schemas` (View), `controllers` (`/api/v1`), `services`, `repositories`. Giao diện Streamlit (`streamlit_app/`) gọi API qua `api.py`, gửi `X-Forwarded-For` để giới hạn tần suất theo IP người dùng |
| Lịch chạy | Scheduler asyncio trong tiến trình, một khoá đảm bảo mỗi lúc chỉ một chu kỳ chạy. Không dùng Redis/Celery, nên chỉ chạy một worker uvicorn |
| Cập nhật thời gian thực | SSE tại `/api/v1/events` (`services/events.py`). Sự kiện nội bộ chỉ gửi cho cán bộ. Streamlit không nhận SSE mà hỏi lại mỗi 60 giây (bản đồ, cảnh báo, dự báo, thông báo) |
| Xác thực | JWT (Bearer) giữ trong `st.session_state`; API vẫn nhận cookie HttpOnly; mật khẩu băm bcrypt |
| Phân quyền | `Operator`, `Admin`, `OptionalUser`, `is_staff` trong `core/deps.py` |
| Audit | Mọi thao tác ghi quan trọng gọi `audit()`, xem ở Cấu hình → Nhật ký |
| Thời gian | DB lưu UTC không múi giờ; API xuất ISO có `Z`; giao diện hiển thị giờ Việt Nam |
| Không gian | PostGIS `geometry(…,4326)`, thứ tự lon/lat, chỉ mục GiST; tìm kiếm không phân biệt hoa thường và dấu (`unaccent`) |
| Khu vực 2 cấp | 24 quận/huyện và 322 phường/xã. Cảnh báo và thống kê theo quận; phường dùng để hiển thị rủi ro |
| Dữ liệu mô phỏng | Luôn có `is_simulated=True` và nhãn "Mô phỏng" |
| Giải thích kết quả | Cột JSON `explanation` lưu đầu vào, điểm từng thành phần, điều kiện ép mức, `cause`, `depth_cm`, `wards` |

**Chế độ chạy:** `DEMO_MODE=true` dùng dữ liệu mô phỏng, `false` dùng Open-Meteo. `CAMERA_ENABLED` bật phân tích ảnh camera.

---

## 6. Vận hành

Chạy từ thư mục `backend`, đặt `PYTHONUTF8=1`, PostgreSQL phải đang chạy.

| Mục đích | Lệnh |
|---|---|
| Khởi tạo toàn bộ (idempotent) | `.venv\Scripts\python scripts\bootstrap.py` |
| Chạy API | `.venv\Scripts\python -m uvicorn app.main:app --port 8000` |
| Khởi động PostgreSQL (portable) | `E:/pgsql/bin/pg_ctl -D E:/pgsql/data -l E:/pgsql/server.log -w start` |
| Chạy cả API và giao diện | `npm run dev` ở thư mục gốc (cần cổng 8000 và 8501 còn trống) |
| Nạp phường | `.venv\Scripts\python scripts\import_wards.py` |
| Nạp camera | `.venv\Scripts\python scripts\import_traffic_cameras.py` |
| Nạp lịch sử ngập từ CSV | `.venv\Scripts\python scripts\import_flood_events.py` |
| Đổi mật khẩu | `.venv\Scripts\python scripts\set_password.py --username <tên> --password <mật khẩu>` |
| Huấn luyện dự báo | `.venv\Scripts\python -m app.ai.forecasting.train --epochs 8` |
| Đánh giá mức rủi ro (chỉ đọc) | `.venv\Scripts\python scripts\evaluate_risk.py` |
| Đo hiệu năng (chạy một server, tắt scheduler) | `.venv\Scripts\python scripts\benchmark.py --cycles 0` |
| Kiểm thử backend | `.venv\Scripts\python -m pytest -q` (DB riêng, không đụng dữ liệu thật) |
| Kiểm thử Streamlit | `backend/.venv/Scripts/python -m pytest -q streamlit_app/tests` (từ thư mục gốc) |
| Tinh chỉnh mô hình theo cụm | `python -m app.ai.forecasting.train --finetune-clusters --epochs 2` |
| Xuất Postman | `python scripts/export_postman.py` |

**Tính lại N ngày sau khi đổi logic** (nên dừng server trước):

```powershell
.venv\Scripts\python -c "from app.core.database import SessionLocal; from app.jobs.backfill import backfill; db=SessionLocal(); print(backfill(db, days=14, alerts=False, force=True))"
```

**Thêm một trận ngập thật:** thêm dòng vào `datasets/gis/flood_events.csv` với URL bài gốc đã đọc, chỉ ghi độ sâu khi bài nêu số, rồi chạy `import_flood_events.py`. Chạy lại không tạo trùng.

**Đổi thư mục dự án:** `model_versions.artifact_path` là đường dẫn tuyệt đối, phải cập nhật lại, nếu không mọi chu kỳ dự báo sẽ lỗi.

---

## 7. Hạn chế cần biết

- **Độ sâu chỉ là ước tính:** dựa trên 3 mốc của 2 đợt triều. Đợt 10/10/2026 bị ước thấp khoảng 27 cm. Không có dữ liệu ngày khô nên chưa biết tỉ lệ báo động giả.
- **Mưa cục bộ bị bỏ sót:** trận 04/11/2026 ngập trên 30 cm nhưng lưới Open-Meteo chỉ ghi tối đa 1,0 mm/h, nên hệ thống không báo được (0/7 sự kiện đối chiếu được). Báo cáo người dân là cách bù duy nhất.
- **Triều chỉ có một số đo** tại Vũng Tàu làm đại diện, không có mực nước cống/kênh của thành phố.
- **Độ cao kém phân biệt:** mỗi phường là một mẫu DEM 90 m tại tâm, nên phạm vi bị triều phải dựa thêm vào danh sách quận.
- **Mưa như nhau trong một quận:** các phường dùng chung điểm lưới của quận cha. Ở mốc hiện tại, độ sâu do mưa của phường chỉ lấy từ dự báo +1 giờ.
- **Dự báo mưa to rất yếu:** F1 khoảng 6% với mưa từ 5 mm/h. Thêm dữ liệu dự báo số GFS không cải thiện đáng kể.
- **Đánh giá trên sự kiện báo chí độc lập:** triều bắt được 16/19 quận–ngày, mưa 0/25, F1 toàn bộ 0,046 (chi tiết ở ai-methodology.md).
- **Dữ liệu cũ quá 3 giờ** làm kết quả về "Không đủ dữ liệu", kể cả khi có báo cáo đã xác nhận.
- **Ranh giới hành chính** theo cấu trúc trước 07/2025; khu vực Dĩ An nằm ngoài ranh giới quận hiện có.
- **Giao diện Streamlit chưa có:** kéo thả điểm A/B, "Vị trí của tôi", ký hiệu cảnh báo trên bản đồ, nền tối, liên kết sâu `?open=`, giữ đăng nhập sau khi tải lại trang; cập nhật bằng hỏi lại 60 giây thay cho SSE.
- **Dịch vụ công cộng:** OSRM và Photon không cam kết sẵn sàng; OSRM chỉ có profile ô tô.

Chi tiết thêm: [ai-methodology.md](ai-methodology.md), [known-limitations.md](known-limitations.md), [api-design.md](api-design.md), [database-design.md](database-design.md), [testing-report.md](testing-report.md).
