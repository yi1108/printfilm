from copy import deepcopy

import pytest
import pytest_asyncio
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models_teams  # noqa: F401
from app.printfilm_studio.canvas.legacy_migration import (
    ASSET, CANVAS, PROJECT, convert_legacy_canvas, migrate_project, restore_project, verify_backup,
)


def legacy():
    return {"unrelated": "keep", "canvas_nodes": [
        {"id": "asset-716", "type": "asset", "position": {"x": 42, "y": -20}, "data": {"kind": "character", "assetId": 716, "mediaUrl": "stale.png", "promptHint": "portrait", "generating": True}},
        {"id": "text", "type": "asset", "position": {"x": 300, "y": 0}, "data": {"kind": "text", "textContent": "story"}},
    ], "canvas_edges": [{"id": "edge", "source": "text", "target": "asset-716"}]}


def asset():
    return {"id": 716, "project_id": 21, "type": "character", "asset_type": "image", "url": "current.png", "cover": "cover.png", "params": {"canvas_node_id": "asset-716", "model_id": "saved-model"}}


def test_conversion_preserves_graph_and_uses_current_assets():
    source, assets = legacy(), [asset()]
    original = deepcopy((source, assets))
    document = convert_legacy_canvas(source, assets)
    image, text = document["nodes"]
    assert image["id"] == "asset-716"
    assert image["type"] == "image"
    assert image["position"] == {"x": 42, "y": -20}
    assert image["data"]["mediaUrl"] == "current.png"
    assert image["data"]["prompt"] == "portrait"
    assert image["data"]["modelId"] == "saved-model"
    assert image["data"]["generating"] is False
    assert text["type"] == "text" and text["data"]["text"] == "story"
    assert document["edges"] == source["canvas_edges"]
    assert (source, assets) == original


@pytest.mark.parametrize("kind", ["video", "audio", "image"])
def test_media_types_and_asset_id_fallback(kind):
    source = legacy()
    source["canvas_nodes"][0]["data"] = {"kind": kind}
    document = convert_legacy_canvas(source, [asset()])
    assert document["nodes"][0]["type"] == kind
    assert document["nodes"][0]["data"]["assetId"] == 716


def test_missing_assets_and_broken_edges_fail_closed():
    with pytest.raises(ValueError, match="asset missing"):
        convert_legacy_canvas(legacy(), [])
    source = legacy()
    source["canvas_edges"][0]["target"] = "missing"
    with pytest.raises(ValueError, match="existing nodes"):
        convert_legacy_canvas(source, [asset()])


@pytest_asyncio.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'migration.db').as_posix()}")
    async with engine.begin() as conn:
        for table in (PROJECT, ASSET, CANVAS):
            await conn.run_sync(table.create)
        await conn.execute(insert(PROJECT).values(id=21, user_id=1, title="migration", content=legacy()))
        await conn.execute(insert(ASSET).values(**asset()))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_dry_run_apply_repeat_and_restore(sessions, existing):
    if existing:
        async with sessions.begin() as db:
            await db.execute(insert(CANVAS).values(id="canvas", project_id=21, created_by=1, updated_by=1, document={"nodes": [], "edges": [], "custom": "keep"}, document_version=3))
    backups = []
    def backup(payload):
        backups.append(payload)
        return "backup.json"
    async with sessions.begin() as db:
        assert (await migrate_project(db, 21))["status"] == "ready"
    async with sessions.begin() as db:
        before = (await db.execute(select(CANVAS))).mappings().one_or_none()
        assert bool(before) is existing
        result = await migrate_project(db, 21, apply=True, write_backup=backup)
        assert result["target_version"] == (4 if existing else 1)
    async with sessions.begin() as db:
        assert (await migrate_project(db, 21, apply=True, write_backup=backup))["status"] == "already_migrated"
        assert len(backups) == 1
        assert await db.scalar(select(PROJECT.c.content)) == legacy()
        assert await db.scalar(select(ASSET.c.url)) == "current.png"
        document = await db.scalar(select(CANVAS.c.document))
        if existing:
            assert document["custom"] == "keep"
        await restore_project(db, backups[0])
    async with sessions.begin() as db:
        assert (await db.scalar(select(CANVAS.c.document)))["nodes"] == []
        assert await db.scalar(select(CANVAS.c.document_version)) == result["target_version"] + 1


