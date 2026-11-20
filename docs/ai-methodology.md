# Phương pháp AI

## 0. Chế độ dữ liệu thật (đang vận hành)

**Dữ liệu**: mưa giờ Open-Meteo 2 năm tại tâm 24 quận/huyện (438.136 bản ghi cùng chuỗi triều), kiểm tra hợp lý: ~2.150 mm/năm;
mưa giờ lớn nhất ~22 mm vì tái phân tích làm mượt cực trị.

**Dự báo mưa 1–6 giờ** (chỉ đầu ra mưa, chia 70/15/15 theo thời gian, 62.448 cửa sổ test):

| Mô hình | MAE (mm) | RMSE | MAE +1h | MAE +6h | Mưa to ≥5 mm/h: P / R / F1 |
|---|---|---|---|---|---|
| Persistence | 0,486 | 1,225 | 0,362 | 0,551 | 0,02 / 0,02 / 0,02 |
| Khí hậu (trung bình train) | 0,419 | 0,942 | 0,419 | 0,419 | 0 / 0 / 0 |
| LSTM | 0,369 | 0,882 | 0,336 | 0,391 | 0,04 / 0,24 / 0,07 |
| **GRU (đang dùng)** | 0,371 | 0,885 | 0,335 | 0,392 | 0,04 / 0,22 / 0,06 |

Mô hình tốt hơn baseline về sai số trung bình, nhưng **rất yếu khi phát hiện mưa to** (giờ mưa to chỉ chiếm 0,8%).
Chỉ có chuỗi mưa tại điểm thì không đủ để dự báo dông đối lưu; cần radar/vệ tinh hoặc dự báo số làm đầu vào.
Đây là hạn chế chính của phần dự báo.

**Xác suất ngập**: không có nhãn ngập thật nên không học được. `services/flood_index.py` tính logistic từ mưa 1h, mưa 3h, triều,
độ cao DEM, gần điểm ngập công bố. Hệ số chọn định tính, **chưa hiệu chỉnh**. Báo cáo người dùng tích luỹ có thể làm nhãn về sau.

**Độ sâu và lý do ngập (ước tính, theo phường)**:
- **Triều:** dùng mực nước Vũng Tàu lệch 4 giờ (`TIDE_LAG_H`, đối chiếu 7 mốc báo chí ngày 10/10 và 27–28/10/2026). Tỉ lệ triều r = (cm − P50)/(P95 − P50).
  - r ≥ 1,15 thì độ sâu = min(60, 20 + 70·(r − 1,15)) cm.
  - Chỉ áp cho khoảng 64 phường bị triều: độ cao dưới 8 m ở Q7, Nhà Bè, Cần Giờ, Q8, Q4, Q2, Bình Thạnh, Thủ Đức, cộng phường có điểm ngập do triều.
  - Kiểm tra: r = 1,42 cho khoảng 39 cm (báo ghi 40–50 cm); r = 1,19 cho khoảng 23 cm (báo ghi khoảng 50 cm).
- **Mưa:** min(40, 1,5·(mưa 3h − 20)) cm, không có mốc kiểm chứng.
- **Báo cáo người dân đã xác nhận:** mắt cá 10, đầu gối 40, sâu 70 cm.
- Kết quả làm tròn 10 cm. Từ 20 cm trở lên thì phường ở mức Cao; quận lấy theo phường xấu nhất.
- Mực nước triều không còn tự ép mức Cao; chỉ trạm đo thật mới có override mực nước.

**Ngập theo đoạn đường**: chia tuyến OSRM thành đoạn ~200 m, phân loại `DRY` (p<0,3), `AT_RISK` (≥0,3), `LIKELY_FLOODED` (≥0,6),
`REPORTED_FLOODED` (báo cáo còn hiệu lực trong 100 m). Tuyến đề xuất: ít km ngập nhất, rồi ít nguy cơ, rồi nhanh nhất.

## Đánh giá phân loại rủi ro (10/11/2026)

