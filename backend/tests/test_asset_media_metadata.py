"""当前媒体来源与生成快照回归，上传与历史还原不能串用旧模型。"""
from types import SimpleNamespace
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.api.drama.assets import _merge_asset_params
from app.services.drama.asset_metadata import current_media_metadata, generated_media_metadata, uploaded_media_metadata
from app.services.drama.generation import activate_asset_image_version, archive_asset_image_version
from app.services.teams.content import asset_card


def test_upload_replaces_generated_metadata_without_old_model():
    """上传来源只描述本次文件，不继承已被替换媒体的模型。"""
    meta = uploaded_media_metadata(filename="portrait.png", size=1024, content_type="image/png")
    params = {"media_metadata": meta, "model_id": "old-model", "generation": {"model_id": "old-model"}}
    assert current_media_metadata(params)["source"] == "upload"
    assert "model_id" not in current_media_metadata(params)
    assert meta["file_size"] == 1024


def test_generated_snapshot_preserves_model_and_exact_options():
    """保存实际调用模型、提示词及参数，而非当前表单默认值。"""
    options = {"aspect_ratio": "3:4", "resolution": "2K", "generate_audio": False, "duration_sec": 0}
    meta = generated_media_metadata(model_id="resolved-model", prompt="完整提示词", options=options)
    options["resolution"] = "4K"
    assert meta["model_id"] == "resolved-model"
    assert meta["parameters"]["resolution"] == "2K"
    assert meta["parameters"]["generate_audio"] is False


def test_legacy_upload_never_uses_old_generation_parameters():
    """旧上传记录即使残留生图参数也必须显示上传。"""
    meta = current_media_metadata({"model_id": "stale", "generation": {"source": "upload", "resolution": "4K"}})
    assert meta["source"] == "upload"
    assert "model_id" not in meta and not meta.get("parameters")


def test_saving_prompt_cannot_replace_server_media_snapshot():
    """编辑提示词保留服务端的当前媒体快照。"""
    original = {"source": "upload", "file_size": 2048}
    result = _merge_asset_params({"media_metadata": original}, {"visualPrompt": "new", "media_metadata": {"source": "generated"}})
    assert result["media_metadata"] == original
    assert result["visualPrompt"] == "new"


def test_archive_and_restore_preserve_corresponding_metadata(monkeypatch):
    """还原旧图时，来源与参数快照一同切换。"""
    monkeypatch.setattr("app.services.drama.generation._snapshot_version_media_url", lambda url, label: url)
    first = generated_media_metadata(model_id="image-model", prompt="长提示词" * 1000, options={"resolution": "2K"})
    asset = SimpleNamespace(id=1, cover="https://cdn/a.png", url="https://cdn/a.png", params={"media_metadata": first})
    archived = archive_asset_image_version(asset, source="upload")
    assert archived["media_metadata"] == first
    asset.cover = asset.url = "https://cdn/b.png"
    asset.params["media_metadata"] = uploaded_media_metadata(filename="b.png", size=2, content_type="image/png")
    activate_asset_image_version(asset, archived["id"])
    assert asset.params["media_metadata"] == first
    assert asset.params["image_versions"][0]["media_metadata"]["source"] == "upload"


def test_team_asset_details_include_media_provenance():
    """团队共享资产详情可读取同一份媒体快照。"""
    meta = generated_media_metadata(model_id="image-model", prompt="实际提示词", options={"resolution": "2K"})
    asset = SimpleNamespace(id=2, name="角色", type="character", asset_type="image", cover="/a.png", url="/a.png", project_id=3, updated_at=None, params={"media_metadata": meta})
    assert asset_card(asset)["params"]["media_metadata"] == meta



