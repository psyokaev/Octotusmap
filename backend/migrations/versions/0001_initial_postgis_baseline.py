"""initial postgis baseline

Revision ID: 0001
Revises: 
Create Date: 2026-11-10 23:02:45.033374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app.core.spatial

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for ext in ("postgis", "unaccent", "citext"):  # citext: username/email không phân biệt hoa thường
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    op.create_table('data_sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('license', sa.String(length=200), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('model_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('model_type', sa.String(length=30), nullable=False),
    sa.Column('version', sa.String(length=40), nullable=False),
    sa.Column('artifact_path', sa.String(length=300), nullable=False),
    sa.Column('dataset_description', sa.Text(), nullable=False),
    sa.Column('trained_on_simulated', sa.Boolean(), nullable=False),
    sa.Column('metrics', sa.JSON(), nullable=True),
    sa.Column('params', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('trained_at', sa.DateTime(), nullable=True),
    sa.Column('training_seconds', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', 'version', name='uq_model_name_version')
    )
    op.create_table('roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', postgresql.CITEXT(), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('username')
    )
    op.create_table('administrative_areas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('geom', app.core.spatial.Geometry(geom_type='MULTIPOLYGON'), nullable=False),
    sa.Column('centroid_lat', sa.Float(), nullable=False),
    sa.Column('centroid_lon', sa.Float(), nullable=False),
    sa.Column('susceptibility', sa.Float(), nullable=False),
    sa.Column('cluster', sa.String(length=30), nullable=False),
    sa.Column('elevation_m', sa.Float(), nullable=True),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_administrative_areas_name'), 'administrative_areas', ['name'], unique=False)
    op.create_index('sx_area_geom', 'administrative_areas', ['geom'], unique=False, postgresql_using='gist')
    op.create_table('alert_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('version')
    )
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('entity_type', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.String(length=50), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_audit_time', 'audit_logs', ['created_at'], unique=False)
    op.create_table('export_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('report_type', sa.String(length=40), nullable=False),
    sa.Column('file_format', sa.String(length=10), nullable=False),
    sa.Column('filters', sa.JSON(), nullable=True),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('flood_simulations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('location', app.core.spatial.Geometry(geom_type='POINT'), nullable=False),
    sa.Column('radius_m', sa.Integer(), nullable=False),
    sa.Column('depth_cm', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('sx_sim_loc', 'flood_simulations', ['location'], unique=False, postgresql_using='gist')
    op.create_table('system_settings',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', sa.JSON(), nullable=True),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('training_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('model_version_id', sa.Integer(), nullable=True),
    sa.Column('task', sa.String(length=30), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('params', sa.JSON(), nullable=True),
    sa.Column('metrics', sa.JSON(), nullable=True),
    sa.Column('log', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_roles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_id')
    )
    op.create_table('alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=False),
    sa.Column('risk_level', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=15), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('recommendations', sa.JSON(), nullable=True),
    sa.Column('explanation', sa.JSON(), nullable=True),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('horizon_h', sa.Integer(), nullable=False),
    sa.Column('rule_id', sa.Integer(), nullable=True),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('assigned_to', sa.Integer(), nullable=True),
    sa.Column('verified_outcome', sa.String(length=15), nullable=False),
    sa.Column('triggered_at', sa.DateTime(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index('ix_alert_status_area', 'alerts', ['status', 'area_id'], unique=False)
    op.create_index('ix_alert_triggered', 'alerts', ['triggered_at'], unique=False)
    op.create_table('cameras',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('location', app.core.spatial.Geometry(geom_type='POINT'), nullable=False),
    sa.Column('stream_url', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('roi', sa.JSON(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('retention_days', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_cameras_deleted_at'), 'cameras', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_cameras_name'), 'cameras', ['name'], unique=False)
    op.create_index('sx_camera_loc', 'cameras', ['location'], unique=False, postgresql_using='gist')
    op.create_table('flood_hotspots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('street', sa.String(length=200), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('location', app.core.spatial.Geometry(geom_type='POINT'), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', 'latitude', 'longitude', name='uq_hotspot')
    )
    op.create_index(op.f('ix_flood_hotspots_area_id'), 'flood_hotspots', ['area_id'], unique=False)
    op.create_index(op.f('ix_flood_hotspots_name'), 'flood_hotspots', ['name'], unique=False)
    op.create_index('sx_hotspot_loc', 'flood_hotspots', ['location'], unique=False, postgresql_using='gist')
    op.create_table('flood_reports',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('location', app.core.spatial.Geometry(geom_type='POINT'), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('confirmations', sa.Integer(), nullable=False),
    sa.Column('confirmed_by', sa.JSON(), nullable=True),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('reported_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_report_status_exp', 'flood_reports', ['status', 'expires_at'], unique=False)
    op.create_index('sx_report_loc', 'flood_reports', ['location'], unique=False, postgresql_using='gist')
    op.create_table('flood_risk_snapshots',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=False),
    sa.Column('issued_at', sa.DateTime(), nullable=False),
    sa.Column('horizon_h', sa.Integer(), nullable=False),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('flood_probability', sa.Float(), nullable=True),
    sa.Column('rainfall_mm', sa.Float(), nullable=True),
    sa.Column('water_level_ratio', sa.Float(), nullable=True),
    sa.Column('camera_flood_ratio', sa.Float(), nullable=True),
    sa.Column('explanation', sa.JSON(), nullable=True),
    sa.Column('rule_id', sa.Integer(), nullable=True),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('area_id', 'issued_at', 'horizon_h', name='uq_risk_area_issue_h')
    )
    op.create_index('ix_risk_issued', 'flood_risk_snapshots', ['issued_at'], unique=False)
    op.create_table('historical_flood_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('location_name', sa.String(length=200), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('location', app.core.spatial.Geometry(geom_type='POINT'), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('max_depth_cm', sa.Float(), nullable=True),
    sa.Column('cause', sa.String(length=50), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_historical_flood_events_area_id'), 'historical_flood_events', ['area_id'], unique=False)
    op.create_index(op.f('ix_historical_flood_events_location_name'), 'historical_flood_events', ['location_name'], unique=False)
    op.create_index(op.f('ix_historical_flood_events_started_at'), 'historical_flood_events', ['started_at'], unique=False)
    op.create_index('sx_flood_loc', 'historical_flood_events', ['location'], unique=False, postgresql_using='gist')
    op.create_table('monitoring_stations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('station_type', sa.String(length=20), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('location', app.core.spatial.Geometry(geom_type='POINT'), nullable=False),
    sa.Column('managing_unit', sa.String(length=150), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('interval_minutes', sa.Integer(), nullable=False),
    sa.Column('flood_threshold_cm', sa.Float(), nullable=False),
    sa.Column('elevation_m', sa.Float(), nullable=True),
    sa.Column('last_observation_at', sa.DateTime(), nullable=True),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('latitude BETWEEN -90 AND 90', name='ck_station_lat'),
    sa.CheckConstraint('longitude BETWEEN -180 AND 180', name='ck_station_lon'),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_monitoring_stations_area_id'), 'monitoring_stations', ['area_id'], unique=False)
    op.create_index(op.f('ix_monitoring_stations_deleted_at'), 'monitoring_stations', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_monitoring_stations_name'), 'monitoring_stations', ['name'], unique=False)
    op.create_index('sx_station_loc', 'monitoring_stations', ['location'], unique=False, postgresql_using='gist')
    op.create_table('alert_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('alert_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('from_status', sa.String(length=15), nullable=True),
    sa.Column('to_status', sa.String(length=15), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('changed_by', sa.Integer(), nullable=True),
    sa.Column('changed_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alert_history_alert_id'), 'alert_history', ['alert_id'], unique=False)
    op.create_table('camera_frames',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('camera_id', sa.Integer(), nullable=True),
    sa.Column('captured_at', sa.DateTime(), nullable=False),
    sa.Column('image_path', sa.String(length=300), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['camera_id'], ['cameras.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_camera_frames_camera_id'), 'camera_frames', ['camera_id'], unique=False)
    op.create_table('forecasts',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('station_id', sa.Integer(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('model_version_id', sa.Integer(), nullable=True),
    sa.Column('issued_at', sa.DateTime(), nullable=False),
    sa.Column('horizon_h', sa.Integer(), nullable=False),
    sa.Column('target_time', sa.DateTime(), nullable=False),
    sa.Column('rainfall_mm', sa.Float(), nullable=False),
    sa.Column('water_level_cm', sa.Float(), nullable=True),
    sa.Column('flood_probability', sa.Float(), nullable=False),
    sa.Column('data_quality', sa.String(length=15), nullable=False),
    sa.Column('is_cold_start', sa.Boolean(), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.CheckConstraint('flood_probability BETWEEN 0 AND 1', name='ck_fc_prob'),
    sa.ForeignKeyConstraint(['area_id'], ['administrative_areas.id'], ),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ),
    sa.ForeignKeyConstraint(['station_id'], ['monitoring_stations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('station_id', 'issued_at', 'horizon_h', name='uq_fc_station_issue_h')
    )
    op.create_index('ix_fc_issued', 'forecasts', ['issued_at'], unique=False)
    op.create_index(op.f('ix_forecasts_area_id'), 'forecasts', ['area_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('alert_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notif_user_read', 'notifications', ['user_id', 'is_read'], unique=False)
    op.create_table('rainfall_observations',
    sa.Column('station_id', sa.Integer(), nullable=False),
    sa.Column('rainfall_mm', sa.Float(), nullable=True),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('observed_at', sa.DateTime(), nullable=False),
    sa.Column('quality_flag', sa.String(length=15), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('ingested_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.ForeignKeyConstraint(['station_id'], ['monitoring_stations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('station_id', 'observed_at', name='uq_rain_station_time')
    )
    op.create_index('ix_rain_time', 'rainfall_observations', ['observed_at'], unique=False)
    op.create_table('sensors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('station_id', sa.Integer(), nullable=False),
    sa.Column('sensor_type', sa.String(length=20), nullable=False),
    sa.Column('unit', sa.String(length=10), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('installed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['station_id'], ['monitoring_stations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('water_level_observations',
    sa.Column('station_id', sa.Integer(), nullable=False),
    sa.Column('water_level_cm', sa.Float(), nullable=True),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('observed_at', sa.DateTime(), nullable=False),
    sa.Column('quality_flag', sa.String(length=15), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('ingested_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.ForeignKeyConstraint(['station_id'], ['monitoring_stations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('station_id', 'observed_at', name='uq_wl_station_time')
    )
    op.create_index('ix_wl_time', 'water_level_observations', ['observed_at'], unique=False)
    op.create_table('camera_detections',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('frame_id', sa.BigInteger(), nullable=False),
    sa.Column('camera_id', sa.Integer(), nullable=True),
    sa.Column('model_version_id', sa.Integer(), nullable=True),
    sa.Column('detected_at', sa.DateTime(), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('flood_ratio', sa.Float(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('num_regions', sa.Integer(), nullable=False),
    sa.Column('result_image_path', sa.String(length=300), nullable=False),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['camera_id'], ['cameras.id'], ),
    sa.ForeignKeyConstraint(['frame_id'], ['camera_frames.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_det_cam_time', 'camera_detections', ['camera_id', 'detected_at'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_det_cam_time', table_name='camera_detections')
    op.drop_table('camera_detections')
    op.drop_index('ix_wl_time', table_name='water_level_observations')
    op.drop_table('water_level_observations')
    op.drop_table('sensors')
    op.drop_index('ix_rain_time', table_name='rainfall_observations')
    op.drop_table('rainfall_observations')
    op.drop_index('ix_notif_user_read', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_forecasts_area_id'), table_name='forecasts')
    op.drop_index('ix_fc_issued', table_name='forecasts')
    op.drop_table('forecasts')
    op.drop_index(op.f('ix_camera_frames_camera_id'), table_name='camera_frames')
    op.drop_table('camera_frames')
    op.drop_index(op.f('ix_alert_history_alert_id'), table_name='alert_history')
    op.drop_table('alert_history')
    op.drop_index('sx_station_loc', table_name='monitoring_stations', postgresql_using='gist')
    op.drop_index(op.f('ix_monitoring_stations_name'), table_name='monitoring_stations')
    op.drop_index(op.f('ix_monitoring_stations_deleted_at'), table_name='monitoring_stations')
    op.drop_index(op.f('ix_monitoring_stations_area_id'), table_name='monitoring_stations')
    op.drop_table('monitoring_stations')
    op.drop_index('sx_flood_loc', table_name='historical_flood_events', postgresql_using='gist')
    op.drop_index(op.f('ix_historical_flood_events_started_at'), table_name='historical_flood_events')
    op.drop_index(op.f('ix_historical_flood_events_location_name'), table_name='historical_flood_events')
    op.drop_index(op.f('ix_historical_flood_events_area_id'), table_name='historical_flood_events')
    op.drop_table('historical_flood_events')
    op.drop_index('ix_risk_issued', table_name='flood_risk_snapshots')
    op.drop_table('flood_risk_snapshots')
    op.drop_index('sx_report_loc', table_name='flood_reports', postgresql_using='gist')
    op.drop_index('ix_report_status_exp', table_name='flood_reports')
    op.drop_table('flood_reports')
    op.drop_index('sx_hotspot_loc', table_name='flood_hotspots', postgresql_using='gist')
    op.drop_index(op.f('ix_flood_hotspots_name'), table_name='flood_hotspots')
    op.drop_index(op.f('ix_flood_hotspots_area_id'), table_name='flood_hotspots')
    op.drop_table('flood_hotspots')
    op.drop_index('sx_camera_loc', table_name='cameras', postgresql_using='gist')
    op.drop_index(op.f('ix_cameras_name'), table_name='cameras')
    op.drop_index(op.f('ix_cameras_deleted_at'), table_name='cameras')
    op.drop_table('cameras')
    op.drop_index('ix_alert_triggered', table_name='alerts')
    op.drop_index('ix_alert_status_area', table_name='alerts')
    op.drop_table('alerts')
    op.drop_table('user_roles')
    op.drop_table('training_runs')
    op.drop_table('system_settings')
    op.drop_index('sx_sim_loc', table_name='flood_simulations', postgresql_using='gist')
    op.drop_table('flood_simulations')
    op.drop_table('export_history')
    op.drop_index('ix_audit_time', table_name='audit_logs')
    op.drop_index('ix_audit_entity', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_table('alert_rules')
    op.drop_index('sx_area_geom', table_name='administrative_areas', postgresql_using='gist')
    op.drop_index(op.f('ix_administrative_areas_name'), table_name='administrative_areas')
    op.drop_table('administrative_areas')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('model_versions')
    op.drop_table('data_sources')
    # ### end Alembic commands ###