Lệnh: `.venv\Scripts\python scripts\evaluate_risk.py` (chỉ đọc). Sự thật dùng để đối chiếu là 74 sự kiện ngập từ báo chí trong `historical_flood_events` (2 sự kiện thiếu quận bị bỏ). Đơn vị là quận–ngày (24 quận), kỳ 01/09/2025–09/11/2026. Ngày 10/10, 27/10, 28/10/2026 đã dùng để hiệu chỉnh nên được tách riêng; các ngày còn lại là tập kiểm tra.

| Tập kiểm tra | n | Dương | Accuracy | Precision | Recall | F1 | tp/fp/fn/tn |
|---|---|---|---|---|---|---|---|
| Tất cả, quận–ngày | 10.368 | 39 | 0,935 | 0,024 | 0,410 | 0,046 | 16/646/23/9683 |
| Triều, quận–ngày | 10.368 | 19 | 0,938 | 0,024 | 0,842 | 0,047 | 16/644/3/9705 |
| Triều, ngày toàn TP | 432 | 10 | 0,875 | 0,133 | 0,800 | 0,229 | 8/52/2/370 |
| Mưa, quận–ngày | 10.368 | 25 | 0,997 | 0 | 0 | 0 | 0/2/25/10341 |
| Luật cũ, triều | 10.368 | 19 | 0,627 | 0,005 | 1,000 | 0,010 | 19/3869/0/6480 |

Cách đọc:
- **Accuracy không có ý nghĩa** vì ngày không ngập áp đảo; đọc Recall và F1.
- **Nhãn âm là giả định:** không có tin báo chí không có nghĩa là không ngập, nên Precision bị đánh giá thấp hơn thực tế.
- **Triều:** bắt được 16/19 quận–ngày, F1 tăng từ 0,010 lên 0,047 so với luật cũ. Một phần mức tăng đến từ việc giới hạn số quận, không chỉ từ độ trễ và độ sâu.
- **Mưa: 0/25.** Đầu vào mưa không thấy các trận này; lượng mưa 3 giờ lớn nhất ở các ngày đó chỉ 18,6 mm, dưới ngưỡng 20 mm.
- **Chỉ đánh giá điều kiện độ sâu ước tính từ 20 cm,** với mưa và triều lấy từ mô hình Open-Meteo, không phải toàn bộ rule engine hay đầu ra GRU.
- **Tập kiểm tra chưa hoàn toàn độc lập:** có đợt triều 11/10 và 26/10/2026 sát ngày hiệu chỉnh.

## Thí nghiệm thêm dự báo số (NWP) vào GRU (10/11/2026)

`scripts/experiment_nwp.py`, tập kiểm tra 62.688 cửa sổ, chưa tích hợp vào hệ thống.

| Mô hình | MAE (mm) | F1 mưa to (≥5 mm/h) |
|---|---|---|
| GRU chỉ dùng lịch sử | 0,352 | 0,054 |
| GRU + GFS | 0,352 | 0,057 |
| GFS đơn thuần | 0,488 | 0,031 |
| Persistence | 0,487 | 0,022 |

- GFS (`gfs_seamless`) được chọn vì độc lập với dữ liệu mục tiêu (tương quan 0,19). Mức cải thiện nằm trong sai số của một lần chạy nên **không tích hợp**.
- Với 25 quận–ngày có ngập do mưa, GFS không đạt ngưỡng 20 mm ở ngày nào (lớn nhất 10,3 mm).
- **Phát hiện về dữ liệu:** chuỗi "mưa quan trắc" trong DB trùng 99,9% với bản dự báo best-match của Open-Meteo. Vì vậy thước đo MAE/F1 của dự báo mưa là so với **một mô hình khí tượng**, không phải mưa đo thật; muốn đánh giá đúng cần trạm đo hoặc radar.
- API lịch sử ghép các lần chạy hạn ngắn nên hạn 6 giờ lạc quan hơn thực tế. `ecmwf_ifs025` (tương quan 0,68) chưa thử.

Các mục dưới đây mô tả chế độ DEMO (dữ liệu mô phỏng) và YOLOv8 (mô hình huấn luyện trên ảnh mô phỏng).

> Mọi chỉ số dưới đây đo trên **dữ liệu MÔ PHỎNG** sinh bởi `app/ai/forecasting/synthetic.py` và
> `app/ai/computer_vision/synthetic.py`. Chúng chứng minh pipeline huấn luyện → đánh giá → triển khai hoạt động
> đúng, **không** chứng minh độ chính xác khi vận hành với quan trắc thật của TP.HCM.

