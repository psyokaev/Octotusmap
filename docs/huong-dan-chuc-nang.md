# OctotusMap: hướng dẫn chức năng, cách sử dụng, thuật toán và cơ chế

Hệ thống hỗ trợ ra quyết định (DSS) cảnh báo sớm ngập úng cho TP.HCM. Tài liệu viết đúng theo code tại ngày 20/11/2026. Mỗi hằng số đều ghi kèm file chứa nó để bạn tra lại.

Hai điều cần nhớ khi đọc:

- Hệ thống chạy trên **dữ liệu thật** (chế độ LIVE, `DEMO_MODE=false`). Riêng mưa và triều là đầu ra của mô hình thời tiết Open-Meteo, không phải số đo của trạm đặt tại chỗ.
- Mọi con số về ngập, gồm xác suất, độ sâu và mức nguy cơ, đều là **ước tính** để tham khảo. Giao diện luôn ghi chữ "ước tính" cạnh các con số này.

**Mục lục**

1. [Khởi động nhanh](#1-khởi-động-nhanh)
2. [Hệ thống hoạt động thế nào](#2-hệ-thống-hoạt-động-thế-nào)
3. [Vai trò và quyền](#3-vai-trò-và-quyền)
4. [Giao diện chung](#4-giao-diện-chung)
5. [Hướng dẫn sử dụng từng trang](#5-hướng-dẫn-sử-dụng-từng-trang)
6. [Thuật toán](#6-thuật-toán)
7. [Cơ chế hệ thống](#7-cơ-chế-hệ-thống)
8. [Vận hành và lệnh](#8-vận-hành-và-lệnh)
9. [Xử lý sự cố thường gặp](#9-xử-lý-sự-cố-thường-gặp)
10. [Hạn chế cần biết](#10-hạn-chế-cần-biết)

---

## 1. Khởi động nhanh

Mở terminal ở thư mục gốc dự án (`E:\Octotusmap`) và chạy:

```powershell
npm run dev
```

Lệnh này tự làm bốn việc (`scripts/dev.mjs`):

1. Bật PostgreSQL nếu đang tắt. Mặc định dùng bản cài ở `E:\pgsql`; đặt biến `PG_HOME` nếu cài ở chỗ khác.
2. Chạy backend FastAPI ở cổng 8000.
3. Chạy giao diện Streamlit ở cổng 5173.
4. Mở trình duyệt tại http://localhost:5173. Đặt `NO_BROWSER=1` nếu không muốn tự mở.

| Thành phần | Địa chỉ |
|---|---|
| Giao diện | http://localhost:5173 (Docker: http://localhost:8501) |
| Tài liệu API (Swagger) | http://127.0.0.1:8000/docs |
| Kiểm tra sống | http://127.0.0.1:8000/health |

Nếu cổng 8000 hoặc 5173 đang bị chiếm (ví dụ lần chạy trước chưa tắt), lệnh sẽ báo rồi dừng. Bấm `Ctrl+C` để dừng backend và giao diện; PostgreSQL vẫn chạy tiếp.

Lần đầu trên máy mới cần chạy `backend\.venv\Scripts\python backend\scripts\bootstrap.py` để tạo cơ sở dữ liệu, nạp dữ liệu và huấn luyện mô hình (xem [mục 8](#8-vận-hành-và-lệnh)). Muốn đặt lại mật khẩu một tài khoản thì dùng `scripts/set_password.py`.

---

## 2. Hệ thống hoạt động thế nào

### 2.1 Chu kỳ xử lý

Cứ 5 phút (`SCHEDULER_INTERVAL_SECONDS=300`), backend chạy một chu kỳ (`jobs/pipeline.py::run_cycle`):

```text
1. Lấy dữ liệu mới từ Open-Meteo: mưa theo giờ, mực nước biển Vũng Tàu
        │  lưu vào rainfall_observations, water_level_observations (không tạo trùng)
        ▼
2. Hết hạn các báo cáo ngập của người dân đã quá 3 giờ
        ▼
3. (Nếu bật) quét ảnh camera giao thông quanh điểm ngập bằng YOLOv8 (mặc định TẮT)
        ▼
3b. Kiểm tra ảnh của 8 camera giao thông lâu chưa kiểm nhất: hỏng thì tự ngừng, có ảnh lại thì tự bật
        ▼
3c. Tối đa 6 giờ một lần: lấy mưa vệ tinh IMERG của các ngày còn thiếu trong 7 ngày gần nhất
        ▼
4. GRU dự báo mưa 1–6 giờ tới cho 24 điểm lưới  ──► forecasts
        ▼
5. Đánh giá 346 khu vực × 7 mốc (hiện tại, +1h … +6h) ──► flood_risk_snapshots
      phường tính trước, quận lấy theo phường xấu nhất
        ▼
6. Sinh hoặc cập nhật cảnh báo cấp quận ──► alerts, notifications
        ▼
7. Dọn ảnh camera hết hạn, dọn bộ đếm giới hạn tốc độ cũ, phát sự kiện "cycle"
```

Mất mạng ở bước 1 không làm hỏng chu kỳ: hệ thống dùng dữ liệu đã có và thử lại ở chu kỳ sau. Lỗi ở bước 3 và 3b cũng không chặn các bước còn lại.

### 2.2 Dữ liệu đầu vào

| Dữ liệu | Nguồn | Ghi chú |
|---|---|---|
| Mưa theo giờ | Open-Meteo, 24 điểm lưới đặt tại tâm 24 quận/huyện | Là dữ liệu mô hình trên lưới ~1–11 km, không phải trạm đo |
| Mực nước biển | Open-Meteo Marine, cửa biển Vũng Tàu | Dùng làm đại diện cho triều |
| Mưa vệ tinh | NASA GPM IMERG (bản Late run theo ngày, lưới 0,1°) | **Số đo vệ tinh**, không phải mô hình; trễ 1–2 ngày; dùng để đối chiếu, không vào luật cảnh báo |
| Dự báo đa mô hình | Open-Meteo (7 mô hình: ECMWF, GFS, ICON, JMA, CMA, UKMO, Météo-France) | Dùng cho tín hiệu mưa dông |
| Độ cao | Open-Meteo Elevation (DEM 90 m) | Mỗi phường lấy một mẫu tại tâm phường |
| Điểm ngập thường xuyên | Phòng CSGT TP.HCM, qua báo Tiền Phong | 31 điểm, toạ độ geocode gần đúng |
| Lịch sử ngập | Báo chí (`datasets/gis/flood_events.csv`) | Mỗi dòng có URL bài gốc |
| Báo cáo ngập | Người dùng gửi trên bản đồ | Hiệu lực 3 giờ |
| Ranh giới | geoBoundaries (24 quận/huyện), GADM (322 phường/xã) | Cấu trúc hành chính trước 07/2025 |
| Camera giao thông | Cổng thông tin giao thông TP.HCM | 796 camera (703 đang hoạt động), ảnh tĩnh cập nhật liên tục |
| Bản đồ nền | OpenStreetMap, kiểu HOT do OSM France phục vụ | |

---

## 3. Vai trò và quyền

Có bốn loại người dùng. Quyền được kiểm tra ở **backend** (`core/deps.py`); giao diện chỉ ẩn bớt menu và nút, nên gọi thẳng API cũng không vượt quyền được.

| Chức năng | Khách | Người dân (USER) | Cán bộ (OPERATOR) | Quản trị (ADMIN) |
|---|:-:|:-:|:-:|:-:|
| Bản đồ, tìm kiếm, chỉ đường | ✓ | ✓ | ✓ | ✓ |
| Xem cảnh báo công khai đang mở | ✓ | ✓ | ✓ | ✓ |
| Xem Dự báo AI, Lịch sử ngập | ✓ | ✓ | ✓ | ✓ |
| Gửi báo cáo ngập, xác nhận báo cáo của người khác | | ✓ | ✓ | ✓ |
| Đổi mật khẩu của mình | | ✓ | ✓ | ✓ |
| Nhận thông báo khi có cảnh báo mới hoặc nâng mức | | | ✓ | ✓ |
| Từ chối báo cáo ngập sai | | | ✓ | ✓ |
| Xử lý cảnh báo, xem cảnh báo đã đóng | | | ✓ | ✓ |
| Tổng quan, Thống kê, xuất Excel/CSV | | | ✓ | ✓ |
| Trạm quan trắc, Camera | | | ✓ | ✓ |
| Thêm/xoá sự kiện ngập lịch sử | | | ✓ | ✓ |
| Thấy dữ liệu mô phỏng ngập | | | ✓ | ✓ |
| Tạo/xoá vùng mô phỏng ngập | | | | ✓ |
| Mô hình AI, Người dùng, Cấu hình | | | | ✓ |

Người dân và khách **không** thấy:

- người phụ trách, trạng thái xử lý và các mốc xử lý của cảnh báo;
- kết quả xác minh thực địa;
- phần giải thích điểm số: trọng số, đầu vào, mã trạm liên quan;
- `stream_url` của camera, ảnh và kết quả nhận dạng của camera giao thông;
- các sự kiện nội bộ và mọi dữ liệu mô phỏng ngập.

Họ vẫn thấy lý do ngập, độ sâu ước tính và danh sách phường bị ảnh hưởng.

---

## 4. Giao diện chung

Giao diện là ứng dụng Streamlit, bố cục và màu theo bản React cũ.

- **Thanh trên cùng** (màu xanh đậm): logo OctotusMap, rồi menu các trang theo vai trò. Ở góc phải:
  - khách thấy nút **Đăng nhập**;
  - người đã đăng nhập thấy nút **Thông báo** (kèm số chưa đọc), **tên của mình** (bấm vào để đổi mật khẩu) và **Đăng xuất**.

  Trên màn hình hẹp, menu thu vào nút "»".
- **Chỉ có giao diện sáng.** Trang vẫn sáng kể cả khi Windows hay trình duyệt bật chế độ tối. Font là Google Sans và Roboto.
- **Giờ hiển thị là giờ Việt Nam**, dạng `dd/mm/yyyy HH:MM`. Cơ sở dữ liệu lưu giờ UTC.
- **Cập nhật tức thì:** khi backend có chu kỳ dữ liệu mới, cảnh báo công khai mới, hoặc báo cáo ngập mới/được xác nhận/bị từ chối, trang tự chạy lại trong khoảng 3 giây. Đã đo: báo cáo mới hiện sau 2,6 giây. Bản đồ, thông báo và cảnh báo vẫn tự hỏi lại mỗi 60 giây để dự phòng. Không cần bấm F5.
- **Giữ đăng nhập khi tải lại trang:** đăng nhập xong, phiên được lưu trong cookie `octo_session` của trình duyệt (8 giờ, `SameSite=Strict`). Bấm F5 vẫn còn đăng nhập. Đăng xuất hoặc đổi mật khẩu thì cookie cũ mất hiệu lực.
- **Dải vàng "Đang bật mô phỏng N vùng ngập"** hiện ở đầu mọi trang khi admin đang bật mô phỏng. Chỉ cán bộ thấy dải này. Trên trang Bản đồ, nó nằm phía trên thanh giờ để không che bản đồ.
- **Xuất tệp cần hai bước:** bấm "Chuẩn bị…" rồi bấm nút "Tải…" xuất hiện sau đó.
- **Các thao tác nguy hiểm** (xoá, đổi trạng thái cảnh báo) luôn có bước xác nhận.

---

## 5. Hướng dẫn sử dụng từng trang

### 5.1 Đăng nhập, đăng ký, đổi mật khẩu

**Đăng nhập**

1. Bấm **Đăng nhập** ở góc phải thanh trên.
2. Ở tab "Đăng nhập", nhập tên đăng nhập và mật khẩu, rồi nhấn Enter hoặc bấm "Đăng nhập".
3. Menu đổi theo vai trò của tài khoản.

Phiên đăng nhập hết hạn sau 480 phút. Hệ thống chặn thử mật khẩu liên tục: xem các giới hạn ở [mục 7.2](#72-bảo-mật-và-giới-hạn-tốc-độ).

**Đăng ký tài khoản người dân**

1. Trang Đăng nhập, tab **"Tạo tài khoản người dân"**.
2. Nhập tên đăng nhập, email, họ tên và mật khẩu, rồi bấm "Tạo tài khoản".

Tên đăng nhập dài 3–50 ký tự, chỉ gồm chữ, số, `_` và `.`. Mật khẩu tối thiểu 10 ký tự và phải có cả chữ lẫn số. Tài khoản mới có vai trò USER; quyền cán bộ do admin cấp ở trang Người dùng.

**Đổi mật khẩu**

1. Bấm vào **tên của bạn** ở góc phải thanh trên.
2. Nhập mật khẩu hiện tại và mật khẩu mới, rồi bấm "Đổi mật khẩu".

Đổi mật khẩu xong, mọi phiên đăng nhập cũ của tài khoản đều mất hiệu lực. Nhập sai mật khẩu hiện tại quá 10 lần trong 15 phút thì bị tạm khoá chức năng này, và mỗi lần sai đều được ghi vào nhật ký.

### 5.2 Bản đồ (trang chủ)

Bản đồ phủ kín màn hình; các bảng điều khiển nổi trên bản đồ.

```text
┌───────────────┬──────────────────────────────────────────────┐
│ Ô tìm kiếm    │  [✓ Nguy cơ ngập] [✓ Mưa] [✓ Điểm ngập] ...  │ ← chip lớp bản đồ
│ Tab: Tình hình│                                              │
│  Chi tiết     │                 BẢN ĐỒ                       │
│  Chỉ đường    │                                              │
│  Báo cáo ngập │                                              │
│  Mô phỏng*    │        [Nay][+1h][+2h]…[+6h]                 │ ← thanh giờ
└───────────────┴──────────────────────────────────────────────┴ (+/−) phóng to
  * chỉ admin
```

#### Đọc bản đồ

- **Màu phường theo mức nguy cơ:**
  - **Thấp:** xanh lá, rất nhạt;
  - **Trung bình:** cam, đậm hơn;
  - **Cao:** đỏ, đậm hơn;
  - **Không đủ dữ liệu:** không tô.

  Quận chỉ có đường viền đậm, phường có viền nét đứt.
- **Rê chuột** lên một phường để xem tên và mức nguy cơ.
- **Thanh giờ** ở cuối màn hình (Nay, +1h … +6h): bấm một mốc thì bản đồ, bảng Tình hình và chi tiết điểm đổi sang mốc đó.
- **Chip lớp bản đồ** ở trên cùng; chip đang bật có dấu ✓. Bấm để bật hoặc tắt:

| Lớp | Hiển thị |
|---|---|
| Nguy cơ ngập | Tô màu phường theo mức |
| Mưa | Điểm lưới mưa; màu càng đậm thì mưa càng to (≥ 1, ≥ 5, ≥ 20 mm/h) |
| Điểm ngập thường xuyên | Chấm cam, 31 điểm theo CSGT |
| Báo cáo ngập | Chấm tím viền trắng, báo cáo còn hiệu lực |
| Cảnh báo | Ký hiệu ở tâm quận có cảnh báo đang mở: **◆** đỏ là Cao, **▲** cam là Trung bình. Bấm vào để xem tóm tắt và nút "Mở cảnh báo". Cán bộ thấy cả cảnh báo mô phỏng (ghi "(MÔ PHỎNG)") |
| Camera | Chấm xanh đậm, các camera giao thông đang hoạt động (mặc định tắt vì nhiều điểm) |
| Ranh giới | Viền quận và phường |

- Nút **◎ (Vị trí của tôi)** ở góc dưới phải: trình duyệt hỏi quyền vị trí. Định vị xong, bản đồ bay tới vị trí của bạn và mở tab Chi tiết tại đó. Nếu đang ở tab Chỉ đường mà chưa có điểm đi, vị trí này thành điểm đi. Nếu không lấy được vị trí, một dòng nhắc đỏ hiện 5 giây trên bản đồ.
- Nút **+ / −** ở góc dưới phải để phóng to, thu nhỏ; hoặc lăn chuột. Kéo bản đồ để di chuyển. Bản đồ giữ nguyên vị trí bạn đang xem khi trang tự cập nhật hay khi đổi mốc giờ.

#### Tab "Tình hình"

- Dòng **"Cập nhật …"** cho biết thời điểm của lần đánh giá mới nhất.
- **Danh sách quận** xếp từ nguy cơ cao xuống thấp, mỗi dòng có chip màu mức nguy cơ ở bên phải.
- **Mở một quận** để xem lý do ngập của quận (ví dụ *"Ngập do triều, khoảng 40 cm (ước tính)"*), số phường nguy cơ trung bình hoặc cao, và danh sách phường. Bấm nút mức của một phường thì bản đồ bay tới phường đó và mở tab Chi tiết.
- Cuối tab là biểu đồ xác suất ngập ước tính lớn nhất toàn thành phố theo giờ, và số cảnh báo đang hoạt động.

#### Tab "Chi tiết": xem một vị trí

Bấm vào bất kỳ đâu trên bản đồ, hoặc chọn một kết quả tìm kiếm. Tab Chi tiết hiện:

- tên phường và quận, toạ độ, thời điểm cập nhật;
- mức nguy cơ ở mốc đang chọn, xác suất ngập ước tính và lượng mưa;
- **câu lý do in đậm**, ví dụ "Ngập do triều, khoảng 40 cm (ước tính)", cùng các điều kiện đã đẩy mức lên;
- mức nguy cơ của cả 7 mốc (Nay … +6h);
- khuyến nghị theo mức;
- số trận ngập lịch sử trong bán kính 1,5 km, kèm trận gần nhất và trận sâu nhất;
- nút **"Chỉ đường tới đây"** và mục **"Báo ngập tại đây"**.

Bấm vào một đối tượng (trạm, điểm ngập, báo cáo, camera) thì tab Chi tiết hiện thông tin của đối tượng đó:

- **Trạm:** trạng thái kết nối, số đo mới nhất, dự báo của trạm.
- **Điểm ngập thường xuyên:** mô tả và liên kết "Xem nguồn".
- **Báo cáo ngập:** mức ngập, ghi chú, giờ báo, thời điểm hết hiệu lực, số người xác nhận.
- **Camera giao thông:** ảnh mới nhất và nút "Làm mới ảnh".

Ở cuối tab có mục "Xem ảnh camera giao thông" để chọn và xem nhanh ảnh của một camera bất kỳ.

#### Tìm kiếm

1. Gõ vào ô **"Tìm đường, quận, điểm ngập, toạ độ…"** ở đầu bảng bên trái, rồi nhấn Enter. Có thể gõ:
   - tên đường hoặc địa chỉ (tra qua Photon/OpenStreetMap);
   - tên quận hoặc phường, mã hay tên trạm, tên điểm ngập;
   - toạ độ dạng `10.77, 106.70`.

   Tìm kiếm không phân biệt hoa thường và có dấu hay không dấu.
2. Chọn một kết quả trong danh sách, rồi bấm **"Chọn"**.
3. Bản đồ bay tới vị trí đó: mức zoom 12 cho quận và phường, 15 cho các kết quả khác. Tab Chi tiết tự mở.

#### Tab "Chỉ đường"

1. Mở tab **Chỉ đường**.
2. Chọn **Điểm đi**, theo một trong hai cách:
   - gõ vào ô "Tìm điểm đi", nhấn Enter, chọn kết quả rồi bấm "Chọn";
   - bấm lên bản đồ: lần bấm đầu tiên là điểm đi.
3. Chọn **Điểm đến** tương tự; lần bấm thứ hai lên bản đồ là điểm đến. Cũng có thể bấm "Chỉ đường tới đây" ở tab Chi tiết, hoặc bấm nút ◎ để lấy vị trí hiện tại làm điểm đi.
   - **Kéo thả:** marker xanh (điểm đi) và đỏ (điểm đến) kéo được. Thả ở đâu thì điểm chuyển tới đó và tuyến được tính lại.
4. Chọn **Khởi hành**: "Bây giờ" hoặc "Sau 1–6 giờ". Hệ thống đánh giá ngập theo mốc giờ đó.
5. Hệ thống trả tối đa 3 tuyến; bản đồ tự thu phóng vừa tuyến được chọn. Mỗi tuyến có một nút ghi thời gian, quãng đường và tình trạng, ví dụ "9 phút · 7,7 km · Tuyến đề xuất | Không có đoạn ngập". Bấm vào nút để chọn tuyến.
6. Danh sách **"Đoạn cần chú ý"** liệt kê các đoạn nguy hiểm, kèm lý do của từng đoạn.
7. Nút **"⇅ Đổi chiều"** hoán đổi điểm đi và điểm đến; nút **"Xoá tuyến"** xoá cả hai điểm.

| Nét đường | Ý nghĩa |
|---|---|
| Xanh liền | Không có dấu hiệu ngập |
| Cam đứt | Có nguy cơ ngập |
| Đỏ đứt | Có thể đang ngập |
| Tím đứt | Người dân báo ngập |

Đường đi do OSRM tính, chỉ có profile ô tô. Mỗi IP được gọi chỉ đường tối đa 30 lần mỗi phút.

#### Báo ngập, xác nhận và từ chối

**Gửi báo cáo** (cần đăng nhập):

1. Bấm vào đúng vị trí đang ngập trên bản đồ.
2. Ở tab Chi tiết, mở **"Báo ngập tại đây"**.
3. Chọn mức: **Ngập mắt cá**, **Ngập đầu gối** hoặc **Ngập sâu**. Ghi chú thêm nếu muốn (tối đa 300 ký tự).
4. Bấm **"Gửi báo cáo"**.

Báo cáo có hiệu lực 3 giờ và hiện ngay cho mọi người. Mỗi tài khoản gửi tối đa 5 báo cáo trong 10 phút.

**Xác nhận:** người khác đã đăng nhập mở báo cáo (bấm chấm tím, hoặc vào tab "Báo cáo ngập") rồi bấm **"Xác nhận vẫn ngập"**. Mỗi người chỉ xác nhận một lần và không tự xác nhận báo cáo của mình. Mỗi lần xác nhận giữ cho báo cáo còn hiệu lực ít nhất 1 giờ nữa.

**Từ chối:** cán bộ bấm **"Từ chối"** với báo cáo sai. Báo cáo bị từ chối biến mất khỏi bản đồ và không còn ảnh hưởng đến cảnh báo.

**Ảnh hưởng của báo cáo:** báo cáo chưa có ai xác nhận nâng phường lên tối thiểu mức Trung bình. Báo cáo đã có người xác nhận đẩy phường lên mức Cao, với lý do "Người dân báo ngập". Đoạn đường cách báo cáo không quá 100 m hiện nét tím.

Tab **"Báo cáo ngập"** liệt kê mọi báo cáo còn hiệu lực.

#### Tab "Mô phỏng" (chỉ admin)

Dùng để diễn tập: giả định một vùng đang ngập rồi xem hệ thống phản ứng thế nào.

1. Mở tab **Mô phỏng**.
2. Bấm lên bản đồ để chọn tâm vùng ngập. Dòng "Tâm: …" hiện toạ độ, và một vòng tròn xem trước được vẽ lên bản đồ.
3. Đặt **bán kính** (100–2000 m) và **độ sâu** (1–300 cm).
4. Bấm **"Tạo vùng ngập"**. Có thể tạo nhiều vùng.
5. Xoá từng vùng bằng nút "Xoá" cạnh vùng đó, hoặc bấm **"Xoá tất cả"**.

Cho tới khi xoá vùng mô phỏng, mọi cán bộ (admin và operator) thấy dữ liệu có nhãn **MÔ PHỎNG** ở:

| Nơi | Ảnh hưởng |
|---|---|
| Đầu mọi trang | Dải vàng "Đang bật mô phỏng N vùng ngập" |
| Bản đồ | Phường và quận giao với vùng mô phỏng lên mức **Cao** nếu độ sâu từ 20 cm, ngược lại lên **Trung bình**. Vòng tròn mô phỏng vẽ màu xanh ngọc |
| Chỉ đường | Đoạn đi qua vùng mô phỏng hiện nét đỏ, lý do "MÔ PHỎNG: ngập X cm" |
| Dự báo AI | Khu vực bị mô phỏng đứng đầu bảng xếp hạng, cột lý do ghi "MÔ PHỎNG…" |
| Cảnh báo | Mỗi quận bị mô phỏng có một cảnh báo `[MÔ PHỎNG] [CAO] Quận …`, mã `SIM-…`, đứng đầu danh sách. Cảnh báo này không có nút xử lý |
| Lịch sử ngập | Mỗi vùng là một dòng "MÔ PHỎNG: vùng bán kính … m", đứng đầu danh sách, không có nút Xoá |
| Tổng quan, Thống kê | Số khu vực theo mức, số cảnh báo đang mở, thống kê cảnh báo theo mức, theo khu vực và theo trạng thái đều cộng vùng mô phỏng. Chọn "Loại dữ liệu = Dữ liệu thật" thì không tính |

Mô phỏng **không ghi gì vào bảng dữ liệu thật**: không có quan trắc, cảnh báo hay thông báo thật nào được tạo. Xoá vùng mô phỏng là mọi dấu vết biến mất. Người dân và khách không bao giờ thấy dữ liệu mô phỏng. Cách tính xem ở [mục 6.11](#611-mô-phỏng-ngập).

### 5.3 Cảnh báo

**Danh sách**

- Mở **Bộ lọc** để lọc theo:
  - **Tìm kiếm:** mã, tiêu đề hoặc nội dung;
  - **Khu vực**, **Từ ngày / Đến ngày**;
  - **Mức:** Cao, Trung bình, Thấp, Không đủ dữ liệu;
  - **Trạng thái** (chỉ cán bộ).
- Sắp xếp theo thời điểm phát sinh, mức rủi ro, điểm rủi ro hoặc trạng thái (trạng thái chỉ dành cho cán bộ), giảm dần hoặc tăng dần.
- Mỗi dòng ghi mã, tiêu đề (ví dụ `[CAO] Quận 7`), câu lý do và độ sâu, danh sách phường, mức, trạng thái, điểm và thời điểm phát sinh. Danh sách có phân trang.
- Dòng "Trên trang này" đếm số cảnh báo theo mức.
- Cán bộ xuất được danh sách ra Excel: bấm "Chuẩn bị tệp Excel" rồi bấm nút tải.
- Người dân và khách chỉ thấy cảnh báo công khai đang mở, và không thấy trạng thái xử lý.

**Chi tiết cảnh báo:** bấm **"Chi tiết"** ở cuối dòng. Phần chi tiết hiện ngay dưới danh sách, gồm:

- nội dung và khuyến nghị;
- phần **"Giải thích mức cảnh báo"**: lý do, độ tin cậy dữ liệu, phiên bản quy tắc, đóng góp của từng thành phần, điều kiện đẩy mức và trạm liên quan (chỉ cán bộ thấy);
- dòng thời gian: phát sinh, tiếp nhận, xử lý xong, đóng;
- **lịch sử xử lý**.

Bấm "Đóng" để thu lại.

**Quy trình xử lý của cán bộ**

```text
NEW (Mới) ──► ACKNOWLEDGED (Đã tiếp nhận) ──► IN_PROGRESS (Đang xử lý) ──► RESOLVED (Đã xử lý) ──► CLOSED (Đã đóng)
   │                 │                              │                          ▲   │
   └─────────────────┴──────────────────────────────┴──── có thể nhảy thẳng ──┘   └─► quay lại IN_PROGRESS
```

Trong chi tiết cảnh báo, cán bộ có thể:

1. **Tiếp nhận:** nút "Tiếp nhận", dùng khi cảnh báo còn ở trạng thái Mới.
2. **Chuyển trạng thái:** chọn trạng thái mới, ghi chú nếu cần, bấm "Cập nhật trạng thái", rồi bấm **"Chuyển trạng thái"** để xác nhận (hoặc "Huỷ").
3. **Thêm ghi chú.**
4. **Phân công:** chọn một cán bộ rồi bấm "Phân công". Người được phân công nhận một thông báo.
5. **Xác minh thực địa:** chọn Xác nhận có ngập, Báo động sai hoặc Chưa xác minh, rồi bấm "Lưu xác minh".

Mọi thao tác được lưu vào lịch sử cảnh báo và nhật ký hệ thống. Cảnh báo không tự đóng ở chế độ LIVE: cán bộ phải đóng.

Cảnh báo mô phỏng (mã `SIM-…`) không có phần xử lý; chi tiết của nó chỉ ghi "Cảnh báo MÔ PHỎNG: không cần xử lý".

### 5.4 Dự báo AI

- **Mô hình dự báo đang dùng:** tên mô hình (ví dụ `flood-gru`), loại mạng, trạng thái và các chỉ số trên tập kiểm tra:
  - MAE và RMSE của lượng mưa (mm);
  - Precision, Recall và F1 cho mưa to (≥ 5 mm/h).

  Kèm thời điểm của lần phát hành gần nhất.
- **Dự báo theo trạm:** chọn một trạm ở ô "Trạm hiển thị biểu đồ" để xem biểu đồ mưa dự báo (cột, mm) và xác suất ngập ước tính (đường, %) cho 6 giờ tới. Bảng bên dưới ghi lượng mưa và xác suất của mọi trạm ở từng mốc.
- **Xếp hạng nguy cơ theo khu vực:** chọn mốc (Hiện tại, +1 giờ … +6 giờ). Bảng xếp quận từ nguy cơ cao xuống thấp, có cột mức, điểm, xác suất, **Lý do** và **"LSTM: ngập trong 6 giờ tới"**. Cột LSTM là xác suất (đã hiệu chỉnh) do mô hình LSTM học từ 246 trận ngập dự báo; chỉ để tham khảo, không dùng phát cảnh báo (mục 6.3b).

### 5.5 Lịch sử ngập

- **Lọc:** tìm theo địa điểm hoặc mô tả, khu vực, từ ngày, đến ngày, độ sâu tối thiểu (cm).
- **Sắp xếp** theo thời điểm bắt đầu, độ sâu lớn nhất hoặc địa điểm; chọn giảm dần hoặc tăng dần.
- **Bảng** gồm địa điểm, khu vực, bắt đầu, kết thúc, độ sâu lớn nhất, nguyên nhân (Mưa, Triều cường, Mưa kết hợp triều, Khác, Mô phỏng) và mô tả. Mô tả có URL bài báo gốc.
- **Cán bộ** thấy thêm biểu đồ số trận theo tháng, và làm được hai việc:
  - **Thêm sự kiện:** nhập địa điểm, vĩ độ và kinh độ (phải nằm trong TP.HCM), ngày và giờ bắt đầu theo giờ Việt Nam, tick "Có thời điểm kết thúc" nếu biết giờ kết thúc, độ sâu lớn nhất (0–500 cm; 0 là không rõ), nguyên nhân, mô tả, rồi bấm "Lưu". Sự kiện tự được gắn vào quận chứa toạ độ.
  - **Xoá sự kiện:** nút "Xoá" ở cuối dòng, rồi "Xoá vĩnh viễn" để xác nhận.

Lịch sử ngập thật được nạp từ `datasets/gis/flood_events.csv`. Mỗi dòng phải có URL bài gốc đã đọc, và độ sâu chỉ được ghi khi bài báo nêu số.

### 5.6 Tổng quan (cán bộ)

- **Bộ lọc:** khoảng thời gian (mặc định 7 ngày), khu vực, trạm quan trắc.
- **Các thẻ số liệu:**
  - tổng số trạm, số trạm đang kết nối và mất kết nối;
  - số camera, số khu vực;
  - số khu vực nguy cơ thấp, trung bình và cao **hiện tại**;
  - số cảnh báo đang mở, có tính cả cảnh báo cho 6 giờ tới;
  - số cảnh báo đã xử lý trong kỳ;
  - lượng mưa trung bình, mực nước cao nhất, tỉ lệ dữ liệu hợp lệ;
  - giờ và ngày của bản dự báo mới nhất.
- **Biểu đồ:** tổng lượng mưa theo ngày, mực nước theo ngày, dự báo 1–6 giờ tới của toàn bộ trạm, sai số dự báo mưa thực tế theo mốc, cảnh báo theo khu vực, tỉ lệ khu vực theo mức nguy cơ hiện tại, xu hướng nguy cơ ngập.

"Khu vực nguy cơ … hiện tại" chỉ tính mốc hiện tại, còn "Cảnh báo đang mở" tính cả dự báo tới 6 giờ. Vì vậy hai số có thể khác nhau; đây không phải lỗi.

### 5.7 Thống kê (cán bộ)

Chọn nhóm thống kê ở hàng tab:

| Tab | Nội dung |
|---|---|
| Lượng mưa | Chuỗi mưa theo thời gian, theo trạm; xuất được CSV |
| Mực nước | Chuỗi mực nước theo thời gian, theo trạm; xuất được CSV |
| Nguy cơ ngập | Xu hướng đánh giá nguy cơ theo khu vực, phân bố mức nguy cơ mới nhất |
| Lịch sử cảnh báo | Cảnh báo theo thời gian, theo mức, theo khu vực, theo trạng thái, kết quả xác minh |
| Sự kiện ngập lịch sử | Số trận và độ sâu theo tháng, theo khu vực |
| Hiệu quả dự báo | Sai số dự báo mưa thực tế theo mốc và theo mô hình |
| Camera | Thống kê nhận dạng ảnh (chỉ hiện khi bật camera) |
| Trạm quan trắc | Trạng thái kết nối, số bản ghi |
| Dữ liệu thiếu/lỗi | Tỉ lệ dữ liệu hợp lệ, nghi ngờ, thiếu |
| Hoạt động xử lý cảnh báo | Thời gian trung bình tới khi tiếp nhận và tới khi xử lý xong, các thao tác theo loại |

- **Bộ lọc mở rộng:**
  - khoảng thời gian (mặc định 7 ngày, tối đa 3700 ngày);
  - khu vực, trạm;
  - mức nguy cơ;
  - loại dữ liệu: Tất cả, Dữ liệu thật, Mô phỏng;
  - nhóm theo giờ, ngày, tháng hoặc năm.
- **Xuất Excel:** chọn một trong 9 loại báo cáo rồi bấm "Xuất Excel". Các loại gồm: tổng hợp, lượng mưa, mực nước, cảnh báo ngập, sự kiện ngập lịch sử, dự báo AI, đánh giá mô hình, trạm quan trắc, camera. Mỗi tab tự chọn sẵn loại phù hợp.
- **Báo cáo PDF tổng hợp:** bấm "Báo cáo PDF tổng hợp" (cũng có ở trang Tổng quan), rồi bấm nút tải. Báo cáo theo đúng bộ lọc đang chọn, gồm:
  1. chỉ số chính và 5 quận có xác suất ngập 6 giờ tới cao nhất theo LSTM;
  2. mưa và mực nước theo ngày, nơi mưa nhiều nhất;
  3. nguy cơ hiện tại, xu hướng nguy cơ, cảnh báo theo mức, khu vực, trạng thái, xác minh;
  4. sự kiện ngập theo tháng, sai số dự báo mưa theo mốc, mô hình AI đang dùng, chất lượng dữ liệu;
  5. mưa vệ tinh IMERG đối chiếu Open-Meteo (khi đã có dữ liệu).
- **Tab Lượng mưa** có thêm biểu đồ **"Mưa vệ tinh GPM IMERG (NASA) so với Open-Meteo"** theo ngày.

### 5.8 Trạm quan trắc (cán bộ)

- **Danh sách trạm:**
  - lọc theo trạng thái kết nối;
  - sắp xếp theo mã, tên, quan trắc gần nhất hoặc thời điểm cập nhật.

  Trạm được tính là **Đang kết nối** khi bản ghi mới nhất không cũ quá 2 lần chu kỳ đo cộng 15 phút.
- **Thêm, sửa trạm:** nhập mã trạm, tên trạm, loại trạm, địa chỉ, đơn vị quản lý, vĩ độ, kinh độ, ngưỡng ngập (cm), chu kỳ gửi dữ liệu (phút), trạng thái, ghi chú, rồi bấm "Lưu".
- **Xoá trạm:** xoá mềm, có bước xác nhận.
- Chọn một trạm ở ô **"Chọn trạm để thao tác"** để mở trang của trạm. Trang này có:
  - lịch sử và biểu đồ quan trắc;
  - **chất lượng dữ liệu 7 ngày**, kèm phát hiện dữ liệu bất thường;
  - dự báo của trạm;
  - **nhập quan trắc thủ công**: ngày, giờ, lượng mưa (mm) và/hoặc mực nước (cm), nút "Gửi quan trắc";
  - nhập tệp CSV/XLSX riêng cho trạm này.
- **Nhập dữ liệu nhiều trạm:** tệp `.csv` hoặc `.xlsx`, tối đa 50.000 dòng, gồm các cột:

| Cột | Bắt buộc | Ghi chú |
|---|---|---|
| `station_code` | Khi nhập nhiều trạm | Không cần nếu nhập trong trang của một trạm |
| `observed_at` | Có | Không ghi múi giờ thì hiểu là giờ Việt Nam |
| `rainfall_mm` | Cần một trong hai cột đo | |
| `water_level_cm` hoặc `water_level_m` | Cần một trong hai cột đo | Đơn vị mét được tự đổi sang cm |

Sau khi nhập, hệ thống báo số dòng thêm mới, số dòng trùng (bị bỏ qua) và lý do của từng dòng lỗi. Dòng có thời gian ở tương lai quá 1 giờ, hoặc thiếu cả hai giá trị đo, bị từ chối chứ không bị nội suy âm thầm.

### 5.9 Camera (cán bộ)

Trang có hai tab.

**Tab "Camera giao thông TP.HCM"**

1. Gõ tên đường hoặc nút giao vào ô **"Tìm camera"** để tìm.
2. Chọn quận/huyện ở ô **"Quận/huyện"** để lọc.
3. Dòng tóm tắt cho biết số camera khớp trên tổng số camera đang hoạt động.
4. Mỗi trang hiện 6 camera. Mỗi thẻ ghi tên, quận và **ảnh trực tiếp**; dùng "‹ Trước / Sau ›" để chuyển trang.
5. **"Làm mới ảnh"** tải ảnh mới. Ảnh tĩnh được backend làm mới mỗi 30 giây; đây không phải video.
6. **"Xem trên bản đồ"** chuyển sang trang Bản đồ, bay tới camera ở mức zoom 16, bật lớp Camera và mở ảnh của camera đó ở tab Chi tiết.

Ảnh được lấy qua backend: backend không lưu ảnh, và mỗi IP lấy tối đa 60 ảnh mỗi phút. Danh sách camera là bản chụp ngày 06/11/2026, vì trang nguồn không có API công khai; nạp lại bằng `scripts/import_traffic_cameras.py` khi có bản chụp mới.

**Camera hỏng tự ẩn:** mỗi chu kỳ 5 phút hệ thống kiểm tra ảnh của 8 camera (lần lượt, nên khoảng 7–8 giờ là đi hết danh sách).
- Camera lỗi 3 lần kiểm tra liên tiếp chuyển sang "Ngừng" và biến khỏi danh sách cùng bản đồ.
- Camera đang "Ngừng" mà có ảnh lại thì tự bật lại.
- Nếu cả loạt kiểm tra đều lỗi, nhiều khả năng cổng của thành phố sập hoặc đổi địa chỉ: hệ thống không ẩn camera nào và ghi cảnh báo vào log. Khi thành phố đổi địa chỉ, đặt biến `TRAFFIC_CAMERA_BASE`.

**Tab "Camera tự quản lý"**

- **Thêm camera:** nhập mã, tên, trạng thái, vĩ độ, kinh độ, URL nguồn (`http(s)://` hoặc `rtsp://`, có thể để trống), vùng quan tâm ROI (JSON `[[x,y],…]` theo tỉ lệ 0–1, tối thiểu 3 điểm), số ngày lưu ảnh (1–365) và tuỳ chọn "Công khai cho người dân".
- Mỗi camera có các nút "Lịch sử nhận dạng", "Sửa", "Xoá".
- **Phân tích ảnh:**
  1. bấm "Phân tích ảnh";
  2. chọn ảnh `.jpg` hoặc `.png` (tối đa 10 MB);
  3. tuỳ chọn gắn ảnh với một camera tự tạo;
  4. bấm "Phân tích".

  Kết quả gồm ảnh tô vùng nước, tỉ lệ ngập, độ tin cậy và phương pháp đã dùng.

**Ảnh vào luồng cảnh báo khi nào:** chỉ khi ảnh được gắn với một camera tự tạo (không phải camera giao thông `TT-…`) và YOLOv8 thấy từ 40% vùng quan sát bị ngập. Khi đó **chỉ phường chứa camera** lên mức Cao trong 90 phút (mốc hiện tại và +1h), với lý do "Camera phát hiện ngập (mô hình thử nghiệm, tham khảo)". Ảnh không gắn camera chỉ để xem thử.

### 5.10 Mô hình AI (admin)

- Danh sách phiên bản mô hình dự báo (LSTM, GRU, các mô hình tinh chỉnh theo cụm) và mô hình thị giác (YOLOv8-seg), kèm chỉ số đánh giá.
- Chọn một mô hình ở ô **"Chọn mô hình"**:
  - **"Chi tiết"** xem chỉ số và sai số theo từng mốc;
  - **"Kích hoạt"** dùng phiên bản đó cho các chu kỳ sau, có bước xác nhận.

  Mô hình tinh chỉnh theo cụm chỉ kích hoạt được khi mô hình nền của nó đang chạy; nếu sai nền, hệ thống trả lỗi 409. Mô hình thị giác học trên ảnh mô phỏng không bao giờ được thay mô hình học trên ảnh thật đang chạy.
- **Huấn luyện lại:** nhập số epoch (1–100) rồi bấm "Huấn luyện lại …". Việc huấn luyện chạy nền trên CPU; khi đang có một lượt chạy, nút bị khoá. Bảng lịch sử huấn luyện ghi trạng thái, thời gian và kết quả.

### 5.11 Người dùng (admin)

- **Tìm kiếm** theo tên đăng nhập, email hoặc họ tên; lọc theo vai trò. Bảng gồm vai trò, trạng thái, lần đăng nhập gần nhất và ngày tạo.
- **"Thêm người dùng":** nhập tên đăng nhập, email, họ tên, mật khẩu và vai trò (Quản trị, Cán bộ vận hành, Người dân), rồi bấm "Tạo người dùng".
- **Sửa người dùng:**
  1. chọn ở ô "Chọn người dùng";
  2. bấm "Sửa";
  3. đổi họ tên, email, vai trò hoặc trạng thái hoạt động; bỏ tick "Tài khoản đang hoạt động" để khoá tài khoản;
  4. đặt lại mật khẩu nếu cần (để trống thì giữ nguyên);
  5. bấm "Lưu".
- **Xoá:** xoá mềm, có xác nhận. Admin không tự xoá chính mình được.

### 5.12 Cấu hình (admin)

| Tab | Cách dùng |
|---|---|
| Quy tắc cảnh báo | Xem phiên bản đang áp dụng; sửa trọng số, ngưỡng mức, các điều kiện đẩy thẳng lên mức Cao, điều kiện phát cảnh báo (độ tin cậy tối thiểu, tuổi dữ liệu tối đa, thời gian chờ sau khi đóng, mức tối thiểu để phát cảnh báo); ghi tên phiên bản và ghi chú rồi bấm **"Lưu thành phiên bản mới"**. Phiên bản mới có hiệu lực ngay; bản cũ được giữ nguyên, không bị sửa đè |
| Cấu hình hệ thống | Các tham số dạng khoá–giá trị; sửa rồi bấm "Lưu" |
| Nhật ký | Nhật ký các thao tác quan trọng: ai làm gì, lúc nào, từ IP nào |
| Nguồn dữ liệu | Danh sách nguồn dữ liệu và giấy phép |
| Vận hành | **"Chạy chu kỳ xử lý ngay"** (không chờ 5 phút); **"Nhập ranh giới"** từ tệp GeoJSON (tối đa 30 MB) |

Các trọng số và ngưỡng mặc định chỉ phục vụ nghiên cứu và trình diễn, chưa phải ngưỡng vận hành chính thức của cơ quan quản lý.

---

## 6. Thuật toán

### 6.1 Thu thập và kiểm tra dữ liệu

File: `services/openmeteo_service.py`, `services/observation_service.py`.

- Mỗi chu kỳ lấy lại 3 ngày gần nhất và chèn bằng `INSERT … ON CONFLICT DO NOTHING`, nên chạy lại không tạo bản ghi trùng.
- Các giờ đã qua được lưu làm quan trắc; các giờ sắp tới của triều được dùng làm dự báo triều.
- Gắn cờ `SUSPECT` (không dùng làm giá trị) khi:
  - mưa < 0 hoặc > 200 mm/h;
  - mực nước nằm ngoài [−300, 600] cm;
  - mực nước đổi quá 150 cm trong một giờ.

### 6.2 Dự báo mưa bằng LSTM/GRU

File: `ai/forecasting/`.

| Thành phần | Giá trị |
|---|---|
| Đầu vào | 24 giờ gần nhất, 5 đặc trưng: `log1p(mưa)`, mực nước tương đối, sin và cos của giờ, cờ thiếu dữ liệu |
| Mạng | 2 lớp LSTM hoặc GRU (48 rồi 24 đơn vị, dropout 0,1), lớp Dense 64 |
| Đầu ra | 6 giá trị mưa cho +1h…+6h, kích hoạt softplus. Ở LIVE chỉ dự báo mưa |
| Hàm mất mát, tối ưu | MSE trên `log1p(mưa)`, Adam 0,001, dừng sớm sau 3 epoch không cải thiện |
| Chia dữ liệu | 70/15/15 theo thời gian; chuẩn hoá chỉ học từ tập train |
| Chọn mô hình | Bản có `val_loss` nhỏ nhất được kích hoạt |
| So sánh | Baseline persistence (giữ giá trị hiện tại) và khí hậu |

**Trạm mới hoặc thiếu dữ liệu (cold-start):**

- Thời điểm thiếu được đánh dấu bằng cờ `missing`.
- Trạm mượn cửa sổ dữ liệu của trạm lân cận cùng cụm (CORE, INNER, SUBURBAN), rồi tới trạm gần nhất.
- Mỗi cụm có thể có mô hình tinh chỉnh riêng (`GRU_CLUSTER`). Mô hình cụm chỉ được giữ nếu `val_loss` tốt hơn mô hình nền.

**Kết quả:** MAE khoảng 0,37 mm, tốt hơn baseline persistence (0,49). Dự báo **mưa to rất yếu**: F1 khoảng 6% với mưa từ 5 mm/h. Chi tiết ở [ai-methodology.md](ai-methodology.md).

### 6.3 Xác suất ngập ước tính

File: `services/flood_index.py`. Chưa có đủ nhãn ngập thật để học, nên xác suất dùng công thức logistic với hệ số chọn định tính. Đã thử cho GRU học xác suất ngập từ 74 sự kiện báo chí, nhưng kết quả kém hơn công thức này nên không dùng.

```text
z = −5 + 0,22·mưa_1h + 0,07·mưa_3h
    + 1,5·min(max(r, 0), 1,5)·k            k = 1 nếu độ cao < 8 m, ngược lại 0,3
    + 0,35·min(max(4 − độ_cao, −6), 4)
    + 1,2  nếu gần điểm ngập thường xuyên
    + 0,8  nếu là điểm ngập nặng

xác suất = 1 / (1 + e^(−z))
```

**Ví dụ:** mưa 15 mm/h, 35 mm trong 3 giờ, r = 0,5, độ cao 3 m, có điểm ngập:

```text
z = −5 + 3,3 + 2,45 + 0,75 + 0,35 + 1,2 = 3,05   →   xác suất ≈ 95,5%
```

`r` là tỉ lệ triều (mục 6.4). "Điểm ngập nặng" là nơi nằm trong 500 m quanh một trận ngập lịch sử sâu từ 30 cm.

### 6.3b LSTM xác suất ngập theo quận (chỉ hiển thị)

File: `ai/forecasting/flood_district.py`, huấn luyện bằng `scripts/experiment_flood_district.py --register`.

- **Bài toán:** xác suất "quận có ngập trong 6 giờ tới".
- **Đầu vào:** 24 giờ gần nhất gồm mưa, triều đã lệch 4 giờ, giờ trong ngày, độ cao, có điểm ngập, quận ven triều.
- **Nhãn:** 246 trận ngập báo chí (65 ngày, 11/2024–11/2026), mỗi trận có URL bài gốc.
- **Hiệu chỉnh:** xác suất được hiệu chỉnh Platt trên tập validation. Trên tập test, xác suất trung bình dự báo là 0,23% so với tần suất ngập thật 0,17%.
- **Kết quả test:** PR-AUC 0,038 so với 0,005 của công thức (6.3). Qua cổng ở cả 3 lần chạy với seed khác nhau (bảng đầy đủ trong `ai-methodology.md`).
- **Chưa dùng phát cảnh báo:** tỉ lệ bắt được ngày ngập ở ngưỡng cảnh báo còn thấp (0,12–0,36). Kết quả chỉ hiện ở Dự báo AI, báo cáo PDF và lưu trong `explanation.lstm_flood_6h` của snapshot quận.

### 6.4 Triều: độ trễ và phạm vi ảnh hưởng

```text
r = (mực nước − P50) / (P95 − P50)
```

P50 và P95 là trung vị và phân vị 95 của mực nước biển trong 1 năm gần nhất (hiện khoảng 100 và 196 cm). r = 1 tương ứng mức triều cao thường gặp.

- **Độ trễ 4 giờ** (`TIDE_LAG_H`): đường phố TP.HCM ngập muộn hơn đỉnh triều ở Vũng Tàu. Ví dụ ngày 27/10/2026, Vũng Tàu đạt đỉnh lúc 14:00, còn đường phố ngập từ 16:30 đến khoảng 19:00. Con số 4 giờ rút ra từ 7 mốc báo chí, khoảng hợp lý là 3–5 giờ. Khi cần triều tại thời điểm t, hệ thống lấy giá trị Vũng Tàu tại t − 4 giờ.
- **Phường bị triều** (`risk_service.tide_exposed_wards`, hiện 64 phường): phường có độ cao dưới 8 m và thuộc Quận 7, Nhà Bè, Cần Giờ, Quận 8, Quận 4, Quận 2, Bình Thạnh hoặc Thủ Đức, cộng các phường có điểm ngập do triều cường. Phường ngoài danh sách này có tỉ lệ triều bằng 0.
- `water_level_ratio` chỉ dành cho trạm đo mực nước thật; triều mô hình không tự ép mức Cao.

### 6.5 Tín hiệu mưa dông đa mô hình

File: `services/risk_service.py::storm_counts`, `services/openmeteo_service.py::storm_model_counts`.

- Mỗi chu kỳ đếm xem trong 7 mô hình thời tiết có bao nhiêu mô hình báo tổng mưa 3 giờ tới từ 10 mm tại mỗi điểm lưới.
- Nếu từ 2 mô hình trở lên cùng báo (`storm_min_models`, mặc định 2), các mốc 0–3 giờ được **nâng tối đa tới mức Trung bình**, với lý do "Nguy cơ mưa dông cục bộ (ước tính)". Tín hiệu này không bao giờ ép lên mức Cao.
- Chỉ áp cho phường thấp (dưới 8 m) hoặc có điểm ngập. Chỉ chạy ở LIVE, khi thời điểm đánh giá nằm trong 3 giờ quanh hiện tại, vì Open-Meteo không lưu dự báo đa mô hình của quá khứ.
- **Đánh giá trên 2 năm** (17.664 ngày-quận, 20 quận-ngày ngập do mưa theo báo chí): bắt được 8/20 (40%); số ngày-quận bị báo là 4,7%, tốt hơn báo ngẫu nhiên khoảng 5 lần. Ngưỡng được chọn trên chính tập đánh giá nên con số có thể lạc quan.

### 6.6 Độ sâu và lý do ngập

| Nguồn | Công thức | Áp dụng cho |
|---|---|---|
| Triều | Nếu r ≥ 1,15: `min(60, 20 + 70·(r − 1,15))` cm; ngược lại 0 | Phường bị triều |
| Mưa | `min(40, 1,5·max(0, mưa_3h − 20))` cm | Phường dưới 8 m hoặc có điểm ngập |
| Báo cáo đã xác nhận | Mắt cá 10, đầu gối 40, sâu 70 cm | Phường có báo cáo, ở mốc 0 và +1h |

- Độ sâu của phường là giá trị lớn nhất trong 3 nguồn, làm tròn tới 10 cm. Dưới 5 cm thì không ghi con số.
- Ngưỡng r = 1,15 lấy từ mức triều thấp nhất từng có tin ngập (1,146). Mức này xảy ra khoảng 49 ngày mỗi năm, đều trong tháng 10 đến tháng 2.
- **Mã lý do** (`cause`) và câu hiển thị:

| `cause` | Câu hiển thị |
|---|---|
| `TIDE` | Ngập do triều, khoảng X cm (ước tính) |
| `RAIN` | Ngập do mưa, khoảng X cm (ước tính) |
| `RAIN_TIDE` | Ngập do mưa kết hợp triều |
| `REPORT` | Người dân báo ngập |
| `CAMERA` | Camera phát hiện ngập (mô hình thử nghiệm, tham khảo) |
| `STORM` | Nguy cơ mưa dông cục bộ (ước tính) |
| `SIMULATION` | MÔ PHỎNG: ngập giả định do admin tạo, khoảng X cm |

**Đối chiếu với thực tế:** r = 1,417 (27/10/2026) cho khoảng 39 cm, báo chí ghi 20–50 cm. r = 1,19 (10/10/2026) cho khoảng 23 cm, báo chí ghi khoảng 50 cm. Công thức chỉ có 3 mốc độ sâu của 2 đợt triều; phần mưa chưa có mốc kiểm chứng.

### 6.7 Phân loại mức nguy cơ

File: `services/rule_engine.py` (hàm thuần, không phụ thuộc cơ sở dữ liệu), `services/risk_service.py`.

**Bước 1: tính điểm.** Mỗi đầu vào được đưa về [0, 1], cộng có trọng số, rồi chia cho tổng trọng số của các đầu vào có dữ liệu.

| Thành phần | Trọng số mặc định | Cách chuẩn hoá |
|---|---|---|
| Xác suất ngập | 0,45 | Giữ nguyên |
| Mưa | 0,20 | mưa / 40 mm, cắt tại 1 |
| Mực nước | 0,20 | Trạm đo thật; nếu không có thì dùng tỉ lệ triều, cắt về [0, 1] |
| Camera | 0,10 | tỉ lệ ngập / 0,5, cắt tại 1 (chỉ ở mốc 0 và +1h) |
| Lịch sử | 0,05 | Độ nhạy ngập của khu vực |

**Bước 2: kiểm tra dữ liệu.** Nếu tổng trọng số có dữ liệu dưới 0,5, hoặc dữ liệu mưa/triều cũ quá 180 phút, thì điểm số không còn tin được. Khi đó hệ thống vẫn xét các **bằng chứng trực tiếp**, vì chúng có hạn dùng riêng:

- báo cáo ngập đã có người xác nhận (hiệu lực 3 giờ) → **Cao**;
- camera thấy từ 40% vùng quan sát bị ngập (kết quả trong 90 phút) → **Cao**;
- báo cáo chưa xác nhận → **Trung bình**.

Câu lý do ghi kèm "(dữ liệu mưa/triều không đủ)". Không có bằng chứng nào thì kết quả là **Không đủ dữ liệu**.

**Bước 3: xếp mức theo điểm.** Từ 0,6 là **Cao**, từ 0,35 là **Trung bình**, còn lại là **Thấp**.

**Bước 4: ép thẳng lên mức Cao** khi có một trong các điều kiện:

- xác suất ngập từ 80%;
- trạm đo thật báo mực nước đạt ngưỡng;
- camera thấy từ 40% vùng quan sát bị ngập;
- độ sâu ước tính từ 20 cm;
- báo cáo ngập đã có người xác nhận.

Ngoài ra, báo cáo chưa xác nhận chỉ nâng phường lên tối thiểu **Trung bình**, và mưa dông chỉ nâng tối đa tới **Trung bình**.

**Bước 5: chống dao động.** Khi không có điều kiện ép, mức chỉ được hạ nếu điểm giảm xuống dưới ngưỡng của mức trước trừ 0,05.

**Phường và quận:** phường được tính trước. Quận lấy độ sâu, lý do và số xác nhận của phường xấu nhất, kèm danh sách các phường có độ sâu (nhiều nhất 8 tên, sâu nhất trước). Báo cáo chưa xác nhận không được đẩy lên cấp quận.

**Ví dụ:**

- Phường Tân Phong (Quận 7) lúc r = 1,417: độ sâu 38,7 cm, từ 20 cm nên lên mức Cao. Câu lý do là "Ngập do triều, khoảng 40 cm (ước tính)".
- Phường Bình Trưng Tây (độ cao 8 m) không thuộc diện bị triều, nên với cùng mức triều đó nó vẫn ở mức Thấp nếu không có mưa.

Quy tắc được lưu theo phiên bản trong bảng `alert_rules`. Mỗi lần lưu tạo một phiên bản mới; không sửa đè phiên bản cũ.

### 6.8 Sinh và cập nhật cảnh báo

File: `services/alert_service.py`.

- Chỉ tạo cảnh báo **cấp quận**, từ mức Trung bình trở lên. Mức của cảnh báo là mức xấu nhất trong 7 mốc; nếu nhiều mốc cùng mức thì lấy mốc sớm nhất.
- **Mỗi quận có tối đa một cảnh báo đang mở:**
  - mức mới cao hơn thì nâng mức và gửi lại thông báo "Nâng mức cảnh báo";
  - cùng mức thì chỉ cập nhật nội dung, không gửi lại;
  - mức thấp hơn thì giữ nguyên.
- **Thời gian chờ:** sau khi xử lý xong hoặc đóng, cùng quận và cùng mức không tạo cảnh báo mới trong 60 phút.
- Mỗi cảnh báo mới hoặc nâng mức tạo thông báo cho mọi cán bộ đang hoạt động.

### 6.9 Báo cáo ngập của người dân

File: `services/report_service.py`.

| Quy định | Giá trị |
|---|---|
| Hiệu lực | 3 giờ; mỗi lần xác nhận bảo đảm còn ít nhất 1 giờ |
| Giới hạn gửi | 5 báo cáo / 10 phút / tài khoản |
| Xác nhận | Người khác đã đăng nhập, mỗi người một lần, không tự xác nhận |
| Từ chối | Chỉ cán bộ |
| Ảnh hưởng | Chưa xác nhận: tối thiểu mức Trung bình. Đã xác nhận: mức Cao (mốc 0 và +1h) |

### 6.10 Chỉ đường và đánh giá ngập từng đoạn

File: `services/routing_service.py`.

1. OSRM trả tối đa 3 tuyến; khoảng cách tối đa 80 km.
2. Mỗi tuyến được chia thành các đoạn khoảng 200 m, lấy độ cao tại điểm giữa mỗi đoạn.
3. Mỗi đoạn được tính xác suất và độ sâu từ:
   - mưa của điểm lưới gần nhất;
   - triều: chỉ khi đoạn dưới 8 m và cách tâm một phường bị triều không quá 1,5 km;
   - độ cao;
   - điểm ngập trong 150 m;
   - báo cáo ngập trong 100 m;
   - vùng mô phỏng (chỉ với tài khoản cán bộ).
4. Trạng thái của đoạn xét theo thứ tự ưu tiên:

| Trạng thái | Điều kiện |
|---|---|
| Người dân báo ngập | Có báo cáo còn hiệu lực trong 100 m |
| Có thể đang ngập | Độ sâu từ 20 cm, xác suất từ 60%, hoặc đi qua vùng mô phỏng (cán bộ) |
| Có nguy cơ ngập | Có độ sâu ước tính, hoặc xác suất từ 30% |
| Không có dấu hiệu | Các trường hợp còn lại |

5. **Tuyến đề xuất:** ít km ngập nhất; nếu bằng nhau thì ít đoạn có nguy cơ hơn (quá 0,5 km); rồi tới tuyến nhanh nhất.

### 6.11 Mô phỏng ngập

File: `services/simulation_overlay.py`.

1. Tìm mọi quận và phường giao với vòng tròn mô phỏng, bằng PostGIS: `ST_DWithin(geom::geography, tâm::geography, bán_kính)`.
2. Mức mô phỏng của một khu vực là **Cao** nếu độ sâu từ 20 cm (cùng ngưỡng với luật cảnh báo), ngược lại **Trung bình**. Nếu một khu vực nằm trong nhiều vùng, lấy độ sâu lớn nhất.
3. Mức thật chỉ được **nâng lên**, không bao giờ bị hạ. Nếu mức thật đã cao hơn, giữ mức thật.
4. Dữ liệu ảo được ghép vào kết quả **lúc đọc**:
   - mỗi quận bị ảnh hưởng thành một cảnh báo ảo, id âm, mã `SIM-<mã quận>`;
   - mỗi vùng thành một dòng lịch sử ngập ảo, id âm;
   - thống kê được cộng thêm phần mô phỏng.

   Chỉ cán bộ nhận dữ liệu này. Không có gì được ghi vào bảng thật, nên xoá vùng mô phỏng là mọi dấu vết biến mất ngay.

### 6.12 Nhận diện ngập qua camera

File: `ai/computer_vision/`, `services/camera_service.py`.

- YOLOv8n-seg phân đoạn vùng nước (ảnh 320 px, ngưỡng tin cậy 0,25), rồi tính tỉ lệ diện tích ngập trong vùng quan sát (ROI; mặc định phần dưới của ảnh).
- Khi không có trọng số mô hình, hệ thống dùng phương pháp dự phòng theo ngưỡng màu HSV. Kết quả được ghi rõ phương pháp "Heuristic".
- **Mô hình đang dùng** (id 12, 19/11/2026) học tiếp từ mô hình cũ (id 8) trên hai nguồn:
  - 290 ảnh ngập thật Kaggle "Flood Area Segmentation";
  - 292 ảnh camera giao thông TP.HCM chụp lúc trời khô (`scripts/collect_dry_camera_frames.py`) làm **ảnh nền**, tức ảnh không có nước, để mô hình học rằng mặt đường không phải nước. Ảnh được chia theo camera (221 train, 34 val, 37 test, không trùng camera).

| Đo trên | Mô hình cũ (id 8) | Mô hình mới (id 12) |
|---|---|---|
| 44 ảnh ngập Kaggle (test): mask mAP50 / recall | 0,450 / 0,483 | **0,507 / 0,517** |
| Ảnh khô của 37 camera chưa từng đưa vào huấn luyện: báo giả | 91,9% (34/37) | **0%** (0/37) |
| Camera thật đang chạy, báo giả 2 lần liên tiếp (luật của quét tự động) | 91% (134/147, đêm 16/11) | **0,8%** (1/119, đêm 20/11) |

  Ca báo giả còn lại (camera Võ Văn Ngân – Đặng Văn Bi) là ảnh mờ đục, ám xanh toàn khung do sương hoặc ống kính bẩn, mặt đường không ngập. Mô hình chỉ được dùng thay mô hình cũ khi báo giả lúc khô giảm **và** mask mAP50 không tụt quá 0,05 (`train_and_register`).
- **Quét tự động camera giao thông** (`CAMERA_SCAN_ENABLED`) đã cài nhưng vẫn **tắt**. Khi bật, cứ 15 phút quét tối đa 20 camera trong bán kính 500 m quanh điểm ngập; cần 2 lần phát hiện liên tiếp mới tính, và lấy giá trị thấp hơn. Kết quả quét có thể đẩy một phường lên mức Cao và sinh cảnh báo công khai, nên chưa bật vì:
  - mọi ảnh khô đều chụp **ban đêm**, chưa đo ban ngày;
  - chưa có ảnh camera TP.HCM lúc **ngập thật**, nên chưa biết mô hình có bỏ sót ngập thật trên camera giao thông không;
  - camera có ảnh mờ đục như ca trên vẫn có thể báo giả.

  Nên thu thêm ảnh ban ngày bằng `collect_dry_camera_frames.py` (chạy lại vào giờ khác, ảnh được cộng dồn), huấn luyện lại, rồi đo lại bằng `scripts/experiment_camera_fp.py` trước khi bật.

### 6.13 Tính lại dữ liệu quá khứ

`jobs/backfill.py` chạy lại dự báo và đánh giá nguy cơ cho từng giờ trong N ngày, chỉ dùng dữ liệu có tới mốc giờ đó (`latest_values(as_of=…)`).

- Ở LIVE luôn chạy với `alerts=False` để không dựng lại cảnh báo chưa từng được phát.
- Thêm `force=True` khi cần tính lại dữ liệu đã có.

Kết quả là số **tính lại**, không phải bản đã phát hành vào thời điểm đó.

---

## 7. Cơ chế hệ thống

### 7.1 Kiến trúc và dữ liệu

| Cơ chế | Cách hoạt động |
|---|---|
| Kiến trúc | Backend MVC: `models` (SQLAlchemy), `schemas` (Pydantic, đóng vai View), `controllers` (router `/api/v1`), `services` (nghiệp vụ), `repositories`. Giao diện Streamlit (`streamlit_app/`) chỉ gọi REST API qua `api.py`, không truy cập cơ sở dữ liệu trực tiếp |
| Cơ sở dữ liệu | PostgreSQL 16 + PostGIS 3.4. Hình học `geometry(…, 4326)` theo thứ tự lon/lat, có chỉ mục GiST. Tìm kiếm không phân biệt hoa thường và dấu (`unaccent` + `ILIKE`); tên đăng nhập và email là CITEXT |
| Thời gian | Cơ sở dữ liệu lưu UTC không múi giờ; API trả ISO có hậu tố `Z`; giao diện hiển thị giờ Việt Nam |
| Khu vực hai cấp | 24 quận/huyện và 322 phường/xã. Cảnh báo và thống kê tính theo quận; phường dùng để hiển thị và tính nguy cơ |
| Nhiều worker | Trạng thái dùng chung nằm trong PostgreSQL: bộ đếm giới hạn tốc độ (bảng `rate_limit_hits`), sự kiện thời gian thực (`pg_notify`/`LISTEN`), quyền chạy lịch (chỉ worker giữ `pg_try_advisory_lock(7340, 1)`). Tắt worker đang giữ lịch thì worker khác nhận ở chu kỳ sau. Docker mặc định chạy 2 worker |
| Chu kỳ song song | `evaluate_all` lấy `pg_advisory_xact_lock` để hai chu kỳ không ghi chồng lên nhau |
| Thời gian thực | SSE tại `/api/v1/events`; sự kiện nội bộ chỉ gửi cho cán bộ. Server Streamlit có một luồng nền nghe SSE (ẩn danh, nên chỉ nhận sự kiện công khai, `streamlit_app/live.py`). Mỗi phiên trình duyệt kiểm tra bộ đếm sự kiện mỗi 3 giây, có sự kiện mới thì chạy lại trang. Trình duyệt không cần nối thẳng tới backend, nên chạy được cả trong Docker |
| Giải thích kết quả | Cột JSON `explanation` lưu đầu vào, điểm từng thành phần, điều kiện ép mức, `cause`, `depth_cm`, `wards`. Người dân chỉ nhận `cause`, `depth_cm`, `wards` |
| Dữ liệu mô phỏng | Dữ liệu sinh ở chế độ DEMO luôn có `is_simulated=True` và nguồn `SIMULATED`. Vùng mô phỏng ngập của admin không ghi vào bảng thật (mục 6.11) |
| Nhật ký | Mọi thao tác ghi quan trọng gọi `audit()`; xem ở Cấu hình › Nhật ký |
| Lỗi cơ sở dữ liệu | Mất kết nối PostgreSQL thì API trả **503** `DB_UNAVAILABLE`, kèm câu "Không kết nối được cơ sở dữ liệu, kiểm tra PostgreSQL" |

### 7.2 Bảo mật và giới hạn tốc độ

- **Xác thực:** JWT kiểu Bearer, hết hạn sau 480 phút. Streamlit giữ token trong `st.session_state`, và lưu thêm vào cookie `octo_session` (`SameSite=Strict`, `Secure` khi chạy HTTPS) để còn đăng nhập sau khi tải lại trang. Cookie này do JavaScript ghi nên không phải HttpOnly: nếu trang bị chèn mã độc (XSS) thì token có thể bị đọc. Vì vậy mọi dữ liệu do người dùng nhập đều được escape trước khi hiển thị, và token chỉ được đưa vào script khi đúng dạng JWT. Đăng xuất hoặc đổi mật khẩu làm mọi token cũ mất hiệu lực ở backend. Mật khẩu băm bằng bcrypt.
- **Phân quyền:** `Operator`, `Admin`, `OptionalUser`, `is_staff` trong `core/deps.py`.
- **Giới hạn tốc độ** (`core/security.py`, lưu trong PostgreSQL):

| Giới hạn | Mức | Ghi chú |
|---|---|---|
| Đăng nhập theo IP + tên đăng nhập | 10 lần / phút | |
| Đăng nhập theo IP | 30 lần / phút | Chặn thử lần lượt nhiều tài khoản |
| Đăng nhập **sai** theo tài khoản | 20 lần / 15 phút | Không phụ thuộc IP, nên đổi IP giả cũng không vượt được; đăng nhập đúng không tính vào hạn mức |
| Đổi mật khẩu | 10 lần / 15 phút / người dùng | Mỗi lần sai ghi `PASSWORD_CHANGE_FAILED` vào nhật ký |
| Gửi báo cáo ngập | 5 / 10 phút / tài khoản | |
| Chỉ đường | 30 / phút / IP | |
| Ảnh camera giao thông | 60 / phút / IP | |

Streamlit gửi kèm IP thật của người dùng trong `X-Forwarded-For`, và uvicorn chỉ tin header này khi nó đến từ 127.0.0.1. Nhờ vậy giới hạn theo IP đúng với từng người dùng.

### 7.3 Chế độ chạy

| Biến | Ý nghĩa |
|---|---|
| `DEMO_MODE` | `true`: dữ liệu mô phỏng (dùng khi chạy test). `false`: dữ liệu thật từ Open-Meteo |
| `CAMERA_ENABLED` | Bật trang Camera và phân tích ảnh |
| `CAMERA_SCAN_ENABLED` | Bật quét tự động camera giao thông (mặc định tắt) |
| `CAMERA_HEALTH_PER_CYCLE` | Số camera giao thông kiểm tra ảnh mỗi chu kỳ, mặc định 8; 0 là tắt |
| `TRAFFIC_CAMERA_BASE` | Địa chỉ cổng camera của thành phố, mặc định `https://giaothong.hochiminhcity.gov.vn` |
| `LIVE_EVENTS` | Giao diện: `0` tắt luồng nghe SSE (dùng khi chạy test) |
| `EARTHDATA_TOKEN` | Token NASA Earthdata (miễn phí) để lấy mưa vệ tinh IMERG; để trống thì không lấy |
| `SCHEDULER_INTERVAL_SECONDS` | Độ dài chu kỳ, mặc định 300 |

### 7.4 Chi phí: toàn bộ miễn phí

Dự án không dùng dịch vụ hay thư viện trả phí nào. Bảng dưới ghi điều kiện để được dùng miễn phí của từng thứ:

| Thành phần | Dùng cho | Điều kiện miễn phí |
|---|---|---|
| Open-Meteo (forecast, archive, marine, elevation, historical-forecast) | Mưa, triều, độ cao, dự báo đa mô hình | Miễn phí cho mục đích phi thương mại, dưới 10.000 lần gọi/ngày (hệ thống dùng khoảng vài trăm/ngày); thương mại phải mua gói |
| NASA Earthdata, GPM IMERG | Mưa vệ tinh | Miễn phí, chỉ cần tài khoản (token trong `backend/.env`) |
| Photon (komoot) | Tìm địa chỉ | Máy chủ công cộng miễn phí, dùng vừa phải; vận hành thật nên tự cài |
| OSRM (router.project-osrm.org) | Chỉ đường | Máy chủ demo miễn phí, không cam kết; vận hành thật nên tự cài |
| OSM France (bản đồ nền HOT) | Bản đồ nền | Miễn phí, dùng vừa phải, phải ghi nguồn OpenStreetMap |
| Google Fonts (Google Sans, Roboto) | Font giao diện | Miễn phí |
| Cổng thông tin giao thông TP.HCM | Ảnh camera | Công khai, không thu phí; hệ thống cache 30 giây để không dồn tải |
| GADM, geoBoundaries | Ranh giới | GADM miễn phí cho học thuật, phi thương mại; geoBoundaries CC BY 4.0 |
| Kaggle "Flood Area Segmentation" | Ảnh huấn luyện YOLOv8 | CC0 |
| PostgreSQL, PostGIS, FastAPI, Streamlit, TensorFlow/Keras, scikit-learn, pandas, matplotlib, Folium, Plotly | Toàn bộ phần mềm | Mã nguồn mở, miễn phí |
| Ultralytics YOLOv8 | Nhận diện ngập | AGPL-3.0: miễn phí; nếu phân phối hoặc cung cấp như dịch vụ thì phải công khai mã nguồn (đồ án đã công khai trên GitHub) |
| GitHub, GitHub Actions | Lưu code, CI Docker | Miễn phí (repo private có 2.000 phút CI/tháng) |
| Docker Desktop | Chạy Docker trên máy | Miễn phí cho cá nhân, giáo dục, doanh nghiệp nhỏ |

---

## 8. Vận hành và lệnh

Các lệnh dưới đây chạy từ thư mục `backend`, đặt `$env:PYTHONUTF8="1"` trước, và PostgreSQL phải đang chạy (`npm run dev` tự bật nó).

| Mục đích | Lệnh |
|---|---|
| Chạy toàn bộ hệ thống | `npm run dev` (ở thư mục gốc) |
| Khởi động PostgreSQL bằng tay | `E:\pgsql\bin\pg_ctl -D E:\pgsql\data -l E:\pgsql\server.log -w start` |
| Khởi tạo toàn bộ (chạy lại an toàn) | `.venv\Scripts\python scripts\bootstrap.py` |
| Chỉ chạy API | `.venv\Scripts\python -m uvicorn app.main:app --port 8000` |
| Chỉ chạy giao diện | `cd ..\streamlit_app; ..\backend\.venv\Scripts\python -m streamlit run app.py --server.port 5173` |
| Chạy bằng Docker | `docker compose up --build` (giao diện ở cổng 8501) |
| Nạp phường | `.venv\Scripts\python scripts\import_wards.py` |
| Nạp camera giao thông | `.venv\Scripts\python scripts\import_traffic_cameras.py` |
| Nạp lịch sử ngập từ CSV | `.venv\Scripts\python scripts\import_flood_events.py` |
| Đặt lại mật khẩu | `.venv\Scripts\python scripts\set_password.py --username <tên> --password <mật khẩu>` |
| Huấn luyện dự báo | `.venv\Scripts\python -m app.ai.forecasting.train --epochs 8` |
| Tinh chỉnh mô hình theo cụm | `.venv\Scripts\python -m app.ai.forecasting.train --finetune-clusters --epochs 2` |
| Huấn luyện YOLOv8 | `.venv\Scripts\python -m app.ai.computer_vision.train --epochs 15` |
| Đánh giá mức nguy cơ (chỉ đọc) | `.venv\Scripts\python scripts\evaluate_risk.py` |
| Đo báo giả của camera | `.venv\Scripts\python scripts\experiment_camera_fp.py` |
| Thu ảnh camera lúc khô (chỉ chạy khi 6 giờ không mưa) | `.venv\Scripts\python scripts\collect_dry_camera_frames.py --n 300` |
| Huấn luyện tiếp YOLOv8 với ảnh khô | `.venv\Scripts\python -m app.ai.computer_vision.train --data ..\datasets\vision\flood_hcm\data.yaml --from-active --epochs 30` |
| Áp migration mới | `.venv\Scripts\python -m alembic upgrade head` |
| Lấy lùi mưa vệ tinh IMERG (chỉ ngày còn thiếu) | `.venv\Scripts\python scripts\import_imerg.py --start 2024-11-01` |
| So sánh IMERG với Open-Meteo | `.venv\Scripts\python scripts\compare_imerg_openmeteo.py` |
| Huấn luyện và đăng ký LSTM ngập theo quận | `.venv\Scripts\python scripts\experiment_flood_district.py --cells lstm --register` |
| Đo hiệu năng | `.venv\Scripts\python scripts\benchmark.py --cycles 0` |
| Kiểm thử backend | `.venv\Scripts\python -m pytest -q` (dùng cơ sở dữ liệu test riêng) |
| Kiểm thử giao diện | `backend\.venv\Scripts\python -m pytest -q streamlit_app\tests` (từ thư mục gốc) |
| Kiểm tra code | `.venv\Scripts\ruff check app` |
| Xuất Postman | `.venv\Scripts\python scripts\export_postman.py` |

**Tính lại N ngày sau khi đổi logic** (nên dừng server trước):

```powershell
.venv\Scripts\python -c "from app.core.database import SessionLocal; from app.jobs.backfill import backfill; db=SessionLocal(); print(backfill(db, days=14, alerts=False, force=True))"
```

**Thêm một trận ngập thật:** thêm một dòng vào `datasets/gis/flood_events.csv`, kèm URL bài gốc đã đọc; chỉ ghi độ sâu khi bài báo nêu số. Sau đó chạy `import_flood_events.py`. Chạy lại không tạo trùng.

**Đổi thư mục dự án:** cột `model_versions.artifact_path` chứa đường dẫn tuyệt đối, nên phải cập nhật lại. Nếu không, mọi chu kỳ dự báo sẽ lỗi.

---

## 9. Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Trang báo lỗi, API trả 503 `DB_UNAVAILABLE` | PostgreSQL chưa chạy, thường do máy vừa khởi động lại | Chạy `npm run dev` (tự bật), hoặc chạy lệnh `pg_ctl … start` |
| `npm run dev` báo "Cổng … đang bị chiếm" | Lần chạy trước chưa tắt, hoặc chương trình khác đang dùng cổng 5173 | Tắt tiến trình đó rồi chạy lại |
| Bản đồ nền màu xám, không có đường phố | Mạng chặn máy chủ bản đồ nền | Hệ thống đã dùng OSM France; nếu vẫn xám thì kiểm tra mạng có tới được `tile.openstreetmap.fr` |
| Mất đăng nhập sau khi bấm F5 | Trình duyệt chặn cookie, hoặc phiên đã quá 8 giờ | Cho phép cookie cho trang, rồi đăng nhập lại |
| "Quá nhiều lần đăng nhập" | Chạm giới hạn ở mục 7.2 | Chờ vài phút; admin có thể đặt lại mật khẩu bằng `set_password.py` |
| Bảng Tình hình toàn "Không đủ dữ liệu" | Dữ liệu cũ quá 180 phút (mất mạng lâu) | Kiểm tra mạng; Cấu hình › Vận hành › "Chạy chu kỳ xử lý ngay" |
| Camera "không có ảnh" | Camera của thành phố tạm ngừng, hoặc chạm giới hạn 60 ảnh/phút | Bấm "Làm mới ảnh" sau ít phút. Camera lỗi 3 lần kiểm tra liên tiếp sẽ tự ẩn khỏi danh sách, và tự hiện lại khi có ảnh |
| Mọi camera giao thông đều lỗi | Cổng thông tin giao thông sập hoặc đổi địa chỉ | Log backend có cảnh báo "cổng thành phố sập hoặc đổi địa chỉ"; hệ thống không tự ẩn camera nào trong trường hợp này. Nếu đổi địa chỉ, đặt biến `TRAFFIC_CAMERA_BASE` |
| Nút ◎ báo "Không lấy được vị trí" | Trình duyệt chặn quyền vị trí, hoặc máy không có GPS/Wi-Fi định vị | Cho phép quyền vị trí cho trang (biểu tượng ổ khoá trên thanh địa chỉ); trang phải mở qua `localhost` hoặc HTTPS |
| Vẫn đăng nhập sau khi tắt trình duyệt | Cookie phiên giữ 8 giờ | Bấm "Đăng xuất" khi dùng máy chung |
| Mọi chu kỳ dự báo lỗi sau khi chuyển thư mục | `artifact_path` vẫn trỏ thư mục cũ | Cập nhật `model_versions.artifact_path` |

---

## 10. Hạn chế cần biết

- **Độ sâu chỉ là ước tính:** dựa trên 3 mốc của 2 đợt triều; đợt 10/10/2026 bị ước thấp khoảng 27 cm. Chưa có dữ liệu ngày khô nên chưa biết tỉ lệ báo động giả thật.
- **Mưa cục bộ vẫn khó bắt:** trận 04/11/2026 ngập trên 30 cm nhưng lưới Open-Meteo chỉ ghi tối đa 1,0 mm/h. Tín hiệu mưa dông đa mô hình bắt được khoảng 40% ngày ngập do mưa trong đánh giá 2 năm, và chỉ nâng tới mức Trung bình. Báo cáo của người dân vẫn là nguồn bù quan trọng nhất.
- **Dữ liệu "quan trắc" mưa là đầu ra mô hình** (trùng 99,9% với dự báo best-match của Open-Meteo). Vì vậy MAE và F1 dự báo mưa chỉ phản ánh mức bám theo mô hình đó, không phải theo mưa đo thật. Mưa vệ tinh GPM IMERG đã được thêm làm nguồn đo độc lập để đối chiếu, nhưng trễ 1–2 ngày và chỉ theo ngày.
- **Dự báo mưa to rất yếu:** F1 khoảng 6% với mưa từ 5 mm/h. Thêm dữ liệu GFS không cải thiện đáng kể.
- **Triều chỉ có một số đo** tại Vũng Tàu; không có mực nước cống và kênh của thành phố.
- **Độ cao kém phân biệt:** mỗi phường là một mẫu DEM 90 m tại tâm, nên phạm vi bị triều phải dựa thêm vào danh sách quận.
- **Mưa như nhau trong một quận:** các phường dùng chung điểm lưới mưa của quận cha.
- **Camera:** báo giả lúc khô đã giảm từ 91% xuống 0,8% nhờ học thêm ảnh khô của camera TP.HCM. Nhưng mới đo ban đêm, chưa có ảnh ngập thật của camera giao thông, và camera ảnh mờ đục vẫn có thể báo giả, nên quét tự động vẫn tắt. Danh sách camera là bản chụp ngày 06/11/2026 (camera hỏng tự ẩn, xem mục 5.9).
- **Mô phỏng ngập** chỉ là vòng tròn theo khoảng cách, không mô phỏng dòng chảy. Biểu đồ cảnh báo theo thời gian và thông báo không tính mô phỏng.
- **Dữ liệu mưa/triều cũ quá 3 giờ** làm khu vực về "Không đủ dữ liệu" nếu không có báo cáo ngập hay kết quả camera. Báo cáo và camera vẫn đẩy được mức nguy cơ (mục 6.7).
- **Ranh giới hành chính** theo cấu trúc trước 07/2025; khu vực Dĩ An nằm ngoài ranh giới hiện có. Giấy phép GADM chỉ cho mục đích học thuật, phi thương mại.
- **Cập nhật tức thì chỉ với sự kiện công khai:** đổi trạng thái cảnh báo (sự kiện nội bộ) vẫn chờ lượt hỏi lại 60 giây. Mỗi lần có sự kiện, trang chạy lại toàn bộ.
- **Dịch vụ công cộng:** OSRM và Photon không cam kết sẵn sàng; OSRM chỉ có profile ô tô.
- **Sẵn sàng cao chưa hoàn chỉnh:** chạy được nhiều worker, nhưng PostgreSQL chỉ có một máy, chưa có bản sao dự phòng.

Chi tiết thêm: [ai-methodology.md](ai-methodology.md), [known-limitations.md](known-limitations.md), [api-design.md](api-design.md), [database-design.md](database-design.md), [architecture.md](architecture.md), [testing-report.md](testing-report.md).
