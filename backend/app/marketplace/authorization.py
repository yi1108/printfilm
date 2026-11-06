"""本平台作品账号授权；仅作用于下游，不自动转让或授予买家权利。"""
import asyncio
import hashlib
import logging
from pathlib import Path
import tempfile
from typing import Annotated, Literal
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import storage
from .config import get_marketplace_settings, resolve_cjk_font
from .dependencies import Actor, DB, storage_ready
from .letter_template import BODY, NOTICES, TITLE, VERSION, archived_text
from .models import Authorization
from .schemas import Input
from .service import data, event, fail, now

logger = logging.getLogger("marketplace.authorization")

Point = tuple[Annotated[float, Field(ge=0, le=800, allow_inf_nan=False)], Annotated[float, Field(ge=0, le=240, allow_inf_nan=False)]]
Stroke = Annotated[list[Point], Field(min_length=2, max_length=1000)]


class SignInput(Input):
    template_version: str = Field(max_length=60)
    signer_name: str = Field(min_length=2, max_length=80)
    accepted_terms: Literal[True]
    adult: Literal[True]
    read_all: Literal[True]
    accept_key: Literal[True]
    strokes: list[Stroke] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def handwritten(self):
        points = [p for stroke in self.strokes for p in stroke]
        distance = sum(((b[0]-a[0])**2 + (b[1]-a[1])**2)**0.5 for stroke in self.strokes for a, b in zip(stroke, stroke[1:]))
        if len(points) < 12 or distance < 80 or max(p[0] for p in points)-min(p[0] for p in points) < 20:
            raise ValueError("请在签名区完整手写签名")
        return self


router = APIRouter()


async def current(db, owner_id: int):
    return (await db.execute(select(Authorization).where(Authorization.owner_id == owner_id, Authorization.template_version == VERSION))).scalar_one_or_none()


def summary(item):
    return data(item, "id", "template_version", "signer_name", "created_at", "body_hash") if item else None


def _pdf_font(path: str) -> str:
    """注册本次签署使用的中文字体。ttc 取第一个字面。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    name = f"MarketplaceCJK{uuid.uuid4().hex[:8]}"
    pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
    return name


def _wrap(text: str, font_name: str, size: float, width: float) -> list[str]:
    from reportlab.pdfbase import pdfmetrics
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for char in paragraph:
            if pdfmetrics.stringWidth(line + char, font_name, size) > width:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return lines


def render_and_store(body: SignInput, signed_at: str, owner_id: int) -> str:
    """把条款和手写签名直接写成 PDF，再存入私有 OSS。生成失败不伪装成存储未配置。"""
    try:
        font_name = _pdf_font(resolve_cjk_font())
        prefix = f"marketplace/authorizations/u{owner_id}/{uuid.uuid4().hex}"
        key = f"{prefix}/letter.pdf"
        with tempfile.TemporaryDirectory(prefix="printfilm-authorization-") as folder:
            path = Path(folder) / "letter.pdf"
            _write_letter(path, font_name, body, signed_at, owner_id)
            storage.upload(key, path, "application/pdf")
        return key
    except HTTPException:
        raise
    except (OSError, FileNotFoundError) as exc:
        logger.warning("授权函字体不可用：%s", type(exc).__name__)
        fail("服务器未找到可用的中文字体，暂时无法生成授权函。", 503)
    except ImportError:
        logger.exception("授权函组件未安装")
        fail("后端依赖未更新，暂时无法生成授权函。请重新构建并发布后端后再试。", 503)
    except Exception:
        logger.exception("授权函生成失败")
        fail("授权函生成失败，请稍后重试。", 503)


def _write_letter(path: Path, font_name: str, body: SignInput, signed_at: str, owner_id: int) -> None:
    """按 A4 排版全文，签名用矢量笔画，不另存图片。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    page_width, page_height = A4
    margin, size, leading = 48, 11, 16
    text_width = page_width - margin * 2
    document = canvas.Canvas(str(path), pagesize=A4)
    document.setTitle(TITLE)
    document.setFont(font_name, size)
    y = page_height - margin
    paragraphs = [TITLE, f"版本：{VERSION}", *archived_text().splitlines(), f"签署人：{body.signer_name}", f"账号：{owner_id}    签署时间（UTC）：{signed_at}", "手写签名："]
    for paragraph in paragraphs:
        for line in _wrap(paragraph, font_name, size, text_width) or [""]:
            if y < margin + 150:
                document.showPage()
                document.setFont(font_name, size)
                y = page_height - margin
            document.drawString(margin, y, line)
            y -= leading
        y -= 4
    scale = text_width / 800
    signature_height = 240 * scale
    if y - signature_height < margin:
        document.showPage()
        document.setFont(font_name, size)
        y = page_height - margin
    document.setLineWidth(1.4)
    document.setLineCap(1)
    document.setLineJoin(1)
    for stroke in body.strokes:
        pen = document.beginPath()
        start_x, start_y = stroke[0]
        pen.moveTo(margin + start_x * scale, y - start_y * scale)
        for point_x, point_y in stroke[1:]:
            pen.lineTo(margin + point_x * scale, y - point_y * scale)
        document.drawPath(pen, stroke=1, fill=0)
    document.save()


