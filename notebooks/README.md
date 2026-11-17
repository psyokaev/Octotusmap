# Notebook huấn luyện và đánh giá

Ba notebook minh hoạ quy trình AI của OctotusMap. Chúng **chỉ đọc** CSDL, không ghi gì vào CSDL, `storage/` hay `artifacts/`, và đã được chạy sẵn (có kết quả trong tệp).

| Notebook | Nội dung | Thời gian (CPU) |
|---|---|---|
| `01_du_bao_mua_lstm.ipynb` | Nạp dữ liệu, kiểm tra, dựng cửa sổ, huấn luyện GRU nhỏ 2 epoch, `evaluate_rain` | ~20 giây |
| `02_yolov8_ngap.ipynb` | Bộ ảnh `flood_area_real`, chỉ số mô hình YOLOv8-seg đang kích hoạt, dự đoán mẫu | ~15 giây |
| `03_danh_gia_canh_bao.ipynb` | `risk_eval` như `scripts/evaluate_risk.py`, bảng chỉ số và ma trận nhầm lẫn | ~10 giây |

## Yêu cầu

- PostgreSQL đang chạy với dữ liệu đã nạp (`python scripts\bootstrap.py`), `backend/.env` đã cấu hình.
- Notebook 02 cần ảnh trong `datasets/vision/flood_area_real/images|labels` (sinh bởi `scripts/prepare_flood_area_real.py`) và một mô hình YOLOv8-seg đang kích hoạt.
- Các gói trong mục Notebook của `backend/requirements.txt`.

## Chạy

```powershell
cd backend; $env:PYTHONUTF8="1"
.venv\Scripts\python -m pip install -r requirements.txt
cd ..\notebooks
..\backend\.venv\Scripts\python -m nbclient --inplace 01_du_bao_mua_lstm.ipynb
```

Hoặc mở trong VS Code / Jupyter với kernel là `backend\.venv`. Mỗi notebook tự chuyển thư mục làm việc về `backend/` để đọc `.env`.

Chạy lại sẽ ghi đè kết quả trong tệp; hãy xem `git diff` trước khi commit (ảnh biểu đồ làm tệp lớn, nhất là notebook 02).
