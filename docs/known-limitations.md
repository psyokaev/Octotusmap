# Hạn chế đã biết

## Chế độ dữ liệu thật (đang vận hành)
- Open-Meteo là mô hình lưới (~1–11 km), không phải trạm đo: không thấy mưa cục bộ quy mô phố, làm mượt mưa cực trị. 24 "điểm lưới" nằm gần nhau nên có thể cùng một ô lưới.
- Không có dữ liệu mực nước cống/kênh của TP.HCM; chỉ có mực nước biển mô hình tại Vũng Tàu làm đại diện triều.
- **Trạng thái ngập là ước tính, chưa hiệu chỉnh và chưa được kiểm chứng với ngập thật.** DEM 90 m không thấy ổ trũng nhỏ; khi không mưa, mọi đoạn hiện "không có dấu hiệu ngập".
- Dự báo mưa to rất yếu (F1 ≈ 6%), xem ai-methodology.
- Điểm ngập: chỉ 31/122 điểm vì bài báo chỉ nêu tên khoảng 37 điểm (tôi bỏ các điểm ngoài ranh giới 2020 như Sóng Thần, QL51, và các điểm trùng khu vực Bình Phước); toạ độ geocode gần đúng, tuyến dài chỉ có một điểm đại diện.
- Báo cáo người dùng chưa được xác minh; bất kỳ tài khoản nào cũng gửi được (giới hạn 5 báo cáo/10 phút). Một báo cáo chưa xác nhận đã có thể đổi tuyến đề xuất; cán bộ có thể từ chối báo cáo sai.
- OSRM demo chỉ có profile ô tô, không có xe máy; Photon/OSRM là dịch vụ công cộng không cam kết sẵn sàng.
- Phường theo GADM, cấu trúc **trước 07/2025** (322 phường/xã, 24 quận/huyện); tên và ranh giới có thể khác hiện hành. Giấy phép GADM chỉ cho học thuật/phi thương mại. Cần GeoJSON mới để đúng hiện hành.
- Rủi ro cấp phường dùng mưa của điểm lưới quận cha; khác biệt giữa các phường chủ yếu đến từ độ cao DEM và điểm ngập.
- Camera: danh sách là snapshot 796 camera ngày 06/11/2026; trang nguồn không có API công khai hay điều khoản rõ ràng, đường dẫn ảnh có thể đổi hoặc bị chặn. 11/31 điểm ngập không có camera trong 500 m; camera gần nhất có thể không nhìn đúng điểm ngập. Không phân tích ngập tự động từ ảnh thật.
- Mô phỏng ngập chỉ là vòng tròn giả định theo khoảng cách, không mô phỏng dòng chảy; chỉ admin thấy.
- Tài khoản quản trị trên máy phát triển đặt bằng `scripts/set_password.py`, bỏ qua chính sách mật khẩu mạnh: chỉ an toàn trên máy cá nhân.
- Không dựng lại cảnh báo trên dữ liệu thật khi tính lại (backfill `alerts=False`). Ngày 07/11/2026 đã đóng 24 cảnh báo Cao phát lúc 06/11 (ghi FALSE_ALARM), sinh ra do luật triều cũ áp cho mọi khu vực.
- **Độ sâu ngập là ước tính** từ 3 mốc báo chí của 2 đợt triều; đợt 10/10 bị ước thấp khoảng 27 cm. Chưa có dữ liệu ngày khô nên không biết tỉ lệ báo động giả.
- **Mưa cục bộ vẫn bị bỏ sót một phần:** đã thêm tín hiệu "≥ 2/7 mô hình thời tiết báo mưa 3 giờ tới ≥ 10 mm" (chỉ nâng tới Trung bình, ghi "ước tính"). Trên lịch sử tín hiệu bắt 8/20 quận-ngày ngập do mưa (trước đây 0/20) và báo 4,7% ngày-quận (mùa mưa 7,4%). Con số này lạc quan: ngưỡng chọn trên chính 20 sự kiện (11 ngày), dữ liệu historical-forecast gần với hạn 0–6 giờ chứ không phải dự báo phát trước 3 giờ, nhãn âm là giả định. Trận 04/11/2026 vẫn bị bỏ sót (mọi mô hình đều mưa nhỏ). Tín hiệu chỉ có khi chạy trực tiếp, không có khi tính lại quá khứ. Báo cáo người dân vẫn là cách bù chính.
- **Dữ liệu "quan trắc" mưa thực chất là đầu ra mô hình** (trùng 99,9% với dự báo best-match của Open-Meteo), nên MAE/F1 dự báo mưa chỉ phản ánh mức bám theo mô hình đó, không phải mưa đo thật.
- Bổ sung NWP (GFS) vào GRU không cải thiện đáng kể (F1 mưa to 0,054 → 0,057), nên chưa tích hợp. Muốn phát hiện mưa to cần trạm đo, radar hoặc vệ tinh.
- **YOLOv8-seg đã huấn luyện lại trên ảnh thật** (Kaggle "Flood Area Segmentation", CC0, 290 ảnh): trên 44 ảnh test mask mAP50 0,4503, mAP50-95 0,207, precision 0,572, recall 0,483 (mô hình mô phỏng cũ chỉ 0,0085 trên cùng tập). Vẫn là ảnh tổng quát, không phải ảnh camera giao thông TP.HCM, nên chỉ số chỉ mang tính tham khảo. Ảnh do cán bộ tải lên, gắn camera tự tạo (không phải camera giao thông), có thể đẩy phường lên mức Cao và tạo cảnh báo công khai.
- **Quét tự động camera giao thông đã cài nhưng TẮT** (`CAMERA_SCAN_ENABLED`; 15 phút/lần, tối đa 20 camera, bán kính 500 m quanh điểm ngập, cần 2 lần phát hiện liên tiếp, ảnh và kết quả TT- chỉ cán bộ thấy). Chưa bật vì đã đo trên camera thật: đêm 16/11/2026, trời khô khoảng 12 giờ, 134/147 camera vượt ngưỡng 0,4 cả 2 lần liên tiếp (91% báo giả); ngưỡng 0,95 vẫn còn 17/147. Mô hình nhận mặt đường nhựa phản sáng là nước, luật "2 lần liên tiếp" không lọc được vì lỗi ổn định theo khung cảnh (`scripts/experiment_camera_fp.py`). Cần tinh chỉnh với ảnh camera TP.HCM (cả ảnh khô làm nền) trước khi bật; chưa đo ban ngày và lúc mưa.
- **LSTM/GRU dự báo xác suất ngập không được dùng**: thử với 74 sự kiện báo chí, PR-AUC GRU 0,0118 so với công thức 0,0132 và event-day recall 0,444 so với 0,667 (chỉ 5 ngày sự kiện trong tập test), không qua cổng đặt trước; hệ thống giữ công thức `flood_index` (`scripts/experiment_flood_head.py`). Recall mưa-ngập trên sự kiện độc lập là 0/25.
- Cold-start mượn dữ liệu trạm cùng cụm; có 3 mô hình tinh chỉnh theo cụm (`GRU_CLUSTER`) nhưng mức cải thiện nhỏ (val loss giảm 2–4%, đánh giá trong mẫu) và phải huấn luyện lại sau mỗi lần huấn luyện lại mô hình nền (mô hình cụm lệch nền bị bỏ qua). Trạm tự thoát cold-start khi có đủ dữ liệu riêng.
- Đánh giá Accuracy/F1 dùng nhãn âm giả định từ việc không có tin báo chí; xem `ai-methodology.md`.
- Trên PostgreSQL (200 GET mỗi mức, một worker, 0 lỗi) p95 là 78,7 / 321,4 / 1542,1 ms ở 1 / 10 / 50 yêu cầu đồng thời (MySQL trước đó: 576 / 1859 / 3668 ms). Số liệu trên đo với một worker. Đã chạy được nhiều worker (Docker mặc định `WEB_CONCURRENCY=2`, tự khởi động lại): giới hạn tốc độ, SSE (`LISTEN/NOTIFY`) và quyền chạy lịch (advisory lock) nằm trong PostgreSQL; đã thử tắt worker giữ lịch, worker khác nhận lịch ở chu kỳ sau. PostgreSQL vẫn là một máy duy nhất (chưa có bản sao/failover DB), nên chưa phải sẵn sàng cao hoàn chỉnh.
- Độ cao phường là một mẫu DEM 90 m tại tâm phường nên phân biệt kém; phạm vi bị triều vì vậy dựa thêm vào danh sách quận ven sông và điểm ngập.

