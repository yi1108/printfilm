import asyncio
import json
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.printfilm_studio.integration.media_edit import command, process_media, tempo_filter
from app.printfilm_studio.integration.agent_media import concatenate


@pytest.mark.asyncio
async def test_project_media_reader_rejects_cross_project_assets_before_download(monkeypatch):
    from app.printfilm_studio.integration import media_edit, agent_media
    from app.printfilm_studio.canvas import service
    monkeypatch.setattr(service, 'get_project', AsyncMock())
    read = AsyncMock(); monkeypatch.setattr(agent_media, 'read_asset_file', read)
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(project_id=2)))
    with pytest.raises(HTTPException) as error:
        await media_edit.read_project_media(1, 7, None, db, SimpleNamespace(id=1))
    assert error.value.status_code == 404
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_media_reader_streams_owned_asset_and_removes_temp_file(monkeypatch):
    from pathlib import Path
    from app.printfilm_studio.integration import media_edit, agent_media
    from app.printfilm_studio.canvas import service
    monkeypatch.setattr(service, 'get_project', AsyncMock())
    async def copy(asset, destination, disconnected): destination.write_bytes(b'owned project media')
    monkeypatch.setattr(agent_media, 'read_asset_file', copy)
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(project_id=1, url='https://storage.example/video.mp4', params={})))
    response = await media_edit.read_project_media(1, 7, SimpleNamespace(is_disconnected=AsyncMock(return_value=False)), db, SimpleNamespace(id=1))
    assert response.media_type == 'video/mp4'
    assert Path(response.path).read_bytes() == b'owned project media'
    assert response.headers['cache-control'] == 'no-store'
    await response.background()
    assert not Path(response.path).exists()


@pytest.fixture
def media_tools():
    settings = get_settings()
    if not shutil.which(settings.ffmpeg_path) or not shutil.which(settings.ffprobe_path):
        pytest.skip('FFmpeg and FFprobe are required for real media round-trip tests')
    return SimpleNamespace(ffmpeg_path=settings.ffmpeg_path, ffprobe_path=settings.ffprobe_path)


