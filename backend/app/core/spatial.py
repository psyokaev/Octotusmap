"""Kiểu Geometry cho PostGIS (SRID 4326). PostGIS luôn dùng thứ tự trục lon-lat, khớp GeoJSON."""

import json

from sqlalchemy import func
from sqlalchemy.types import Text, TypeDecorator, UserDefinedType

SRID = 4326


class _GeoJSON(TypeDecorator):
    """Kết quả ST_AsGeoJSON (chuỗi) -> dict GeoJSON."""

    impl = Text
    cache_ok = True

    def process_result_value(self, value, dialect):
        return json.loads(value) if value else None


class Geometry(UserDefinedType):
    cache_ok = True

    def __init__(self, geom_type: str = "GEOMETRY"):
        self.geom_type = geom_type

    def get_col_spec(self, **kw):
        return f"geometry({self.geom_type},{SRID})"

    def bind_expression(self, bindvalue):
        # nhận WKT
        return func.ST_GeomFromText(bindvalue, SRID)

    def column_expression(self, col):
        return func.ST_AsGeoJSON(col, type_=_GeoJSON())


def point_wkt(lon: float, lat: float) -> str:
    return f"POINT({lon} {lat})"


def geojson_to_wkt(geom: dict) -> str:
    """Polygon/MultiPolygon/Point/LineString GeoJSON -> WKT (lon lat)."""
    t = geom["type"]
    c = geom["coordinates"]

    def ring(r):
        return "(" + ",".join(f"{x} {y}" for x, y, *_ in r) + ")"

    def poly(p):
        return "(" + ",".join(ring(r) for r in p) + ")"

    if t == "Point":
        return point_wkt(c[0], c[1])
    if t == "LineString":
        return "LINESTRING" + ring(c)
    if t == "Polygon":
        return "MULTIPOLYGON(" + poly(c) + ")"
    if t == "MultiPolygon":
        return "MULTIPOLYGON(" + ",".join(poly(p) for p in c) + ")"
    raise ValueError(f"Không hỗ trợ geometry {t}")


def st_point(lon: float, lat: float):
    return func.ST_GeomFromText(point_wkt(lon, lat), SRID)


def valid_hcm_coordinate(lat: float, lon: float) -> bool:
    """Khung bao rộng TP.HCM (gồm vùng mở rộng 2025)."""
    return 10.0 <= lat <= 11.8 and 106.0 <= lon <= 107.7
