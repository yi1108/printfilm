"""独立创作工具：文生图 / 图生图 / 图生产品 / 文生视频 / 视频生视频 / 电商拼图。"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ToolRun, User
from app.models_tasks import TaskRun
from app.services.ark import get_ark
from app.services.billing import record_line, run_billed_ephemeral
from app.services.drama.billing_util import record_seedream_image_usage
from app.services.billing.estimates import estimate_task_fen
from app.services.billing.settlement import billing_active
from app.services.ffmpeg_compose import extract_video_poster_frame
from app.services import storage

logger = logging.getLogger("app.studio_tools")

RATIO_SIZE = {
    "1:1": "1920x1920",
    "16:9": "2560x1440",
    "9:16": "1440x2560",
}

PRODUCT_PROMPTS = {
    "白底图": "电商商品白底精修图，纯白无缝背景，主体居中，光线均匀，无文字、无水印、无logo",
    "场景图": "电商商品生活场景图，自然光，真实使用氛围，主体清晰，无文字、无水印",
    "详情长图": "竖构图商品细节展示图，干净背景，材质与细节清晰，无文字、无水印",
}

ECOM_POSTER = "竖构图卖点海报氛围图，主体突出，干净构图，无文字、无字幕、无logo、无水印"


# 用户独立工具产出目录（挂在 p0/tools 下，不占用项目 id）
def tools_dir(user_id: int) -> Path:
    path = storage.project_dir(0) / "tools" / f"u{user_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Seedream 需要公网 https 参考图，同步上传 OSS
def publish_public(path: Path) -> str:
    local = storage.publish_local(path, sync=True)
    return storage.republish_url(local, sync=True) or local


# 结果 URL 尽量落到 OSS（本地 /static 同步上传）
def ensure_public_url(url: str | None) -> str | None:
    if not url:
        return url
    return storage.republish_url(url, sync=True) or url


# 批量把结果 URL 同步到 OSS
def ensure_public_urls(urls: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in urls or []:
        if not raw:
            continue
        published = ensure_public_url(raw)
        if published:
            out.append(published)
    return out


# 画幅文案转 Seedream size 像素
def ratio_to_size(ratio: str | None) -> str:
    return RATIO_SIZE.get((ratio or "").strip(), RATIO_SIZE["1:1"])


# 时长芯片（5s/10s/15s）转秒
def duration_seconds(raw: str | None) -> int:
    text = (raw or "5s").strip().lower().replace("s", "")
    try:
        n = int(text)
    except ValueError:
        n = 5
    return max(4, min(n, 15))


# 图生图相似度：低=改动大，高=尽量贴近参考图
def strength_hint(level: str | None) -> str:
    if level == "低":
        return "允许大幅改变构图与风格，仅保留主体可识别特征"
    if level == "高":
        return "尽量保持参考图主体外形、构图与色彩"
    return "在保持主体可识别的前提下适度改变风格"


# 视频运动强度提示，拼进 Seedance 文案
def motion_hint(level: str | None) -> str:
    if level == "弱":
        return "镜头几乎静止，只有轻微呼吸感运动"
    if level == "强":
        return "镜头运动明显，推拉或环绕，节奏更快"
    return "中等镜头运动，平稳跟拍"


# 把上传文件落到用户工具目录
def save_upload(user_id: int, data: bytes, filename: str) -> Path:
    ext = Path(filename or "bin").suffix.lower() or ".bin"
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm"}:
        raise ValueError("仅支持 png / jpg / webp / gif / mp4 / mov / webm")
    dest = tools_dir(user_id) / f"{uuid.uuid4().hex[:12]}{ext}"
    dest.write_bytes(data)
    return dest


# 用 ffmpeg 把多张图拼成一张（横向主图 / 纵向详情）
def collage_images(paths: list[Path], dest: Path, *, vertical: bool) -> None:
    ffmpeg = shutil.which(get_settings().ffmpeg_path) or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法拼接图片")
    if len(paths) < 2:
        shutil.copy2(paths[0], dest)
        return
    inputs: list[str] = []
    for p in paths[:4]:
        inputs.extend(["-i", str(p)])
    n = min(len(paths), 4)
    scaled = "".join(f"[{i}:v]scale=720:-2[s{i}];" for i in range(n))
    labels = "".join(f"[s{i}]" for i in range(n))
    layout = "vstack" if vertical else "hstack"
    filt = f"{scaled}{labels}{layout}=inputs={n}[out]"
    cmd = [ffmpeg, "-y", *inputs, "-filter_complex", filt, "-map", "[out]", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError((proc.stderr or "拼接失败")[-800:])


# 文生图 / 图生图 / 图生产品 / 电商拼图：同步调用 Seedream 或 ffmpeg
async def run_image_tool(
    db: AsyncSession,
    user: User,
    *,
    tool_id: str,
    prompt: str,
    negative: str,
    ratio: str | None,
    strength: str | None,
    mode: str | None,
    pack: str | None,
    files: list[Path],
) -> dict:
    ark = get_ark()
    size = ratio_to_size(ratio)
    refs: list[str] = []
    full_prompt = (prompt or "").strip()

    if tool_id == "t2i":
        if len(full_prompt) < 4:
            raise ValueError("请填写提示词")
    elif tool_id in {"i2i", "i2p"}:
        if not files:
            raise ValueError("请上传参考图")
        refs = [publish_public(files[0])]
        if tool_id == "i2i":
            full_prompt = f"{full_prompt or '保持主体，生成风格一致的变体'}。{strength_hint(strength)}"
        else:
            mode_prompt = PRODUCT_PROMPTS.get(mode or "白底图", PRODUCT_PROMPTS["白底图"])
            full_prompt = f"{mode_prompt}。{full_prompt}".strip("。")
            if (mode or "白底图") == "详情长图":
                size = RATIO_SIZE["9:16"]
            elif mode == "场景图":
                size = RATIO_SIZE["16:9"]
    elif tool_id == "ecom":
        pack_name = pack or "主图拼接"
        if pack_name == "卖点海报":
            if not files:
                raise ValueError("请上传商品图")
            refs = [publish_public(files[0])]
            full_prompt = f"{ECOM_POSTER}。{full_prompt}".strip("。")
        else:
            if len(files) < 2:
                raise ValueError("拼接至少上传 2 张图片")
            dest = tools_dir(user.id) / f"collage_{uuid.uuid4().hex[:8]}.jpg"
            collage_images(files, dest, vertical=pack_name == "详情排版")
            url = publish_public(dest)
            return {"kind": "image", "urls": [url], "status": "succeeded"}
    else:
        raise ValueError("不支持的生图工具")

    result = await ark.gen_image(
        full_prompt,
        negative,
        refs or None,
        project_id=0,
        shot_no=user.id,
        size=size,
    )
    await record_seedream_image_usage(
        db,
        user_id=user.id,
        model=get_settings().model_image,
        domain="studio",
        image_result=result,
        extra_raw={"tool_id": tool_id},
    )
    url = result.local_url or result.remote_url or ""
    if url:
        url = ensure_public_url(url) or url
    return {"kind": "image", "urls": [url], "status": "succeeded"}


def _dispatch_tool_image(run_id: int) -> str:
    """启动工具生图后台任务。"""
    import asyncio

    asyncio.create_task(execute_image_tool_run(run_id))
    return f"local-{run_id}"


# 入队前同步校验余额（与 run_billed_ephemeral 预扣估算一致）
async def _ensure_image_tool_balance(db: AsyncSession, user: User, tool_id: str) -> None:
    if not billing_active(user):
        return
    synthetic = TaskRun(domain="studio", task_type="tool_image", payload={"tool_id": tool_id})
    need = await estimate_task_fen(db, synthetic)
    available = int(user.balance_fen or 0)
    if available < need:
        raise ValueError(f"余额不足：需要 ¥{need/100:.2f}，当前 ¥{available/100:.2f}，请先充值")


# 提交生图任务：立即返回 task_id，实际生成在后台执行
async def enqueue_image_tool(
    db: AsyncSession,
    user: User,
    *,
    tool_id: str,
    prompt: str,
    negative: str,
    ratio: str | None,
    strength: str | None,
    mode: str | None,
    pack: str | None,
    files: list[Path],
    params: dict,
) -> dict:
    await _ensure_image_tool_balance(db, user, tool_id)
    row = ToolRun(
        user_id=user.id,
        tool_id=tool_id,
        kind="image",
        status="queued",
        prompt=(prompt or "").strip()[:2000],
        params={
            **(params or {}),
            "file_paths": [str(p) for p in files],
        },
    )
    db.add(row)
    await db.flush()
    task_id = _dispatch_tool_image(row.id)
    row.task_id = task_id
    await db.flush()
    return {
        "kind": "image",
        "urls": [],
        "task_id": task_id,
        "status": "queued",
        "message": "生图任务已提交，请稍候",
        "run_id": row.id,
    }


# 后台执行已入队的生图任务并回写 tool_runs
async def execute_image_tool_run(run_id: int) -> dict:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await db.get(ToolRun, run_id)
        if not row:
            return {"ok": False, "error": "run_not_found"}
        if row.status == "succeeded" and row.urls:
            return {"ok": True, "run_id": run_id}

        user = await db.get(User, row.user_id)
        if not user:
            row.status = "failed"
            row.error = "用户不存在"
            await db.commit()
            return {"ok": False, "error": row.error}

        stored = row.params if isinstance(row.params, dict) else {}
        file_paths = [Path(p) for p in stored.get("file_paths") or [] if p]
        row.status = "running"
        await db.commit()

        try:
            async def _exec() -> dict:
                return await run_image_tool(
                    db,
                    user,
                    tool_id=row.tool_id,
                    prompt=row.prompt or "",
                    negative=str(stored.get("negative") or ""),
                    ratio=stored.get("ratio") or None,
                    strength=stored.get("strength") or None,
                    mode=stored.get("mode") or None,
                    pack=stored.get("pack") or None,
                    files=file_paths,
                )

            billing_task, data = await run_billed_ephemeral(
                db,
                user,
                domain="studio",
                task_type="tool_image",
                executor=_exec,
                payload={"tool_id": row.tool_id, "run_id": run_id},
                commit=False,
            )
            urls = ensure_public_urls(list(data.get("urls") or []))
            row.kind = str(data.get("kind") or "image")
            row.status = str(data.get("status") or "succeeded")
            row.urls = urls
            row.preview_url = urls[0] if urls else row.preview_url
            row.error = None
            params = dict(row.params or {})
            params["billing_task_id"] = billing_task.id
            row.params = params
            await db.commit()
            return {"ok": True, "run_id": run_id, "urls": urls, "billing_task_id": billing_task.id}
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.error = str(exc)[:512]
            await db.commit()
            logger.exception("execute_image_tool_run failed run_id=%s", run_id)
            return {"ok": False, "run_id": run_id, "error": row.error}


# 轮询工具生图任务状态。
async def poll_image_tool_task(db: AsyncSession, user: User, task_id: str) -> dict:
    stmt = select(ToolRun).where(ToolRun.user_id == user.id, ToolRun.task_id == task_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return {"status": "failed", "kind": "image", "urls": [], "error": "任务不存在"}

    if row.status == "succeeded":
        row = await hydrate_tool_run_urls(db, row)
        return {"status": "succeeded", "kind": "image", "urls": list(row.urls or [])}
    if row.status == "failed":
        return {
            "status": "failed",
            "kind": "image",
            "urls": [],
            "error": row.error or "生成失败",
        }

    return {"status": "running", "kind": "image", "urls": []}


# 文生视频 / 视频生视频：先出静帧再提交 Seedance，返回 task_id
async def start_video_tool(
    db: AsyncSession,
    user: User,
    *,
    tool_id: str,
    prompt: str,
    ratio: str | None,
    duration_raw: str | None,
    motion: str | None,
    files: list[Path],
) -> dict:
    ark = get_ark()
    duration = duration_seconds(duration_raw)
    still_path: Path | None = None
    preview_url: str | None = None

    if tool_id == "t2v":
        text = (prompt or "").strip()
        if len(text) < 4:
            raise ValueError("请填写视频脚本")
        still = await ark.gen_image(
            f"{text}。电影感静帧，无文字",
            "文字，字幕，水印，logo",
            project_id=0,
            shot_no=user.id,
            size=ratio_to_size(ratio or "9:16"),
        )
        await record_seedream_image_usage(
            db,
            user_id=user.id,
            model=get_settings().model_image,
            domain="studio",
            image_result=still,
            extra_raw={"tool_id": "t2v-still"},
        )
        preview_url = still.local_url or still.remote_url
        if preview_url:
            published = storage.republish_url(preview_url, sync=True)
            if published:
                preview_url = published
        image_url = preview_url or still.remote_url
        video_prompt = text
    elif tool_id == "v2v":
        if not files:
            raise ValueError("请上传源视频或首帧图")
        src = files[0]
        if src.suffix.lower() in {".mp4", ".mov", ".webm"}:
            still_path = tools_dir(user.id) / f"frame_{uuid.uuid4().hex[:8]}.jpg"
            if not extract_video_poster_frame(src, still_path):
                raise ValueError("无法从视频抽取首帧")
        else:
            still_path = src
        image_url = publish_public(still_path)
        preview_url = image_url
        video_prompt = f"{(prompt or '保持主体，变换画面风格').strip()}。{motion_hint(motion)}"
    else:
        raise ValueError("不支持的视频工具")

    if not image_url:
        raise ValueError("缺少首帧图，无法生成视频")

    task_id = await ark.gen_video_i2v(
        image_url,
        video_prompt,
        duration,
        resolution="480p",
        generate_audio=False,
    )
    digest = hashlib.md5(f"{user.id}:{task_id}".encode()).hexdigest()[:8]
    logger.info("tool video queued user=%s tool=%s task=%s hash=%s", user.id, tool_id, task_id, digest)
    return {
        "kind": "video",
        "urls": [],
        "task_id": task_id,
        "status": "queued",
        "preview_url": preview_url,
        "message": "视频生成中，请稍候",
    }


# 单次查询视频任务；成功则下载并同步 OSS
async def poll_video_task(user: User, task_id: str) -> dict:
    ark = get_ark()
    result = await ark.fetch_task_once(task_id)
    usage = {
        "total_tokens": int(result.total_tokens or 0),
        "completion_tokens": int(result.completion_tokens or 0),
    }
    if result.status == "succeeded" and result.url:
        dest = tools_dir(user.id) / f"v_{task_id[-10:]}.mp4"
        if result.url.startswith("/static/"):
            url = ensure_public_url(result.url) or result.url
        elif dest.exists() and dest.stat().st_size > 1000:
            url = publish_public(dest)
        else:
            await storage.download_to(result.url, dest)
            url = publish_public(dest)
        return {
            "status": "succeeded",
            "kind": "video",
            "urls": [url],
            "usage": usage,
            "raw_usage": result.raw_usage,
        }
    if result.status == "failed":
        return {
            "status": "failed",
            "kind": "video",
            "urls": [],
            "error": result.error or "生成失败",
            "usage": usage,
            "raw_usage": result.raw_usage,
        }
    return {"status": "running", "kind": "video", "urls": [], "usage": usage}


# 把一次工具生成写入 tool_runs（结果 URL 优先 OSS）
async def persist_tool_run(
    db: AsyncSession,
    *,
    user_id: int,
    tool_id: str,
    prompt: str,
    params: dict,
    data: dict,
) -> ToolRun:
    urls = ensure_public_urls(list(data.get("urls") or []))
    preview = ensure_public_url(data.get("preview_url")) or (urls[0] if urls else None)
    row = ToolRun(
        user_id=user_id,
        tool_id=tool_id,
        kind=str(data.get("kind") or "image"),
        status=str(data.get("status") or "succeeded"),
        prompt=(prompt or "").strip()[:2000],
        preview_url=preview,
        urls=urls,
        task_id=data.get("task_id"),
        params=params or None,
        error=data.get("error"),
    )
    db.add(row)
    await db.flush()
    return row


# 按 Seedance task_id 回写视频结果（同步 OSS）
async def update_tool_run_task(db: AsyncSession, user_id: int, task_id: str, data: dict) -> None:
    stmt = select(ToolRun).where(ToolRun.user_id == user_id, ToolRun.task_id == task_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return
    row.status = str(data.get("status") or row.status)
    if data.get("urls"):
        urls = ensure_public_urls(list(data["urls"]))
        row.urls = urls
        if not row.preview_url and urls:
            row.preview_url = urls[0]
        elif row.preview_url:
            row.preview_url = ensure_public_url(row.preview_url)
    if data.get("error"):
        row.error = str(data["error"])[:512]
    await db.flush()


# 读取时把本地 URL 补传到 OSS，并回写库
async def hydrate_tool_run_urls(db: AsyncSession, row: ToolRun) -> ToolRun:
    changed = False
    urls = ensure_public_urls(list(row.urls or []))
    if urls != list(row.urls or []):
        row.urls = urls
        changed = True
    preview = ensure_public_url(row.preview_url) or (urls[0] if urls else None)
    if preview != row.preview_url:
        row.preview_url = preview
        changed = True
    if changed:
        await db.flush()
    return row


# 按 id 取当前用户的一条创作记录
async def get_tool_run(db: AsyncSession, user_id: int, run_id: int) -> ToolRun | None:
    stmt = select(ToolRun).where(ToolRun.user_id == user_id, ToolRun.id == run_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    return await hydrate_tool_run_urls(db, row)


# 分页列出当前用户的工具创作记录
async def list_tool_runs(
    db: AsyncSession,
    user_id: int,
    *,
    page: int,
    page_size: int,
) -> tuple[list[ToolRun], int]:
    where = ToolRun.user_id == user_id
    total = int(await db.scalar(select(func.count()).select_from(ToolRun).where(where)) or 0)
    stmt = (
        select(ToolRun)
        .where(where)
        .order_by(ToolRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    hydrated: list[ToolRun] = []
    for row in rows:
        hydrated.append(await hydrate_tool_run_urls(db, row))
    return hydrated, total
