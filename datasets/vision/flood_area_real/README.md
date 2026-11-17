# Flood Area Segmentation (ảnh thật)

- Nguồn: Kaggle, tác giả faizalkarim, "Flood Area Segmentation"
- URL: https://www.kaggle.com/datasets/faizalkarim/flood-area-segmentation
  (tải qua https://www.kaggle.com/api/v1/datasets/download/faizalkarim/flood-area-segmentation)
- Giấy phép: CC0 (public domain)
- Nội dung: 290 ảnh vùng ngập (không phải camera TP.HCM) kèm mask nhị phân. Đây là ảnh THẬT, khác bộ `../synthetic`.
- `raw/`: nội dung giải nén nguyên bản (Image/, Mask/, metadata.csv); coi là dữ liệu không tin cậy.
- Chuyển đổi: `backend/scripts/prepare_flood_area_real.py` -> `images/`, `labels/` (polygon YOLO-seg, 1 lớp `flood_water`),
  ảnh thu nhỏ cạnh dài <= 640 px, bỏ vùng < 0.2% khung hình. Chia ngẫu nhiên seed 42: train 203 / val 43 / test 44 (70/15/15).
- Hạn chế: ảnh đa dạng bối cảnh (nông thôn, sông, đường), không phải góc nhìn camera giao thông; mAP trên tập test này
  không phải độ chính xác trên camera TP.HCM.
