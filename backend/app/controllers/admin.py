import threading
from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.core.deps import DB, Admin
from app.core.errors import AppError, NotFound
from app.core.spatial import point_wkt, valid_hcm_coordinate
from app.jobs import pipeline
from app.models import AlertRule, AuditLog, DataSource, FloodSimulation, ModelVersion, SystemSetting, TrainingRun
from app.repositories.base import contains, paginate
from app.schemas.common import Page
from app.schemas.views import (
    AuditOut,
    DataSourceOut,
    ModelVersionOut,
    RuleIn,
    RuleOut,
    SettingIn,
    SettingOut,
    SimulationIn,
    SimulationOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import user_service
from app.services.audit_service import audit
from app.services.rule_engine import validate_config

router = APIRouter(prefix="/admin", tags=["Administration"])


# ------------------------------------------------------------ users
@router.get("/users", response_model=Page[UserOut])
def users(db: DB, _: Admin, q: str | None = None, role: str | None = None, page: int = Query(1, ge=1),
          size: int = Query(20, le=200)):
    rows, total = user_service.list_users(db, q, role, page, size)
    return Page(items=rows, total=total, page=page, size=size)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, user: Admin, request: Request, db: DB):
    return user_service.create_user(db, **body.model_dump(), actor=user, request=request)


@router.patch("/users/{uid}", response_model=UserOut)
def update_user(uid: int, body: UserUpdate, user: Admin, request: Request, db: DB):
    return user_service.update_user(db, uid, body, user, request)


@router.delete("/users/{uid}", status_code=204)
def delete_user(uid: int, user: Admin, request: Request, db: DB):
    user_service.soft_delete(db, uid, user, request)


# ------------------------------------------------------------ settings
@router.get("/settings", response_model=list[SettingOut])
def settings(db: DB, _: Admin):
    return list(db.scalars(select(SystemSetting).order_by(SystemSetting.key)))


@router.put("/settings/{key}", response_model=SettingOut)
def put_setting(key: str, body: SettingIn, user: Admin, request: Request, db: DB):
    s = db.get(SystemSetting, key)
    if not s:
        raise NotFound("Cấu hình")
    audit(db, user, "SETTING_UPDATE", "setting", key, {"before": s.value, "after": body.value}, request)
    s.value, s.updated_by = body.value, user.id
    db.commit()
    return s


@router.get("/data-sources", response_model=list[DataSourceOut])
def data_sources(db: DB, _: Admin):
    return list(db.scalars(select(DataSource).order_by(DataSource.code)))


# ------------------------------------------------------------ rules (mỗi lần lưu = version mới)
@router.get("/rules", response_model=list[RuleOut])
def rules(db: DB, _: Admin):
    return list(db.scalars(select(AlertRule).order_by(AlertRule.version.desc())))


@router.post("/rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, user: Admin, request: Request, db: DB):
    errs = validate_config(body.config)
    if errs:
        raise AppError(422, "INVALID_RULE", "Cấu hình quy tắc không hợp lệ", errs)
    ver = (db.scalar(select(func.max(AlertRule.version))) or 0) + 1
    db.query(AlertRule).update({"is_active": False})
    r = AlertRule(version=ver, name=body.name, config=body.config, notes=body.notes, is_active=True,
                  created_by=user.id)
    db.add(r)
    db.flush()
    audit(db, user, "RULE_CREATE", "alert_rule", r.id, {"version": ver, "config": body.config}, request)
    db.commit()
    return r


@router.post("/rules/{rid}/activate", response_model=RuleOut)
def activate_rule(rid: int, user: Admin, request: Request, db: DB):
    r = db.get(AlertRule, rid)
    if not r:
        raise NotFound("Quy tắc")
    db.query(AlertRule).update({"is_active": False})
    r.is_active = True
    audit(db, user, "RULE_ACTIVATE", "alert_rule", rid, {"version": r.version}, request)
    db.commit()
    return r


# ------------------------------------------------------------ models
@router.get("/models", response_model=list[ModelVersionOut])
def models(db: DB, _: Admin):
    return list(db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc())))


@router.get("/training-runs")
def training_runs(db: DB, _: Admin):
    return [{"id": r.id, "task": r.task, "status": r.status, "started_at": r.started_at.isoformat() + "Z",
             "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None, "params": r.params,
             "model_version_id": r.model_version_id, "log": r.log[-2000:]}
            for r in db.scalars(select(TrainingRun).order_by(TrainingRun.started_at.desc()).limit(50))]