## Chế độ DEMO (khi `DEMO_MODE=true`)

## Dữ liệu
- **Chưa có dữ liệu quan trắc thật.** Trạm, camera, chuỗi mưa/mực nước, sự kiện ngập lịch sử và khung hình camera
  ở chế độ DEMO đều là **mô phỏng** (vị trí đặt gần điểm ngập được báo chí nhắc đến, nhưng trạm/camera là hư cấu).
  Hệ thống hỗ trợ nhập CSV/Excel, API thủ công, import GeoJSON và tắt `DEMO_MODE` để chuyển sang dữ liệu thật.
- **Ranh giới hành chính năm 2020** (24 quận/huyện, geoBoundaries) — chưa phản ánh việc thành lập TP Thủ Đức (2021)
  và sắp xếp đơn vị hành chính 2025. Có thể import ranh giới mới (Cấu hình → Vận hành → Import GeoJSON).
- 3 huyện (Cần Giờ, Củ Chi, Hóc Môn) không có trạm DEMO trong bán kính 6 km → thường `INSUFFICIENT_DATA` (đúng thiết kế).
- Không có dữ liệu đoạn đường ngập → gợi ý tuyến chỉ xét rủi ro theo **khu vực hành chính**, không theo từng đoạn.

## AI
- Chỉ số DEMO cũ của LSTM/GRU (F1 ngập 0,62, AUC 0,97) và YOLOv8 mô phỏng (mask mAP50 0,995) đo trên dữ liệu **mô phỏng** → không dùng
  làm bằng chứng độ chính xác thực tế. Ảnh mô phỏng đơn giản hơn nhiều so với camera thật.
