"""Validated studio references from uploaded files or the current personal library."""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from PIL import Image
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import case, func, or_, select

from app.models_drama import DramaAsset, DramaProject
from app.schemas_tools import MAX_TOOL_REFERENCES, ToolReference

ROLE_KIND = {"first_frame": "image", "last_frame": "image", "reference_image": "image",
             "reference_video": "video", "reference_audio": "audio"}
REFERENCE_FIELDS = {"reference_image": "reference_images", "reference_video": "reference_videos",
                    "reference_audio": "reference_audios"}
EXTENSIONS = {"image": {".jpg", ".jpeg", ".png", ".webp"},
              "video": {".mp4", ".mov", ".webm"},
              "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}}
MAX_UPLOAD_BYTES = 40 * 1024 * 1024


def parse_references(raw: str | list) -> list[dict]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        refs = TypeAdapter(list[ToolReference]).validate_python(value)
    except (ValueError, TypeError, ValidationError):
        raise ValueError("references: 参考资料格式无效，请选择上传文件或资产") from None
    if len(refs) > MAX_TOOL_REFERENCES:
        raise ValueError(f"references: 全能参考最多支持 {MAX_TOOL_REFERENCES} 个资料")
    return [ref.model_dump(exclude_none=True) for ref in refs]


def validate_reference_mode(mode: str, refs: list[dict], file_count: int | None = None) -> None:
    if mode not in {"text_to_video", "first_last_frame", "omni_reference"}:
        raise ValueError("video_mode: 不支持的生成模式")
    roles = [ref["role"] for ref in refs]
    if mode == "text_to_video" and refs:
        raise ValueError("references: 文生视频无需参考资料")
    if mode == "first_last_frame":
        if roles.count("first_frame") != 1 or roles.count("last_frame") > 1 or any(
            role not in {"first_frame", "last_frame"} for role in roles
        ):
            raise ValueError("references: 首尾帧模式需要一张首帧，尾帧可选")
    if mode == "omni_reference" and (not refs or any(role in {"first_frame", "last_frame"} for role in roles)):
        raise ValueError("references: 全能参考请选择图片、视频或音频资料")
    indices = [ref["file_index"] for ref in refs if "file_index" in ref]
    if len(set(indices)) != len(indices):
        raise ValueError("references: 上传文件不能重复引用")
    if file_count is not None and set(indices) != set(range(file_count)):
        raise ValueError("references: 上传文件与参考资料不匹配")


def asset_kind_expression():
    """Match historical character/scene/prop rows and explicit canvas media types."""
    primary = func.lower(func.coalesce(DramaAsset.type, ""))
    media = func.lower(func.coalesce(DramaAsset.asset_type, ""))
    return case((or_(primary == "video", media == "video"), "video"),
                (or_(primary.in_(["audio", "voice"]), media.in_(["audio", "voice"])), "audio"),
                (or_(primary.in_(["character", "scene", "prop", "image", "material"]),
                     (media == "image") & (primary != "text")), "image"),
                else_="")


def asset_url_expression():
    return case((asset_kind_expression() == "image", func.coalesce(func.nullif(DramaAsset.url, ""), DramaAsset.cover)),
                else_=DramaAsset.url)


def personal_asset_filters(user_id: int):
    return (DramaProject.user_id == user_id, DramaProject.team_id.is_(None),
            func.trim(func.coalesce(asset_url_expression(), "")) != "")


async def reference_params(db, user, refs: list[dict], *, files: list[Path] | None = None) -> dict:
    """Resolve only authorized server-owned URLs; placeholder uploads support price estimation."""
    params: dict = {}
    for ref in refs:
        role = ref["role"]
        if "asset_id" in ref:
            result = (await db.execute(select(DramaAsset, asset_kind_expression()).join(
                DramaProject, DramaProject.id == DramaAsset.project_id
            ).where(DramaAsset.id == ref["asset_id"], *personal_asset_filters(user.id)))).first()
            if result is None:
                raise ValueError("references: 资产不存在或无权访问")
            asset, kind = result
            if kind != ROLE_KIND[role]:
                raise ValueError("references: 资产媒体类型与参考位置不匹配")
            url = (asset.url or asset.cover) if kind == "image" else asset.url
        else:
            index = ref["file_index"]
            url = str(files[index]) if files is not None else f"pending://upload/{index}"
        if role in {"first_frame", "last_frame"}:
            params[role] = url
        else:
            params.setdefault(REFERENCE_FIELDS[role], []).append(url)
    return params


def validate_upload(raw: bytes, filename: str, kind: str, content_type: str | None) -> None:
    suffix = Path(filename).suffix.lower()
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("上传文件不能为空，且单个文件不能超过 40MB")
    if suffix not in EXTENSIONS[kind]:
        raise ValueError(f"参考{ {'image': '图片', 'video': '视频', 'audio': '音频'}[kind] }格式不支持")
    if content_type and content_type != "application/octet-stream" and not content_type.startswith(kind + "/"):
        raise ValueError("上传文件类型与参考位置不匹配")
    if kind == "image":
        try:
            with Image.open(BytesIO(raw)) as image:
                image.verify()
        except Exception as exc:
            raise ValueError("参考图片文件无效") from exc
        return
    is_mp4 = len(raw) >= 12 and raw[4:8] == b"ftyp"
    is_webm = raw.startswith(b"\x1aE\xdf\xa3")
    if kind == "video":
        valid = is_mp4 or is_webm or (suffix == ".mov" and raw[4:8] in {b"moov", b"mdat", b"wide"})
    else:
        valid = (raw.startswith((b"ID3", b"OggS", b"fLaC"))
                 or (raw.startswith(b"RIFF") and raw[8:12] == b"WAVE")
                 or (len(raw) > 1 and raw[0] == 0xff and raw[1] & 0xe0 == 0xe0)
                 or (suffix == ".m4a" and is_mp4))
    if not valid:
        raise ValueError("参考媒体文件内容无效")
