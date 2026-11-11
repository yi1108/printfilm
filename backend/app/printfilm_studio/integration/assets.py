"""Project-scoped asset import and durable upload through the existing OSS service."""
from copy import deepcopy
import uuid

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_drama import DramaAsset, DramaProject
from app.services.drama.access import get_owned_asset
from app.services import oss


def asset_out(asset: DramaAsset) -> dict:
    return {key: getattr(asset, key) for key in ('id', 'name', 'type', 'asset_type', 'url', 'cover', 'params')}


async def import_asset(db: AsyncSession, project: DramaProject, user: User, source_id: int) -> DramaAsset:
    source = await db.get(DramaAsset, source_id)
    if source and source.project_id == project.id:
        return source
    source = await get_owned_asset(db, source_id, user)
    copied = DramaAsset(project_id=project.id, name=source.name, type=source.type, asset_type=source.asset_type,
                        url=source.url, cover=source.cover, params=deepcopy(source.params))
    db.add(copied)
    await db.commit()
    await db.refresh(copied)
    return copied


async def upload_asset(db: AsyncSession, project: DramaProject, file: UploadFile) -> DramaAsset:
    formats = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif',
               'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov',
               'audio/mpeg': '.mp3', 'audio/wav': '.wav', 'audio/x-wav': '.wav', 'audio/mp4': '.m4a',
               'audio/aac': '.aac', 'audio/ogg': '.ogg', 'audio/webm': '.webm'}
    content_type = (file.content_type or '').lower()
    if content_type not in formats:
        raise HTTPException(status_code=422, detail='请选择 PNG/JPG/WebP/GIF、MP4/WebM/MOV 或常见音频文件')
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    kind = content_type.split('/')[0]
    limit = {'image': 20, 'audio': 30, 'video': 100}[kind] * 1024 * 1024
    if size <= 0 or size > limit:
        raise HTTPException(status_code=422, detail=f'文件不能为空，{kind} 最大 {limit // 1024 // 1024}MB')
    if not oss.oss_enabled():
        raise HTTPException(status_code=503, detail='媒体存储未启用，暂时无法导入文件')
    key = f'{oss.folder_prefix()}/generated/p{project.id}/studio_{uuid.uuid4().hex}{formats[content_type]}'
    try:
        url = await run_in_threadpool(oss.upload_fileobj, file.file, key, content_type=content_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail='媒体上传失败，请稍后重试') from exc
    asset = DramaAsset(project_id=project.id, name=(file.filename or '导入素材')[:200], type='material',
                       asset_type=kind, url=url, cover=url if kind == 'image' else None,
                       params={'source': 'upload', 'media_metadata': {'size': size, 'content_type': content_type}})
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset
