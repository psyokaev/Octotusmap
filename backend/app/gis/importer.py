"""Import ranh giới hành chính từ GeoJSON vào PostGIS (SRID 4326, lon/lat)."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.spatial import geojson_to_wkt
from app.models import AdministrativeArea, DataSource

# geoBoundaries VNM ADM2 (2020) -> tên tiếng Việt, mã, cụm (dùng cho cold-start)
HCM_DISTRICTS = {
    "Quan 1": ("Quận 1", "CORE"), "Quan 3": ("Quận 3", "CORE"), "Quan 4": ("Quận 4", "CORE"),
    "Quan 5": ("Quận 5", "CORE"), "Quan 10": ("Quận 10", "CORE"), "Quan 11": ("Quận 11", "CORE"),
    "Phu Nhuan": ("Quận Phú Nhuận", "CORE"), "Binh Thanh": ("Quận Bình Thạnh", "CORE"),
    "Tan Binh": ("Quận Tân Bình", "CORE"),
    "Quan 2": ("Quận 2", "INNER"), "Quan 6": ("Quận 6", "INNER"), "Quan 7": ("Quận 7", "INNER"),
    "Quan 8": ("Quận 8", "INNER"), "Quan 9": ("Quận 9", "INNER"), "Quan 12": ("Quận 12", "INNER"),
    "Go Vap": ("Quận Gò Vấp", "INNER"), "Tan Phu": ("Quận Tân Phú", "INNER"),
    "Binh Tan": ("Quận Bình Tân", "INNER"), "Thu Duc": ("Quận Thủ Đức", "INNER"),
    "Binh Chanh": ("Huyện Bình Chánh", "SUBURBAN"), "Hoc Mon": ("Huyện Hóc Môn", "SUBURBAN"),
    "Cu Chi": ("Huyện Củ Chi", "SUBURBAN"), "Nha Be": ("Huyện Nhà Bè", "SUBURBAN"),
    "Can Gio": ("Huyện Cần Giờ", "SUBURBAN"),
}
HCM_BBOX = (106.33, 10.35, 107.05, 11.2)


def _rings(geom: dict):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def centroid(geom: dict) -> tuple[float, float]:
    """Trọng tâm diện tích (shoelace) của polygon lớn nhất -> (lon, lat)."""
    best, best_a = None, -1.0
    for poly in _rings(geom):
        ring = poly[0]
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:], strict=False):
            c = x0 * y1 - x1 * y0
            a += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
        if abs(a) > best_a and a != 0:
            best_a, best = abs(a), (cx / (3 * a), cy / (3 * a))
    return best


def _in_bbox(geom: dict) -> bool:
    lon, lat = centroid(geom)
    return HCM_BBOX[0] < lon < HCM_BBOX[2] and HCM_BBOX[1] < lat < HCM_BBOX[3]


def import_hcm_districts(db: Session, path: Path, source: DataSource) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for f in data["features"]:
        raw = f["properties"].get("shapeName", "")
        if raw not in HCM_DISTRICTS or not _in_bbox(f["geometry"]):
            continue
        name, cluster = HCM_DISTRICTS[raw]
        code = "HCM-" + raw.upper().replace(" ", "")
        if db.scalar(select(AdministrativeArea.id).where(AdministrativeArea.code == code)):
            continue
        lon, lat = centroid(f["geometry"])
        db.add(AdministrativeArea(code=code, name=name, level="DISTRICT", geom=geojson_to_wkt(f["geometry"]),
                                  centroid_lat=lat, centroid_lon=lon, cluster=cluster, source_id=source.id))
        n += 1
    db.flush()
    return n


def import_geojson(db: Session, data: dict, source: DataSource, level: str = "WARD",
                   name_field: str = "name", code_field: str = "code") -> int:
    """Import GeoJSON tuỳ ý (ví dụ ranh giới phường sau 2025) do quản trị viên cung cấp."""
    n = 0
    for i, f in enumerate(data.get("features", [])):
        g = f.get("geometry") or {}
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        props = f.get("properties") or {}
        code = str(props.get(code_field) or f"{level}-{i:04d}")[:30]
        if db.scalar(select(AdministrativeArea.id).where(AdministrativeArea.code == code)):
            continue
        lon, lat = centroid(g)
        parent = None
        if level == "WARD":  # phường thuộc quận chứa tâm phường
            from app.services import gis_service

            parent = gis_service.area_at(db, lon, lat, "DISTRICT")
        db.add(AdministrativeArea(code=code, name=str(props.get(name_field) or code)[:120], level=level,
                                  parent_id=parent.id if parent else None, cluster=parent.cluster if parent else "",
                                  geom=geojson_to_wkt(g), centroid_lat=lat, centroid_lon=lon,
                                  source_id=source.id))
        n += 1
    db.flush()
    return n