@router.get(
    "/authorization", response_model=dict,
    summary='获取授权函模板与我的签署状态',
    description='登录后读取当前授权函模板、版本与注意事项，并返回当前账号的有效签署记录；未签署时 current 为 null。',
    response_description='授权函模板 template 与当前签署记录 current。',
)
async def status(db: DB, user: Actor):
    from .letter_reference import reading_reference
    return {"template": {"version": VERSION, "title": TITLE, "notices": list(NOTICES), "body": BODY}, "reading_reference": reading_reference(VERSION), "current": summary(await current(db, user.id))}


@router.post(
    "/authorization", response_model=dict, dependencies=[Depends(storage_ready)],
    summary='签署当前版本的授权函',
    description='登录后提交姓名、确认项及签名轨迹，须匹配当前 template_version；版本过期返回 409。生成签署 PDF 并存入私有 OSS，已存在当前有效签署记录时直接返回该记录。',
    response_description='已签署授权函的摘要信息。',
)
async def sign(body: SignInput, request: Request, db: DB, user: Actor):
    if body.template_version != VERSION:
        fail("授权条款已更新，请刷新后重新阅读并签署", 409)
    existing = await current(db, user.id)
    if existing:
        return summary(existing)
    signed_at = now()
    letter_key = await asyncio.to_thread(render_and_store, body, signed_at.isoformat(), user.id)
    text = archived_text()
    item = Authorization(owner_id=user.id, template_version=VERSION, signer_name=body.signer_name,
                         body=text, body_hash=hashlib.sha256(text.encode()).hexdigest(), signature_key=letter_key,
                         letter_key=letter_key, created_at=signed_at, client_ip=(request.client.host if request.client else "")[:64],
                         user_agent=request.headers.get("user-agent", "")[:512])
    db.add(item)
    try:
        await db.flush()
        event(db, user.id, "authorization", item.id, "signed", version=1)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await current(db, user.id)
        if existing:
            return summary(existing)
        raise
    return summary(item)


@router.get(
    "/authorizations/{record_id}/letter", response_model=dict, dependencies=[Depends(storage_ready)],
    summary='获取已签署授权函的临时链接',
    description='仅签署本人或管理员可查看。为授权函生成短期访问签名，并记录读取事件；无权访问或不存在时返回 404。',
    response_description='访问链接 url、有效秒数 expires_in 与建议文件名 filename。',
)
async def letter(record_id: int, db: DB, user: Actor):
    item = await db.get(Authorization, record_id)
    if not item or (item.owner_id != user.id and user.role != "admin"):
        fail("授权函不存在或无权查看", 404)
    pdf = item.letter_key.lower().endswith(".pdf")
    url = await asyncio.to_thread(storage.signed, item.letter_key, "application/pdf" if pdf else "image/png")
    event(db, user.id, "authorization", item.id, "read")
    await db.commit()
    return {"url": url, "expires_in": get_marketplace_settings().signed_url_seconds, "filename": "授权函.pdf" if pdf else "授权函.png"}


def _disposition(filename: str, download: bool) -> str:
    """预览用 inline，只有明确下载时才用 attachment。"""
    encoded = quote(filename)
    kind = "attachment" if download else "inline"
    ascii_name = "letter.pdf" if filename.endswith(".pdf") else "letter.png"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


@router.get(
    "/authorizations/{record_id}/file", dependencies=[Depends(storage_ready)],
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "image/png": {"schema": {"type": "string", "format": "binary"}},
            },
        },
    },
    summary='预览或下载已签署授权函',
    description='仅签署本人或管理员可访问。直接返回 PDF 或兼容历史图片的文件内容；默认在线打开，download=true 时作为附件下载，并记录访问事件。',
    response_description='授权函二进制文件，响应包含 Content-Disposition 和禁止缓存标记。',
)
async def letter_file(record_id: int, db: DB, user: Actor, download: bool = False):
    """把已签署授权函以文件流返回。默认在线打开，download=true 时才作为附件下载。"""
    item = await db.get(Authorization, record_id)
    if not item or (item.owner_id != user.id and user.role != "admin"):
        fail("授权函不存在或无权查看", 404)
    pdf = item.letter_key.lower().endswith(".pdf")
    payload = await asyncio.to_thread(storage.read, item.letter_key)
    filename = "授权函.pdf" if pdf else "授权函.png"
    event(db, user.id, "authorization", item.id, "download" if download else "preview")
    await db.commit()
    return Response(content=payload, media_type="application/pdf" if pdf else "image/png", headers={
        "Content-Disposition": _disposition(filename, download), "Cache-Control": "private, no-store",
    })
