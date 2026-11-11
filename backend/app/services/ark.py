"""Volcengine Ark gateway via HTTP (chat / Seedream / Seedance / TTS)."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlparse

import httpx

from app.services.tasks.upstream import observed_request

from app.config import Settings, get_settings
from app.services.billing.pricing import parse_upstream_cost_fen, parse_usage_dict
from app.schemas_routing import ResolvedModelRoute
from app.services.logical_model_router import (
    resolve_logical_model,
    resolve_logical_model_id,
    resolve_upstream_model,
)
from app.services.tokenfree_audio import (
    TOKENFREE_DEFAULT_TTS_MODEL,
    build_omni_tts_chat_body,
    extract_chat_audio_bytes,
    extract_sse_audio_bytes,
    iter_tokenfree_tts_models,
    resolve_tokenfree_tts_model,
    tokenfree_speech_voice,
    tokenfree_tts_chat_model,
    tokenfree_tts_uses_chat_audio,
    tokenfree_tts_uses_omni_stream,
    wrap_pcm_s16le_wav,
)
from app.services.tokenfree_image import (
    build_tokenfree_image_body,
    extract_tokenfree_image_url,
    is_tokenfree_image_url,
    is_tokenfree_input_text_sensitive,
    is_tokenfree_rate_limit,
    post_until_not_rate_limited,
    raise_tokenfree_image_if_failed,
    tokenfree_image_slot,
    tokenfree_image_user_error,
)
from app.services.voices import edge_tts_voice_for_speaker
from app.services.tokenfree_video import (
    extract_video_result_url,
    extract_video_task_id,
    format_video_task_error,
    is_tokenfree_content_url,
    normalize_video_task_status,
    prepare_video_create_body,
    post_video_create,
    remap_video_path,
    resolve_tokenfree_media_download_url,
    tokenfree_video_content_url,
    unwrap_video_task_payload,
    uses_tokenfree_video,
)
from app.services import storage
from app.services import local_media_mock
from app.services.media_models.runtime import (
    current_snapshot, current_operation, execution_params, operation_for, restore_route, stamp_usage,
)
from app.services.drama.seedance_i2v_role import resolve_seedance_i2v_image_role
from app.services.ffmpeg_compose import is_near_silent_audio
from app.services.drama.llm import _extract_json
from app.services.llm_client import chat_completions
from app.services.content_expansion import expansion_messages, fallback_expansion, expansion_language_matches, topic_language
from app.services import seedance_segments as segplan
from app.services.storyboard_language import storyboard_language_rule, validate_storyboard_language

logger = logging.getLogger(__name__)
# 画布生图在本地媒体模拟开启时仍走真实上游；视频和配音继续模拟。
_force_real_image: contextvars.ContextVar[bool] = contextvars.ContextVar("force_real_image", default=False)


class force_real_image:
    """在当前任务内让生图请求真正发到上游。"""

    def __enter__(self) -> None:
        self._token = _force_real_image.set(True)

    def __exit__(self, *_args: object) -> None:
        _force_real_image.reset(self._token)

# TokenFree /v1/responses 同步等图；Kie sunburst 偶发超过 10 分钟才回
IMAGE_GEN_READ_SEC = 1200.0
# 创建视频任务应返回 task_id；TokenFree 拉参考图时可能拖到一两分钟
VIDEO_CREATE_READ_SEC = 180.0
# 轮询/单次查询只要状态 JSON
VIDEO_POLL_READ_SEC = 60.0
VIDEO_FETCH_READ_SEC = 30.0


def _upstream_timeout(read_sec: float, *, connect: float = 30.0) -> httpx.Timeout:
    """上游 HTTP 超时：建连短、等结果长，避免 ReadTimeout 被当成连不上。"""
    return httpx.Timeout(connect=connect, read=float(read_sec), write=60.0, pool=30.0)


def reraise_upstream_timeout(exc: BaseException, *, kind: str, read_sec: float) -> NoReturn:
    """把 httpx 超时翻成可读 RuntimeError；ReadTimeout 表示已连通但等结果超时。"""
    if isinstance(exc, httpx.ReadTimeout):
        raise RuntimeError(
            f"{kind}等待上游超时（ReadTimeout）：已连通 TokenFree，但 {read_sec:.0f} 秒内未返回结果，请稍后重试"
        ) from exc
    if isinstance(exc, httpx.WriteTimeout):
        raise RuntimeError(
            f"{kind}发送请求超时（WriteTimeout）：已连通 TokenFree，但 {read_sec:.0f} 秒内未能发完请求，请稍后重试"
        ) from exc
    name = type(exc).__name__
    raise RuntimeError(
        f"{kind}无法连接上游（{name}）：请检查网络、代理或 TokenFree 是否可达"
    ) from exc


def _raise_seedream_http_error(
    status_code: int,
    body: str,
    *,
    model: str = "",
    tokenfree: bool = False,
) -> None:
    """将出图 HTTP 错误转为可读 RuntimeError；TokenFree 文案与官方方舟分开。"""
    snippet = (body or "")[:800]
    if status_code == 403 and "AccountOverdueError" in snippet:
        logger.error("Seedream AccountOverdueError — upstream Ark account overdue: %s", snippet[:200])
        raise RuntimeError(
            "上游 Seedream 账户欠费（AccountOverdueError），生图暂不可用，请联系管理员充值 TokenFree 账户"
        )
    logger.warning(
        "出图上游失败 model=%s tokenfree=%s status=%s body=%s",
        (model or "").strip() or "-",
        tokenfree,
        status_code,
        snippet[:200],
    )
    if tokenfree:
        if is_tokenfree_input_text_sensitive(status_code=status_code, body=snippet):
            raise RuntimeError(
                "生图文案未通过内容审核（可能含敏感或历史名人相关表述），"
                "请修改提示词后重试。"
                f" 详情：{snippet[:240]}"
            )
        raise RuntimeError(tokenfree_image_user_error(model=model, status_code=status_code, body=snippet))
    if "InputTextSensitive" in snippet or "InputTextSensitiveContentDetected" in snippet:
        raise RuntimeError(
            "生图文案未通过内容审核（可能含敏感或历史名人相关表述），"
            "请修改提示词后重试。"
            f" 详情：{snippet[:240]}"
        )
    raise RuntimeError(f"Seedream error {status_code}: {snippet}")


def _fallback_overlay_title(text: str, shot_no: int) -> str:
    """Last resort when LLM omits title — never blind-slice mid-word (e.g. ERP→ER)."""
    raw = re.sub(r"\s+", "", (text or "").strip())
    if not raw:
        return f"场景{shot_no}"
    clause = re.split(r"[，。；！？、,:;]", raw, maxsplit=1)[0].strip()
    if 2 <= len(clause) <= 10 and not _looks_truncated_token(clause, raw):
        return clause
    return f"场景{shot_no}"


def _fallback_overlay_subtitle(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    cleaned = re.sub(r"\s+", "", raw)
    clause = re.split(r"[，。；！？、,:;]", cleaned, maxsplit=1)[0].strip()
    if 4 <= len(clause) <= 22:
        return clause
    if len(clause) > 22:
        # Prefer a trailing noun-ish chunk over a head that cuts mid-phrase
        for n in range(18, 7, -1):
            tail = clause[-n:].lstrip("的与和及")
            if 6 <= len(tail) <= 18 and not re.match(r"[A-Za-z0-9]", tail[:1] or ""):
                if not _looks_truncated_token(tail, clause):
                    return tail
        head = clause[:18]
        if re.search(r"[A-Za-z0-9]$", head) and re.match(r"[A-Za-z0-9]", clause[18:19] or ""):
            m = re.search(r"[A-Za-z0-9]+$", head)
            if m and m.start() > 6:
                head = head[: m.start()]
        return head
    return cleaned[:22] if len(cleaned) > 22 else cleaned


def _looks_truncated_token(title: str, full_text: str) -> bool:
    """True if title is a prefix of narration that cuts a Latin/数字专有词 mid-way."""
    t = re.sub(r"\s+", "", (title or "").strip())
    full = re.sub(r"\s+", "", (full_text or "").strip())
    if not t or not full.startswith(t):
        return False
    if len(full) <= len(t):
        return False
    # Truncated mid-ASCII token: title ends with alnum and next char is alnum
    if re.search(r"[A-Za-z0-9]$", t) and re.match(r"[A-Za-z0-9]", full[len(t)]):
        return True
    # Obvious raw prefix grab of long narration
    if len(t) <= 12 and len(full) > len(t) + 8 and full.startswith(t):
        return True
    return False


def _normalize_overlay_title(title: str, text: str, shot_no: int) -> str:
    t = (title or "").strip()
    if not t or _looks_truncated_token(t, text):
        return _fallback_overlay_title(text, shot_no)
    return t[:32]


def _normalize_overlay_subtitle(subtitle: str, text: str) -> str:
    s = (subtitle or "").strip()
    if not s or _looks_truncated_token(s, text):
        return _fallback_overlay_subtitle(text)[:64]
    return s[:64]


# Soften brand / IP names that Seedream often rejects as copyright
_SEEDREAM_SANITIZE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bspacex\b"), "民营商业航天公司"),
    (re.compile(r"(?i)\bspace\s*x\b"), "民营商业航天公司"),
    (re.compile(r"(?i)\bfalcon\s*heavy\b"), "重型运载火箭"),
    (re.compile(r"(?i)\bfalcon\s*1\b"), "首枚试验运载火箭"),
    (re.compile(r"(?i)\bfalcon\s*9\b"), "可回收运载火箭"),
    (re.compile(r"(?i)\bfalcon\b"), "试验运载火箭"),
    (re.compile(r"(?i)\bstarship\b"), "巨型运载飞船"),
    (re.compile(r"(?i)\belon\s*musk\b"), "航天企业家"),
    (re.compile(r"(?i)\btesla\b"), "电动车企业"),
    (re.compile(r"猎鹰一号"), "首枚试验运载火箭"),
    (re.compile(r"猎鹰\s*9"), "可回收运载火箭"),
    (re.compile(r"猎鹰重型"), "重型运载火箭"),
    (re.compile(r"猎鹰"), "试验运载火箭"),
    (re.compile(r"马斯克"), "航天企业家"),
    (re.compile(r"埃隆"), "航天企业家"),
    (re.compile(r"Space\s*X"), "民营商业航天公司"),
]

# 真人 / 写实人脸审核命中后追加的画风引导，压低照片级真人触发概率
_SEEDREAM_CG_STYLE = (
    "用CG厚涂、游戏CG的风格打造的画面，色彩层次丰富，质感细腻逼真，"
    "真实的光影效果赋予画面生动感"
)


def storyboard_name_policy(allow_source_names: bool) -> str:
    """旁白是否保留用户文案中的店名/产品名；画面始终不烧录 logo。"""
    if allow_source_names:
        return (
            "用户文案里出现的店名、地址、产品名、人名必须在旁白与 title 原样保留，"
            "禁止改成某店/某品牌；文案没有的名称一律不许编。"
            "img_prompt 仍禁止烧录真实 logo、商标图形或屏幕可读文字。"
        )
    return "禁止真实商标/公司名/人名（改用泛称）。"


@dataclass
class ShotPlan:
    shot: int
    duration: float
    text: str
    img_prompt: str
    video_prompt: str
    camera: str
    bgm: str
    overlay_title: str = ""
    overlay_subtitle: str = ""
    segment_script: str = ""


@dataclass
class StoryboardResult:
    shots: list[ShotPlan]
    character_bible: str = ""
    bgm_lock: str = ""


@dataclass
class TaskResult:
    status: str  # pending | running | succeeded | failed
    url: str | None = None
    last_frame_url: str | None = None
    error: str | None = None
    total_tokens: int = 0
    completion_tokens: int = 0
    raw_usage: dict[str, Any] | None = None
    provider_task_id: str | None = None
    # Kie credits 等换算后的上游成本（分）；有值时优先于 token 估算
    upstream_cost_fen: int | None = None


# 任务查询的瞬时 HTTP 状态：限流/网关故障，任务本身仍可能在跑，
# 必须交给轮询退避（poller 有总超时兜底），单次命中绝不能判任务 failed。
def _is_transient_http_status(status_code: int) -> bool:
    """429 限流或 5xx 网关/上游故障视为可重试。"""
    return status_code == 429 or status_code >= 500


def _retry_after_seconds(resp: httpx.Response, default: float) -> float:
    """尊重 Retry-After（delta-seconds）；缺失或 HTTP-date 形式时用默认间隔，上限 60s。"""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(0.0, min(60.0, float(raw.strip())))
        except ValueError:
            pass
    return default


# 从任务 payload 提取 New API quota（单次消耗，不是账户余额）
def _extract_task_quota(payload: dict[str, Any], usage: dict[str, Any] | None) -> int | None:
    for block in (usage or {}, payload):
        if not isinstance(block, dict):
            continue
        for key in ("quota", "quota_consumed", "consumed_quota"):
            raw = block.get(key)
            if raw is None:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return None


# 从 Seedance / New API 任务查询响应解析状态、媒体 URL 与官方 usage
def _build_task_result_from_payload(data: dict[str, Any]) -> TaskResult:
    payload = unwrap_video_task_payload(data)
    status = normalize_video_task_status(str(payload.get("status", "") or "running"))
    usage_parsed = parse_usage_dict(payload)
    total_tokens = int(usage_parsed.get("total_tokens") or 0)
    completion_tokens = int(usage_parsed.get("completion_tokens") or 0)
    # usage 为空对象时 parse 会得到 0；再扫顶层字段（部分网关只在顶层回 completion_tokens）
    if total_tokens <= 0 and completion_tokens <= 0:
        for key in ("completion_tokens", "total_tokens", "output_tokens"):
            try:
                n = int(payload.get(key) or 0)
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                if key == "completion_tokens" or key == "output_tokens":
                    completion_tokens = n
                total_tokens = max(total_tokens, n)
                break
    raw_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    if not raw_usage and (total_tokens > 0 or completion_tokens > 0):
        raw_usage = {
            "total_tokens": total_tokens,
            "completion_tokens": completion_tokens or total_tokens,
        }
    elif isinstance(raw_usage, dict) and total_tokens > 0:
        # 空 usage {} 补齐，避免下游当成「无用量」
        merged = dict(raw_usage)
        merged.setdefault("total_tokens", total_tokens)
        if completion_tokens > 0:
            merged.setdefault("completion_tokens", completion_tokens)
        raw_usage = merged

    # New API 任务级 quota → 上游成本（分），供结算优先对齐 TokenFree 账单
    upstream_cost_fen: int | None = None
    quota = _extract_task_quota(payload, raw_usage if isinstance(raw_usage, dict) else None)
    if quota is not None:
        from app.services.tokenfree_usage import quota_to_cost_fen

        cost = quota_to_cost_fen(quota)
        if cost > 0:
            upstream_cost_fen = cost
            merged_usage = dict(raw_usage or {})
            merged_usage["quota"] = quota
            merged_usage["cost_fen"] = cost
            if total_tokens > 0:
                merged_usage.setdefault("total_tokens", total_tokens)
                merged_usage.setdefault("tokens", total_tokens)
            raw_usage = merged_usage

    if status == "succeeded":
        return TaskResult(
            status="succeeded",
            url=extract_video_result_url(payload),
            last_frame_url=_extract_seedance_last_frame_url(payload),
            total_tokens=total_tokens,
            completion_tokens=completion_tokens,
            raw_usage=raw_usage,
            upstream_cost_fen=upstream_cost_fen,
        )
    if status == "failed":
        err = payload.get("error") or payload.get("message") or payload.get("fail_reason") or "failed"
        return TaskResult(
            status="failed",
            error=format_video_task_error(err),
            total_tokens=total_tokens,
            completion_tokens=completion_tokens,
            raw_usage=raw_usage,
            upstream_cost_fen=upstream_cost_fen,
        )
    return TaskResult(
        status="running",
        total_tokens=total_tokens,
        completion_tokens=completion_tokens,
        raw_usage=raw_usage,
        upstream_cost_fen=upstream_cost_fen,
    )


# 从 Seedance 任务成功响应中提取尾帧 URL
def _extract_seedance_last_frame_url(data: dict[str, Any]) -> str | None:
    content = data.get("content")
    if isinstance(content, dict):
        for key in ("last_frame_url", "last_frame_image_url", "lastFrameUrl"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = content.get("last_frame")
        if isinstance(nested, dict):
            nested_url = nested.get("url")
            if isinstance(nested_url, str) and nested_url.strip():
                return nested_url.strip()
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    for key in ("last_frame_url", "last_frame_image_url", "lastFrameUrl"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# 从错误文案解析 content[n] 下标与可选标签
def _seedance_content_slot_label(
    text: str,
    content_labels: list[str] | None = None,
) -> tuple[int, str]:
    m = re.search(r"content\[(\d+)\]", text or "", re.I)
    idx = int(m.group(1)) if m else -1
    label = ""
    if idx >= 0 and content_labels and idx < len(content_labels):
        label = str(content_labels[idx] or "").strip()
    return idx, label


# 将 Seedance 创建失败响应转为可读中文（保留关键 code 便于前端匹配）
def _format_seedance_create_error(
    status_code: int,
    body: str,
    content_labels: list[str] | None = None,
) -> str:
    text = (body or "")[:800]
    if any(
        k in text
        for k in ("PrivacyInformation", "InputImageSensitive", "SensitiveContentDetected", "real person")
    ):
        idx, label = _seedance_content_slot_label(text, content_labels)
        if label:
            return (
                f"参考图疑似真人：{label}（content[{idx}]，PrivacyInformation），"
                "请更换该形象为动漫或插画后重试"
            )
        if idx >= 0:
            return (
                f"参考图疑似真人（提交内容第 {idx + 1} 项 / content[{idx}]，PrivacyInformation），"
                "请更换对应角色/场景形象为动漫或插画后重试"
            )
        return "参考图疑似真人（PrivacyInformation），请更换角色/场景形象为动漫或插画后重试"
    if "InputTextSensitive" in text or "text sensitive" in text.lower():
        return "分镜文案未通过内容审核，请修改敏感表述后重试"
    if "resource download failed" in text and "audio" in text.lower():
        return "参考音频无法下载，请检查角色音色绑定后重试"
    # 参考图槽位收到非图片（常见：音色 cover 写成 mp3）
    if re.search(r"invalid image format", text, re.I) or (
        re.search(r"File type not supported", text, re.I)
        and re.search(r"content\[\d+\]", text, re.I)
    ):
        idx, label = _seedance_content_slot_label(text, content_labels)
        who = label or (f"提交内容第 {idx + 1} 项 / content[{idx}]" if idx >= 0 else "某张参考图")
        return (
            f"参考图格式无效：{who}。"
            "上游按图片校验失败（常见原因：音频文件被误当作参考图，或链接不是 PNG/JPG/WEBP）。"
            "请检查本镜引用的角色/场景封面，确认音色资产未占用参考图槽位后重试。"
        )
    # Seedance r2v：reference_audio 时长须 ≥ 1.8 秒
    if re.search(r"audio duration.*(?:1\.8|greater than or equal)", text, re.I) or (
        "audio duration" in text.lower() and "content[" in text.lower()
    ):
        idx, label = _seedance_content_slot_label(text, content_labels)
        who = label or (f"提交内容第 {idx + 1} 项 / content[{idx}]" if idx >= 0 else "某条参考音频")
        return (
            f"参考音频过短：{who}，Seedance 要求时长 ≥ 1.8 秒。"
            "请打开对应角色/旁白，重新生成或上传更长的试听音频后再生成该分镜。"
        )
    # Seedance 2.0 输出时长仅 4–15s；2.5 为 4–30s
    if re.search(r"parameter\s+duration.*not valid|duration.*not valid for model", text, re.I):
        if re.search(r"seedance-2-0|seedance-2\.0|doubao-seedance-2-0", text, re.I):
            return "成片时长超出 Seedance 2.0 允许范围（4–15 秒），请缩短到 15 秒以内后重试"
        return "成片时长参数无效，请按当前模型允许范围调整后重试"
    # TokenFree New API：分组下无 distributor
    if (
        "model_not_found" in text
        or "无可用渠道" in text
        or ("distributor" in text.lower() and "seedance" in text.lower())
    ):
        if re.search(r"seedance-2\.5|seedance-2-5", text, re.I):
            return (
                "当前 TokenFree 账号未开通 Seedance 2.5（分组 default 无可用渠道）。"
                "请改用 Seedance 2.0，或在 TokenFree 控制台为 default 分组配置 2.5 渠道后再试"
            )
        return "上游未开通该视频模型渠道，请更换模型或在 TokenFree 控制台检查分组配置后重试"
    return f"Seedance create error {status_code}: {text}"


@dataclass
class ImageResult:
    local_url: str
    remote_url: str | None = None
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_usage: dict[str, Any] | None = None
    upstream_cost_fen: int | None = None


class ArkGateway:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings_override = settings

    @property
    def settings(self) -> Settings:
        return self._settings_override or get_settings()

    # 优先后台 TokenFree / 方舟渠道 Key，env 仅作空渠道时的兜底
    def _ark_api_key(self) -> str:
        try:
            from app.services.model_settings import get_routing_snapshot
            from app.services.tokenfree_gateway import TOKENFREE_CHANNEL_ID

            channels = get_routing_snapshot().channels
        except Exception:  # noqa: BLE001
            channels = []
            TOKENFREE_CHANNEL_ID = "tokenfree"
        enabled = [ch for ch in channels if ch.enabled and (ch.api_key or "").strip()]
        preferred = next((ch for ch in enabled if ch.id == TOKENFREE_CHANNEL_ID), None)
        if preferred is None:
            preferred = enabled[0] if enabled else None
        if preferred is not None:
            return (preferred.api_key or "").strip()
        return (self.settings.ark_api_key or "").strip()

    @property
    def mock(self) -> bool:
        if getattr(self.settings, "local_media_mock", False):
            return False  # Media has its own branches; storyboard/expansion must use real LLM.
        return self.settings.ark_mock or not self._ark_api_key()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ark_api_key()}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        """拼接方舟/TokenFree 基址；视频任务路径在 TokenFree 上改写为 /videos。"""
        path = remap_video_path(path, base_url=self.settings.ark_base_url)
        base = self.settings.ark_base_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}"

    # 按逻辑路由解析 ARK 渠道凭证
    def _resolve_ark_route(self, capability: str, model_id: str | None) -> ResolvedModelRoute | None:
        operation = current_operation.get()
        snapshot = current_snapshot.get()
        if snapshot and (capability in {"image", "video"} or any(
            item["capability"] == capability for item in snapshot.get("items", [])
        )):
            if not operation or operation["capability"] != capability:
                operation = operation_for(capability, model=model_id)
            if operation:
                return restore_route(operation["route"])
        resolve_upstream_model(capability, model_id)
        logical_id = resolve_logical_model_id(capability, model_id)
        route = resolve_logical_model(capability, logical_id)
        if route is None:
            from app.services.model_settings import get_routing_snapshot
            if get_routing_snapshot().channels:
                raise RuntimeError(f"固定模型 {logical_id} 没有可用渠道，不会自动切换路由")
        return route

    def _poll_route(self) -> ResolvedModelRoute | None:
        operation = operation_for("video") if current_snapshot.get() else None
        if operation:
            current_operation.set(operation)
            return restore_route(operation["route"])
        return None

    def _route_headers(self, route: ResolvedModelRoute | None = None) -> dict[str, str]:
        if route and route.api_key:
            return {
                "Authorization": f"Bearer {route.api_key}",
                "Content-Type": "application/json",
            }
        return self._headers()

    def _route_url(self, path: str, route: ResolvedModelRoute | None = None) -> str:
        """按逻辑路由基址拼 URL；无路由时回落到 _url。"""
        if route and route.base_url:
            path = remap_video_path(
                path,
                base_url=route.base_url,
                channel_id=getattr(route, "channel_id", "") or "",
            )
            base = route.base_url.rstrip("/")
            if not path.startswith("/"):
                path = "/" + path
            return f"{base}{path}"
        return self._url(path)

    def _video_json(
        self,
        body: dict[str, Any],
        route: ResolvedModelRoute | None = None,
    ) -> dict[str, Any]:
        """TokenFree 上把 Seedance 方舟 body 包装成 POST /v1/videos 请求体。"""
        base = (route.base_url if route and route.base_url else self.settings.ark_base_url) or ""
        channel_id = (route.channel_id if route else "") or ""
        request = prepare_video_create_body(body, base_url=base, channel_id=channel_id)
        if route is not None:
            request["model"] = route.upstream_model
        return request

    def _finalize_video_result(self, result: TaskResult, task_id: str) -> TaskResult:
        """TokenFree 成功但无公网 URL 时，改用 GET /videos/{id}/content。"""
        result.provider_task_id = task_id
        if result.status == "succeeded" and not result.url and uses_tokenfree_video(
            base_url=self.settings.ark_base_url
        ):
            route = self._poll_route()
            result.url = tokenfree_video_content_url(route.base_url if route else self.settings.ark_base_url, task_id)
        return result

    async def _request_media(self, client: Any, method: str, endpoint: str, **kwargs: Any) -> Any:
        if getattr(self.settings, "local_media_mock", False) and not _force_real_image.get():
            return await local_media_mock.simulate_http_request(method, endpoint, **kwargs)
        return await observed_request(client, method, endpoint, **kwargs)

    async def download_result_media(self, url: str, dest: Path) -> None:
        """下载生成媒体；每次重试都重新解析 TokenFree 直链，避免沿用已断开的连接。"""
        from app.services.storage import is_retryable_download_error

        source = (url or "").strip()
        last_exc: BaseException | None = None
        for attempt in range(4):
            headers: dict[str, str] | None = None
            timeout: float | httpx.Timeout = 300.0
            download_url = source
            if is_tokenfree_content_url(download_url) or is_tokenfree_image_url(download_url):
                route = self._poll_route() if is_tokenfree_content_url(download_url) else None
                api_key = route.api_key if route else self._ark_api_key()
                headers = {"Authorization": f"Bearer {api_key}"}
                timeout = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=30.0)
                if is_tokenfree_content_url(download_url):
                    resolved = await resolve_tokenfree_media_download_url(download_url, api_key=api_key)
                    if resolved and resolved != download_url:
                        logger.info(
                            "TokenFree content 改走直链 %s -> %s",
                            download_url[:96],
                            resolved[:140],
                        )
                        download_url = resolved
                        headers = None  # TOS/CDN 签名直链无需 Bearer
            try:
                await storage.download_to(
                    download_url,
                    dest,
                    headers=headers,
                    timeout=timeout,
                    retries=1,
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= 3 or not is_retryable_download_error(exc):
                    raise
                logger.warning(
                    "成片下载中断，重新解析直链后重试 %s/4 url=%s err=%s",
                    attempt + 1,
                    download_url[:120],
                    exc,
                )
                await asyncio.sleep(1.5 + attempt * 2.0)
        if last_exc is not None:
            raise last_exc

    async def chat_storyboard(
        self,
        source_text: str,
        source_type: str,
        style_prefix: str,
        llm_system_addon: str,
        duration_min: int,
        duration_max: int,
        max_shot_duration: int,
        *,
        pipeline_mode: str = "full",
        character_hint: str = "",
        extra_requirements: str = "",
        consistency_mode: str = "character",
        output_ratio: str = "16:9",
        shot_range_override: tuple[int, int] | None = None,
        allow_source_names: bool = False,
    ) -> StoryboardResult:
        if self.mock:
            resolve_upstream_model("text", None)
            return await asyncio.to_thread(
                self._mock_storyboard,
                source_text,
                source_type,
                style_prefix,
                duration_min,
                duration_max,
                pipeline_mode,
                shot_range_override,
            )

        user_constraints = ""
        if (character_hint or "").strip():
            user_constraints += (
                f"用户指定人物设定（必须严格遵守，写入 character_bible）：{(character_hint or '').strip()}。"
            )
        if (extra_requirements or "").strip():
            user_constraints += f"用户其他画面要求：{(extra_requirements or '').strip()}。"

        mode = (consistency_mode or "character").strip().lower()
        if mode not in {"character", "style", "diverse"}:
            mode = "character"

        if mode == "diverse":
            if (character_hint or "").strip():
                person_rule = (
                    "character_bible：概括用户人物设定（可换具体个人，但须同类）。"
                    "【人物硬性】每镜必须出现符合用户人物设定的真人，面容清晰可见"
                    "（三分之四侧脸或浅景深半身），禁止只拍手部、后脑勺、过肩无脸或空界面无人。"
                    "img_prompt 须写清该镜人物族裔/发型/服装与可见面容角度，以及面前界面类型；各镜可换人。"
                )
            else:
                person_rule = (
                    "character_bible：根据主题与模板系统规则决定是否出人物，不要默认全片必须有人或必须无人。"
                    "模板要求人在场则写清操作者类型（可不锁同一张脸）；主题以界面/场景/示意图为主则可写「无固定人物」。"
                    "img_prompt 写清本镜主体与构图，禁止与模板系统附加规则对着干。"
                )
            consistency = (
                "必须输出严格 JSON 对象（不要数组、不要 markdown、不要代码围栏）："
                '{"character_bible":"...","shots":[...]}。'
                f"{person_rule}"
                f"视觉气质仅作底线参考（不要被其颜色绑架）：{style_prefix}。"
                f"{user_constraints}"
                "【动态规划】先分析用户内容的领域、产品形态与使用场景，再决定色板与界面类型，"
                "再拆镜；每镜对应不同操作或能力（总览、接入、工作台、流程、结果、部署、生态等）。"
                "配色与材质必须贴合内容（浅色SaaS、文档站、深色IDE、终端、架构图、白板均可），"
                "禁止默认霓虹蓝/赛博大屏/蓝紫渐变HUD，禁止各镜画面雷同，禁止待办任务清单，"
                "禁止同一仪表盘复制粘贴换字。"
            )
        elif mode == "style":
            consistency = (
                "必须输出严格 JSON 对象（不要数组、不要 markdown、不要代码围栏）："
                '{"character_bible":"...","shots":[...]}。'
                "character_bible：可简写「无固定主角」或留空说明；不要强行统一人物外形。"
                f"画风气质统一：{style_prefix}。"
                f"{user_constraints}"
                "各镜场景与构图应随内容变化，只需保持同类画风，禁止镜头间画面几乎一样。"
                "每镜 img_prompt 只写本镜场景与构图。"
            )
        else:
            consistency = (
                "必须输出严格 JSON 对象（不要数组、不要 markdown、不要代码围栏）："
                '{"character_bible":"...","shots":[...]}。'
                "character_bible：80-160字，固定描述本片反复出现的人物/主体外形"
                "（年龄感、发型发色、五官气质、体型、服装配色与辨识物），全片唯一设定，禁止每镜改人设。"
                f"画风要求（全片强制统一）：{style_prefix}。"
                f"{user_constraints}"
                "禁止镜头间混用写实摄影/真人脸与插画或动漫；禁止换脸换装换发型。"
                "每镜 img_prompt 只写本镜场景与构图（景物、动作、光影），不要重复粘贴大段画风/人物锁定原文；"
                "出现人物时用短句点出与 character_bible 一致的关键特征即可。"
            )
        # shot_cap 单镜 duration 上限（秒）；shot_lo/shot_hi 按文案字数或模板锁定
        shot_cap = min(duration_max, max_shot_duration)
        if shot_range_override:
            shot_lo, shot_hi = shot_range_override
        else:
            shot_lo, shot_hi = segplan.suggested_kepu_shot_range(source_text, pipeline_mode=pipeline_mode)
        shot_range = f"{shot_lo}-{shot_hi}"
        # name_rule 获客模板保留用户文案中的店名；其它模板改用泛称以免商标入画
        name_rule = storyboard_name_policy(allow_source_names)
        # segment_rules 科普逐段脚本生产约束（对齐漫剧 cue，无 @asset）
        segment_rules = (
            "【segments 生产规范】"
            "segments 必填；系统会落成 @duration +【字幕：后期叠旁白字幕】/【BGM：后期混音】/"
            "【旁白·自然语速·同步字幕】生产脚本，成片字幕与配乐由后期合成，不由视频模型烧录。"
            "因此 kind/text/duration 必须可直接消费。"
            "段序优先「画面→旁白」交替，首段尽量 kind=visual（保证首帧有料）；"
            "visual/action 的 text 必须含景别+主体动作+场景/界面类型，禁止空镜与模糊氛围词堆砌；"
            "narration 的 text 为一句一事、可朗读口播，按约 5 字/秒估 duration（语速自然偏快）；"
            "旁白 duration 严格跟字数，最多多 1 秒呼吸，禁止把短句拉满到镜长上限或拖腔注水；"
            "单段 duration 3-12 秒，镜内各段之和约等于本镜 duration，且不超过 "
            f"{shot_cap} 秒。"
            f"{name_rule}"
            "character_bible 与 bgm_lock 全片唯一，各镜不得改人设或漂移 BGM 氛围。"
        )
        if pipeline_mode == "image_text":
            diversity_note = (
                f"拆成 {shot_range} 个分镜，每镜一个独立视觉场景；"
                + (
                    "画风气质可统一，但界面/场景构图必须明显不同。"
                    if mode != "character"
                    else "但画风与人物必须一致。"
                )
            )
            ratio = (output_ratio or "16:9").strip() or "16:9"
            orient = "竖屏" if ratio == "9:16" else ("方形" if ratio == "1:1" else "横屏")
            system = (
                f"你是{orient}图文短视频编剧。输出语言由原始素材决定。"
                f"{consistency}{llm_system_addon}"
                f"每镜 duration 在 {duration_min}-{shot_cap} 秒。"
                "这是「静图+叠字+配音」模式：不生成 AI 视频，但需要旁白配音；"
                "画面禁止出现任何文字/水印/字幕。"
                "shots 字段说明："
                "shot(序号)、duration(秒)、"
                "title(对本镜内容的概括短标题，2-8字，语义完整有力；"
                "必须是总结提炼，禁止从 text 截取前几个字，禁止截断专有名词如 ERP→ER)、"
                "subtitle(对本镜卖点/要点的一句概括，8-22字，同样禁止原文截取前缀)、"
                "text(旁白台词，口语化，约匹配该镜时长，可供 TTS 朗读，一般 20-60 字)、"
                "segments(数组，精确到每一段：每项含 duration 秒、kind=visual|narration、text；"
                "visual 写景别与画面动作，narration 写口播)、"
                f"img_prompt({orient} {ratio} 构图画面提示词，留出边缘给文字叠层，主体居中，"
                f"禁止要求画面内写字；{name_rule})、"
                "video_prompt(可留空或写轻微推拉)、camera(如：缓慢推近/轻拉远)、bgm(情绪，全片尽量同一氛围)。"
                "另输出顶层 bgm_lock(全片统一 BGM 氛围一句)。"
                f"{segment_rules}"
                f"{diversity_note}"
            )
        else:
            diversity_note = (
                f"拆成 {shot_range} 个分镜，短镜快切，各镜场景随内容变化，禁止雷同空镜。"
                if mode != "character"
                else f"画风与人物必须全片一致；拆成 {shot_range} 镜，短镜快切。"
            )
            system = (
                "你是短视频分镜编剧。所有自然语言字段跟随原始素材语言"
                "（包括 title、text、img_prompt、video_prompt、camera、bgm、segments）。"
                f"{consistency}{llm_system_addon}"
                f"每镜 duration 在 {duration_min}-{shot_cap} 秒，不要为凑满上限而注水。"
                "shots 字段说明："
                "shot(序号)、duration(秒)、"
                "title(对本镜旁白的概括短标题，2-8字，语义完整；"
                "必须是总结提炼，禁止从 text 截取前缀，禁止截断专有名词如 ERP→ER)、"
                "subtitle(可选，一句要点概括 8-22字)、"
                "text(旁白台词，与 segments 中 narration 文案一致或为其摘要)、"
                "segments(必填数组，精确到每一段：每项 duration、kind=visual|narration|action、text)、"
                "img_prompt(与首段 visual 一致的首帧提示词，含具体景物与构图)、"
                "video_prompt(可与 segments 画面摘要一致)、"
                "camera(运镜，如：缓慢上摇/轻推/横移)、bgm(情绪，全片同一氛围)。"
                "顶层另输出 bgm_lock(全片统一 BGM 氛围一句，与各镜 bgm 一致)。"
                "img_prompt 与 video_prompt 跟随原始素材语言，专有名词可保留原文。"
                f"{segment_rules}"
                f"{diversity_note}"
            )
        system += storyboard_language_rule(source_text)
        user = (
            f"输入类型：{source_type}。请先理解内容与应用场景，再拆成精确到每一段的分镜"
            f"（{shot_range} 镜，短镜快切，禁止拖腔注水）：\n{source_text}"
        )
        json_format = {"type": "json_object"}
        try:
            content = await chat_completions(
                system,
                user,
                temperature=0.6,
                timeout=120.0,
                response_format=json_format,
            )
        except RuntimeError as exc:
            if "response_format" not in str(exc).lower():
                raise
            logger.warning("分镜 LLM 不支持 response_format，降级普通调用: %s", exc)
            content = await chat_completions(system, user, temperature=0.6, timeout=120.0)

        if not (content or "").strip():
            logger.warning("分镜 LLM 返回空内容，重试一次 source_type=%s", source_type)
            retry_user = (
                f"{user}\n\n"
                "【重要】请只输出一个完整 JSON 对象，顶层含 character_bible、bgm_lock、shots 数组；"
                "不要 markdown、不要代码围栏、字符串内不要未转义换行。"
            )
            try:
                content = await chat_completions(
                    system,
                    retry_user,
                    temperature=0.6,
                    timeout=120.0,
                    response_format=json_format,
                )
            except RuntimeError as exc:
                if "response_format" not in str(exc).lower():
                    raise
                content = await chat_completions(
                    system, retry_user, temperature=0.6, timeout=120.0
                )

        if not (content or "").strip():
            raise RuntimeError("分镜模型返回空内容，请检查文字模型渠道配置或稍后重试")

        return self._parse_storyboard(
            content,
            style_prefix,
            duration_min,
            duration_max,
            max_shot_duration,
            source_text=source_text,
        )

    async def gen_image(
        self,
        prompt: str,
        negative: str = "",
        ref_urls: list[str] | None = None,
        *,
        project_id: int | None = None,
        shot_no: int | None = None,
        size: str | None = None,
        model: str | None = None,
        aspect_ratio: str | None = None,
        style_ref_urls: list[str] | None = None,
    ) -> ImageResult:
        """调用 TokenFree 生图（Seedream 家族在网关侧重映射）。

        只软化用户正文并保留设定板前缀；InputTextSensitive 时仍用简化三视图重试，
        最后一档才缩成「三视图+服装风格」。不做空主体 / CG 厚涂兜底。
        """
        resolved = (model or "").strip()
        if not resolved or resolved in {"ark-seedream"} or resolved.startswith("kie-"):
            ark_model = None
        else:
            ark_model = resolved

        if self.mock:
            self._resolve_ark_route("image", ark_model)
            local = await asyncio.to_thread(self._write_mock_image, prompt, size)
            # _write_mock_image returns /static/...; publish to OSS when enabled
            path = storage.local_path_from_url(local)
            url = storage.publish_local(path) if path and path.exists() else local
            return ImageResult(local_url=url, remote_url=None)

        from app.services.seedream_text_soften import (
            compact_seedream_prompt_for_retry,
            soften_seedream_input_text,
            style_only_seedream_prompt_for_retry,
        )

        # 只软化用户正文，保留角色/场景/道具结构前缀（三视图等）
        original = (prompt or "").strip()
        current = soften_seedream_input_text(original)
        if current != original:
            logger.info(
                "Seedream input softened shot=%s before=%s after=%s",
                shot_no,
                len(original),
                len(current),
            )

        attempts = [current]
        for builder in (
            compact_seedream_prompt_for_retry,
            style_only_seedream_prompt_for_retry,
        ):
            candidate = builder(current)
            if candidate and candidate not in attempts:
                attempts.append(candidate)

        last_err: Exception | None = None
        labels = ("softened", "compact", "style_only")
        for idx, candidate in enumerate(attempts):
            full_prompt = f"{candidate}。避免：{negative}" if negative else candidate
            try:
                return await self._seedream_once(
                    full_prompt,
                    ref_urls,
                    project_id=project_id,
                    shot_no=shot_no,
                    size=size,
                    model=ark_model,
                    aspect_ratio=aspect_ratio,
                    style_ref_urls=style_ref_urls,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                msg = str(exc)
                # 仅文本审核可走压缩/风格重试；其它策略/错误直接失败
                if not self._is_seedream_input_text_sensitive(msg):
                    if self._is_seedream_policy_error(msg):
                        logger.warning(
                            "Seedream policy hit shot=%s; failing without fallback",
                            shot_no,
                        )
                    raise
                if idx + 1 < len(attempts):
                    nxt = labels[idx + 1] if idx + 1 < len(labels) else "next"
                    logger.warning(
                        "Seedream InputTextSensitive shot=%s; retrying %s prompt",
                        shot_no,
                        nxt,
                    )
                    continue
                logger.warning(
                    "Seedream InputTextSensitive shot=%s; retries exhausted",
                    shot_no,
                )
                raise
        raise RuntimeError(str(last_err) if last_err else "Seedream failed")

    async def _seedream_once(
        self,
        full_prompt: str,
        ref_urls: list[str] | None,
        *,
        project_id: int | None,
        shot_no: int | None,
        size: str | None,
        model: str | None = None,
        aspect_ratio: str | None = None,
        style_ref_urls: list[str] | None = None,
    ) -> ImageResult:
        """单次 Seedream 请求并落盘（文件名含 uuid，避免重生成覆盖）。"""
        strategy, normalized, pinned_route = execution_params("image", {
            "prompt": full_prompt, "size": size or self.settings.ark_image_size,
            "aspect_ratio": aspect_ratio or "auto", "ref_urls": ref_urls or [],
            "style_ref_urls": style_ref_urls or [],
        }, shot_no=shot_no, model=model)
        route = pinned_route or self._resolve_ark_route("image", model)
        upstream_model = route.upstream_model if route else strategy.model_id
        request = strategy.build_provider_request(normalized, {"upstream_model": upstream_model})
        resolved_size = request["size"]
        subject_refs, style_refs = request["ref_urls"], request["style_ref_urls"]
        chosen = upstream_model
        aspect_ratio = normalized["aspect_ratio"]
        from app.services.tokenfree_image import (
            build_tokenfree_openai_image_body,
            is_gpt_image_25,
        )

        # 2.5 的渠道是 image-generation，走 /responses 会报 default 分组无 distributor
        if is_gpt_image_25(chosen):
            path = "/images/generations"
            body = build_tokenfree_openai_image_body(
                model=chosen,
                prompt=full_prompt,
                size=str(resolved_size or ""),
                aspect_ratio=str(aspect_ratio or ""),
                ref_urls=subject_refs,
                style_ref_urls=style_refs,
            )
            body["resolution"] = normalized["resolution"]
        else:
            path = "/responses"
            body = build_tokenfree_image_body(
                model=chosen,
                prompt=full_prompt,
                size=str(resolved_size or ""),
                aspect_ratio=str(aspect_ratio or ""),
                ref_urls=subject_refs,
                style_ref_urls=style_refs,
                structured_refs=True,
            )

        try:
            async with httpx.AsyncClient(timeout=_upstream_timeout(IMAGE_GEN_READ_SEC)) as client:
                async def _post():
                    # 单次上游 POST，限流重试由外层包住
                    return await self._request_media(client, "POST",
                        self._route_url(path, route),
                        headers=self._route_headers(route),
                        json=body,
                    )

                async with tokenfree_image_slot():
                    resp = await post_until_not_rate_limited(_post)
                # 限流/4xx 走 HTTP 文案；200 + status=failed 留给 raise_tokenfree_image_if_failed
                if resp.status_code >= 400 or is_tokenfree_rate_limit(
                    status_code=resp.status_code, body=resp.text
                ):
                    _raise_seedream_http_error(
                        resp.status_code,
                        resp.text,
                        model=chosen,
                        tokenfree=True,
                    )
                data = resp.json()
        except httpx.TimeoutException as exc:
            reraise_upstream_timeout(exc, kind="生图", read_sec=IMAGE_GEN_READ_SEC)

        if getattr(self.settings, "local_media_mock", False) and not _force_real_image.get():
            return ImageResult(local_url=local_media_mock.media_url("default.jpg"), raw_usage={"simulated": True}, upstream_cost_fen=0)

        raise_tokenfree_image_if_failed(data)

        usage_parsed = parse_usage_dict(data)
        raw_usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        if not raw_usage and isinstance(data.get("data"), list) and data["data"]:
            first = data["data"][0]
            if isinstance(first, dict) and isinstance(first.get("usage"), dict):
                raw_usage = first["usage"]
                usage_parsed = parse_usage_dict({"usage": raw_usage})
        upstream_cost_fen = parse_upstream_cost_fen(data)
        if upstream_cost_fen is None and raw_usage:
            upstream_cost_fen = parse_upstream_cost_fen({"usage": raw_usage})

        remote = extract_tokenfree_image_url(data)
        if not remote:
            remote = self._extract_image_url(data) or extract_tokenfree_image_url(data)
        if not remote:
            logger.warning("出图响应无图片地址: %s", json.dumps(data, ensure_ascii=False)[:500])
            raise RuntimeError("出图未返回图片地址，请稍后重试")

        dest_dir = storage.project_dir(project_id or 0)
        name = f"shot_{(shot_no or 0):03d}_{uuid.uuid4().hex[:12]}.png"
        dest = dest_dir / name
        dl_headers = None
        if is_tokenfree_image_url(remote) or is_tokenfree_content_url(remote):
            dl_headers = self._route_headers(route)
        await storage.download_to(remote, dest, headers=dl_headers)
        merged_usage = dict(raw_usage or {})
        if resolved_size:
            merged_usage.setdefault("size", str(resolved_size))
        return ImageResult(
            local_url=storage.publish_local(dest, sync=True),
            remote_url=remote,
            total_tokens=int(usage_parsed.get("total_tokens") or 0),
            prompt_tokens=int(usage_parsed.get("prompt_tokens") or 0),
            completion_tokens=int(usage_parsed.get("completion_tokens") or 0),
            raw_usage=stamp_usage(merged_usage, delivery=str(dest)),
            upstream_cost_fen=upstream_cost_fen,
        )

    @staticmethod
    def _is_seedream_input_text_sensitive(msg: str) -> bool:
        """Seedream 输入文案审核拦截（可压缩提示词重试）。"""
        text = msg or ""
        return (
            "InputTextSensitive" in text
            or "InputTextSensitiveContentDetected" in text
            or "生图文案未通过内容审核" in text
        )

    @staticmethod
    def _is_seedream_input_privacy_error(msg: str) -> bool:
        """参考图 / 输入侧真人隐私拦截（改文案无效）。"""
        text = msg or ""
        return any(
            k in text
            for k in ("PrivacyInformation", "InputImageSensitive")
        )

    @staticmethod
    def _is_seedream_policy_error(msg: str) -> bool:
        """文案或输出内容策略拦截（生图侧直接失败，不做提示词兜底）。"""
        text = msg or ""
        if ArkGateway._is_seedream_input_privacy_error(text):
            return False
        if ArkGateway._is_seedream_input_text_sensitive(text):
            return True
        return (
            "PolicyViolation" in text
            or "SensitiveContent" in text
            or "OutputImageSensitive" in text
        )

    @staticmethod
    def _is_seedance_input_privacy_error(msg: str) -> bool:
        """Seedance 参考图真人隐私拦截（改视频文案无效）。"""
        text = msg or ""
        return any(
            k in text
            for k in (
                "PrivacyInformation",
                "InputImageSensitive",
                "参考图疑似真人",
                "may contain real person",
            )
        )

    @staticmethod
    def _is_seedance_text_policy_error(msg: str) -> bool:
        """Seedance 文案/策略拦截（可追加 CG 风格重试一次）。"""
        text = msg or ""
        if ArkGateway._is_seedance_input_privacy_error(text):
            return False
        lowered = text.lower()
        if "分镜文案未通过内容审核" in text:
            return True
        return any(
            k in lowered
            for k in (
                "inputtextsensitive",
                "text sensitive",
                "policyviolation",
                "outputimagesensitive",
                "sensitivecontentdetected",
                "sensitivecontent",
            )
        )

    @staticmethod
    def _with_seedream_cg_style(prompt: str) -> str:
        """在提示词末尾追加 CG 厚涂风格（已含则原样返回）。"""
        base = (prompt or "").strip()
        if not base:
            return _SEEDREAM_CG_STYLE
        if _SEEDREAM_CG_STYLE in base:
            return base
        return f"{base}。{_SEEDREAM_CG_STYLE}"

    @staticmethod
    def _with_seedance_cg_style(prompt: str) -> str:
        """视频提示词追加 CG 厚涂（与 Seedream 同款文案）。"""
        return ArkGateway._with_seedream_cg_style(prompt)

    @staticmethod
    def _seedance_content_with_cg_style(
        content: list[Any] | None,
    ) -> list[dict[str, Any]] | None:
        """给 content[] 内全部 text 项追加 CG；无变化则返回 None。"""
        if not isinstance(content, list):
            return None
        changed = False
        out: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                out.append(item)
                continue
            if item.get("type") != "text":
                out.append(dict(item))
                continue
            text = str(item.get("text") or "")
            cg = ArkGateway._with_seedance_cg_style(text)
            if cg != text:
                changed = True
                out.append({**item, "text": cg})
            else:
                out.append(dict(item))
        return out if changed else None

    @staticmethod
    def _sanitize_seedream_prompt(prompt: str) -> str:
        """品牌/IP 软化（科普分镜等调用方可选使用；生图主路径不做兜底改写）。"""
        out = prompt or ""
        for pat, repl in _SEEDREAM_SANITIZE:
            out = pat.sub(repl, out)
        return out

    def _extract_image_url(self, data: dict[str, Any]) -> str | None:
        if "data" in data and data["data"]:
            item = data["data"][0]
            return item.get("url") or item.get("b64_json")
        if "url" in data:
            return data["url"]
        return None

    @staticmethod
    def _seedance_prompt_text(prompt: str) -> str:
        """Seedance 2.0 may require JSON text with summary_caption (BodyFormat)."""
        clean = (prompt or "").strip() or "画面轻微动态，保持主体外形稳定"
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean.startswith("{"):
            try:
                obj = json.loads(clean)
                if isinstance(obj, dict):
                    if not str(obj.get("summary_caption") or "").strip():
                        obj["summary_caption"] = str(
                            obj.get("prompt") or obj.get("text") or clean
                        )[:500]
                    return json.dumps(obj, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        return json.dumps({"summary_caption": clean[:500]}, ensure_ascii=False)

    @staticmethod
    def _seedance_duration(duration: int | float, *, model: str | None = None) -> int:
        """按模型钳时长；无模型时退回站点 Seedance 4–30。"""
        from app.services.seedance_resolutions import clamp_video_duration

        mid = (model or "").strip()
        if mid:
            return clamp_video_duration(mid, duration)
        s = get_settings()
        lo = int(getattr(s, "seedance_duration_min", 4) or 4)
        hi = int(getattr(s, "seedance_duration_max", 30) or 30)
        return int(max(lo, min(int(round(float(duration))), hi)))

    async def gen_video_i2v(
        self,
        image_url: str,
        prompt: str,
        duration: int,
        *,
        character_consistency: bool = True,
        resolution: str = "480p",
        ratio: str | None = None,
        prompt_as_json: bool = False,
        return_last_frame: bool = True,
        generate_audio: bool = False,
        extra_image_urls: list[str] | None = None,
        model: str | None = None,
    ) -> str:
        strategy, normalized, pinned_route = execution_params("video", {
            "duration": duration, "resolution": resolution, "aspect_ratio": ratio or "9:16",
            "generate_audio": generate_audio,
            "reference_images": [image_url, *(extra_image_urls or [])],
        }, model=model)
        duration, resolution, ratio = normalized["duration"], normalized["resolution"], normalized["aspect_ratio"]
        from app.services.media_models.runtime import existing_provider_task
        existing = await existing_provider_task()
        if existing:
            return existing
        if self.mock:
            digest = hashlib.md5(f"{image_url}:{prompt}".encode()).hexdigest()[:10]
            return f"mock-task-{digest}"

        # Seedance 拒绝对角外宽高比（实测 2.5006→报 2.50）；提交前垫黑边钳到安全区间
        from app.services.seedance_image_aspect import ensure_seedance_compatible_image_url

        safe_image_url = await ensure_seedance_compatible_image_url(image_url)
        # Seedance needs a publicly reachable https image (data URI often rejected / odd errors)
        image_ref = await self._resolve_image_ref(safe_image_url, prefer_https=True)
        route = pinned_route or self._resolve_ark_route("video", model or strategy.model_id)
        from app.services.tokenfree_pricing import canonicalize_channel_model_id

        video_model = canonicalize_channel_model_id(
            route.upstream_model if route else self.settings.model_video
        )
        # Plain text is the default. Legacy JSON captions are opt-in for Seedance 2.0 only.
        legacy_caption_model = "seedance" in video_model.lower() and bool(re.search(r"2[._-]0(?:[._-]|$)", video_model.lower()))
        prompt_as_json = prompt_as_json and legacy_caption_model
        plain = (prompt or "").strip() or "画面轻微动态，保持主体外形稳定"
        text = plain if not prompt_as_json else self._seedance_prompt_text(prompt)
        # If prompt looks like manju-style script, always send plain text
        if "@duration:" in plain or "00:" in plain or plain.startswith("【"):
            text = plain
            prompt_as_json = False
        # 有目标画幅时用 reference_image + ratio（可强制 9:16）。
        # 纯 first_frame 禁止传 ratio，且实测即使静帧竖屏也可能吐横屏。
        image_role, target_ratio = resolve_seedance_i2v_image_role(ratio)
        extra_refs: list[str] = []
        for raw in extra_image_urls or []:
            text_url = str(raw or "").strip()
            if not text_url:
                continue
            try:
                safe_extra = await ensure_seedance_compatible_image_url(text_url)
                extra_refs.append(await self._resolve_image_ref(safe_extra, prefer_https=True))
            except Exception as exc:
                raise ValueError("reference_images: 参考图无法处理，请修正后重新提交") from exc
        if extra_refs:
            # 多图只能走 reference_image，不能与 first_frame 混用
            image_role = "reference_image"
            if not target_ratio:
                target_ratio = (ratio or "").strip() or "16:9"
        content: list[dict[str, Any]] = [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": image_ref},
                "role": image_role,
            },
        ]
        for extra in extra_refs:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": extra},
                    "role": "reference_image",
                }
            )
        body: dict[str, Any] = {
            "model": video_model,
            "content": content,
            "duration": duration,
            "resolution": resolution,
            "watermark": False,
            "generate_audio": bool(generate_audio),
            "return_last_frame": bool(return_last_frame),
        }
        if target_ratio:
            body["ratio"] = target_ratio
        # Do not send character_consistency — unknown fields have caused BodyFormat failures
        logger.info(
            "Seedance i2v create model=%s duration=%s resolution=%s ratio=%s role=%s generate_audio=%s",
            body["model"],
            body["duration"],
            resolution,
            body.get("ratio") or "(omit)",
            image_role,
            body["generate_audio"],
        )

        try:
            async with httpx.AsyncClient(timeout=_upstream_timeout(VIDEO_CREATE_READ_SEC)) as client:
                resp = await post_video_create(client, "POST",
                    self._route_url("/contents/generations/tasks", route), request_call=self._request_media,
                    headers=self._route_headers(route),
                    json=self._video_json(body, route),
                )
                # 枚举兼容已在提交层尝试一次，不能继续走文案/画幅回退重复发送。
                if resp.status_code == 400 and '"plugin_usage_invalid"' in resp.text:
                    raise RuntimeError(_format_seedance_create_error(resp.status_code, resp.text))
                if resp.status_code >= 400 and prompt_as_json:
                    # Fallback: plain text prompt
                    body["content"][0]["text"] = plain
                    resp = await post_video_create(client, "POST",
                        self._route_url("/contents/generations/tasks", route), request_call=self._request_media,
                        headers=self._route_headers(route),
                        json=self._video_json(body, route),
                    )
                # 文案策略：在 ratio/adaptive 结构回退前，对当前意图 body 追加 CG 重试
                if resp.status_code >= 400:
                    raw_err = resp.text or ""
                    if self._is_seedance_input_privacy_error(raw_err):
                        raise RuntimeError(_format_seedance_create_error(resp.status_code, raw_err))
                    if self._is_seedance_text_policy_error(raw_err):
                        cg_content = self._seedance_content_with_cg_style(body.get("content"))
                        if cg_content is not None:
                            logger.warning("Seedance i2v text policy hit; retrying with CG style")
                            body = {**body, "content": cg_content}
                            resp = await post_video_create(client, "POST",
                                self._route_url("/contents/generations/tasks", route), request_call=self._request_media,
                                headers=self._route_headers(route),
                                json=self._video_json(body, route),
                            )
                        if resp.status_code >= 400:
                            raise RuntimeError(
                                _format_seedance_create_error(resp.status_code, resp.text)
                            )
                if resp.status_code >= 400:
                    err_text = resp.text or ""
                    # 仅「误用 first_frame + ratio」时去掉 ratio；有目标画幅时不得回落到 adaptive 横屏
                    if (
                        not target_ratio
                        and "ratio" in err_text.lower()
                        and "ratio" in body
                    ):
                        body.pop("ratio", None)
                        resp = await post_video_create(client, "POST",
                            self._route_url("/contents/generations/tasks", route), request_call=self._request_media,
                            headers=self._route_headers(route),
                            json=self._video_json(body, route),
                        )
                if resp.status_code >= 400 and not target_ratio:
                    # 无目标画幅时的兼容回退；有竖屏目标时禁止 adaptive，避免再次出横屏
                    body["content"][1].pop("role", None)
                    body["ratio"] = "adaptive"
                    resp = await post_video_create(client, "POST",
                        self._route_url("/contents/generations/tasks", route), request_call=self._request_media,
                        headers=self._route_headers(route),
                        json=self._video_json(body, route),
                    )
                if resp.status_code >= 400:
                    raise RuntimeError(_format_seedance_create_error(resp.status_code, resp.text))
                data = resp.json()
        except httpx.TimeoutException as exc:
            reraise_upstream_timeout(exc, kind="生视频", read_sec=VIDEO_CREATE_READ_SEC)

        task_id = extract_video_task_id(data)
        if not task_id:
            raise RuntimeError(f"Seedance missing task id: {data}")
        return task_id

    async def _resolve_media_ref(self, media_url: str, *, prefer_https: bool = False) -> str:
        """解析图片/音频 URL 供 Seedance 拉取。"""
        return await self._resolve_image_ref(media_url, prefer_https=prefer_https)

    async def _resolve_seedance_content_items(
        self,
        items: list[dict[str, Any]],
        *,
        project_id: int = 0,
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for item in items:
            copy = dict(item)
            if item.get("type") == "image_url":
                raw_url = (item.get("image_url") or {}).get("url") or ""
                from app.services.seedance_image_aspect import ensure_seedance_compatible_image_url

                safe_url = await ensure_seedance_compatible_image_url(str(raw_url))
                copy["image_url"] = {
                    "url": await self._resolve_media_ref(safe_url, prefer_https=True)
                }
            elif item.get("type") in {"audio_url", "video_url"}:
                media_key = item["type"]
                raw_url = (item.get(media_key) or {}).get("url") or ""
                copy[media_key] = {
                    "url": await self._resolve_media_ref(str(raw_url), prefer_https=True)
                }
            resolved.append(copy)
        return resolved

    async def gen_video_seedance_body(
        self,
        body: dict[str, Any],
        *,
        project_id: int = 0,
        content_labels: list[str] | None = None,
    ) -> str:
        """提交 Seedance 多模态请求体（参考图 + reference_audio）。

        文案/策略拦截时追加 CG 厚涂提示词重试一次；参考图真人隐私拦截不重试。
        """
        strategy, normalized, pinned_route = execution_params("video", {
            **{key: body[key] for key in ("duration", "resolution", "generate_audio", "watermark", "return_last_frame", "content") if key in body},
            "aspect_ratio": body.get("ratio") or "9:16",
        }, model=str(body.get("model") or ""))
        route = pinned_route or self._resolve_ark_route("video", str(body.get("model") or ""))
        body = {**body, **strategy.build_provider_request(normalized, {"upstream_model": route.upstream_model if route else strategy.model_id})}
        from app.services.media_models.runtime import existing_provider_task
        existing = await existing_provider_task()
        if existing:
            return existing
        if self.mock:
            digest = hashlib.md5(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[
                :10
            ]
            return f"mock-task-{digest}"

        payload = dict(body)
        content = payload.get("content")
        if isinstance(content, list):
            payload["content"] = await self._resolve_seedance_content_items(
                content,
                project_id=project_id,
            )
        # 提交上游前硬校验 reference_audio 时长，避免 InvalidParameter 才暴露
        from app.services.drama.voice_reference_audio import (
            validate_seedance_body_reference_audios,
        )

        await validate_seedance_body_reference_audios(
            payload,
            content_labels=content_labels,
            project_id=project_id,
        )

        logger.info(
            "Seedance multimodal create model=%s duration=%s items=%s",
            payload.get("model"),
            payload.get("duration"),
            len(payload.get("content") or []),
        )

        try:
            async with httpx.AsyncClient(timeout=_upstream_timeout(VIDEO_CREATE_READ_SEC)) as client:
                resp = await post_video_create(client, "POST",
                    self._route_url("/contents/generations/tasks", route), request_call=self._request_media,
                    headers=self._route_headers(route),
                    json=self._video_json(payload, route),
                )
                if resp.status_code >= 400:
                    raw_err = resp.text or ""
                    # 参考图真人：改文案无效
                    if self._is_seedance_input_privacy_error(raw_err):
                        raise RuntimeError(
                            _format_seedance_create_error(
                                resp.status_code,
                                raw_err,
                                content_labels=content_labels,
                            )
                        )
                    cg_content = None
                    if self._is_seedance_text_policy_error(raw_err):
                        cg_content = self._seedance_content_with_cg_style(payload.get("content"))
                    if cg_content is not None:
                        logger.warning(
                            "Seedance text policy hit project=%s; retrying with CG style",
                            project_id,
                        )
                        payload = {**payload, "content": cg_content}
                        resp = await post_video_create(client, "POST",
                            self._route_url("/contents/generations/tasks", route), request_call=self._request_media,
                            headers=self._route_headers(route),
                            json=self._video_json(payload, route),
                        )
                    if resp.status_code >= 400:
                        raise RuntimeError(
                            _format_seedance_create_error(
                                resp.status_code,
                                resp.text,
                                content_labels=content_labels,
                            )
                        )
                data = resp.json()
        except httpx.TimeoutException as exc:
            reraise_upstream_timeout(exc, kind="生视频", read_sec=VIDEO_CREATE_READ_SEC)

        task_id = extract_video_task_id(data)
        if not task_id:
            raise RuntimeError(f"Seedance missing task id: {data}")
        return task_id

    async def gen_and_wait_seedance_body(
        self,
        body: dict[str, Any],
        *,
        project_id: int,
        shot_no: int,
        max_attempts: int = 2,
        content_labels: list[str] | None = None,
        on_task_created: Any | None = None,
    ) -> tuple[str, str | None, TaskResult]:
        """Submit once; retries only fetch/download the original provider task."""
        task_id = await self.gen_video_seedance_body(body, project_id=project_id, content_labels=content_labels)
        if on_task_created is not None:
            try:
                await on_task_created(task_id)
            except Exception as exc:
                from app.services.storage import RetryableMediaDownloadError
                raise RetryableMediaDownloadError(
                    f"记录上游任务号失败: {exc}", provider_task_id=task_id, counts_attempt=False,
                ) from exc
        try:
            return await self.wait_video_assets(task_id, project_id=project_id, shot_no=shot_no)
        except Exception as exc:
            from app.services.storage import RetryableMediaDownloadError, is_retryable_download_error
            if isinstance(exc, RetryableMediaDownloadError):
                if not exc.provider_task_id:
                    exc.provider_task_id = task_id
                raise
            if is_retryable_download_error(exc):
                raise RetryableMediaDownloadError(str(exc), provider_task_id=task_id) from exc
            raise

    async def poll_task(self, task_id: str) -> TaskResult:
        if getattr(self.settings, "local_media_mock", False) or task_id.startswith(local_media_mock.VIDEO_PREFIX):
            return self._local_media_result(task_id)
        if self.mock or task_id.startswith("mock-task-"):
            return TaskResult(
                status="succeeded",
                url=f"/static/mock/video_{task_id[-8:]}.mp4",
                last_frame_url=f"/static/mock/last_{task_id[-8:]}.jpg",
            )

        deadline = time.monotonic() + self.settings.ark_video_poll_timeout
        async with httpx.AsyncClient(timeout=_upstream_timeout(VIDEO_POLL_READ_SEC, connect=15.0)) as client:
            while time.monotonic() < deadline:
                try:
                    resp = await observed_request(client, "GET",
                        self._route_url(f"/contents/generations/tasks/{task_id}", self._poll_route()),
                        headers=self._route_headers(self._poll_route()),
                    )
                except httpx.HTTPError as exc:
                    # 单次网络抖动：退避后继续轮询，由 deadline 收敛，不直接判失败
                    logger.warning(
                        "Seedance poll network error task=%s: %s; backing off", task_id, exc
                    )
                    await asyncio.sleep(float(self.settings.ark_video_poll_interval))
                    continue
                if resp.status_code >= 400:
                    # 429/5xx 是上游瞬时故障，任务状态未知，按轮询间隔退避继续，
                    # 由 deadline 总超时收敛；400/401/403/404 等才是确定终态。
                    if _is_transient_http_status(resp.status_code):
                        logger.warning(
                            "Seedance poll transient HTTP %s task=%s; backing off",
                            resp.status_code,
                            task_id,
                        )
                        await asyncio.sleep(
                            _retry_after_seconds(
                                resp, float(self.settings.ark_video_poll_interval)
                            )
                        )
                        continue
                    return TaskResult(status="failed", error=resp.text[:500])
                data = resp.json()
                result = self._finalize_video_result(_build_task_result_from_payload(data), task_id)
                if result.status == "succeeded":
                    # TokenFree 偶发先回成功、usage/quota 稍后才到；短等补齐避免按估算低扣
                    if int(result.total_tokens or 0) <= 0 and not result.upstream_cost_fen:
                        for _ in range(3):
                            await asyncio.sleep(1.5)
                            try:
                                refreshed = await self.fetch_task_once(task_id)
                            except Exception:  # noqa: BLE001
                                break
                            if refreshed.status == "failed":
                                return refreshed
                            if int(refreshed.total_tokens or 0) > 0 or refreshed.upstream_cost_fen:
                                return refreshed
                    return result
                if result.status == "failed":
                    return result
                await asyncio.sleep(self.settings.ark_video_poll_interval)
        return TaskResult(status="failed", error="poll timeout", provider_task_id=task_id)

    async def fetch_task_once(self, task_id: str) -> TaskResult:
        """单次查询 Seedance 任务，不阻塞等待。"""
        if getattr(self.settings, "local_media_mock", False) or task_id.startswith(local_media_mock.VIDEO_PREFIX):
            return self._local_media_result(task_id)
        if self.mock or task_id.startswith("mock-task-"):
            return TaskResult(
                status="succeeded",
                url=f"/static/mock/video_{task_id[-8:]}.mp4",
                last_frame_url=f"/static/mock/last_{task_id[-8:]}.jpg",
            )
        try:
            async with httpx.AsyncClient(timeout=_upstream_timeout(VIDEO_FETCH_READ_SEC, connect=15.0)) as client:
                resp = await observed_request(client, "GET",
                    self._route_url(f"/contents/generations/tasks/{task_id}", self._poll_route()),
                    headers=self._route_headers(self._poll_route()),
                )
        except httpx.HTTPError as exc:
            # 网络抖动对 poller 是下轮重试、对同步端点是继续转圈，均优于 500/误判失败
            logger.warning("Seedance fetch network error task=%s: %s", task_id, exc)
            return TaskResult(status="running", provider_task_id=task_id)
        if resp.status_code >= 400:
            if _is_transient_http_status(resp.status_code):
                logger.warning(
                    "Seedance fetch transient HTTP %s task=%s; treat as running",
                    resp.status_code,
                    task_id,
                )
                return TaskResult(status="running", provider_task_id=task_id)
            return TaskResult(status="failed", error=resp.text[:500], provider_task_id=task_id)
        return self._finalize_video_result(_build_task_result_from_payload(resp.json()), task_id)

    def _local_media_result(self, task_id: str) -> TaskResult:
        return TaskResult(status="succeeded", url=local_media_mock.media_url("default.mp4"),
                          last_frame_url=local_media_mock.media_url("default.jpg"),
                          provider_task_id=task_id, raw_usage={"simulated": True}, upstream_cost_fen=0)

    async def save_video_assets_from_result(
        self,
        result: TaskResult,
        *,
        project_id: int,
        shot_no: int,
    ) -> tuple[str, str | None]:
        """将单次 poll 成功结果落盘为本地视频与可选尾帧。"""
        if result.status != "succeeded" or not result.url:
            raise RuntimeError(result.error or "video generation failed")

        if result.url.startswith("/static/"):
            video_local = result.url
        else:
            # 每次生成独立文件名，避免覆盖旧成片导致历史版本失效
            stamp = int(time.time())
            dest = storage.project_dir(project_id) / f"shot_{shot_no:03d}_{stamp}.mp4"
            await self.download_result_media(result.url, dest)
            video_local = storage.publish_local(dest)

        last_local: str | None = None
        if result.last_frame_url:
            try:
                if result.last_frame_url.startswith("/static/"):
                    last_local = result.last_frame_url
                else:
                    stamp = int(time.time())
                    frame_dest = (
                        storage.project_dir(project_id)
                        / f"shot_{shot_no:03d}_{stamp}_last.jpg"
                    )
                    await self.download_result_media(result.last_frame_url, frame_dest)
                    last_local = storage.publish_local(frame_dest)
            except Exception:  # noqa: BLE001
                logger.warning("failed to save last frame project=%s shot=%s", project_id, shot_no)
        return video_local, last_local

    async def wait_video_assets(
        self,
        task_id: str,
        *,
        project_id: int,
        shot_no: int,
    ) -> tuple[str, str | None, TaskResult]:
        """等待任务完成并落盘视频；若有尾帧则一并落盘。"""
        result = await self.poll_task(task_id)
        video_local, last_local = await self.save_video_assets_from_result(
            result,
            project_id=project_id,
            shot_no=shot_no,
        )
        return video_local, last_local, result

    async def wait_video(
        self,
        task_id: str,
        *,
        project_id: int,
        shot_no: int,
    ) -> tuple[str, TaskResult]:
        """等待成片并优先把已落盘尾帧写回 result，供下一镜参考。"""
        video_local, last_local, result = await self.wait_video_assets(
            task_id, project_id=project_id, shot_no=shot_no
        )
        if last_local:
            result.last_frame_url = last_local
        return video_local, result

    async def gen_and_wait_video(
        self,
        image_url: str,
        prompt: str,
        duration: int,
        *,
        project_id: int,
        shot_no: int,
        character_consistency: bool = True,
        resolution: str = "480p",
        ratio: str | None = None,
        max_attempts: int = 3,
        generate_audio: bool = False,
        model: str | None = None,
        extra_image_urls: list[str] | None = None,
    ) -> tuple[str, TaskResult]:
        """Create i2v task and wait；开源版只走 TokenFree（不直连 Kie / 火山）。"""
        if current_snapshot.get():
            current_operation.set(operation_for("video", shot_no=shot_no, model=model))
        last_err: Exception | None = None
        use_json = False
        for attempt in range(max_attempts):
            try:
                task_id = await self.gen_video_i2v(
                    image_url,
                    prompt,
                    duration,
                    character_consistency=character_consistency,
                    resolution=resolution,
                    ratio=ratio,
                    prompt_as_json=use_json,
                    generate_audio=generate_audio,
                    extra_image_urls=extra_image_urls,
                    model=model,
                )
                return await self.wait_video(
                    task_id,
                    project_id=project_id,
                    shot_no=shot_no,
                )
            except Exception:
                raise
        raise RuntimeError("视频生成失败")

    def _resolved_audio_model(self) -> str:
        routed = (resolve_upstream_model("audio", None) or "").strip()
        mid = routed or (self.settings.model_audio or "").strip() or TOKENFREE_DEFAULT_TTS_MODEL
        return resolve_tokenfree_tts_model(mid)

    async def _tts_openai_speech(
        self,
        text: str,
        voice: str,
        dest: Path,
        *,
        model: str | None = None,
    ) -> bool:
        """TokenFree 上 Qwen-TTS 的 /audio/speech 未实现，改走 Omni/Gemini chat。"""
        requested = (model or self._resolved_audio_model()).strip()
        route = self._resolve_ark_route("audio", requested)
        base = (route.base_url if route else self.settings.ark_base_url or "").rstrip("/")
        key = (route.api_key if route else self.settings.ark_api_key or "").strip()
        if not base or (not key and not getattr(self.settings, "local_media_mock", False)):
            return False
        model_id = tokenfree_tts_chat_model(
            resolve_tokenfree_tts_model(route.upstream_model if route else requested)
        )
        voice = tokenfree_speech_voice(voice, model_id)
        if tokenfree_tts_uses_chat_audio(model_id):
            return await self._tts_openai_chat_audio(text, voice, dest, model=model_id)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await self._request_media(client, "POST",
                f"{base}/audio/speech",
                headers=self._route_headers(route),
                json={
                    "model": model_id,
                    "input": text,
                    "voice": voice,
                    "response_format": "mp3",
                },
            )
        if resp.status_code < 400 and resp.content and len(resp.content) >= 1000:
            dest.write_bytes(resp.content)
            return True
        if resp.status_code >= 400:
            logger.warning(
                "OpenAI speech HTTP %s model=%s: %s",
                resp.status_code,
                model_id,
                (resp.text or "")[:300],
            )
        return False

    async def _tts_openai_chat_audio(
        self,
        text: str,
        voice: str,
        dest: Path,
        *,
        model: str,
    ) -> bool:
        """Gemini 非流式 chat 出音频；Qwen-Omni 必须 SSE 流式。"""
        route = self._resolve_ark_route("audio", model)
        model = tokenfree_tts_chat_model(resolve_tokenfree_tts_model(route.upstream_model if route else model))
        base = (route.base_url if route else self.settings.ark_base_url or "").rstrip("/")
        if not base:
            return False
        omni = tokenfree_tts_uses_omni_stream(model)
        body = (
            build_omni_tts_chat_body(text, voice, model)
            if omni
            else {
                "model": model,
                "messages": [{"role": "user", "content": text}],
                "modalities": ["audio"],
                "audio": {"voice": voice, "format": "mp3"},
            }
        )
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await self._request_media(client, "POST", f"{base}/chat/completions", headers=self._route_headers(route), json=body)
        if resp.status_code >= 400:
            logger.warning(
                "OpenAI chat-audio HTTP %s model=%s: %s",
                resp.status_code,
                model,
                (resp.text or "")[:300],
            )
            return False
        if getattr(self.settings, "local_media_mock", False):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
        audio: bytes | None = extract_sse_audio_bytes(resp.text or "") if omni else None
        if not audio:
            try:
                payload = resp.json()
            except Exception:  # noqa: BLE001
                payload = None
            if isinstance(payload, dict):
                audio = extract_chat_audio_bytes(payload)
        if not audio:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        wav = wrap_pcm_s16le_wav(audio)
        if not wav:
            return False
        return await asyncio.to_thread(self._persist_tts_mp3, dest, wav)

    async def tts(
        self,
        text: str,
        voice: str,
        *,
        project_id: int | None = None,
        shot_no: int | None = None,
        duration_hint: float = 4.0,
        result_metadata: dict | None = None,
    ) -> str:
        """整片/单镜配音：TokenFree 多 TTS → edge-tts；失败则抛错，不写静音。"""
        if result_metadata is not None:
            result_metadata.clear()
        audio_model = self._resolved_audio_model()
        voice_map = {
            "narrator_calm": "zh_female_cancan_uranus_bigtts",
            "warm_storyteller": "zh_female_tianmeixiaoyuan_uranus_bigtts",
            "teacher_clear": "zh_male_shaonianzixin_uranus_bigtts",
            "urban_editorial": "zh_female_shuangkuaisisi_uranus_bigtts",
            "retro_host": "zh_male_shaonianzixin_uranus_bigtts",
            "guqin_narrator": "zh_female_vv_uranus_bigtts",
        }
        speaker = voice_map.get(voice, voice) or "zh_female_cancan_uranus_bigtts"
        clean = (text or "").strip() or "这一幕。"

        if self.mock:
            digest = hashlib.md5(f"{speaker}:{clean}".encode()).hexdigest()[:8]
            dest = Path(__file__).resolve().parents[2] / "static" / "mock" / f"audio_{digest}.mp3"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size < 1000:
                await self._tts_edge(clean, dest)
            if result_metadata is not None:
                result_metadata.update(model_id="edge-tts", speaker=edge_tts_voice_for_speaker(""), simulated=True)
            return f"/static/mock/audio_{digest}.mp3"

        dest_dir = storage.project_dir(project_id or 0)
        dest = dest_dir / f"shot_{(shot_no or 0):03d}_tts.mp3"

        async def _accept_if_audible(label: str) -> str | None:
            if not dest.exists() or dest.stat().st_size < 2000:
                return None
            if await asyncio.to_thread(is_near_silent_audio, dest):
                logger.warning("%s produced near-silence shot=%s", label, shot_no)
                return None
            return storage.publish_local(dest)

        # TokenFree：默认模型 + Gemini / ElevenLabs / Qwen 其它 TTS 依次试
        for model_id in iter_tokenfree_tts_models(audio_model):
            try:
                resolve_upstream_model("audio", model_id)
            except ValueError:
                continue
            try:
                ok = await self._tts_openai_speech(clean, speaker, dest, model=model_id)
                if ok:
                    if getattr(self.settings, "local_media_mock", False):
                        if result_metadata is not None:
                            result_metadata.update(model_id=model_id, speaker=speaker, simulated=True)
                        return local_media_mock.media_url("default.mp3")
                    url = await _accept_if_audible("tokenfree-speech")
                    if url:
                        if result_metadata is not None:
                            result_metadata.update(model_id=model_id, speaker=speaker)
                        logger.info(
                            "TTS tokenfree ok shot=%s model=%s bytes=%s",
                            shot_no,
                            model_id,
                            dest.stat().st_size,
                        )
                        return url
            except Exception as exc:  # noqa: BLE001
                logger.warning("tokenfree speech failed model=%s: %s", model_id, exc)
                if getattr(self.settings, "local_media_mock", False):
                    raise RuntimeError("模拟语音请求组装失败，请检查模型配置和参数") from exc

        if getattr(self.settings, "local_media_mock", False):
            raise RuntimeError("模拟语音请求组装失败，未调用备用语音服务")
        # edge-tts：按 speaker 映射不同 neural，上游都失败时仍能分出角色声线
        try:
            await self._tts_edge(clean, dest, voice_hint=speaker)
            url = await _accept_if_audible("edge-tts")
            if url:
                if result_metadata is not None:
                    result_metadata.update(model_id="edge-tts", speaker=edge_tts_voice_for_speaker(speaker))
                logger.info("TTS edge-tts ok shot=%s speaker=%s bytes=%s", shot_no, speaker, dest.stat().st_size)
                return url
        except Exception as exc:  # noqa: BLE001
            logger.warning("edge-tts failed: %s", exc)

        logger.error("TTS all providers failed shot=%s", shot_no)
        raise RuntimeError("配音失败：语音服务暂不可用，请稍后重试")

    async def _tts_edge(self, text: str, dest: Path, voice_hint: str = "") -> None:
        """微软 edge-tts 兜底。国内连 api.msedgeservices.com 常超过默认 10s，拉长握手并重试。"""
        import edge_tts

        voice = edge_tts_voice_for_speaker(voice_hint)
        dest.parent.mkdir(parents=True, exist_ok=True)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    voice,
                    connect_timeout=30,
                    receive_timeout=90,
                )
                await communicate.save(str(dest))
                return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning("edge-tts attempt %s/3 failed: %s", attempt + 1, exc)
                if attempt < 2:
                    await asyncio.sleep(1.2 * (attempt + 1))
        raise RuntimeError(str(last_err) if last_err else "edge-tts failed")

    def _persist_tts_mp3(self, dest: Path, audio: bytes) -> bool:
        """把 Omni WAV 转成配音 mp3；已是 MPEG 则直接落盘。转码失败返回 False。"""
        if len(audio) < 1000:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        if audio[:3] == b"ID3" or (audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0):
            dest.write_bytes(audio)
            return True
        import shutil
        import subprocess
        import tempfile

        # ffmpeg 可执行文件 / 临时 wav / 转码进程
        ffmpeg = shutil.which(self.settings.ffmpeg_path) or shutil.which("ffmpeg")
        if not ffmpeg:
            logger.warning("tts persist skipped: ffmpeg not found")
            return False
        with tempfile.TemporaryDirectory(prefix="pf_tts_") as tmp_dir:
            src = Path(tmp_dir) / "omni.wav"
            src.write_bytes(audio)
            proc = subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-y",
                    "-i",
                    str(src),
                    "-q:a",
                    "4",
                    "-acodec",
                    "libmp3lame",
                    str(dest),
                ],
                capture_output=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        if proc.returncode == 0 and dest.exists() and dest.stat().st_size >= 1000:
            return True
        logger.warning(
            "tts persist ffmpeg failed code=%s stderr=%s",
            proc.returncode,
            (proc.stderr or b"").decode("utf-8", errors="replace")[:300],
        )
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False

    def _write_silence_mp3(self, dest: Path, duration: float) -> None:
        import shutil
        import subprocess

        ffmpeg = shutil.which(self.settings.ffmpeg_path) or shutil.which("ffmpeg")
        if not ffmpeg:
            dest.write_bytes(b"")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                f"{max(duration, 0.5):.3f}",
                "-q:a",
                "9",
                "-acodec",
                "libmp3lame",
                str(dest),
            ],
            capture_output=True,
            check=False,
        )

    async def _resolve_image_ref(self, image_url: str, *, prefer_https: bool = False) -> str:
        raw = (image_url or "").strip()
        if raw.startswith("https://"):
            return raw
        if raw.startswith("http://"):
            # Ark cloud cannot fetch LAN/localhost; keep only if public host
            host = (urlparse(raw).hostname or "").lower()
            if host and host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith(
                ("192.168.", "10.")
            ):
                return raw
        if prefer_https:
            # Seedance 2.0: 需要公网 https；本地 /static 先同步上 OSS
            local = storage.local_path_from_url(raw)
            if local and local.exists():
                from app.services.kepu_image_references import public_image_reference

                public = await asyncio.to_thread(public_image_reference, raw)
                if public and str(public).startswith("https://"):
                    return str(public)
                raise RuntimeError(
                    "Seedance 需要公网可访问的图片 URL（请配置 HTTPS 公网访问地址或启用 OSS 并上传参考图），"
                    "本地 /static 图无法被方舟拉取"
                )
            if raw.startswith("data:"):
                raise RuntimeError("Seedance 不支持 data URI 图片，请使用 Ark CDN https 链接")
        if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("data:"):
            return raw
        local = storage.local_path_from_url(raw)
        if local and local.exists():
            # Prefer data URI so Seedance can read without public CDN
            return storage.file_to_data_uri(local)
        # Last resort: absolute local public URL (only works if Ark can reach your machine)
        return storage.to_public_url(raw)

    def _write_mock_image(self, prompt: str, size: str | None = None) -> str:
        """写出 mock 立绘 SVG；每次唯一文件名，避免重试覆盖。"""
        digest = uuid.uuid4().hex[:12]
        root = Path(__file__).resolve().parents[2] / "static" / "mock"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"image_{digest}.svg"
        hue = int(digest[:2], 16)
        label = (prompt[:42] + "…") if len(prompt) > 42 else prompt
        safe = (
            label.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        # Portrait mock for image_text / 9:16
        portrait = bool(size and ("x" in size.lower()) and self._is_portrait_size(size))
        w, h = (720, 1280) if portrait else (960, 540)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="hsl({hue},28%,22%)"/>
      <stop offset="100%" stop-color="hsl({(hue + 40) % 360},22%,38%)"/>
    </linearGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#g)"/>
  <rect x="{int(w*0.08)}" y="{int(h*0.28)}" width="{int(w*0.4)}" height="{int(h*0.28)}" rx="10" fill="hsl({(hue + 20) % 360},35%,72%)" opacity="0.9"/>
  <circle cx="{int(w*0.72)}" cy="{int(h*0.38)}" r="{int(w*0.14)}" fill="hsl({(hue + 80) % 360},30%,65%)" opacity="0.55"/>
  <text x="{int(w*0.08)}" y="{int(h*0.78)}" fill="#f2ebe0" font-family="Georgia, serif" font-size="28">Mock Storyboard</text>
  <text x="{int(w*0.08)}" y="{int(h*0.84)}" fill="#d7cfc3" font-family="sans-serif" font-size="18">{safe}</text>
</svg>"""
        path.write_text(svg, encoding="utf-8")
        return f"/static/mock/image_{digest}.svg"

    @staticmethod
    def _is_portrait_size(size: str) -> bool:
        m = re.match(r"^(\d+)x(\d+)$", size.strip().lower())
        if not m:
            return False
        return int(m.group(2)) > int(m.group(1))

    def _mock_storyboard(
        self,
        source_text: str,
        source_type: str,
        style_prefix: str,
        duration_min: int,
        duration_max: int,
        pipeline_mode: str = "full",
        shot_range_override: tuple[int, int] | None = None,
    ) -> StoryboardResult:
        if topic_language(source_text) == "en":
            # 离线 mock 也遵守素材语言；不把中文模板拼回英文画面描述。
            lo, _ = shot_range_override or segplan.suggested_kepu_shot_range(source_text, pipeline_mode=pipeline_mode)
            chunks = [c.strip() for c in re.split(r"[.!?\n]+", source_text) if c.strip()] or ["An introduction"]
            items = [{"shot": i + 1, "title": f"Key idea {i + 1}",
                      "text": chunks[i % len(chunks)],
                      "img_prompt": f"Wide shot illustrating {chunks[i % len(chunks)]}, no visible text",
                      "camera": "Slow push in", "bgm": "Calm"} for i in range(lo)]
            return self._parse_storyboard(json.dumps({"shots": items}), "", duration_min,
                                          duration_max, duration_max, source_text=source_text)
        chunks = [c.strip() for c in re.split(r"[。！？\n\.\!\?]+", source_text) if c.strip()]
        if source_type == "theme" and len(chunks) <= 1:
            topic = source_text.strip()
            chunks = [
                f"引入主题：{topic}",
                f"核心概念解释：{topic}",
                f"一个关键例子说明{topic}",
                f"常见误解与澄清",
                f"总结与启发",
            ]
        if len(chunks) < 3:
            chunks = chunks + ["补充画面过渡", "收尾总结"]
        # shot_lo/shot_hi 与正式拆镜区间一致，避免 mock 仍只出 5 镜
        if shot_range_override:
            shot_lo, shot_hi = shot_range_override
        else:
            shot_lo, shot_hi = segplan.suggested_kepu_shot_range(source_text, pipeline_mode=pipeline_mode)
        chunks = chunks[:shot_hi]
        while len(chunks) < shot_lo:
            chunks.append("补充画面过渡")
        mid = (duration_min + duration_max) // 2
        if pipeline_mode == "image_text":
            mid = min(mid, max(duration_min, 3))
        bible = (
            f"统一角色：与「{source_text.strip()[:24]}」相关的核心人物，"
            "中等身材，简洁服饰配色固定，五官清晰可辨，全片外形不变"
        )
        bgm_lock = segplan.infer_bgm_mood(source_text, style_prefix)
        plans: list[ShotPlan] = []
        for i, text in enumerate(chunks, start=1):
            # Mock: invent short summary titles, do not slice narration mid-token
            topic_bit = re.sub(r"^(引入主题|核心概念解释|一个关键例子说明)[：:]?", "", text).strip()
            title = f"要点{i}" if len(topic_bit) > 10 else (topic_bit[:8] or f"场景{i}")
            if "：" in text or ":" in text:
                title = text.split("：", 1)[0].split(":", 1)[0][-6:] or title
            subtitle = _fallback_overlay_subtitle(text)
            img = f"{style_prefix}，{bible}，画面表现：{text[:80]}，竖屏构图，顶部留白，画面无文字"
            beats = [
                segplan.SegmentBeat(duration=segplan.estimate_visual_duration(img), kind="visual", text=img),
                segplan.SegmentBeat(
                    duration=segplan.estimate_narration_duration(text),
                    kind="narration",
                    text=text[:120],
                ),
            ]
            script = segplan.build_segment_script(beats, bgm_mood=bgm_lock, max_total=min(duration_max, 30))
            dur = float(segplan.resolve_api_duration(script, fallback=mid, lo=duration_min, hi=duration_max))
            plans.append(
                ShotPlan(
                    shot=i,
                    duration=dur,
                    text=text[:120],
                    overlay_title=_normalize_overlay_title(title, text, i),
                    overlay_subtitle=_normalize_overlay_subtitle(subtitle, text),
                    img_prompt=img,
                    video_prompt=script,
                    segment_script=script,
                    camera="缓慢推近" if i % 2 else "轻拉远",
                    bgm=bgm_lock,
                )
            )
        return StoryboardResult(shots=plans, character_bible=bible, bgm_lock=bgm_lock)

    def _parse_storyboard(
        self,
        content: str,
        style_prefix: str,
        duration_min: int,
        duration_max: int,
        max_shot_duration: int,
        *,
        source_text: str | None = None,
    ) -> StoryboardResult:
        raw = (content or "").strip()
        if not raw:
            raise RuntimeError("分镜 JSON 为空，无法解析")
        try:
            data = _extract_json(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"分镜 JSON 解析失败：{exc}") from exc
        if source_text is not None:
            validate_storyboard_language(data, source_text)
        language = topic_language(source_text) if source_text is not None else "zh"
        english = language == "en"
        character_bible = ""
        bgm_lock = ""
        items = data
        if isinstance(data, dict):
            character_bible = str(
                data.get("character_bible") or data.get("characters") or data.get("cast") or ""
            ).strip()
            bgm_lock = str(data.get("bgm_lock") or data.get("bgm") or "").strip()
            items = data.get("shots") or data.get("storyboard") or data.get("scenes") or []
        if not isinstance(items, list):
            raise RuntimeError("LLM storyboard JSON 格式无效：需要 shots 数组")
        if not items:
            raise RuntimeError("分镜模型未返回任何镜头（shots 为空）")
        hi = min(duration_max, max_shot_duration)
        plans: list[ShotPlan] = []
        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("audio_text") or (f"Shot {i}" if english else f"镜头{i}"))
            title = str(item.get("title") or item.get("overlay_title") or "").strip()
            subtitle = str(item.get("subtitle") or item.get("overlay_subtitle") or "").strip()
            title = (title or f"Scene {i}") if english else _normalize_overlay_title(title, text, i)
            subtitle = (subtitle or text) if english else _normalize_overlay_subtitle(subtitle, text)
            img = str(item.get("img_prompt") or f"{text}")
            camera = str(item.get("camera") or ("Slow pan" if english else "缓慢横移"))
            bgm = str(item.get("bgm") or item.get("bgm_mood") or bgm_lock or ("Calm" if english else "平稳"))
            if not bgm_lock:
                bgm_lock = bgm
            beats = segplan.parse_beats_from_llm_shot(item, narration_fallback=text)
            script = segplan.build_segment_script(beats, bgm_mood=bgm_lock or bgm, max_total=hi, language=language)
            narr = segplan.narration_from_script(script) or text
            visual = segplan.first_visual_prompt(script) or img
            dur = float(
                segplan.resolve_api_duration(
                    script,
                    fallback=float(item.get("duration", (duration_min + duration_max) / 2)),
                    lo=duration_min,
                    hi=hi,
                )
            )
            plans.append(
                ShotPlan(
                    shot=int(item.get("shot", i)),
                    duration=dur,
                    text=narr,
                    overlay_title=title,
                    overlay_subtitle=subtitle,
                    img_prompt=visual,
                    video_prompt=script,
                    segment_script=script,
                    camera=camera,
                    bgm=bgm_lock or bgm,
                )
            )
        if not bgm_lock and plans:
            bgm_lock = plans[0].bgm
        return StoryboardResult(
            shots=plans,
            character_bible=character_bible,
            bgm_lock=bgm_lock or ("Calm" if english else segplan.infer_bgm_mood(style_prefix)),
        )

    async def expand_content(
        self, topic: str, mode: str = "theme", *,
        target_duration_sec: int | None = None, style: str | None = None,
    ) -> dict[str, str]:
        """按原始输入语言扩写；可选时长和风格兼容旧的两参数调用。"""
        topic = (topic or "").strip() or "人工智能如何改变日常生活"
        mode = "script" if mode == "script" else "theme"
        if self.mock:
            resolve_upstream_model("text", None)
            return self._mock_expand_content(
                topic, mode, target_duration_sec=target_duration_sec, style=style,
            )
        system, user = expansion_messages(
            topic, mode, target_duration_sec=target_duration_sec, style=style,
        )
        content = await chat_completions(
            system, user, temperature=0.6,
            max_tokens=8192 if (target_duration_sec or 60) > 180 else 4096,
            timeout=90.0,
        )
        result = self._parse_expand_content(
            content or "{}", topic, mode,
            target_duration_sec=target_duration_sec, style=style,
        )
        if expansion_language_matches(result, topic):
            return result
        language = "English" if topic_language(topic) == "en" else "Chinese"
        logger.warning("文案输出语言错配，进行一次语言纠正 language=%s", language)
        corrected = await chat_completions(
            f"Rewrite the supplied JSON in {language}. Both title and content MUST be in {language}. "
            "Preserve the original topic, story and meaning. Return only JSON with title and content keys.",
            json.dumps({"original_topic": topic, "output_language": language, "draft": result}, ensure_ascii=False),
            temperature=0.6, max_tokens=8192 if (target_duration_sec or 60) > 180 else 4096, timeout=90.0,
        )
        # 纠正失败必须报错，不得用离线示意稿冒充真实生成成功。
        try:
            corrected_data = json.loads(corrected)
        except (ValueError, TypeError):
            raise ValueError("AI 输出语言校验失败，请重试") from None
        if not isinstance(corrected_data, dict) or not all(
            isinstance(corrected_data.get(key), str) and corrected_data[key].strip() for key in ("title", "content")
        ):
            raise ValueError("AI 输出语言校验失败，请重试")
        result = self._parse_expand_content(corrected, topic, mode)
        if not expansion_language_matches(result, topic):
            raise ValueError("AI 未按输入语言生成文案，请重试")
        return result

    def _mock_expand_content(
        self, topic: str, mode: str, *,
        target_duration_sec: int | None = None, style: str | None = None,
    ) -> dict[str, str]:
        """mock 与解析回退共用按语言生成的离线文案。"""
        return fallback_expansion(
            topic, mode, target_duration_sec=target_duration_sec, style=style,
        )

    def _parse_expand_content(
        self, raw: str, topic: str, mode: str, *,
        target_duration_sec: int | None = None, style: str | None = None,
    ) -> dict[str, str]:
        """容错解析模型 JSON，不对英文主题施加汉字长度截断。"""
        def fallback() -> dict[str, str]:
            """保留请求时长与语言选择。"""
            return self._mock_expand_content(
                topic, mode, target_duration_sec=target_duration_sec, style=style,
            )

        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}", text)
            if not m:
                return fallback()
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return fallback()
        if not isinstance(data, dict):
            return fallback()
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return fallback()
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            title = fallback()["title"]
        # 安全上限而非语言长度规则；允许十分钟旁白和自然英文标题。
        title = title.strip()[:240]
        content = content.strip()
        if mode == "theme":
            content = " ".join(content.splitlines()).strip()[:2000]
        else:
            content = content[:16000]
        return {"title": title, "content": content}


_gateway: ArkGateway | None = None


def get_ark() -> ArkGateway:
    global _gateway
    if _gateway is None:
        _gateway = ArkGateway()
    return _gateway


def reset_ark() -> None:
    global _gateway
    _gateway = None