def db_returning_project(project):
    """AsyncSession stand-in returning *project* from scalar_one_or_none().

    On Python 3.12 the child mocks of an unspec'd AsyncMock are async too, so
    a bare AsyncMock() makes `await db.execute(...)` yield a mock whose
    scalar_one_or_none() is a coroutine instead of a row. Configure the
    execute result explicitly so the access path receives a real object.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    db.execute.return_value = result
    return db

def media_asset(**changes):
    values = dict(id=1, project_id=2, type="character", asset_type="image", name="portrait", cover="https://cdn/old.png", url="https://cdn/old.png", params={"media_metadata": {"source": "generated", "model_id": "old"}})
    return SimpleNamespace(**{**values, **changes})


@pytest.mark.asyncio
async def test_upload_endpoint_replaces_metadata_and_archives_previous(monkeypatch):
    from app.api.drama.assets import upload_asset_media

    asset = media_asset()
    monkeypatch.setattr("app.api.drama.assets.get_owned_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr("app.services.oss.oss_enabled", lambda: True)
    monkeypatch.setattr("app.services.oss.folder_prefix", lambda: "test")
    monkeypatch.setattr("app.services.oss.upload_fileobj", lambda *args, **kwargs: "https://cdn/upload.png")
    monkeypatch.setattr("app.services.drama.generation._snapshot_version_media_url", lambda url, label: url)
    file = UploadFile(BytesIO(b"image-data"), filename="upload.png", headers=Headers({"content-type": "image/png"}))
    project = SimpleNamespace(id=asset.project_id, team_id=None, user_id=1)
    result = await upload_asset_media(1, file=file, db=db_returning_project(project), user=SimpleNamespace(id=1))
    assert result.params["media_metadata"]["source"] == "upload"
    assert result.params["media_metadata"]["file_size"] == 10
    assert "model_id" not in result.params["media_metadata"]
    assert result.params["image_versions"][0]["media_metadata"]["model_id"] == "old"


@pytest.mark.asyncio
async def test_editing_next_generation_freezes_legacy_media_options(monkeypatch):
    from app.api.drama.assets import update_asset
    from app.schemas_drama import DramaAssetUpdate

    asset = media_asset(params={"model_id": "old-model", "resolution": "2K"})
    monkeypatch.setattr("app.api.drama.assets.get_owned_asset", AsyncMock(return_value=asset))
    project = SimpleNamespace(id=asset.project_id, team_id=None, user_id=1)
    result = await update_asset(1, DramaAssetUpdate(params={"model_id": "next-model", "resolution": "4K"}), db=db_returning_project(project), user=SimpleNamespace(id=1))
    assert result.params["model_id"] == "next-model"
    assert result.params["media_metadata"]["model_id"] == "old-model"
    assert result.params["media_metadata"]["parameters"]["resolution"] == "2K"


@pytest.mark.asyncio
@pytest.mark.parametrize("imported", [True, False])
async def test_media_replacement_cannot_keep_previous_model(monkeypatch, imported):
    from app.api.drama.assets import update_asset
    from app.schemas_drama import DramaAssetUpdate

    target = media_asset()
    source = media_asset(id=3, url="https://cdn/new.png", params={"media_metadata": {"source": "upload"}})
    access = AsyncMock(side_effect=lambda db, ident, user: source if ident == 3 else target)
    monkeypatch.setattr("app.api.drama.assets.get_owned_asset", access)
    project = SimpleNamespace(id=target.project_id, team_id=None, user_id=1)
    result = await update_asset(1, DramaAssetUpdate(url=source.url, params={"importedFromAssetId": 3} if imported else {}), db=db_returning_project(project), user=SimpleNamespace(id=1))
    assert result.params["media_metadata"] == {"source": "upload" if imported else "unknown"}
    assert access.await_count == (2 if imported else 1)


@pytest.mark.asyncio
async def test_image_generation_saves_the_actual_call(monkeypatch):
    from app.services.drama import generation

    asset = media_asset(cover="", url="")
    image = AsyncMock(return_value=SimpleNamespace(local_url="https://cdn/new.png", remote_url=None))
    monkeypatch.setattr(generation, "get_ark", lambda: SimpleNamespace(gen_image=image))
    monkeypatch.setattr(generation, "resolve_seedream_model_endpoint", lambda _: "actual-image-model")
    monkeypatch.setattr(generation, "resolve_seedream_size", lambda **kwargs: "1536x2048")
    monkeypatch.setattr(generation, "resolve_image_style_board_url", lambda _: None)
    monkeypatch.setattr(generation, "build_generation_prompt", lambda prompt, **kwargs: prompt + " styled")
    monkeypatch.setattr(generation, "record_seedream_image_usage", AsyncMock())
    monkeypatch.setattr("app.services.storage.republish_url", lambda url, **kwargs: url)
    result = await generation.generate_asset_image(AsyncMock(), SimpleNamespace(id=1), SimpleNamespace(id=2, params={}), "portrait", asset=asset, model_id="requested", aspect_ratio="3:4", resolution="2K")
    meta = result.params["media_metadata"]
    assert meta["model_id"] == image.call_args.kwargs["model"] == "actual-image-model"
    assert meta["prompt"] == image.call_args.args[0] == "portrait styled"
    assert meta["parameters"]["size"] == image.call_args.kwargs["size"]


@pytest.mark.asyncio
async def test_video_publish_saves_successful_model_and_false_options(monkeypatch):
    from app.services.drama.asset_video import _publish_asset_video

    asset = media_asset()
    monkeypatch.setattr("app.services.storage.republish_url", lambda url, **kwargs: url)
    monkeypatch.setattr("app.services.storage.local_path_from_url", lambda _: None)
    await _publish_asset_video(SimpleNamespace(id=2), asset, "move camera", "https://cdn/movie.mp4", None, model_id="requested", actual_model="actual-video-model", ratio="9:16", res="480p", duration=14, style_id=None, generation_options={"generate_audio": False, "seed": 0})
    meta = asset.params["media_metadata"]
    assert meta["model_id"] == "actual-video-model"
    assert meta["parameters"]["duration_sec"] == 14
    assert meta["parameters"]["generate_audio"] is False
    assert meta["parameters"]["seed"] == 0


@pytest.mark.asyncio
async def test_tts_records_successful_fallback_model(monkeypatch, tmp_path):
    from app.config import Settings
    from app.services.ark import ArkGateway

    gateway = ArkGateway(Settings(ark_mock=False, local_media_mock=False))
    monkeypatch.setattr(gateway, "_ark_api_key", lambda: "test-only")
    monkeypatch.setattr(gateway, "_tts_edge", AsyncMock(side_effect=AssertionError("Unexpected external TTS call")))
    monkeypatch.setattr("app.services.ark.storage.project_dir", lambda _: tmp_path)
    monkeypatch.setattr("app.services.ark.storage.publish_local", lambda _: "https://cdn/audio.mp3")
    monkeypatch.setattr("app.services.ark.is_near_silent_audio", lambda _: False)
    monkeypatch.setattr("app.services.ark.iter_tokenfree_tts_models", lambda _: ["first", "fallback"])
    monkeypatch.setattr(gateway, "_resolved_audio_model", lambda: "first")

    async def speech(text, speaker, dest, *, model):
        if model == "first":
            return False
        dest.write_bytes(b"x" * 3000)
        return True

    monkeypatch.setattr(gateway, "_tts_openai_speech", speech)
    metadata = {}
    await gateway.tts("hello", "voice", result_metadata=metadata)
    assert metadata == {"model_id": "fallback", "speaker": "voice"}