@pytest.mark.asyncio
async def test_nonempty_target_is_never_overwritten(sessions):
    async with sessions.begin() as db:
        await db.execute(insert(CANVAS).values(id="canvas", project_id=21, created_by=1, updated_by=1, document={"nodes": [{"id": "new"}]}, document_version=5))
        assert (await migrate_project(db, 21, apply=True))["status"] == "skipped_nonempty_target"
        assert await db.scalar(select(CANVAS.c.document_version)) == 5


@pytest.mark.asyncio
async def test_backup_failure_rolls_back_and_restore_refuses_new_edits(sessions):
    def failed_backup(_):
        raise OSError("disk full")
    with pytest.raises(OSError):
        async with sessions.begin() as db:
            await migrate_project(db, 21, apply=True, write_backup=failed_backup)
    backups = []
    async with sessions.begin() as db:
        assert await db.scalar(select(CANVAS.c.id)) is None
        await migrate_project(db, 21, apply=True, write_backup=lambda b: backups.append(b) or "backup.json")
    async with sessions.begin() as db:
        await db.execute(update(CANVAS).values(document_version=2))
    with pytest.raises(ValueError, match="changed since migration"):
        async with sessions.begin() as db:
            await restore_project(db, backups[0])


def test_identical_duplicates_collapse_without_modifying_source_or_edges():
    source = legacy()
    source["canvas_nodes"].append(deepcopy(source["canvas_nodes"][0]))
    original = deepcopy(source)
    with pytest.raises(ValueError, match="unique"):
        convert_legacy_canvas(source, [asset()])
    document = convert_legacy_canvas(source, [asset()], repair_legacy=True)
    assert len(document["nodes"]) == 2
    assert document["edges"] == source["canvas_edges"]
    assert document["legacyRepairs"] == [{"kind": "duplicate_node_collapsed", "source_index": 0, "node_id": "asset-716", "target_id": "asset-716", "target_source_index": 2}]
    assert source == original


def test_distinct_duplicates_keep_last_id_for_edges_and_avoid_id_collisions():
    source = legacy()
    last = deepcopy(source["canvas_nodes"][0])
    last["position"]["x"] = 200
    reserved = {"id": "asset-716--legacy-1", "type": "asset", "data": {"kind": "text", "textContent": "keep"}}
    source["canvas_nodes"].extend([last, reserved])
    first = convert_legacy_canvas(source, [asset()], repair_legacy=True)
    assert first == convert_legacy_canvas(source, [asset()], repair_legacy=True)
    assert len(first["nodes"]) == 4
    assert first["nodes"][0]["id"] == "asset-716--legacy-1-1"
    assert first["nodes"][0]["position"]["x"] == 42
    canonical = next(n for n in first["nodes"] if n["id"] == "asset-716")
    assert canonical["position"]["x"] == 200
    assert first["edges"] == source["canvas_edges"]


def test_equal_older_variants_share_a_new_id_without_losing_the_latest_variant():
    source = legacy()
    older = deepcopy(source["canvas_nodes"][0])
    latest = deepcopy(older)
    latest["data"]["promptHint"] = "new prompt"
    source["canvas_nodes"].extend([older, latest])
    document = convert_legacy_canvas(source, [asset()], repair_legacy=True)
    assert len(document["nodes"]) == 3
    assert sorted(n["data"]["prompt"] for n in document["nodes"] if n["type"] == "image") == ["new prompt", "portrait"]
    assert {r["kind"] for r in document["legacyRepairs"]} == {"duplicate_node_collapsed", "duplicate_node_renamed"}