## Tín hiệu mưa dông đa mô hình (16/11/2026)

Thí nghiệm `scripts/experiment_convective.py` (Open-Meteo historical-forecast, 11/2024–11/2026, 24 quận, 17.664 ngày-quận) so các tín hiệu miễn phí với 20 quận-ngày ngập do mưa từ báo chí. Một quận-ngày bị báo nếu có ít nhất một giờ thoả điều kiện.

| Quy tắc | Recall (n=20) | Báo ngày-quận | Mùa mưa |
|---|---|---|---|
| Hiện tại (mưa 3 giờ ≥ 33 mm) | 0,00 | 0,1% | 0,1% |
| CAPE ≥ 2000 và xác suất mưa ≥ 70% | 0,85 | 31,4% | 50,5% |
| Lưới 3×3 quanh điểm, mưa 3 giờ ≥ 10 mm | 0,50 | 26,6% | 39,3% |
| **≥ 2/7 mô hình, mưa 3 giờ ≥ 10 mm** | **0,40** | **4,7%** | **7,4%** |

CAPE, lifted index và xác suất mưa gần như ngày nào mùa mưa cũng cao, nên không phân biệt được ngày ngập. Đồng thuận đa mô hình (ECMWF, GFS, ICON, JMA, CMA, UKMO, Météo-France) tốt hơn báo ngẫu nhiên khoảng 5 lần. Hệ thống dùng quy tắc này (`openmeteo_service.storm_model_counts`, `rule_engine` khoá `storm_min_models`, mặc định 2) với mốc 0–3 giờ, chỉ nâng tối đa tới Trung bình, nguyên nhân `STORM`. Phường chỉ nhận tín hiệu khi thấp hoặc có điểm ngập.

Hạn chế: ngưỡng chọn trên chính tập đánh giá, không có tập held-out; historical-forecast ghép các giờ đầu của mỗi lần chạy nên lạc quan hơn dự báo thật. Cần đo lại bằng Previous Runs API.

## Mưa vệ tinh GPM IMERG đối chiếu Open-Meteo (20/11/2026)

`services/imerg_service.py` lấy IMERG Late run theo ngày (NASA, miễn phí, lưới 0,1°) cho ô chứa tâm mỗi quận, 748 ngày 01/11/2024–18/11/2026, lưu bảng `satellite_rainfall_daily`. `scripts/compare_imerg_openmeteo.py` so với tổng mưa giờ Open-Meteo của điểm lưới quận trong cùng ngày UTC:

| | Mọi quận-ngày (17.832) | Quận-ngày có ngập do mưa theo báo chí (99) |
|---|---|---|
| Mưa trung bình IMERG / Open-Meteo | 5,91 / 5,92 mm | **19,44 / 11,08 mm** |
| Trung vị IMERG / Open-Meteo | 2,03 / 2,30 mm | 13,31 / 9,60 mm |
| Tỉ lệ ngày ≥ 20 mm IMERG / Open-Meteo | 7,1% / 6,7% | **33,3% / 14,1%** |
| Tỉ lệ ngày ≥ 50 mm IMERG / Open-Meteo | 0,6% / 0,1% | **7,1% / 0%** |
| Pearson r | 0,566 | 0,522 |

Trung bình dài hạn hai nguồn khớp nhau, nhưng ở đúng các ngày ngập do mưa, Open-Meteo ghi thiếu khoảng 43% lượng mưa và gần như không có ngày từ 50 mm, còn IMERG có. Đây là bằng chứng định lượng cho việc hệ thống bỏ sót mưa cục bộ khi chỉ dựa vào dữ liệu mô hình. IMERG trễ 1–2 ngày và chỉ có theo ngày, nên hiện dùng để đối chiếu và đánh giá, chưa dùng cho cảnh báo tức thời. Hướng tiếp: dùng IMERG nửa giờ một (Early run, trễ ~4 giờ) làm đặc trưng cho LSTM ngập theo quận.

## 1. Dữ liệu mô phỏng (thay thế tạm thời cho dữ liệu khí tượng thủy văn)