- Không có dữ liệu radar/vệ tinh; dự báo mưa chỉ dựa trên chuỗi tại trạm → hạn chế với mưa dông hình thành nhanh.
- Hệ luật mặc định cho precision ≈ 41% trên backfill mô phỏng (nhiều báo động giả) — cần hiệu chỉnh ngưỡng.
- Huấn luyện chạy CPU trong tiến trình API (endpoint admin) — chỉ phù hợp quy mô đồ án.

## Hạ tầng
- **Docker Compose đã chạy thật trên GitHub Actions** (16/11/2026, commit 608ba1a): build 3 image khoảng 5 phút, bootstrap ở chế độ dữ liệu thật (tải Open-Meteo 2 năm, phường, huấn luyện 1 epoch) khoảng 11 phút, sau đó backend `/health` và Streamlit đều trả OK. Với 8 epoch mặc định, bootstrap vượt 30 phút. Máy phát triển vẫn chưa chạy được Docker (CPU chưa bật ảo hoá; Windows 11 Home cần WSL2). `requirements.txt` không ghim phiên bản nên CI có thể vỡ khi thư viện ra bản mới (đã gặp với FastAPI bỏ tham số `enum` của `Query`).
- Rate limit dùng cửa sổ cố định trong bảng `rate_limit_hits` (ở ranh giới cửa sổ có thể lọt tới 2 lần hạn mức). Sự kiện SSE phát khi worker đang mất kết nối DB sẽ bị bỏ (client tự hỏi lại mỗi 60 s).
- Photon/OSRM dùng máy chủ công cộng (giới hạn sử dụng, không SLA) → chỉ phục vụ demo; vận hành cần tự host.
- Email thông báo chưa triển khai (chỉ có thông báo trong web; `SMTP_HOST` để trống).
- Camera thật (RTSP) chưa được đọc trực tiếp: hệ thống nhận ảnh tải lên/khung hình; `stream_url` chỉ lưu cấu hình.
- Không điều khiển trạm bơm/hạ tầng thật — khuyến nghị chỉ mang tính tham khảo, theo yêu cầu đề bài.

## Giao diện
- Giao diện là Streamlit; thư mục `frontend/` (React) còn trong repo nhưng không dùng, chỉ xoá khi chủ dự án xác nhận.
- Chưa có trong Streamlit: kéo thả điểm A/B, nút "vị trí của tôi", ký hiệu cảnh báo theo mức zoom, nền bản đồ tối, tự gợi ý khi gõ (chọn từ danh sách sau khi Enter), liên kết sâu `?open=` tới cảnh báo.
- Đăng nhập chỉ giữ trong `st.session_state`: tải lại trang phải đăng nhập lại.
- Cập nhật gần thời gian thực bằng hỏi lại mỗi 60 s thay cho SSE; không có toast cảnh báo mới.
- Xuất Excel/CSV cần hai lần bấm (chuẩn bị rồi tải).
- Tooltip bản đồ chọn đối tượng nhờ hậu tố `· mã N` ở cuối chuỗi; đổi chuỗi này sẽ hỏng việc chọn.
- Kiểm thử giao diện bằng AppTest (không bấm được vào iframe bản đồ); đã chạy smoke trực tiếp 12 trang, 0 ngoại lệ. Không còn bộ E2E Playwright của bản React.
- Chưa chỉnh sửa ROI camera bằng giao diện đồ hoạ (ROI mặc định 55% dưới khung hình).
- Cột `code` của trạm/khu vực/camera phân biệt hoa thường sau khi chuyển sang PostgreSQL; `username`/`email` là CITEXT (mất giới hạn độ dài ở DB, schema vẫn kiểm).
