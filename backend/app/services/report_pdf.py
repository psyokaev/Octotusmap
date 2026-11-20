"""Báo cáo PDF tổng hợp (thống kê, cảnh báo, mô hình AI, chất lượng dữ liệu, mưa vệ tinh) bằng matplotlib.

Không thêm thư viện: matplotlib đã có, font DejaVu Sans đi kèm hiển thị đủ tiếng Việt. Giờ in theo giờ Việt Nam.
"""

import io
from datetime import timedelta

import matplotlib

matplotlib.use("Agg")  # không cần màn hình
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core.database import utcnow  # noqa: E402
from app.models import AdministrativeArea, FloodRiskSnapshot  # noqa: E402
from app.services import statistics_service as stats  # noqa: E402
from app.services.statistics_service import Filters  # noqa: E402

VN = timedelta(hours=7)
A4 = (8.27, 11.69)
INK, WATER, LOW, MED, HIGH, GREY = "#0E2A3B", "#1C7CB5", "#2E8B57", "#D99A00", "#C62828", "#8A949C"
LEVEL_VI = {"LOW": "Thấp", "MEDIUM": "Trung bình", "HIGH": "Cao", "INSUFFICIENT_DATA": "Không đủ dữ liệu"}
STATUS_VI = {"NEW": "Mới", "ACKNOWLEDGED": "Đã tiếp nhận", "IN_PROGRESS": "Đang xử lý", "RESOLVED": "Đã xử lý",
             "CLOSED": "Đã đóng"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.titlesize": 10, "axes.titleweight": "bold",
                     "axes.spines.top": False, "axes.spines.right": False})


def _vn(d) -> str:
    return (d + VN).strftime("%d/%m/%Y %H:%M") if d else "—"


def _num(v, unit="", nd=1) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{nd}f}".replace(",", " ").replace(".", ",") if isinstance(v, float) else f"{v:,}".replace(",", " ")
    return s + unit


def _page(pdf, title: str, n: int):
    fig = plt.figure(figsize=A4)
    fig.text(0.07, 0.965, "OctotusMap · Báo cáo ngập úng TP.HCM", color=GREY, fontsize=8)
    fig.text(0.93, 0.965, f"Trang {n}", color=GREY, fontsize=8, ha="right")
    fig.text(0.07, 0.93, title, color=INK, fontsize=14, weight="bold")
    return fig


def _table(fig, rect, header, rows, widths=None, title=None):
    ax = fig.add_axes(rect)
    ax.axis("off")
    if title:
        ax.set_title(title, loc="left")
    if not rows:
        ax.text(0, 0.9, "Không có dữ liệu trong kỳ.", color=GREY)
        return
    t = ax.table(cellText=[[str(c) for c in r] for r in rows], colLabels=header, colWidths=widths,
                 loc="upper left", cellLoc="left", colLoc="left")
    t.auto_set_font_size(False)
    t.set_fontsize(7.5)
    t.scale(1, 1.25)
    for (r, _), c in t.get_celld().items():
        c.set_edgecolor("#DBE3E9")
        if r == 0:
            c.set_facecolor("#F5F8FA")
            c.set_text_props(weight="bold")