- **Mưa đối lưu**: xác suất phát sinh dông theo mùa (tháng 5–11) và giờ trong ngày (đỉnh 14–18h giờ VN); dông có tâm
  di chuyển, cường độ Gamma, suy giảm Gaussian theo khoảng cách → các trạm gần nhau tương quan. Tổng mưa mô phỏng
  tháng 7–10 ≈ 1.100–1.450 mm/trạm (cùng bậc với khí hậu TP.HCM).
- **Mực nước** (cm so với cao độ tham chiếu cống/kênh): thuỷ triều bán nhật triều M2 (12,42h) + nhật triều + chu kỳ
  triều cường/kém (14,77 ngày) + đáp ứng dòng chảy mặt (tích chập mưa với kernel trễ ~2h) + nhiễu.
- **Ngập** (nhãn): mực nước > ngưỡng ngập của trạm.
- **Lỗi cảm biến**: mất bản ghi ~0,8% và gai bất thường ~0,1% → được bộ kiểm tra chất lượng gắn cờ `SUSPECT`.
- Chuỗi xác định theo seed và mốc EPOCH cố định nên có thể sinh nối tiếp theo thời gian thực.

## 2. Dự báo LSTM/GRU (`app/ai/forecasting/`)

| Bước | Cài đặt |
|---|---|
| Load | Từ PostgreSQL (`load_frames_from_db`), loại bản ghi `SUSPECT` |
| Validate schema | `validate_schema`: cột bắt buộc, thời gian tăng dần |
| Missing | Đưa về lưới giờ đều; mưa thiếu → 0, mực nước → ffill; **cờ `missing`** là một feature (không coi là quan trắc thật) |
| Đặc trưng/giờ | `log1p(mưa)`, `mực nước − ngưỡng`, sin/cos giờ VN, cờ missing |
| Chuẩn hoá | z-score, **fit chỉ trên tập train** (`Scaler.fit`) |
| Cửa sổ | 24 giờ quá khứ → 6 giờ tới (`make_windows`) |
| Chia tập | **Theo thời gian** 70/15/15 cho từng trạm; cửa sổ không vượt ranh giới đoạn → không rò rỉ (có test) |
| Mô hình | RNN 2 lớp (48→24) + Dense 64, 3 đầu ra: mưa 6h (softplus, log1p), mực nước 6h, xác suất ngập 6h (sigmoid) |
| Huấn luyện | Adam 1e-3, loss mse+mse+BCE (trọng số 1/1/2), EarlyStopping(patience 3), 8 epoch, seed 42 |
| Ngưỡng phân loại | Chọn theo F1 trên **validation**, không dùng test |
| Baseline | Persistence (giá trị giờ cuối giữ nguyên 6h) |
| Lưu | `model.keras`, `scaler.json`, `metadata.json` (ranh giới split, metrics), bảng `model_versions`/`training_runs` |
| Triển khai | Mô hình có val_loss thấp nhất được kích hoạt; Admin có thể đổi phiên bản |
| Cold-start | Mô hình dùng chung, chuẩn hoá theo ngưỡng trạm; trạm mới/thiếu dữ liệu mượn cửa sổ của trạm lân cận, ưu tiên cùng cụm (≤15 km, `ST_DistanceSphere`), đánh dấu `is_cold_start`, chất lượng `POOR` |

### Kết quả trên tập test mô phỏng (5.252 cửa sổ, 13 trạm có mực nước, 120 ngày)

| Mô hình | MAE mưa (mm) | RMSE mưa | MAE mực nước (cm) | Precision | Recall | F1 | Brier | ROC-AUC |
|---|---|---|---|---|---|---|---|---|
| Persistence (baseline) | 0,513 | 3,083 | 21,83 | 0,239 | 0,239 | 0,239 | 0,0206 | 0,615 |
| **LSTM (triển khai)** | 0,381 | 2,189 | **3,73** | 0,664 | 0,575 | **0,616** | **0,0081** | **0,967** |
| GRU | 0,374 | 2,165 | 4,13 | 0,652 | 0,573 | 0,610 | 0,0083 | 0,966 |

