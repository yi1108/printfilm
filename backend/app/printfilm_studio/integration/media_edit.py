"""Bounded FFmpeg node operations. No user-supplied command or remote URL is executed."""
import asyncio
import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.datastructures import Headers
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.printfilm_studio.canvas.routes import writable_project
from app.printfilm_studio.integration.assets import asset_out, upload_asset

router = APIRouter(prefix='/printfilm-studio', tags=['printfilm-studio-media-edit'])
Operation = Literal['trim', 'extract_audio', 'separate', 'mute', 'speed', 'frame', 'frames']
_slots = asyncio.Semaphore(2)


class MediaSourceRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)


class MediaComposeRequest(BaseModel):
    urls: list[str] = Field(min_length=2, max_length=8)


@router.post('/projects/{project_id}/media/compose')
async def compose_media(body: MediaComposeRequest, request: Request, project=Depends(writable_project), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models_drama import DramaAsset
    from app.printfilm_studio.integration.agent_media import read_asset_file, concatenate
    rows = (await db.scalars(select(DramaAsset).where(DramaAsset.project_id == project.id, DramaAsset.url.in_(body.urls)))).all()
    by_url = {row.url: row for row in rows}
    if set(body.urls) != set(by_url):
        raise HTTPException(404, '拼接素材必须属于当前项目')
    try:
        async with _slots:
            with TemporaryDirectory(prefix='printfilm-compose-') as temp:
                folder = Path(temp); sources = []; total = 0
                for index, url in enumerate(body.urls):
                    path = folder / f'source-{index}.media'
                    await read_asset_file(by_url[url], path, request.is_disconnected)
                    total += path.stat().st_size
                    if total > 200 * 1024 * 1024:
                        raise ValueError('拼接素材合计不能超过 200MB')
                    validate_media_file(path); sources.append(path)
                outputs = await concatenate(sources, folder, request.is_disconnected)
                # The lock can expire while the clips are being encoded.
                await writable_project(project.id, db, user, request.headers.get('X-Edit-Session'), request.headers.get('X-Edit-Token'), int(request.headers['X-Edit-Version']) if request.headers.get('X-Edit-Version') else None)
                assets = []
                for path, mime in outputs:
                    if await request.is_disconnected():
                        raise HTTPException(499, '视频合成已取消')
                    with path.open('rb') as handle:
                        assets.append(asset_out(await upload_asset(db, project, UploadFile(handle, filename=path.name, headers=Headers({'content-type': mime})))))
                return {'assets': assets}
    except FileNotFoundError as error:
        raise HTTPException(503, '媒体处理服务缺少 FFmpeg/FFprobe') from error
    except TimeoutError as error:
        raise HTTPException(504, '合成超时，请缩短视频') from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post('/projects/{project_id}/media/source')
async def resolve_project_media(project_id: int, body: MediaSourceRequest, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.printfilm_studio.canvas.service import get_project
    from app.printfilm_studio import ensure_enabled
    from app.models_drama import DramaAsset
    ensure_enabled()
    await get_project(db, project_id, user)
    asset_id = await db.scalar(select(DramaAsset.id).where(DramaAsset.project_id == project_id, DramaAsset.url == body.url))
    if not asset_id:
        raise HTTPException(404, '此媒体尚未保存到当前项目，请先从素材库添加')
    return await read_project_media(project_id, asset_id, request, db, user)


@router.get('/projects/{project_id}/media/assets/{asset_id}')
async def read_project_media(project_id: int, asset_id: int, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.printfilm_studio.canvas.service import get_project
    from app.printfilm_studio import ensure_enabled
    from app.models_drama import DramaAsset
    from app.printfilm_studio.integration.agent_media import read_asset_file
    import mimetypes
    from urllib.parse import urlparse
    ensure_enabled()
    await get_project(db, project_id, user)
    asset = await db.get(DramaAsset, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, '素材不属于当前项目')
    temp = TemporaryDirectory(prefix='printfilm-media-read-')
    try:
        path = Path(temp.name) / 'source.media'
        async with _slots:
            await read_asset_file(asset, path, request.is_disconnected)
        mime = (asset.params or {}).get('media_metadata', {}).get('content_type') or mimetypes.guess_type(urlparse(asset.url or '').path)[0] or 'application/octet-stream'
        return FileResponse(path, media_type=mime, headers={'Cache-Control': 'no-store'}, background=BackgroundTask(temp.cleanup))
    except Exception as error:
        temp.cleanup()
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(422, str(error) if isinstance(error, ValueError) else '项目素材暂时无法读取') from error


@router.post('/projects/{project_id}/media/analyze')
async def analyze_media(request: Request, project=Depends(writable_project), file: UploadFile = File(...), detector: Literal['adaptive', 'content'] = Form('adaptive'), threshold: float = Form(3, gt=0, le=10, allow_inf_nan=False), minimum: float = Form(.6, ge=.1, le=60, allow_inf_nan=False), frames: bool = Form(True), clips: bool = Form(True), audio: bool = Form(True), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.printfilm_studio.integration.frame_analysis import analyze_frames
    if detector == 'content' and threshold > 1:
        raise HTTPException(422, '内容检测阈值必须在 0 到 1 之间')
    async with _slots:
        with TemporaryDirectory(prefix='printfilm-analysis-') as temp:
            folder = Path(temp); source = folder / 'source.media'
            size = 0
            with source.open('wb') as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise HTTPException(422, '源文件不能超过 100MB')
                    target.write(chunk)
            try:
                validate_media_file(source)
                report, outputs = await analyze_frames(source, folder, detector, threshold, minimum, frames, clips, audio, request.is_disconnected)
                lock_version = request.headers.get('X-Edit-Version')
                await writable_project(project.id, db, user, request.headers.get('X-Edit-Session'), request.headers.get('X-Edit-Token'), int(lock_version) if lock_version else None)
                assets = []
                for path, mime in outputs:
                    if await request.is_disconnected():
                        raise HTTPException(499, '分析已取消')
                    with path.open('rb') as handle:
                        assets.append(asset_out(await upload_asset(db, project, UploadFile(handle, filename=path.name, headers=Headers({'content-type': mime})))))
                for shot in report['shots']:
                    for kind in ('frame', 'clip'):
                        index = shot.pop(f'{kind}_index', None)
                        if index is not None:
                            shot[kind] = assets[index]
                index = report.pop('audio_index')
                report['audio'] = assets[index] if index is not None else None
                return {'report': report, 'assets': assets}
            except FileNotFoundError as error:
                raise HTTPException(503, '媒体处理服务缺少 FFmpeg/FFprobe') from error
            except TimeoutError as error:
                raise HTTPException(504, '视频分析超时，请缩短视频') from error
            except ValueError as error:
                raise HTTPException(422, str(error)) from error


def validate_media_file(source: Path):
    with source.open('rb') as handle:
        magic = handle.read(16)
    if not (b'ftyp' in magic or magic.startswith((b'RIFF', b'ID3', b'\x1aE\xdf\xa3', b'OggS', b'fLaC')) or (len(magic) > 1 and magic[0] == 255 and magic[1] & 224 == 224)):
        raise ValueError('请选择 MP4/WebM/MOV、MP3/WAV/M4A/OGG 音视频文件')


async def command(args, disconnected=None):
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    result = asyncio.create_task(process.communicate())
    try:
        async with asyncio.timeout(180):
            while not result.done():
                await asyncio.wait({result}, timeout=.25)
                if disconnected and await disconnected():
                    raise HTTPException(499, '媒体处理已取消')
            out, err = await result
            if process.returncode:
                raise ValueError('媒体无法完成此操作，请检查轨道和文件格式')
            return out
    finally:
        if process.returncode is None:
            process.kill()
        await asyncio.gather(result, return_exceptions=True)


def tempo_filter(speed):
    filters = []
    while speed < .5:
        filters.append('atempo=0.5'); speed /= .5
    while speed > 2:
        filters.append('atempo=2'); speed /= 2
    return ','.join([*filters, f'atempo={speed:g}'])


async def process_media(source: Path, folder: Path, operation: str, start: float = 0, end: float | None = None, speed: float = 1, disconnected=None):
    settings = get_settings()
    probe = json.loads(await command([settings.ffprobe_path, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_format', '-show_streams', '-of', 'json', str(source)], disconnected))
    streams = probe.get('streams', [])
    video = any(s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic') for s in streams)
    audio = any(s.get('codec_type') == 'audio' for s in streams)
    duration = float((probe.get('format') or {}).get('duration') or 0)
    # MediaRecorder writes streaming WebM without a duration header. Remux to a
    # seekable file before validating/editing it; the extra second detects excess.
    if not duration and 'webm' in str((probe.get('format') or {}).get('format_name')) and (video or audio):
        normalized = folder / 'seekable-source.mkv'
        await command([settings.ffmpeg_path, '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(source), '-t', '601', '-map', '0:v:0?', '-map', '0:a:0?', '-c', 'copy', str(normalized)], disconnected)
        probe = json.loads(await command([settings.ffprobe_path, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(normalized)], disconnected))
        duration = float((probe.get('format') or {}).get('duration') or 0)
        source = normalized
        streams = probe.get('streams', [])
    if not 0 < duration <= 600 or not (video or audio):
        raise ValueError('请选择时长不超过 10 分钟的音视频')
    if operation not in {'trim', 'extract_audio', 'separate', 'mute', 'speed', 'frame', 'frames'}:
        raise ValueError('不支持的媒体操作')
    if not 0 <= start < duration or (end is not None and not start < end <= duration + .05):
        raise ValueError('截取时间必须在媒体时长内，结束时间必须大于开始时间')
    if not .1 <= speed <= 4:
        raise ValueError('变速范围为 0.1 到 4 倍')
    if operation in {'extract_audio', 'separate'} and not audio:
        raise ValueError('原视频没有音轨')
    if operation in {'mute', 'separate', 'frame', 'frames'} and not video:
        raise ValueError('此操作需要视频轨道')
    outputs = []
    async def render(name, kind, flags, offset=0):
        path = folder / name
        await command([settings.ffmpeg_path, '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-ss', str(offset), '-i', str(source), '-threads', '2', *flags, str(path)], disconnected)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('所选时间没有可读取的画面，请选择更早的时间')
        if path.stat().st_size > 100 * 1024 * 1024:
            raise ValueError('处理结果超过 100MB，请缩短片段')
        outputs.append((path, kind))
    if operation in {'extract_audio', 'separate'}:
        await render('提取音轨.m4a', 'audio/mp4', ['-map', '0:a:0', '-vn', '-c:a', 'aac'])
    if operation in {'mute', 'separate'}:
        await render('静音视频.mp4', 'video/mp4', ['-map', '0:v:0', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'])
    if operation in {'frame', 'frames'}:
        video_stream = next(s for s in streams if s.get('codec_type') == 'video')
        try:
            frame_time = 1 / float(Fraction(video_stream.get('avg_frame_rate') or '25'))
        except (ValueError, ZeroDivisionError):
            frame_time = .04
        last_frame = max(0, duration - frame_time * 1.1)
        times = [min(start, last_frame)] if operation == 'frame' else [min(duration * i / 12, last_frame) for i in range(12)]
        for index, offset in enumerate(times):
            await render(f'帧{index + 1:02d}_{offset:.2f}s.png', 'image/png', ['-map', '0:v:0', '-frames:v', '1'], offset)
    if operation in {'trim', 'speed'}:
        flags = ['-t', str((end if end is not None else duration) - start)] if operation == 'trim' else []
        if video:
            flags += ['-map', '0:v:0', '-vf', f'setpts=PTS/{speed:g}' if operation == 'speed' else 'setpts=PTS-STARTPTS', '-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        if audio:
            flags += ['-map', '0:a:0', '-af', tempo_filter(speed) if operation == 'speed' else 'asetpts=PTS-STARTPTS', '-c:a', 'aac']
        flags += ['-movflags', '+faststart']
        await render('处理视频.mp4' if video else '处理音频.m4a', 'video/mp4' if video else 'audio/mp4', flags, start)
    return outputs


@router.post('/projects/{project_id}/media/edit')
async def edit_media(request: Request, project=Depends(writable_project), file: UploadFile = File(...), operation: Operation = Form(...), start: float = Form(0, ge=0, allow_inf_nan=False), end: float | None = Form(None, ge=0, allow_inf_nan=False), speed: float = Form(1, ge=.1, le=4, allow_inf_nan=False), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    async with _slots:
        with TemporaryDirectory(prefix='printfilm-edit-') as temp:
            folder = Path(temp); source = folder / 'source.media'
            size = 0
            with source.open('wb') as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise HTTPException(422, '源文件不能超过 100MB')
                    target.write(chunk)
            try:
                validate_media_file(source)
                outputs = await process_media(source, folder, operation, start, end, speed, request.is_disconnected)
                lock_version = request.headers.get('X-Edit-Version')
                await writable_project(project.id, db, user, request.headers.get('X-Edit-Session'), request.headers.get('X-Edit-Token'), int(lock_version) if lock_version else None)
                assets = []
                for path, mime in outputs:
                    if await request.is_disconnected():
                        raise HTTPException(499, '媒体处理已取消')
                    with path.open('rb') as handle:
                        assets.append(asset_out(await upload_asset(db, project, UploadFile(handle, filename=path.name, headers=Headers({'content-type': mime})))))
                return {'assets': assets}
            except FileNotFoundError as error:
                raise HTTPException(503, '媒体处理服务缺少 FFmpeg/FFprobe') from error
            except TimeoutError as error:
                raise HTTPException(504, '媒体处理超时，请缩短片段') from error
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
