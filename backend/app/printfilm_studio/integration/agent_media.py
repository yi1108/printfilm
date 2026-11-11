"""Agent media edits accept only assets owned by the current project."""
import asyncio
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import UploadFile
from sqlalchemy import select
from starlette.datastructures import Headers

from app.config import get_settings
from app.models_drama import DramaAsset
from app.printfilm_studio.integration.assets import upload_asset
from app.printfilm_studio.integration.media_edit import command, process_media, validate_media_file, _slots
from app.services import oss, storage


async def read_asset_file(asset, destination: Path, stopped):
    url = str(asset.url or '')
    local = storage.local_path_from_url(url)
    if local and local.resolve().is_relative_to(storage.GENERATED_ROOT.resolve()) and local.is_file():
        if local.stat().st_size > 100 * 1024 * 1024:
            raise ValueError('源文件超过 100MB')
        await asyncio.to_thread(shutil.copyfile, local, destination)
        return
    # Never follow arbitrary model-supplied URLs or redirects. The configured
    # storage host is trusted; the asset must also belong to this project.
    base = oss.public_base().rstrip('/')
    if not oss.oss_enabled() or not url.startswith(base + '/') or urlparse(url).scheme != 'https':
        raise ValueError('此素材尚未保存到项目媒体存储，请先在画布重新上传')
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            size = 0
            with destination.open('wb') as target:
                async for chunk in response.aiter_bytes():
                    if await stopped():
                        raise ValueError('媒体处理已停止')
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise ValueError('源文件超过 100MB')
                    target.write(chunk)


async def concatenate(sources: list[Path], folder: Path, stopped=None):
    settings = get_settings()
    streams = []
    for source in sources:
        probe = json.loads(await command([settings.ffprobe_path, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_streams', '-show_format', '-of', 'json', str(source)], stopped))
        video = next((item for item in probe.get('streams', []) if item.get('codec_type') == 'video'), None)
        duration = float(probe.get('format', {}).get('duration') or 0)
        if not video or not 0 < duration <= 600:
            raise ValueError('拼接需要可读取的视频，每段不超过 10 分钟')
        streams.append((video, duration, any(item.get('codec_type') == 'audio' for item in probe['streams'])))
    if sum(item[1] for item in streams) > 600:
        raise ValueError('合并视频总时长不能超过 10 分钟')
    width, height = int(streams[0][0]['width']), int(streams[0][0]['height'])
    factor = min(1, 1920 / max(width, height)); width = max(2, int(width * factor) // 2 * 2); height = max(2, int(height * factor) // 2 * 2)
    args = [settings.ffmpeg_path, '-nostdin', '-v', 'error', '-y']
    filters = []
    for index, source in enumerate(sources):
        args += ['-protocol_whitelist', 'file,pipe', '-i', str(source)]
        filters.append(f'[{index}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v{index}]')
        if streams[index][2]:
            filters.append(f'[{index}:a:0]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={streams[index][1]},asetpts=PTS-STARTPTS[a{index}]')
        else:
            filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={streams[index][1]},asetpts=PTS-STARTPTS[a{index}]')
    filters.append(''.join(f'[v{i}][a{i}]' for i in range(len(sources))) + f'concat=n={len(sources)}:v=1:a=1[v][a]')
    output = folder / '拼接成片.mp4'
    await command([*args, '-filter_complex_threads', '2', '-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', '-movflags', '+faststart', str(output)], stopped)
    if not output.is_file() or output.stat().st_size > 100 * 1024 * 1024:
        raise ValueError('拼接结果超过 100MB，请缩短视频')
    return [(output, 'video/mp4')]


async def edit_project_media(canvas, payload):
    document, _ = await canvas.load()
    source_node = next((item for item in document['nodes'] if item['id'] == payload.get('node_id')), None)
    ids = payload.get('asset_ids') or [payload.get('asset_id') or (source_node or {}).get('data', {}).get('assetId')]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 8 or any(type(value) is not int for value in ids):
        raise ValueError('请提供 1 到 8 个本项目素材 ID，或带素材的 node_id')
    rows = (await canvas.db.scalars(select(DramaAsset).where(DramaAsset.project_id == canvas.project.id, DramaAsset.id.in_(ids)))).all()
    by_id = {row.id: row for row in rows}
    if set(ids) != set(by_id):
        raise ValueError('素材不属于当前项目')
    operation = payload.get('operation', 'trim')
    if operation != 'concat' and len(ids) != 1:
        raise ValueError('此操作只接受一个素材')
    if operation == 'concat' and len(ids) < 2:
        raise ValueError('拼接至少需要两个素材')
    async def stopped(): return bool(getattr(canvas, 'stopped', lambda: False)())
    async with _slots:
        with TemporaryDirectory(prefix='printfilm-agent-edit-') as temp:
            folder = Path(temp); sources = []
            for index, asset_id in enumerate(ids):
                source = folder / f'{index}.media'; await read_asset_file(by_id[asset_id], source, stopped); validate_media_file(source); sources.append(source)
            outputs = await concatenate(sources, folder, stopped) if operation == 'concat' else await process_media(sources[0], folder, operation, float(payload.get('start', 0)), float(payload['end']) if payload.get('end') is not None else None, float(payload.get('speed', 1)), stopped)
            # Recheck lock and access after potentially long processing.
            from app.printfilm_studio.canvas.routes import writable_project
            await writable_project(canvas.project.id, canvas.db, canvas.user, canvas.edit_session_id, canvas.edit_lock_token, canvas.edit_lock_version)
            created = []
            for index, (path, mime) in enumerate(outputs):
                if await stopped(): raise ValueError('媒体处理已停止')
                with path.open('rb') as handle:
                    asset = await upload_asset(canvas.db, canvas.project, UploadFile(handle, filename=path.name, headers=Headers({'content-type': mime})))
                node = {'id': f'agent-{uuid4()}', 'type': asset.asset_type, 'position': {'x': 400 + index % 4 * 320, 'y': 120 + index // 4 * 280}, 'data': {'label': asset.name, 'assetId': asset.id, 'mediaUrl': asset.url, 'mediaType': asset.asset_type, 'status': 'completed'}}
                document['nodes'].append(node); created.append({'node_id': node['id'], 'asset_id': asset.id})
                if source_node:
                    document['edges'].append({'id': f'edge-{uuid4()}', 'source': source_node['id'], 'target': node['id']})
            version = await canvas.save(document)
            return {'ok': True, 'version': version, 'outputs': created, 'summary': '已处理并保存到项目素材和画布'}
