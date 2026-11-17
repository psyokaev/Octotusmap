from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.ai.forecasting import train
from app.models import Forecast, ModelVersion, MonitoringStation
from app.services import forecast_service as fs
from app.services import gis_service
from tests.integration.test_api import API, STATION


@pytest.fixture(autouse=True)
def _drop_cluster_models(db):
    yield
    db.rollback()
    ids = select(ModelVersion.id).where(ModelVersion.model_type.like("%_CLUSTER"))
    db.execute(delete(Forecast).where(Forecast.model_version_id.in_(ids)))
    db.execute(delete(ModelVersion).where(ModelVersion.id.in_(ids)))
    db.commit()


def _fc_models(db, issued_at):
    db.rollback()
    return {sid: mid for sid, mid in db.execute(select(Forecast.station_id, Forecast.model_version_id)
                                                .where(Forecast.issued_at == issued_at)).all()}


def test_cluster_model_used_for_its_stations_and_cold_start(client, operator, db):
    from app.jobs.pipeline import run_cycle

    run_cycle()
    base = fs.active_model(db)
    areas = gis_service.area_geometries(db)
    sts = list(db.scalars(select(MonitoringStation).where(MonitoringStation.deleted_at.is_(None),
                                                          MonitoringStation.area_id.is_not(None))))
    cl = {s.id: fs._cluster(areas, s.area_id) for s in sts}
    target = cl[sts[0].id]
    other = next(s for s in sts if cl[s.id] and cl[s.id] != target)
    r = client.post(f"{API}/stations", headers=operator, json={
        **STATION, "code": "T950", "name": "Trạm lạnh", "latitude": sts[0].latitude, "longitude": sts[0].longitude})
    db.rollback()
    new = db.get(MonitoringStation, r.json()["id"])
    new.area_id = sts[0].area_id  # cold-start trong cụm có mô hình cụm
    cm = ModelVersion(name="flood-gru-X", model_type=f"{base.model_type}_CLUSTER", version="t1",
                      artifact_path=base.artifact_path, params={"cluster": target, "base_model_id": base.id},
                      status="DEPLOYED", is_active=True)
    db.add(cm)
    db.commit()
    assert fs.active_model(db).id == base.id  # mô hình gốc vẫn là active_model
    info = fs.run_inference(db)
    used = _fc_models(db, info["issued_at"])
    assert used[sts[0].id] == cm.id and used[new.id] == cm.id and "T950" in info["cold_start"]
    assert used[other.id] == base.id  # cụm không có mô hình cụm -> mô hình gốc


def test_finetune_keeps_only_if_better(db, monkeypatch):
    from app.core.config import get_settings

    class Fake:
        def save(self, path):
            path.write_text("x", encoding="utf-8")

    base = fs.active_model(db) or None
    assert base, "cần mô hình gốc từ fixture"
    scores = {"CORE": 0.5, "INNER": 1.5}  # val_loss sau tinh chỉnh; gốc = 1.0

    def fake_fit(base_dir, frames, epochs, batch=256):
        c = next(iter(frames))
        b = {"val_loss": 1.0, "rain_mae": 1.0, "n_val": 1}
        return Fake(), b, {**b, "val_loss": scores[c]}

    monkeypatch.setattr(train, "_fit_eval", fake_fit)
    monkeypatch.setattr(train, "load_frames_from_db", lambda db: ({"CORE": (None, 0), "INNER": (None, 0)}, False))
    monkeypatch.setattr(train, "_cluster_of_codes", lambda db: {"CORE": "CORE", "INNER": "INNER"})
    res = train.finetune_clusters(db, epochs=1, log=lambda *_: None)
    assert res["CORE"]["kept"] and not res["INNER"]["kept"]
    mine = list(db.scalars(select(ModelVersion).where(ModelVersion.model_type.like("%_CLUSTER"),
                                                      ModelVersion.version != "t1")))
    assert [m.params["cluster"] for m in mine] == ["CORE"] and mine[0].is_active
    assert fs.active_model(db).id == base.id
    assert get_settings().artifacts_dir in Path(mine[0].artifact_path).parents


def _cm(db, base, cluster, base_id, version):
    cm = ModelVersion(name="flood-x", model_type=f"{base.model_type}_CLUSTER", version=version,
                      artifact_path=base.artifact_path, params={"cluster": cluster, "base_model_id": base_id},
                      status="DEPLOYED", is_active=True)
    db.add(cm)
    db.commit()
    return cm


def test_stale_cluster_model_ignored_and_newest_wins(db):
    base = fs.active_model(db)
    _cm(db, base, "CORE", base.id + 999, "stale")
    old = _cm(db, base, "INNER", base.id, "a")
    new = _cm(db, base, "INNER", base.id, "b")
    got = fs.cluster_models(db)
    assert "CORE" not in got and got["INNER"].id == new.id != old.id


def test_activate_cluster_model_scoped_and_base_checked(client, admin, db):
    base = fs.active_model(db)
    core = _cm(db, base, "CORE", base.id, "a")
    inner = _cm(db, base, "INNER", base.id, "b")
    stale = _cm(db, base, "CORE", base.id + 999, "stale")
    stale.is_active = False
    new_core = _cm(db, base, "CORE", base.id, "c")
    new_core.is_active = False
    db.commit()
    assert client.post(f"{API}/admin/models/{stale.id}/activate", headers=admin).status_code == 409
    assert client.post(f"{API}/admin/models/{new_core.id}/activate", headers=admin).status_code == 200
    db.rollback()
    db.refresh(core), db.refresh(inner)
    assert not core.is_active and inner.is_active  # chỉ cụm CORE bị thay