@pytest.mark.parametrize("has_media", [False, True])
def test_deleted_asset_keeps_node_and_snapshot_but_removes_invalid_binding(has_media):
    source = legacy()
    source["canvas_nodes"][0]["data"]["mediaUrl"] = "snapshot.png" if has_media else None
    original = deepcopy(source)
    document = convert_legacy_canvas(source, [], repair_legacy=True, missing_asset_ids={716})
    node = document["nodes"][0]
    assert "assetId" not in node["data"]
    assert node["data"]["legacyMissingAssetId"] == 716
    assert node["data"]["mediaUrl"] == source["canvas_nodes"][0]["data"]["mediaUrl"]
    assert node["position"] == source["canvas_nodes"][0]["position"]
    assert document["legacyRepairs"][0]["has_media_snapshot"] is has_media
    assert source == original


def test_repair_does_not_guess_unverified_asset_ownership_or_drop_broken_edges():
    with pytest.raises(ValueError, match="asset missing"):
        convert_legacy_canvas(legacy(), [], repair_legacy=True)
    source = legacy()
    source["canvas_edges"][0]["source"] = "missing"
    with pytest.raises(ValueError, match="existing nodes"):
        convert_legacy_canvas(source, [asset()], repair_legacy=True)


@pytest.mark.asyncio
async def test_repaired_migration_preview_apply_and_repeat(sessions):
    source = legacy()
    source["canvas_nodes"].append(deepcopy(source["canvas_nodes"][0]))
    source["canvas_nodes"].append({"id": "deleted", "type": "asset", "data": {"kind": "image", "label": "deleted asset", "assetId": 999}})
    backups = []
    async with sessions.begin() as db:
        await db.execute(update(PROJECT).values(content=source))
        report = await migrate_project(db, 21, repair_legacy=True)
        assert report["status"] == "ready"
        assert report["source_nodes"] == 4 and report["nodes"] == 3
        assert len(report["repairs"]) == 2
        assert await db.scalar(select(CANVAS.c.id)) is None
    async with sessions.begin() as db:
        report = await migrate_project(db, 21, apply=True, repair_legacy=True, write_backup=lambda b: backups.append(b) or "backup.json")
        assert report["status"] == "migrated"
        assert backups[0]["source_content"] == source
    async with sessions.begin() as db:
        assert (await migrate_project(db, 21, apply=True, repair_legacy=True))["status"] == "already_migrated"
        assert await db.scalar(select(PROJECT.c.content)) == source
        verified = await verify_backup(db, backups[0])
        assert verified["status"] == "verified"
        await restore_project(db, backups[0])
        assert (await db.scalar(select(CANVAS.c.document)))["nodes"] == []


@pytest.mark.asyncio
async def test_cross_project_asset_is_never_detached_or_imported(sessions):
    async with sessions.begin() as db:
        await db.execute(update(ASSET).values(project_id=99))
    with pytest.raises(ValueError, match="another project"):
        async with sessions.begin() as db:
            await migrate_project(db, 21, apply=True, repair_legacy=True, write_backup=lambda _: pytest.fail("must fail before backup or writes"))
    async with sessions.begin() as db:
        assert await db.scalar(select(CANVAS.c.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["source", "asset", "target", "version"])
async def test_verification_detects_changes_without_writing(sessions, field):
    backups = []
    async with sessions.begin() as db:
        await migrate_project(db, 21, apply=True, write_backup=lambda b: backups.append(b) or "backup.json")
    async with sessions.begin() as db:
        if field == "source":
            await db.execute(update(PROJECT).values(content={"changed": True}))
        elif field == "asset":
            await db.execute(update(ASSET).values(url="changed.png"))
        elif field == "target":
            await db.execute(update(CANVAS).values(document={"changed": True}))
        else:
            await db.execute(update(CANVAS).values(document_version=2))
    async with sessions.begin() as db:
        before = (await db.execute(select(CANVAS))).mappings().one()
        result = await verify_backup(db, backups[0])
        assert result["status"] == "verification_failed"
        assert result[{"source": "legacy_unchanged", "asset": "assets_unchanged", "target": "target_matches", "version": "version_matches"}[field]] is False
        assert (await db.execute(select(CANVAS))).mappings().one() == before
