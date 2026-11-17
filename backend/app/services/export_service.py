"""Xuất báo cáo Excel (OpenPyXL) / CSV theo đúng bộ lọc thống kê."""

import csv
import io
from datetime import datetime, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.models import DataSource, ExportHistory, User
from app.services import statistics_service as stats
from app.services.statistics_service import Filters

VN = timedelta(hours=7)
MAX_ROWS = 200_000
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
THIN = Side(style="thin", color="B7B7B7")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
DT_FMT = "dd/mm/yyyy hh:mm"

REPORTS = {
    "full": ["Tong_quan", "Luong_mua", "Muc_nuoc", "Du_bao_AI", "Canh_bao_ngap", "Lich_su_ngap", "Tram_quan_trac",
             "Camera", "Danh_gia_mo_hinh", "Chat_luong_du_lieu", "Nguon_du_lieu"],
    "rainfall": ["Tong_quan", "Luong_mua", "Nguon_du_lieu"],
    "water_level": ["Tong_quan", "Muc_nuoc", "Nguon_du_lieu"],
    "forecasts": ["Tong_quan", "Du_bao_AI", "Danh_gia_mo_hinh", "Nguon_du_lieu"],
    "alerts": ["Tong_quan", "Canh_bao_ngap", "Nguon_du_lieu"],
    "history": ["Tong_quan", "Lich_su_ngap", "Nguon_du_lieu"],
    "stations": ["Tong_quan", "Tram_quan_trac", "Chat_luong_du_lieu", "Nguon_du_lieu"],
    "cameras": ["Tong_quan", "Camera", "Nguon_du_lieu"],
    "models": ["Tong_quan", "Danh_gia_mo_hinh", "Nguon_du_lieu"],
}
TITLES = {"full": "Báo cáo tổng hợp cảnh báo ngập", "rainfall": "Báo cáo lượng mưa",
          "water_level": "Báo cáo mực nước", "forecasts": "Báo cáo dự báo AI", "alerts": "Báo cáo cảnh báo ngập",
          "history": "Báo cáo sự kiện ngập lịch sử", "stations": "Báo cáo trạm quan trắc",
          "cameras": "Báo cáo camera", "models": "Báo cáo đánh giá mô hình"}


def safe(v):
    """Chống Excel formula injection; datetime UTC -> giờ VN; giữ nguyên số."""
    if isinstance(v, datetime):
        return v + VN
    if isinstance(v, bool):
        return "Có" if v else "Không"
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _local(d: datetime) -> str:
    return (d + VN).strftime("%d/%m/%Y %H:%M")


class _Book:
    def __init__(self, title: str, f: Filters, user: User):
        self.wb = Workbook()
        self.wb.remove(self.wb.active)
        self.title, self.f, self.user = title, f, user
        self.rows_written = 0

    def sheet(self, name: str, headers: list[tuple[str, str]], rows: list, unit_note: str, source_note: str,
              notes: str = "") -> int:
        """headers: [(tiêu đề, định dạng số | 'dt' | 'text' | '')]."""
        ws = self.wb.create_sheet(name)
        meta = [
            (self.title + f" — {name}",),
            (f"Khoảng thời gian (giờ VN, UTC+7): {_local(self.f.date_from)} → {_local(self.f.date_to)}",),
            (f"Ngày xuất: {_local(utcnow())}  |  Người xuất: {self.user.full_name or self.user.username}",),
            (f"Đơn vị: {unit_note}",),
            (f"Nguồn dữ liệu: {source_note}",),
            (f"Bộ lọc: {self._filters_text()}",),
            (f"Ghi chú: {notes or 'Dữ liệu thiếu được để trống, không nội suy.'}",),
        ]
        for i, m in enumerate(meta, start=1):
            ws.cell(i, 1, m[0]).font = Font(bold=(i == 1), size=14 if i == 1 else 10)
        hr = len(meta) + 2
        for j, (h, _) in enumerate(headers, start=1):
            c = ws.cell(hr, j, h)
            c.font, c.fill, c.border = Font(bold=True, color="FFFFFF"), HEADER_FILL, BORDER
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if not rows:
            ws.cell(hr + 1, 1, "Không có dữ liệu trong khoảng/bộ lọc đã chọn")
        for i, r in enumerate(rows, start=hr + 1):
            for j, ((_, fmt), v) in enumerate(zip(headers, r, strict=True), start=1):
                c = ws.cell(i, j, safe(v))
                c.border = BORDER
                if fmt == "dt":
                    c.number_format = DT_FMT
                elif fmt == "text":
                    c.number_format = "@"
                elif fmt:
                    c.number_format = fmt
        last_row = hr + max(len(rows), 1)
        ws.auto_filter.ref = f"A{hr}:{get_column_letter(len(headers))}{last_row}"
        ws.freeze_panes = ws.cell(hr + 1, 1)
        for j, (h, fmt) in enumerate(headers, start=1):
            width = max([len(h)] + [len(str(r[j - 1])) for r in rows[:200]]) + 2
            ws.column_dimensions[get_column_letter(j)].width = min(max(width, 16 if fmt == "dt" else 10), 50)
        self.rows_written += len(rows)
        return len(rows)

    def _filters_text(self) -> str:
        f = self.f
        parts = [f"khu vực #{f.area_id}" if f.area_id else "", f"trạm #{f.station_id}" if f.station_id else "",
                 f"mức {f.risk_level}" if f.risk_level else "", f"loại dữ liệu {f.data_type}" if f.data_type else ""]
        return ", ".join(p for p in parts if p) or "không"


