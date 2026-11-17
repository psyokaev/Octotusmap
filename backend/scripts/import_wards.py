"""Nạp ranh giới phường/xã từ GADM 4.1 (cấu trúc quận -> phường CŨ, trước sắp xếp 07/2025).

Chạy từ thư mục backend:  .venv\\Scripts\\python scripts\\import_wards.py
File GADM không được phân phối lại nên không commit: tải về datasets/gis/ (dùng học thuật/phi thương mại).
"""

import json
import re
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_VNM_3.json.zip"


def spaced(name: str) -> str:
    """GADM viết liền: 'AnPhúTây' -> 'An Phú Tây', 'Phường1' -> 'Phường 1'."""
    return re.sub(r"(?<=[^\W\d_])(?=[A-ZĐ\d])", " ", name).strip()


def key(name: str) -> str:
    s = unicodedata.normalize("NFD", name.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn").lower())


def ward_name(p: dict) -> str:
    name = spaced(p["NAME_3"])
    kind = {"Thịtrấn": "Thị trấn"}.get(p["TYPE_3"], p["TYPE_3"])
    return name if name.startswith(kind) else f"{kind} {name}"


def main() -> None:
    from sqlalchemy import select

    from app import seed
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.gis.importer import HCM_DISTRICTS, centroid
    from app.core.spatial import geojson_to_wkt
    from app.models import AdministrativeArea, DataSource
    from app.services import openmeteo_service as om

    path = get_settings().datasets_dir / "gis" / "gadm41_VNM_3.json.zip"
    if not path.exists():
        urllib.request.urlretrieve(URL, path)  # noqa: S310  (URL cố định)
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read(z.namelist()[0]))
    wards = [f for f in data["features"] if f["properties"]["NAME_1"] == "HồChíMinh"]
    with SessionLocal() as db:
        src = db.scalar(select(DataSource).where(DataSource.code == "GADM"))
        if not src:
            src = DataSource(code="GADM", name="GADM 4.1 (phường/xã, cấu trúc trước 07/2025)", kind="OPEN_DATA",
                             is_simulated=False, license="Học thuật/phi thương mại, không phân phối lại",
                             url="https://gadm.org")
            db.add(src)
            db.flush()
        by_key = {key(raw): "HCM-" + raw.upper().replace(" ", "") for raw in HCM_DISTRICTS}
        districts = {a.code: a for a in db.scalars(select(AdministrativeArea).where(AdministrativeArea.level == "DISTRICT"))}
        added = []
        for f in wards:
            p = f["properties"]
            parent = districts[by_key[key(p["NAME_2"])]]  # thiếu quận -> lỗi ngay, không gán sai
            code = "W-" + p["GID_3"].removeprefix("VNM.")[:27]
            if db.scalar(select(AdministrativeArea.id).where(AdministrativeArea.code == code)):
                continue
            lon, lat = centroid(f["geometry"])
            a = AdministrativeArea(code=code, name=ward_name(p), level="WARD", parent_id=parent.id,
                                   geom=geojson_to_wkt(f["geometry"]), centroid_lat=lat, centroid_lon=lon,
                                   cluster=parent.cluster, source_id=src.id)
            db.add(a)
            added.append(a)
        db.flush()
        for a, e in zip(added, om.elevations([(a.centroid_lat, a.centroid_lon) for a in added]), strict=True):
            a.elevation_m = e
        db.commit()
        print(f"+{len(added)} phường/xã; thiếu độ cao: {sum(a.elevation_m is None for a in added)}")
        print(f"Điểm ngập gán lại phường: {seed.assign_hotspots_to_wards(db)}")
        seed.update_susceptibility_from_hotspots(db)


if __name__ == "__main__":
    main()