def _bars(ax, labels, values, color=WATER, title="", ylabel=""):
    ax.bar(range(len(values)), values, color=color)
    step = max(1, len(labels) // 12)
    ax.set_xticks(range(0, len(labels), step), [labels[i] for i in range(0, len(labels), step)], rotation=45,
                  ha="right")
    ax.set_title(title, loc="left")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#E8EDF1")


def build(db, f: Filters, user, area_name: str | None = None) -> bytes:
    o = stats.overview(db, f)
    a = stats.alert_stats(db, f, "day")
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # ---- 1. Tổng quan
        fig = _page(pdf, "Báo cáo tổng hợp", 1)
        fig.text(0.07, 0.895, f"Kỳ báo cáo: {_vn(f.date_from)} – {_vn(f.date_to)} (giờ Việt Nam)", fontsize=9.5)
        fig.text(0.07, 0.875, f"Khu vực: {area_name or 'Toàn thành phố'} · Người xuất: "
                 f"{user.full_name or user.username} · Lúc {_vn(utcnow())}", fontsize=9.5)
        kpi = [
            ("Trạm quan trắc (đang kết nối / tổng)", f"{o['stations_online']} / {o['stations_total']}"),
            ("Camera tự quản lý", _num(o["cameras_total"])),
            ("Khu vực (quận/huyện)", _num(o["areas_total"])),
            ("Khu vực nguy cơ Thấp / Trung bình / Cao (hiện tại)",
             f"{o['areas_low']} / {o['areas_medium']} / {o['areas_high']}"),
            ("Cảnh báo đang mở", _num(o["alerts_active"])),
            ("Cảnh báo trong kỳ / đã xử lý", f"{o['alerts_in_range']} / {o['alerts_handled']}"),
            ("Mưa trung bình (mm/h)", _num(o["rainfall_avg_mm"], nd=2)),
            ("Mực nước cao nhất (cm)", _num(o["water_level_max_cm"])),
            ("Tỉ lệ dữ liệu hợp lệ", f"{o['valid_data_ratio'] * 100:.1f}%" if o["valid_data_ratio"] else "—"),
            ("Bản dự báo mới nhất", _vn(o["latest_forecast_at"])),
            ("Thời gian TB tới khi tiếp nhận / xử lý xong (phút)",
             f"{_num(a['avg_minutes_to_ack'])} / {_num(a['avg_minutes_to_resolve'])}"),
            ("Độ chính xác cảnh báo đã xác minh", f"{a['precision_verified'] * 100:.0f}%"
             if a["precision_verified"] is not None else "chưa có xác minh"),
        ]
        _table(fig, [0.07, 0.42, 0.86, 0.42], ["Chỉ số", "Giá trị"], kpi, [0.65, 0.35], "Chỉ số chính")
        fig.text(0.07, 0.36, "Lưu ý", weight="bold", fontsize=9.5)
        notes = ("Mưa và triều là dữ liệu mô hình Open-Meteo (không phải trạm đo tại chỗ); mưa vệ tinh GPM IMERG\n"
                 "(NASA) dùng để đối chiếu. Xác suất, độ sâu và mức nguy cơ ngập là ƯỚC TÍNH, chỉ để tham khảo.\n"
                 "Mức nguy cơ và cảnh báo tính theo hệ luật trong Cấu hình › Quy tắc cảnh báo.")
        fig.text(0.07, 0.29, notes, fontsize=8.5, va="bottom", linespacing=1.6)
        issued = db.scalar(select(func.max(FloodRiskSnapshot.issued_at)))
        lstm = sorted(((a_.name, (s_.explanation or {}).get("lstm_flood_6h")) for s_, a_ in db.execute(
            select(FloodRiskSnapshot, AdministrativeArea).join(AdministrativeArea,
                                                               AdministrativeArea.id == FloodRiskSnapshot.area_id)
            .where(FloodRiskSnapshot.issued_at == issued, FloodRiskSnapshot.horizon_h == 0,
                   AdministrativeArea.level == "DISTRICT")).all()
            if (s_.explanation or {}).get("lstm_flood_6h") is not None), key=lambda r: -r[1])[:5] if issued else []
        _table(fig, [0.07, 0.04, 0.86, 0.2], ["Quận/huyện", "Xác suất có ngập trong 6 giờ tới (LSTM, ước tính)"],
               [(n, f"{p * 100:.1f}%") for n, p in lstm], [0.45, 0.55],
               f"LSTM dự báo ngập theo quận, lúc {_vn(issued)} (chỉ tham khảo, không dùng phát cảnh báo)")
        pdf.savefig(fig)
        plt.close(fig)

        # ---- 2. Mưa và mực nước
        fig = _page(pdf, "Lượng mưa và mực nước", 2)
        rain, wl = stats.obs_series(db, f, "rainfall", "day"), stats.obs_series(db, f, "water_level", "day")
        _bars(fig.add_axes([0.1, 0.66, 0.83, 0.22]), [r["bucket"][5:] for r in rain], [r["sum"] or 0 for r in rain],
              title="Tổng lượng mưa theo ngày (mọi điểm lưới)", ylabel="mm")
        ax = fig.add_axes([0.1, 0.36, 0.83, 0.22])
        ax.plot([r["bucket"][5:] for r in wl], [r["max"] for r in wl], color=HIGH, label="Cao nhất")
        ax.plot([r["bucket"][5:] for r in wl], [r["avg"] for r in wl], color=WATER, label="Trung bình")
        ax.set_title("Mực nước theo ngày", loc="left")
        ax.set_ylabel("cm")
        ax.legend(frameon=False)
        ax.tick_params(axis="x", rotation=45)
        ax.set_xticks(ax.get_xticks()[:: max(1, len(wl) // 12)])
        top = sorted(stats.by_station(db, f, "rainfall"), key=lambda r: -(r["sum"] or 0))[:8]
        _table(fig, [0.07, 0.05, 0.86, 0.24], ["Điểm lưới / trạm", "Tổng (mm)", "Lớn nhất (mm/h)"],
               [(r["name"][:60], _num(r["sum"]), _num(r["max"])) for r in top], [0.66, 0.17, 0.17],
               "Nơi mưa nhiều nhất trong kỳ")
        pdf.savefig(fig)
        plt.close(fig)

        # ---- 3. Nguy cơ và cảnh báo
        fig = _page(pdf, "Nguy cơ ngập và cảnh báo", 3)
        cur = stats.latest_risk_counts(db)
        lv = ["LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA"]
        ax = fig.add_axes([0.1, 0.7, 0.36, 0.18])
        ax.bar([LEVEL_VI[x] for x in lv], [cur.get(x, 0) for x in lv], color=[LOW, MED, HIGH, GREY])
        ax.set_title("Số quận theo mức nguy cơ hiện tại", loc="left")
        ax.tick_params(axis="x", labelsize=7)
        ax = fig.add_axes([0.57, 0.7, 0.36, 0.18])
        ax.bar([LEVEL_VI[x] for x in lv[:3]], [a["by_level"].get(x, 0) for x in lv[:3]], color=[LOW, MED, HIGH])
        ax.set_title(f"Cảnh báo trong kỳ theo mức ({a['total']})", loc="left")
        trend = stats.risk_trend(db, f, "day")
        ax = fig.add_axes([0.1, 0.42, 0.83, 0.2])
        x = [r["bucket"][5:] for r in trend]
        bottom = [0] * len(trend)
        for k, c in (("LOW", LOW), ("MEDIUM", MED), ("HIGH", HIGH)):
            vals = [r[k] for r in trend]
            ax.bar(x, vals, bottom=bottom, color=c, label=LEVEL_VI[k])
            bottom = [b + v for b, v in zip(bottom, vals, strict=True)]
        ax.set_title("Xu hướng đánh giá nguy cơ (lượt đánh giá khu vực theo ngày)", loc="left")
        ax.legend(frameon=False, ncol=3)
        ax.tick_params(axis="x", rotation=45)
        ax.set_xticks(ax.get_xticks()[:: max(1, len(trend) // 12)])
        _table(fig, [0.07, 0.07, 0.4, 0.27], ["Khu vực", "Số cảnh báo"],
               [(r["area"], r["count"]) for r in a["by_area"][:10]], [0.72, 0.28], "Cảnh báo theo khu vực")
        _table(fig, [0.53, 0.07, 0.4, 0.27], ["Trạng thái", "Số"],
               [(STATUS_VI.get(k, k), v) for k, v in a["by_status"].items()]
               + [("Xác minh: " + k, v) for k, v in a["verification"].items()], [0.72, 0.28], "Xử lý và xác minh")
        pdf.savefig(fig)
        plt.close(fig)

        # ---- 4. Sự kiện ngập, mô hình AI, chất lượng dữ liệu
        fig = _page(pdf, "Sự kiện ngập, mô hình AI và chất lượng dữ liệu", 4)
        fe = stats.flood_event_stats(db, f, "month")
        _bars(fig.add_axes([0.1, 0.72, 0.36, 0.16]), [r["bucket"] for r in fe["by_time"]],
              [r["count"] for r in fe["by_time"]], title=f"Sự kiện ngập theo tháng ({fe.get('total', '')})")
        _table(fig, [0.53, 0.68, 0.4, 0.2], ["Khu vực", "Số trận"],
               [(r["area"], r["count"]) for r in fe["by_area"][:6]], [0.72, 0.28])
        skill = stats.forecast_skill(db, f)
        _table(fig, [0.07, 0.47, 0.4, 0.17], ["Mốc", "MAE (mm)", "RMSE (mm)", "Số cặp"],
               [(f"+{r['horizon_h']}h", _num(r["mae"], nd=3), _num(r["rmse"], nd=3), r["n"]) for r in skill],
               [0.2, 0.27, 0.27, 0.26], "Sai số dự báo mưa thực tế")
        mods = [m for m in stats.model_performance(db, f)["models"] if m.get("active")]
        rows = []
        for m in mods:
            mt = m.get("metrics") or {}
            key = ("mask_map50", "mask mAP50") if "mask_map50" in mt else ("rain_mae", "MAE mưa")
            rows.append((f"{m['name']} ({m['type']})", f"{key[1]}: {_num(mt.get(key[0]), nd=3)}",
                         "ảnh mô phỏng" if m.get("trained_on_simulated") else "dữ liệu thật"))
        _table(fig, [0.53, 0.47, 0.4, 0.17], ["Mô hình đang dùng", "Chỉ số", "Học trên"], rows, [0.5, 0.3, 0.2],
               "Mô hình AI")
        dq = sorted(stats.data_quality(db, f), key=lambda r: r["valid_ratio"] if r["valid_ratio"] is not None else 2)
        _table(fig, [0.07, 0.07, 0.86, 0.33], ["Loại", "Trạm", "Bản ghi", "Hợp lệ"],
               [(r["kind"], r["name"][:58], r["total"], f"{(r['valid_ratio'] or 0) * 100:.1f}%") for r in dq[:10]],
               [0.15, 0.55, 0.15, 0.15], "Chất lượng dữ liệu (10 trạm kém nhất)")
        pdf.savefig(fig)
        plt.close(fig)

        # ---- 5. Mưa vệ tinh đối chiếu (nếu đã có IMERG)
        sat = stats.satellite_vs_model(db, f)
        if sat:
            fig = _page(pdf, "Mưa vệ tinh GPM IMERG (NASA) đối chiếu", 5)
            days = [r["day"][5:] for r in sat]
            ax = fig.add_axes([0.1, 0.55, 0.83, 0.3])
            ax.plot(days, [r["imerg_mm"] for r in sat], color=INK, marker="o", ms=3, label="IMERG (vệ tinh, ngày UTC)")
            ax.plot(days, [r["model_mm"] for r in sat], color=WATER, marker="o", ms=3, label="Open-Meteo (mô hình)")
            ax.set_title("Mưa trung bình mỗi quận theo ngày", loc="left")
            ax.set_ylabel("mm/ngày")
            ax.legend(frameon=False)
            ax.tick_params(axis="x", rotation=45)
            ax.set_xticks(ax.get_xticks()[:: max(1, len(days) // 12)])
            fig.text(0.07, 0.45, "IMERG là ước tính mưa từ vệ tinh (lưới 0,1°, bản Late run), dùng làm nguồn đo "
                     "độc lập để kiểm tra dữ liệu mô hình.", fontsize=8.5)
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


def area_name(db, area_id: int | None) -> str | None:
    return db.get(AdministrativeArea, area_id).name if area_id and db.get(AdministrativeArea, area_id) else None