@pytest.mark.asyncio
async def test_compose_rejects_foreign_sources_before_reading(monkeypatch):
    from app.printfilm_studio.integration import media_edit, agent_media
    read = AsyncMock(); monkeypatch.setattr(agent_media, 'read_asset_file', read)
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [SimpleNamespace(url='owned')])) )
    with pytest.raises(HTTPException) as error:
        await media_edit.compose_media(media_edit.MediaComposeRequest(urls=['owned', 'foreign']), None, SimpleNamespace(id=1), db, SimpleNamespace(id=1))
    assert error.value.status_code == 404
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_recorded_webm_exports_seekable_mp4(tmp_path, media_tools):
    source = tmp_path / 'streaming.webm'
    source.write_bytes(await command([media_tools.ffmpeg_path, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=128x96:r=12:d=1', '-c:v', 'libvpx', '-f', 'webm', 'pipe:1']))
    before = json.loads(await command([media_tools.ffprobe_path, '-v', 'error', '-show_format', '-of', 'json', str(source)]))
    assert not before['format'].get('duration')
    outputs = await process_media(source, tmp_path, 'speed', speed=1)
    after = json.loads(await command([media_tools.ffprobe_path, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(outputs[0][0])]))
    assert .9 <= float(after['format']['duration']) <= 1.2
    assert after['streams'][0]['codec_name'] == 'h264'
    assert source.is_file()


@pytest.mark.asyncio
async def test_real_video_trim_split_speed_and_frames(tmp_path, media_tools):
    source = tmp_path / 'source.mp4'
    await command([media_tools.ffmpeg_path, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=128x96:r=12:d=2', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)])
    async def probe(path):
        return json.loads(await command([media_tools.ffprobe_path, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))
    for operation in ['trim', 'separate', 'speed', 'frame', 'frames']:
        folder = tmp_path / operation; folder.mkdir()
        outputs = await process_media(source, folder, operation, start=.5 if operation in {'trim', 'frame'} else 0, end=1.25 if operation == 'trim' else None, speed=2 if operation == 'speed' else 1)
        assert all(path.stat().st_size > 0 for path, _ in outputs)
        info = await probe(outputs[0][0])
        if operation == 'trim':
            assert .65 <= float(info['format']['duration']) <= .95
        elif operation == 'speed':
            assert .9 <= float(info['format']['duration']) <= 1.3
        elif operation == 'separate':
            assert {s['codec_type'] for s in info['streams']} == {'audio'}
            assert {s['codec_type'] for s in (await probe(outputs[1][0]))['streams']} == {'video'}
        else:
            assert len(outputs) == (1 if operation == 'frame' else 12)
            assert outputs[0][0].read_bytes().startswith(b'\x89PNG')
    assert source.exists(), 'original must never be overwritten'
    joined = await concatenate([source, tmp_path / 'separate' / '静音视频.mp4'], tmp_path)
    joined_info = await probe(joined[0][0])
    assert 3.8 <= float(joined_info['format']['duration']) <= 4.3
    assert {s['codec_type'] for s in joined_info['streams']} == {'video', 'audio'}
    with pytest.raises(ValueError, match='截取时间'):
        await process_media(source, tmp_path, 'trim', start=1.5, end=.5)


@pytest.mark.asyncio
async def test_audio_trim_speed_and_missing_video(tmp_path, media_tools):
    source = tmp_path / 'source.wav'
    await command([media_tools.ffmpeg_path, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', str(source)])
    outputs = await process_media(source, tmp_path, 'speed', speed=.25)
    assert outputs[0][1] == 'audio/mp4'
    info = json.loads(await command([media_tools.ffprobe_path, '-v', 'error', '-show_format', '-of', 'json', str(outputs[0][0])]))
    assert 7.5 <= float(info['format']['duration']) <= 8.3
    with pytest.raises(ValueError, match='视频轨道'):
        await process_media(source, tmp_path, 'frame')


def test_tempo_chain_stays_within_supported_filter_range():
    for speed in [.1, .25, .5, 1, 2, 4]:
        product = 1
        for item in tempo_filter(speed).split(','):
            value = float(item.split('=')[1]); assert .5 <= value <= 2
            product *= value
        assert product == pytest.approx(speed)


@pytest.mark.asyncio
async def test_real_shot_detection_exports_exact_cuts_and_audio(tmp_path, media_tools):
    from app.printfilm_studio.integration.frame_analysis import analyze_frames
    source = tmp_path / 'cuts.mp4'
    await command([media_tools.ffmpeg_path, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=128x96:r=10:d=1', '-f', 'lavfi', '-i', 'color=c=blue:s=128x96:r=10:d=1', '-f', 'lavfi', '-i', 'color=c=white:s=128x96:r=10:d=1', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]', '-map', '[v]', '-map', '3:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)])
    report, outputs = await analyze_frames(source, tmp_path, 'content', .28, .6, True, True, True)
    assert len(report['shots']) == 3
    assert [shot['start'] for shot in report['shots']] == pytest.approx([0, 1, 2], abs=.11)
    assert len(outputs) == 7 and report['has_audio']
    for shot in report['shots']:
        assert outputs[shot['frame_index']][0].read_bytes().startswith(b'\x89PNG')
        clip = outputs[shot['clip_index']][0]
        probe = json.loads(await command([media_tools.ffprobe_path, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(clip)]))
        assert .9 <= float(probe['format']['duration']) <= 1.2
        assert {s['codec_type'] for s in probe['streams']} == {'video', 'audio'}
    adaptive, _ = await analyze_frames(source, tmp_path, 'adaptive', 3, .6, False, False, False)
    assert len(adaptive['shots']) == 3
    assert source.is_file()


@pytest.mark.asyncio
async def test_disconnect_terminates_media_process():
    async def disconnected(): return True
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(command([sys.executable, '-c', 'import time; time.sleep(30)'], disconnected), timeout=3)
    assert error.value.status_code == 499


@pytest.mark.asyncio
async def test_media_http_route_denies_nonmember_before_processing(monkeypatch):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from unittest.mock import AsyncMock
    from app.printfilm_studio.integration import media_edit
    from app.printfilm_studio.canvas import routes as canvas_routes
    app = FastAPI(); app.include_router(media_edit.router)
    async def db(): yield SimpleNamespace()
    app.dependency_overrides[media_edit.get_db] = db
    app.dependency_overrides[media_edit.get_current_user] = lambda: SimpleNamespace(id=1)
    monkeypatch.setattr(canvas_routes, 'ensure_enabled', lambda: None)
    monkeypatch.setattr(canvas_routes, 'get_project', AsyncMock(side_effect=HTTPException(404, 'not a project member')))
    process = AsyncMock(); monkeypatch.setattr(media_edit, 'process_media', process)
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        response = await client.post('/printfilm-studio/projects/7/media/edit', data={'operation': 'trim'}, files={'file': ('clip.mp4', b'not-media', 'video/mp4')})
    assert response.status_code == 404
    process.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_media_rejects_untrusted_host_and_path_escape(tmp_path, monkeypatch):
    from app.printfilm_studio.integration.agent_media import read_asset_file
    from app.services import oss
    monkeypatch.setattr(oss, 'oss_enabled', lambda: True)
    monkeypatch.setattr(oss, 'public_base', lambda: 'https://storage.example.test')
    async def stopped(): return False
    for url in ['http://127.0.0.1/private', 'https://storage.example.test.evil.test/file.mp4', '/static/generated/../../secret.txt']:
        with pytest.raises(ValueError, match='项目媒体存储'):
            await read_asset_file(SimpleNamespace(url=url), tmp_path / 'out', stopped)