def _demo(sim) -> str:
    return "DEMO/MÔ PHỎNG" if sim else "Thực tế"


def build_workbook(db: Session, report: str, f: Filters, user: User) -> tuple[bytes, int]:
    if report not in REPORTS:
        raise ValueError("Loại báo cáo không hợp lệ")
    b = _Book(TITLES[report], f, user)
    sim_note = "Dữ liệu gắn nhãn DEMO/MÔ PHỎNG là dữ liệu sinh tự động phục vụ trình diễn, không phải quan trắc thật."
    for name in REPORTS[report]:
        if name == "Camera" and not get_settings().camera_enabled:
            continue
        if name == "Tong_quan":
            o = stats.overview(db, f)
            a = stats.alert_stats(db, f)
            rows = [
                ("Tổng số trạm quan trắc", o["stations_total"], "trạm"),
                ("Trạm đang hoạt động (ONLINE)", o["stations_online"], "trạm"),
                ("Trạm mất kết nối / chưa có dữ liệu", o["stations_offline"], "trạm"),
                ("Tổng số camera", o["cameras_total"], "camera"),
                ("Số khu vực giám sát", o["areas_total"], "khu vực"),
                ("Khu vực nguy cơ LOW (hiện tại)", o["areas_low"], "khu vực"),
                ("Khu vực nguy cơ MEDIUM (hiện tại)", o["areas_medium"], "khu vực"),
                ("Khu vực nguy cơ HIGH (hiện tại)", o["areas_high"], "khu vực"),
                ("Cảnh báo đang hoạt động", o["alerts_active"], "cảnh báo"),
                ("Cảnh báo phát sinh trong khoảng lọc", a["total"], "cảnh báo"),
                ("Cảnh báo đã xử lý (RESOLVED/CLOSED)", o["alerts_handled"], "cảnh báo"),
                ("Lượng mưa trung bình giờ", o["rainfall_avg_mm"], "mm/h"),
                ("Mực nước cao nhất", o["water_level_max_cm"], "cm"),
                ("Tỉ lệ dữ liệu quan trắc hợp lệ", o["valid_data_ratio"], "%"),
                ("Lần dự báo mới nhất", o["latest_forecast_at"], "giờ VN"),
            ]
            b.sheet(name, [("Chỉ tiêu", ""), ("Giá trị", "#,##0.###"), ("Đơn vị", "")],
                    [(k, v, u) for k, v, u in rows], "theo từng chỉ tiêu", "Tổng hợp từ CSDL urban_flood_dss",
                    sim_note)
            ws = b.wb[name]
            for r in ws.iter_rows(min_row=10):
                if r[0].value == "Tỉ lệ dữ liệu quan trắc hợp lệ":
                    r[1].number_format = "0.00%"
                if r[0].value == "Lần dự báo mới nhất":
                    r[1].number_format = DT_FMT
        elif name == "Luong_mua":
            rows = stats.rainfall_rows(db, f, MAX_ROWS)
            b.sheet(name, [("Thời gian (giờ VN)", "dt"), ("Mã trạm", "text"), ("Tên trạm", ""), ("Khu vực", ""),
                           ("Lượng mưa (mm/h)", "0.0"), ("Chất lượng", ""), ("Trạng thái dữ liệu", "")],
                    [(r[0], r[1], r[2], r[3], r[4], r[5], _demo(r[6])) for r in rows], "mm/giờ",
                    "Trạm đo mưa", f"Tối đa {MAX_ROWS:,} dòng. SUSPECT = giá trị bất thường; MISSING = mất dữ liệu.")
        elif name == "Muc_nuoc":
            rows = stats.water_rows(db, f, MAX_ROWS)
            b.sheet(name, [("Thời gian (giờ VN)", "dt"), ("Mã trạm", "text"), ("Tên trạm", ""), ("Khu vực", ""),
                           ("Mực nước (cm)", "0.0"), ("Chất lượng", ""), ("Trạng thái dữ liệu", "")],
                    [(r[0], r[1], r[2], r[3], r[4], r[5], _demo(r[6])) for r in rows], "cm (so với cao độ tham chiếu)",
                    "Trạm đo mực nước", f"Tối đa {MAX_ROWS:,} dòng.")
        elif name == "Du_bao_AI":
            rows = stats.forecast_rows(db, f, MAX_ROWS)
            b.sheet(name, [("Thời điểm phát hành", "dt"), ("Thời điểm dự báo", "dt"), ("Horizon (giờ)", "0"),
                           ("Mã trạm", "text"), ("Tên trạm", ""), ("Mưa dự báo (mm/h)", "0.00"),
                           ("Mực nước dự báo (cm)", "0.0"), ("Xác suất ngập", "0.0%"), ("Chất lượng dữ liệu", ""),
                           ("Cold-start", ""), ("Trạng thái dữ liệu", ""), ("Mô hình", "")],
                    [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], _demo(r[10]),
                      f"{r[11]}:{r[12]}" if r[11] else "") for r in rows], "mm/h, cm, xác suất 0–100%",
                    "Mô hình LSTM/GRU (Keras)", "Mô hình huấn luyện trên dữ liệu mô phỏng chưa được kiểm chứng thực tế.")
        elif name == "Canh_bao_ngap":
            alerts = list(db.scalars(stats.alert_stmt(f).order_by("triggered_at")))
            b.sheet(name, [("Mã cảnh báo", "text"), ("Thời điểm phát sinh", "dt"), ("Khu vực", ""), ("Mức rủi ro", ""),
                           ("Điểm rủi ro", "0.000"), ("Horizon (giờ)", "0"), ("Trạng thái", ""), ("Xác minh", ""),
                           ("Tiếp nhận lúc", "dt"), ("Xử lý xong lúc", "dt"), ("Người phụ trách", ""),
                           ("Nội dung", ""), ("Trạng thái dữ liệu", "")],
                    [(a.code, a.triggered_at, a.area.name, a.risk_level, a.score, a.horizon_h, a.status,
                      a.verified_outcome, a.acknowledged_at, a.resolved_at,
                      a.assignee.username if a.assignee else "", a.message, _demo(a.is_simulated)) for a in alerts],
                    "điểm 0–1", "Rule engine cảnh báo", "Ngưỡng cảnh báo phục vụ nghiên cứu/demo.")
        elif name == "Lich_su_ngap":
            evs = list(db.scalars(stats.flood_event_stmt(f).order_by("started_at")))
            b.sheet(name, [("Bắt đầu", "dt"), ("Kết thúc", "dt"), ("Vị trí", ""), ("Khu vực", ""), ("Vĩ độ", "0.00000"),
                           ("Kinh độ", "0.00000"), ("Độ sâu lớn nhất (cm)", "0.0"), ("Nguyên nhân", ""),
                           ("Trạng thái dữ liệu", "")],
                    [(e.started_at, e.ended_at, e.location_name, e.area.name if e.area else "", e.latitude,
                      e.longitude, e.max_depth_cm, e.cause, _demo(e.is_simulated)) for e in evs], "cm, độ (WGS84)",
                    "Sự kiện ngập lịch sử")
        elif name == "Tram_quan_trac":
            rows = stats.station_status(db)
            if f.area_id:
                rows = [r for r in rows if r["area_id"] == f.area_id]
            b.sheet(name, [("Mã trạm", "text"), ("Tên trạm", ""), ("Loại", ""), ("Khu vực", ""), ("Vĩ độ", "0.00000"),
                           ("Kinh độ", "0.00000"), ("Trạng thái", ""), ("Kết nối", ""), ("Chu kỳ (phút)", "0"),
                           ("Ngưỡng ngập (cm)", "0"), ("Quan trắc gần nhất", "dt"), ("Đơn vị quản lý", ""),
                           ("Nguồn", ""), ("Trạng thái dữ liệu", "")],
                    [(r["code"], r["name"], r["type"], r["area"], r["latitude"], r["longitude"], r["status"],
                      r["connection"], r["interval_minutes"], r["flood_threshold_cm"], r["last_observation_at"],
                      r["managing_unit"], r["source"], _demo(r["is_simulated"])) for r in rows],
                    "phút, cm, độ", "Danh mục trạm (trạng thái tại thời điểm xuất)")
        elif name == "Camera":
            rows = stats.camera_status(db, f)
            b.sheet(name, [("Mã camera", "text"), ("Tên", ""), ("Khu vực", ""), ("Trạng thái", ""), ("Công khai", ""),
                           ("Số lần phân tích", "0"), ("Tỉ lệ ngập lớn nhất", "0.0%"), ("Tỉ lệ ngập TB", "0.0%"),
                           ("Phân tích gần nhất", "dt"), ("Trạng thái dữ liệu", "")],
                    [(r["code"], r["name"], r["area"], r["status"], r["is_public"], r["detections"],
                      r["max_flood_ratio"], r["avg_flood_ratio"], r["last_detection_at"], _demo(r["is_simulated"]))
                     for r in rows], "% diện tích ROI", "YOLOv8-seg / HEURISTIC")
        elif name == "Danh_gia_mo_hinh":
            mp = stats.model_performance(db, f)
            rows = []
            for m in mp["models"]:
                mt = m["metrics"] or {}
                fl, rn = mt.get("flood") or mt.get("heavy_rain") or {}, mt.get("rainfall", {})
                rows.append((m["name"], m["type"], m["version"], m["active"], m["trained_on_simulated"],
                             rn.get("mae"), rn.get("rmse"), fl.get("precision", mt.get("precision")),
                             fl.get("recall", mt.get("recall")), fl.get("f1"), fl.get("brier"),
                             mt.get("mask_map50"), mt.get("box_map50")))
            b.sheet(name, [("Mô hình", ""), ("Loại", ""), ("Phiên bản", "text"), ("Đang triển khai", ""),
                           ("Huấn luyện trên dữ liệu mô phỏng", ""), ("MAE mưa (mm)", "0.000"),
                           ("RMSE mưa (mm)", "0.000"), ("Precision", "0.000"), ("Recall", "0.000"), ("F1", "0.000"),
                           ("Brier", "0.0000"), ("mAP50 mask", "0.000"), ("mAP50 box", "0.000")], rows,
                    "mm, chỉ số 0–1", "Bảng model_versions (đánh giá trên tập test tách theo thời gian)",
                    "Chỉ số đo trên dữ liệu MÔ PHỎNG không phản ánh độ chính xác vận hành thực tế.")
        elif name == "Chat_luong_du_lieu":
            rows = stats.data_quality(db, f)
            b.sheet(name, [("Loại dữ liệu", ""), ("Mã trạm", "text"), ("Tên trạm", ""), ("Tổng bản ghi", "0"),
                           ("VALID", "0"), ("SUSPECT", "0"), ("MISSING", "0"), ("Tỉ lệ hợp lệ", "0.00%")],
                    [(r["kind"], r["code"], r["name"], r["total"], r.get("VALID", 0), r.get("SUSPECT", 0),
                      r.get("MISSING", 0), r["valid_ratio"]) for r in rows], "bản ghi",
                    "Kiểm tra chất lượng tự động khi nhập dữ liệu")
        elif name == "Nguon_du_lieu":
            srcs = list(db.scalars(select(DataSource).order_by(DataSource.code)))
            b.sheet(name, [("Mã", "text"), ("Tên nguồn", ""), ("Loại", ""), ("Mô phỏng", ""), ("Giấy phép", ""),
                           ("URL", "")],
                    [(s.code, s.name, s.kind, s.is_simulated, s.license, s.url) for s in srcs], "—",
                    "Bảng data_sources")
    buf = io.BytesIO()
    b.wb.save(buf)
    return buf.getvalue(), b.rows_written


def build_csv(db: Session, kind: str, f: Filters) -> tuple[bytes, int]:
    out = io.StringIO()
    w = csv.writer(out)
    if kind == "rainfall":
        w.writerow(["observed_at_vn", "station_code", "station_name", "area", "rainfall_mm", "quality", "simulated"])
        rows = stats.rainfall_rows(db, f, MAX_ROWS)
    elif kind == "water_level":
        w.writerow(["observed_at_vn", "station_code", "station_name", "area", "water_level_cm", "quality", "simulated"])
        rows = stats.water_rows(db, f, MAX_ROWS)
    else:
        raise ValueError("CSV hỗ trợ: rainfall, water_level")
    for r in rows:
        w.writerow([_local(r[0]), *[safe(x) for x in r[1:6]], r[6]])
    return ("﻿" + out.getvalue()).encode("utf-8"), len(rows)


def record(db: Session, user: User, report: str, fmt: str, f: Filters, name: str, n: int) -> None:
    db.add(ExportHistory(user_id=user.id, report_type=report, file_format=fmt, filters=f.as_dict(), file_name=name,
                         row_count=n))
    db.commit()
