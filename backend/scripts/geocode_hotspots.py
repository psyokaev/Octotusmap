"""Geocode danh sách điểm ngập (datasets/gis/flood_hotspots_raw.csv) bằng Photon (OSM) -> flood_hotspots.csv.

Nguồn danh sách: Phòng CSGT Công an TP.HCM qua báo Tiền Phong, 06/10/2026.
Toạ độ là kết quả geocode gần đúng (tâm đối tượng OSM), không phải toạ độ khảo sát.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SOURCE_URL = "https://tienphong.vn/122-diem-co-nguy-co-ngap-tai-tphcm-csgt-canh-bao-khan-post1882808.tpo"


def main() -> None:
    from app.core.config import get_settings
    from app.services.search_service import geocode

    gis = get_settings().datasets_dir / "gis"
    rows = list(csv.DictReader(open(gis / "flood_hotspots_raw.csv", encoding="utf-8")))
    out, failed = [], []
    for r in rows:
        res = geocode(r["query"], limit=1)
        if not res:
            failed.append(r["name"])
            continue
        out.append({"name": r["name"], "street": r["query"].split(",")[0], "lat": round(res[0]["lat"], 6),
                    "lon": round(res[0]["lon"], 6), "cause": r["cause"], "note": r["note"], "source_url": SOURCE_URL})
        print(f"OK  {r['name']}: {out[-1]['lat']}, {out[-1]['lon']}")
    with open(gis / "flood_hotspots.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} điểm geocode được; không tìm thấy: {failed}")


if __name__ == "__main__":
    main()