@router.post("/models/{mid}/activate", response_model=ModelVersionOut)
def activate_model(mid: int, user: Admin, request: Request, db: DB):
    m = db.get(ModelVersion, mid)
    if not m or m.model_type == "BASELINE" or not m.artifact_path:
        raise AppError(422, "NOT_DEPLOYABLE", "Mô hình không thể triển khai")
    group = ["LSTM", "GRU"] if m.model_type in ("LSTM", "GRU") else [m.model_type]
    if m.model_type.endswith("_CLUSTER"):  # chỉ thay bản cùng cụm, và chỉ khi gốc của nó là mô hình gốc đang dùng
        from app.services.forecast_service import active_model

        base = active_model(db)
        try:
            ok = bool(base) and int((m.params or {})["base_model_id"]) == base.id
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            raise AppError(409, "BASE_MISMATCH", "Mô hình cụm không tinh chỉnh từ mô hình gốc đang hoạt động")
        for o in db.scalars(select(ModelVersion).where(ModelVersion.model_type.in_(group),
                                                       ModelVersion.is_active.is_(True))):
            if (o.params or {}).get("cluster") == (m.params or {}).get("cluster"):
                o.is_active, o.status = False, "ARCHIVED"
    else:
        db.query(ModelVersion).filter(ModelVersion.model_type.in_(group), ModelVersion.is_active.is_(True)).update(
            {"is_active": False, "status": "ARCHIVED"})
    m.is_active, m.status = True, "DEPLOYED"
    audit(db, user, "MODEL_ACTIVATE", "model_version", mid, {"name": m.name, "version": m.version}, request)
    db.commit()
    return m


_training = threading.Lock()


@router.post("/models/train", status_code=202)
def train(user: Admin, request: Request, db: DB, task: Literal["forecast", "vision"] = "forecast",
          epochs: int = Query(8, ge=1, le=100)):
    """Huấn luyện chạy nền; theo dõi qua /admin/training-runs."""
    if not _training.acquire(blocking=False):
        raise AppError(409, "BUSY", "Đang có phiên huấn luyện khác")

    def job():
        try:
            with SessionLocal() as s:
                if task == "forecast":
                    from app.ai.forecasting.train import train_and_register
                else:
                    from app.ai.computer_vision.train import train_and_register
                if task == "vision":
                    real = get_settings().datasets_dir / "vision" / "flood_area_real" / "data.yaml"
                    train_and_register(s, epochs=epochs, data_yaml=real if real.exists() else None)
                else:
                    train_and_register(s, epochs=epochs)
        finally:
            _training.release()

    threading.Thread(target=job, daemon=True).start()
    audit(db, user, "MODEL_TRAIN", "model_version", "", {"task": task, "epochs": epochs}, request)
    db.commit()
    return {"message": f"Đã bắt đầu huấn luyện {task}", "started_at": utcnow().isoformat() + "Z"}


# ------------------------------------------------------------ mô phỏng ngập (chỉ admin thấy)
@router.get("/simulations", response_model=list[SimulationOut])
def simulations(db: DB, _: Admin):
    return list(db.scalars(select(FloodSimulation).order_by(FloodSimulation.id)))


@router.post("/simulations", response_model=SimulationOut, status_code=201)
def create_simulation(body: SimulationIn, user: Admin, request: Request, db: DB):
    if not valid_hcm_coordinate(body.latitude, body.longitude):
        raise AppError(422, "OUT_OF_AREA", "Vị trí nằm ngoài phạm vi TP.HCM")
    s = FloodSimulation(**body.model_dump(), created_by=user.id, location=point_wkt(body.longitude, body.latitude))
    db.add(s)
    db.flush()
    audit(db, user, "SIMULATION_CREATE", "flood_simulation", s.id, body.model_dump(), request)
    db.commit()
    return s


@router.delete("/simulations", status_code=204)
def clear_simulations(user: Admin, request: Request, db: DB):
    db.query(FloodSimulation).delete()
    audit(db, user, "SIMULATION_CLEAR", "flood_simulation", "", None, request)
    db.commit()


@router.delete("/simulations/{sid}", status_code=204)
def delete_simulation(sid: int, user: Admin, request: Request, db: DB):
    s = db.get(FloodSimulation, sid)
    if not s:
        raise NotFound("Mô phỏng")
    db.delete(s)
    audit(db, user, "SIMULATION_DELETE", "flood_simulation", sid, None, request)
    db.commit()


# ------------------------------------------------------------ audit & jobs
@router.get("/audit-logs", response_model=Page[AuditOut])
def audit_logs(db: DB, _: Admin, q: str | None = None, action: str | None = None, page: int = Query(1, ge=1),
               size: int = Query(50, le=200)):
    stmt = select(AuditLog)
    if q:
        stmt = stmt.where(contains(AuditLog.username, q) | contains(AuditLog.entity_type, q))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows, total = paginate(db, stmt, page, size, AuditLog.created_at, "desc")
    return Page(items=rows, total=total, page=page, size=size)


@router.post("/jobs/run-cycle")
def run_cycle(user: Admin, request: Request, db: DB):
    audit(db, user, "JOB_RUN_CYCLE", "job", "", None, request)
    db.commit()
    out = pipeline.run_cycle()
    return {k: (str(v) if k == "issued_at" else v) for k, v in out.items()}
