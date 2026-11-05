"""Startup, configuration, logging and routing boundaries for operations."""
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, inspect, text

from app.marketplace.app_logging import safe_request_path
from app.marketplace.app_schema import apply_schema, check_schema, register_models
from app.marketplace.bootstrap import install
from app.marketplace.models import MarketBase
from app.marketplace.sharing_config import validate_share_origin


def test_new_operations_routes_are_mounted_on_the_real_installation():
    app = FastAPI()
    install(app)
    paths = app.openapi()["paths"]
    for path in (
        "/api/admin/marketplace/app/social/metrics",
        "/api/admin/marketplace/app/social/metrics/{target_type}/{target_id}",
        "/api/admin/marketplace/app/social/initialization-jobs",
        "/api/admin/marketplace/curation/{target_type}/{target_id}",
        "/api/admin/marketplace/curation/batch",
        "/api/marketplace/app/v1/{target_type}/{target_id}/share-sessions",
        "/api/marketplace/app/v1/share-sessions/{token}/events",
    ):
        assert path in paths
    routes = {route.path for route in app.routes}
    assert {"/s/{public_id}", "/.well-known/apple-app-site-association"} <= routes


def test_additive_schema_upgrades_an_old_stats_table_twice_without_losing_counts():
    register_models()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        MarketBase.metadata.create_all(connection)
        connection.execute(text("ALTER TABLE marketplace_app_content_stats DROP COLUMN share_count"))
        connection.execute(text("INSERT INTO marketplace_app_content_stats (target_type,target_id,like_count,favorite_count,comment_count) VALUES ('work', 1, 23, 7, 2)"))
        apply_schema(connection)
        apply_schema(connection)
        assert check_schema(connection) == []
        assert "share_count" in {row["name"] for row in inspect(connection).get_columns("marketplace_app_content_stats")}
        assert tuple(connection.execute(text("SELECT like_count,favorite_count,comment_count,share_count FROM marketplace_app_content_stats")).one()) == (23, 7, 2, 0)


@pytest.mark.parametrize("url", ["http://example.com", "https://localhost", "https://192.168.110.37", "https://127.0.0.1", "https://example.com/path", "https://a:b@example.com", "https://example.com?next=x", "https://example.com:8000", "https://foo.local"])
def test_sharing_origin_rejects_private_or_noncanonical_links(url):
    with pytest.raises(ValueError):
        validate_share_origin(url)


def test_system_configuration_is_used_without_environment_changes(monkeypatch):
    from app.marketplace import app_settings
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "marketplace_social_initialization_enabled", True)
    monkeypatch.setattr(settings, "marketplace_sharing_enabled", True)
    monkeypatch.setattr(settings, "marketplace_share_base_url", "https://share.example.com")
    monkeypatch.setattr(settings, "marketplace_share_apple_team_id", "TEAM123456")
    app_settings.get_app_settings.cache_clear()
    value = app_settings.get_app_settings()
    assert value.social_initialization_enabled and value.sharing_enabled
    assert value.share_base_url == "https://share.example.com"
    assert value.share_apple_team_id == "TEAM123456"
    app_settings.get_app_settings.cache_clear()


def test_share_session_tokens_are_redacted_from_access_logs():
    assert safe_request_path("/api/marketplace/app/v1/share-sessions/private-token/events?secret=1") == "/api/marketplace/app/v1/share-sessions/[redacted]/events"


async def test_engagement_runtime_is_idempotent_and_stops_without_media(monkeypatch):
    import asyncio
    from app.marketplace import engagement_runtime, app_bootstrap, app_engagement
    started = asyncio.Event()
    async def ready():
        return True
    async def maintain():
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(app_bootstrap, "schema_ready", ready)
    monkeypatch.setattr(app_engagement, "run_engagement_maintenance_once", maintain)
    try:
        await engagement_runtime.start_engagement_runtime()
        await asyncio.wait_for(started.wait(), 1)
        task = engagement_runtime._task
        await engagement_runtime.start_engagement_runtime()
        assert engagement_runtime._task is task
    finally:
        await engagement_runtime.stop_engagement_runtime()
    assert engagement_runtime._task is None