Tỉ lệ giờ ngập ~2,4% (mất cân bằng lớp). Có MAE/RMSE theo từng horizon trong `metadata.json` và trang Mô hình AI.
Ngoài ra trang Thống kê tính **kỹ năng trực tuyến**: so sánh dự báo mưa đã phát hành với quan trắc tại `target_time`.

### Tinh chỉnh theo cụm (11/2026)

`python -m app.ai.forecasting.train --finetune-clusters --epochs 2` tinh chỉnh mô hình nền cho từng cụm (`GRU_CLUSTER`, đầu mưa, lr 1e-4) và chỉ giữ nếu val loss tốt hơn mô hình nền. Mô hình cụm chỉ dùng khi `params.base_model_id` trùng mô hình nền đang active; `active_model` và kích hoạt thủ công không đụng tới chúng. Kết quả (val loss / MAE mưa, nền → tinh chỉnh):

| Cụm | Val loss | MAE mưa |
|---|---|---|
| CORE | 0,0801 → 0,0778 | 0,259 → 0,246 |
| INNER | 0,0835 → 0,0815 | 0,265 → 0,253 |
| SUBURBAN | 0,0775 → 0,0741 | 0,251 → 0,236 |

Mức cải thiện nhỏ (khoảng 2–4% loss) và đánh giá trong mẫu (các trạm của cụm cũng nằm trong tập huấn luyện nền).

### Thí nghiệm đầu xác suất ngập (11/2026, không tích hợp)

`scripts/experiment_flood_head.py` huấn luyện đầu ngập từ 74 sự kiện báo chí với cổng chấp nhận đặt trước. Kết quả test: PR-AUC GRU 0,0118 so với công thức `flood_index` 0,0132; event-day recall 0,444 so với 0,667; tập test chỉ có 5 ngày sự kiện. Không qua cổng nên sản phẩm giữ công thức `flood_index`.

### Mô hình ngập riêng theo quận (20/11/2026, qua cổng, chưa tích hợp)

`scripts/experiment_flood_district.py`. Thay đổi so với lần trên:

- **Nhãn:** 246 sự kiện báo chí (thêm 172, mỗi dòng có URL bài gốc đã đọc; kiểm chứng ngẫu nhiên 2 dòng khớp bài), 65 ngày, 11/2024–11/2026.
- **Bài toán:** "quận có ngập trong 6 giờ tới" (một đầu ra), thay vì đầu ngập theo giờ gắn vào GRU mưa.
- **Mô hình:** GRU/LSTM 32 đơn vị riêng cho ngập; đầu vào 24 giờ gồm mưa, triều đã lệch 4 giờ, sin/cos giờ, cùng độ cao, cờ điểm ngập và cờ quận ven triều; class weight cho lớp hiếm.
- **Chia:** theo ngày giờ Việt Nam, ngày có sự kiện 60/20/20 (38/13/13 ngày). Ngưỡng chọn trên validation. Công thức được tính bằng mưa quan trắc (lợi thế cho công thức).

| Seed | Công thức PR-AUC / event-day recall | GRU | LSTM | LSTM + công thức |
|---|---|---|---|---|
| 42 | 0,005 / 0,08 | 0,035 / 0,12 | 0,043 / 0,12 | 0,012 / 0,12 |
| 7 | 0,006 / 0,06 | 0,020 / 0,12 | 0,023 / 0,18 | 0,019 / 0,09 |
| 123 | 0,008 / 0,36 | 0,046 / 0,32 | 0,046 / 0,36 | 0,026 / 0,41 |

LSTM qua cổng (PR-AUC và event-day recall đều không kém công thức) ở cả 3 seed; GRU trượt ở seed 123. Mô hình xếp hạng nguy cơ tốt hơn 4–8 lần, nhưng recall theo ngày ở ngưỡng cảnh báo còn thấp (0,12–0,36) và xác suất chưa hiệu chỉnh (class weight làm xác suất phồng), nên chưa thay công thức trong luồng cảnh báo.

Hạn chế của nhãn: các tháng 2025-01, 2026-02 đến 2026-04 và 2026-08 không tìm được tin ngập. 2026-08 là mùa mưa, nên có thể có trận bị coi nhầm là "không ngập". 130/172 dòng mới có giờ gần đúng.

