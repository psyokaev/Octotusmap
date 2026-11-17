"""Truy vấn không gian (PostGIS, SRID 4326)."""


from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.spatial import SRID, st_point
from app.models import AdministrativeArea, FloodRiskSnapshot


def area_at(db: Session, lon: float, lat: float, level: str | None = None) -> AdministrativeArea | None:
    """Khu vực chứa điểm (point-in-polygon), ưu tiên cấp chi tiết nhất (WARD trước DISTRICT)."""
    stmt = select(AdministrativeArea).where(func.ST_Contains(AdministrativeArea.__table__.c.geom, st_point(lon, lat)))
    if level:
        stmt = stmt.where(AdministrativeArea.level == level)
    return db.scalars(stmt.order_by(AdministrativeArea.level.desc()).limit(1)).first()


def nearest_area(db: Session, lon: float, lat: float, max_m: float = 5000,
                 level: str | None = None) -> AdministrativeArea | None:
    a = area_at(db, lon, lat, level)
    if a:
        return a
    d = func.ST_DistanceSphere(func.ST_SetSRID(func.ST_MakePoint(AdministrativeArea.centroid_lon,
                                                                 AdministrativeArea.centroid_lat), SRID),
                               st_point(lon, lat))
    stmt = select(AdministrativeArea).where(d <= max_m * 4)
    if level:
        stmt = stmt.where(AdministrativeArea.level == level)
    return db.scalars(stmt.order_by(d).limit(1)).first()


def nearest_stations(db: Session, lon: float, lat: float, limit: int = 3, max_m: float = 8000):
    """[(station_id, distance_m)] theo ST_DistanceSphere."""
    rows = db.execute(text(
        "SELECT id, d FROM (SELECT id, ST_DistanceSphere(location, ST_GeomFromText(:p, 4326)) AS d "
        "FROM monitoring_stations WHERE deleted_at IS NULL AND status='ACTIVE') s "
        "WHERE d <= :m ORDER BY d LIMIT :l"), {"p": f"POINT({lon} {lat})", "m": max_m, "l": limit}).all()
    return [(r[0], float(r[1])) for r in rows]


_geom_cache: dict = {"key": None, "value": {}}


def area_geometries(db: Session) -> dict[int, dict]:
    """Geometry ít thay đổi -> cache, làm mới khi số lượng/thời điểm cập nhật đổi."""
    key = tuple(db.execute(select(func.count(), func.max(AdministrativeArea.updated_at))).one())
    if _geom_cache["key"] != key:
        rows = db.execute(select(AdministrativeArea.id, AdministrativeArea.code, AdministrativeArea.name,
                                 AdministrativeArea.level, AdministrativeArea.geom,
                                 AdministrativeArea.susceptibility, AdministrativeArea.cluster,
                                 AdministrativeArea.parent_id)).all()
        _geom_cache["value"] = {r[0]: {"code": r[1], "name": r[2], "level": r[3], "geom": r[4],
                                       "susceptibility": r[5], "cluster": r[6], "parent_id": r[7]} for r in rows}
        _geom_cache["key"] = key
    return _geom_cache["value"]


def latest_issue_time(db: Session):
    return db.scalar(select(func.max(FloodRiskSnapshot.issued_at)))


def risk_geojson(db: Session, horizon: int) -> dict:
    """FeatureCollection khu vực + mức rủi ro của lần đánh giá mới nhất tại mốc horizon."""
    issued = latest_issue_time(db)
    snaps = {}
    if issued:
        snaps = {s.area_id: s for s in db.scalars(select(FloodRiskSnapshot).where(
            FloodRiskSnapshot.issued_at == issued, FloodRiskSnapshot.horizon_h == horizon))}
    feats = []
    for aid, a in area_geometries(db).items():
        s = snaps.get(aid)
        feats.append({"type": "Feature", "id": aid, "geometry": a["geom"], "properties": {
            "id": aid, "code": a["code"], "name": a["name"], "level": a["level"], "parent_id": a["parent_id"],
            "risk_level": s.risk_level if s else "NO_DATA", "score": s.score if s else None,
            "flood_probability": s.flood_probability if s else None,
            "cause": (s.explanation or {}).get("cause") if s else None,
            "depth_cm": (s.explanation or {}).get("depth_cm") if s else None,
            "rainfall_mm": s.rainfall_mm if s else None, "is_simulated": s.is_simulated if s else False,
        }})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"horizon_h": horizon, "issued_at": issued.isoformat() + "Z" if issued else None}}


def areas_on_line(db: Session, coords: list[list[float]]) -> list[int]:
    """Các khu vực mà tuyến (LineString lon/lat) đi qua."""
    step = max(1, len(coords) // 300)  # shortcut: lấy mẫu tối đa ~300 đỉnh cho truy vấn ST_Intersects
    pts = coords[::step] + [coords[-1]]
    wkt = "LINESTRING(" + ",".join(f"{x} {y}" for x, y in pts) + ")"
    rows = db.execute(text(
        "SELECT id FROM administrative_areas "
        "WHERE ST_Intersects(geom, ST_GeomFromText(:w, 4326))"), {"w": wkt}).all()
    return [r[0] for r in rows]
