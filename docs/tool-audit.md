# Audit công cụ Claude Code

> Lịch sử: bản kiểm kê công cụ tại thời điểm làm bản MySQL/React ban đầu. Hiện dùng PostgreSQL 16 + PostGIS 3.4 (`E:/pgsql`) và Streamlit.

| Công cụ | Phát hiện | Sử dụng | Ghi chú |
|---|---|---|---|
| Claude Code (VS Code extension, Windows) | ✅ | ✅ | Model Opus 5.5 |
| Python 3.13.16 / TensorFlow 2.21 / Keras 3.15 | ✅ | ✅ | venv `--system-site-packages`; PATH `python` là venv PlatformIO nên dùng `py -3.13` |
| Node 24.21 / npm 11.19 | ✅ | ✅ | |
| MySQL 8.0.46 (service MySQL80) | ✅ | ✅ | Cần mật khẩu root do người dùng cung cấp |
| Docker | ❌ | ❌ | Không cài → compose/Dockerfile chưa kiểm chứng |
| Git 2.56 | ✅ | ✅ | Repo khởi tạo mới; commit cục bộ, không push |
| superpowers | ✅ | ✅ | brainstorming/plan → plan mode; subagent-driven development cho trang frontend |
| ponytail | ✅ | ✅ | Hook phiên: giữ thay đổi nhỏ, ghi `shortcut:` cho giới hạn đã biết |
| feature-dev | ✅ | — | Không gọi riêng; quy trình tương đương qua plan + test |
| code-review / security-guidance | ✅ | ✅ | Security review tự động sau commit báo 4 lỗi (open redirect, lộ `stream_url`, lộ thông tin xử lý cảnh báo, SSE nội bộ) → đã sửa + test |
| hookify | ✅ | — | Không tạo rule mới; `.env` gitignore + kiểm tra secret trước commit thực hiện thủ công |
| commit-commands | ✅ | — | Commit qua git trực tiếp (cùng quy ước) |
| claude-mem | ✅ | — | Không cần; tiến độ ghi trong `docs/progress.md` |
| context7 | ✅ | ❌ | MCP cần xác thực OAuth — không khả dụng trong phiên |
| claude-md-management | ✅ | ✅ | Tạo `CLAUDE.md` ngắn gọn |
| frontend-design | ✅ | ✅ | Định hướng palette "sông Sài Gòn", font Be Vietnam Pro, thủy đồ thời gian, ký hiệu hình dạng cho rủi ro |
| python-development / javascript-typescript (wshobson) | ✅ | ✅ | 2 sub-agent `typescript-pro` xây 10 trang frontend song song |
| debugging-toolkit | ✅ | — | Lỗi được debug trực tiếp theo root cause (xem testing-report §4) |
| arm-cortex-microcontrollers | ✅ | — | Không có thiết bị IoT; API nhập quan trắc sẵn sàng cho ESP32 |
| Playwright CLI 0.1.23 + skill playwright-cli | ✅ | ✅ | Chrome không có → dùng `--browser=msedge`; 25 luồng E2E, ảnh trong `docs/screenshots/` |
| find-skills / Vercel agent-skills | ✅ | — | Không cần thêm skill |
| Graphify 0.9.100 | ✅ | ✅ | `graphify update .` (AST, không LLM): 1.382 node, 4.082 cạnh, 55 cộng đồng → `graphify-out/GRAPH_REPORT.md` |
| OmniRoute 3.8.52 | ✅ | — | Gateway LLM của người dùng; ứng dụng không có thành phần LLM nên không dùng, không thay đổi cấu hình |
| ccusage 20.0.46 | ✅ | ✅ | Theo dõi usage phiên làm việc |
| Sub-agents | ✅ | ✅ | Frontend/Analytics agent (Dashboard, Thống kê, Dự báo, Mô hình) và Frontend/Operations agent (Trạm, Camera, Cảnh báo, Lịch sử, Tài khoản, Cấu hình); mỗi agent sở hữu file riêng, kiểm tra tsc/eslint/vitest; tích hợp và QA do agent chính |