## 3. YOLOv8-seg phát hiện vùng ngập (`app/ai/computer_vision/`)

### Mô hình hiện hành: huấn luyện trên ảnh thật (11/2026)

Tập Kaggle "Flood Area Segmentation" (faizalkarim, CC0, 290 ảnh), chuyển sang YOLO-seg ở `datasets/vision/flood_area_real/`. Trên tập test 44 ảnh: mask mAP50 **0,4503**, mAP50-95 0,207, precision 0,572, recall 0,483; mô hình mô phỏng cũ trên cùng tập chỉ đạt mask mAP50 0,0085. Mô hình id 8 đang active, `trained_on_simulated=False`. Huấn luyện lại qua admin dùng tập thật khi có và không bao giờ để mô hình mô phỏng thay mô hình thật đang active. Ảnh tổng quát chứ không phải camera giao thông TP.HCM nên vẫn chỉ là tham khảo.

Quét camera giao thông tự động (`CAMERA_SCAN_ENABLED`, mặc định tắt): 15 phút/lần, tối đa 20 camera/lần, bán kính 500 m quanh điểm ngập, cần 2 lần phát hiện liên tiếp mới tính; ảnh và kết quả camera TT- chỉ cán bộ thấy. Ảnh cán bộ tải lên vẫn đi vào camera tự tạo.

### Mô hình mô phỏng ban đầu (lịch sử)

- Không có bộ ảnh camera ngập TP.HCM đã gán nhãn → sinh **240 ảnh đường phố mô phỏng** (vùng nước nâu đục, gợn
  sóng, phản chiếu) với nhãn polygon YOLO-seg (`datasets/vision/synthetic/data.yaml`, gắn nhãn SIMULATED).
- Fine-tune `yolov8n-seg` (trọng số COCO) 15 epoch, imgsz 320, CPU (~5 phút).
- **Tỉ lệ ngập** = diện tích mask ∩ ROI / diện tích ROI (ROI đa giác cấu hình theo camera) — dùng segmentation,
  không suy diện tích từ bounding box.
- Kết quả trên tập val mô phỏng: box mAP50 0,995 · mask mAP50 0,995 · mask mAP50-95 0,993. Con số rất cao vì ảnh mô
  phỏng đơn giản — **không** phản ánh ảnh camera thật (mưa đêm, phản quang, che khuất…).
- Dự phòng `HEURISTIC` (ngưỡng màu HSV) khi chưa có trọng số — ghi rõ "không phải YOLO", độ tin cậy 0,3.
- Để dùng dữ liệu thật: gán nhãn polygon (CVAT/Roboflow, xuất YOLO-seg) và chạy
  `python -m app.ai.computer_vision.train --data <data.yaml>`.

## 4. Hệ luật cảnh báo (`app/services/rule_engine.py`)

Điểm rủi ro = trung bình có trọng số của các đầu vào **có dữ liệu** (trọng số mặc định: xác suất ngập 0,45 · mưa 0,2 ·
mực nước/ngưỡng 0,2 · camera 0,1 · lịch sử 0,05). MEDIUM ≥ 0,35, HIGH ≥ 0,6; override HIGH khi xác suất ≥ 80%, mực nước
≥ ngưỡng hoặc camera ≥ 40% ROI. Độ tin cậy (tổng trọng số có dữ liệu) < 0,5 hoặc dữ liệu cũ > 180 phút →
`INSUFFICIENT_DATA`. Hysteresis 0,05 chống dao động; 1 cảnh báo mở/khu vực (chỉ escalate); cooldown 60 phút. Mỗi
snapshot lưu `explanation` (đầu vào, đóng góp, override, ghi chú). Quy tắc có version, sửa = tạo version mới.

**Đánh giá hệ luật** (backfill 14 ngày mô phỏng, đối chiếu mực nước mô phỏng trong `horizon + 2h`): 51 cảnh báo,
21 xác nhận có ngập, 30 báo động giả → precision ≈ 41%. Ngưỡng mặc định thiên về an toàn (nhiều báo động giả);
cần hiệu chỉnh với dữ liệu thật.

Ngưỡng mặc định **chỉ phục vụ nghiên cứu/demo**, chưa phải ngưỡng vận hành chính thức.
