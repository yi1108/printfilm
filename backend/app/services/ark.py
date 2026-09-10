"""Volcengine Ark gateway via HTTP (chat / Seedream / Seedance / TTS)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings, get_settings
from app.services.billing.pricing import parse_upstream_cost_fen, parse_usage_dict
from app.schemas_routing import ResolvedModelRoute
from app.services.logical_model_router import resolve_logical_model, resolve_logical_model_id
from app.services import storage
from app.services.drama.seedance_i2v_role import resolve_seedance_i2v_image_role
from app.services.ffmpeg_compose import is_near_silent_audio
from app.services.drama.llm import _extract_json
from app.services.llm_client import chat_completions
from app.services import seedance_segments as segplan

logger = logging.getLogger(__name__)


def _raise_seedream_http_error(status_code: int, body: str) -> None:
    """将 Seedream HTTP 错误转为可读 RuntimeError（含上游账户欠费）。"""
    snippet = (body or "")[:800]
    if status_code == 403 and "AccountOverdueError" in snippet:
        logger.error("Seedream AccountOverdueError — upstream Ark account overdue: %s", snippet[:200])
        raise RuntimeError(
            "上游 Seedream 账户欠费（AccountOverdueError），生图暂不可用，请联系管理员充值火山方舟账户"
        )
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


# 从 Seedance 任务查询响应解析状态、媒体 URL 与官方 usage
def _build_task_result_from_payload(data: dict[str, Any]) -> TaskResult:
    status = str(data.get("status", "")).lower() or "running"
    usage_parsed = parse_usage_dict(data)
    total_tokens = int(usage_parsed.get("total_tokens") or 0)
    completion_tokens = int(usage_parsed.get("completion_tokens") or 0)
    raw_usage = data.get("usage") if isinstance(data.get("usage"), dict) else None

    if status in {"succeeded", "success"}:
        url = None
        content = data.get("content")
        if isinstance(content, dict):
            url = content.get("video_url")
        if not url:
            url = data.get("video_url")
        return TaskResult(
            status="succeeded",
            url=url,
            last_frame_url=_extract_seedance_last_frame_url(data),
            total_tokens=total_tokens,
            completion_tokens=completion_tokens,
            raw_usage=raw_usage,
        )
    if status in {"failed", "cancelled", "canceled", "expired"}:
        err = data.get("error") or data.get("message") or status
        return TaskResult(
            status="failed",
            error=str(err),
            total_tokens=total_tokens,
            completion_tokens=completion_tokens,
            raw_usage=raw_usage,
        )
    return TaskResult(
        status="running",
        total_tokens=total_tokens,
        completion_tokens=completion_tokens,
        raw_usage=raw_usage,
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

    # 优先后台渠道 Key，env 仅作空渠道时的兜底
    def _ark_api_key(self) -> str:
        try:
            from app.services.model_settings import get_routing_snapshot

            channels = get_routing_snapshot().channels
        except Exception:  # noqa: BLE001
            channels = []
        ark_channels = [
            ch
            for ch in channels
            if ch.enabled
            and (ch.api_key or "").strip()
            and (
                ch.protocol == "ark"
                or ch.api_format == "ark"
                or "ark.cn-beijing.volces.com" in (ch.base_url or "")
            )
        ]
        if ark_channels:
            preferred = next((ch for ch in ark_channels if ch.id == "ark-default"), ark_channels[0])
            return (preferred.api_key or "").strip()
        return (self.settings.ark_api_key or "").strip()

    @property
    def mock(self) -> bool:
        return self.settings.ark_mock or not self._ark_api_key()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ark_api_key()}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        base = self.settings.ark_base_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}"

    # 按逻辑路由解析 ARK 渠道凭证
    def _resolve_ark_route(self, capability: str, model_id: str | None) -> ResolvedModelRoute | None:
        logical_id = resolve_logical_model_id(capability, model_id)
        return resolve_logical_model(capability, logical_id)

    def _route_headers(self, route: ResolvedModelRoute | None = None) -> dict[str, str]:
        if route and route.api_key:
            return {
                "Authorization": f"Bearer {route.api_key}",
                "Content-Type": "application/json",
            }
        return self._headers()

    def _route_url(self, path: str, route: ResolvedModelRoute | None = None) -> str:
        if route and route.base_url:
            base = route.base_url.rstrip("/")
            if not path.startswith("/"):
                path = "/" + path
            return f"{base}{path}"
        return self._url(path)

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
    ) -> StoryboardResult:
        if self.mock:
            return await asyncio.to_thread(
                self._mock_storyboard,
                source_text,
                source_type,
                style_prefix,
                duration_min,
                duration_max,
                pipeline_mode,
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
                    "character_bible：填「无固定人物，各镜为独立系统/场景界面」。"
                    "每镜 img_prompt 必须写清该镜独特的界面类型、布局分区、主色与信息层级，不要粘贴人物锁定。"
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
        # shot_cap 单镜 duration 上限（秒）；shot_lo/shot_hi 按文案字数动态拆镜数
        shot_cap = min(duration_max, max_shot_duration)
        shot_lo, shot_hi = segplan.suggested_kepu_shot_range(source_text, pipeline_mode=pipeline_mode)
        shot_range = f"{shot_lo}-{shot_hi}"
        # segment_rules 科普逐段脚本生产约束（对齐漫剧 cue，无 @asset）
        segment_rules = (
            "【segments 生产规范】"
            "segments 必填；系统会落成 @duration +【字幕】/【BGM】/【旁白·自然语速·同步字幕】生产脚本，"
            "因此 kind/text/duration 必须可直接消费。"
            "段序优先「画面→旁白」交替，首段尽量 kind=visual（保证首帧有料）；"
            "visual/action 的 text 必须含景别+主体动作+场景/界面类型，禁止空镜与模糊氛围词堆砌；"
            "narration 的 text 为一句一事、可朗读口播，按约 5 字/秒估 duration（语速自然偏快）；"
            "旁白 duration 严格跟字数，最多多 1 秒呼吸，禁止把短句拉满到镜长上限或拖腔注水；"
            "单段 duration 3-12 秒，镜内各段之和约等于本镜 duration，且不超过 "
            f"{shot_cap} 秒。"
            "禁止真实商标/公司名/人名（改用泛称）。"
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
                f"你是{orient}图文短视频编剧。所有字段必须使用简体中文。"
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
                "禁止要求画面内写字；禁止出现真实商标/公司名/人名，用泛称)、"
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
                "你是短视频分镜编剧。所有字段必须使用简体中文"
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
                "img_prompt(与首段 visual 一致的中文首帧提示词，含具体景物与构图)、"
                "video_prompt(可与 segments 画面摘要一致)、"
                "camera(运镜，如：缓慢上摇/轻推/横移)、bgm(情绪，全片同一氛围)。"
                "顶层另输出 bgm_lock(全片统一 BGM 氛围一句，与各镜 bgm 一致)。"
                "img_prompt 与 video_prompt 禁止英文句子，专有名词可保留原文。"
                f"{segment_rules}"
                f"{diversity_note}"
            )
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
    ) -> ImageResult:
        """调用 Seedream 生图。

        只软化用户正文并保留设定板前缀；InputTextSensitive 时仍用简化三视图重试，
        最后一档才缩成「三视图+服装风格」。不做空主体 / CG 厚涂兜底。
        """
        if self.mock:
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
                    model=model,
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
    ) -> ImageResult:
        """单次 Seedream 请求并落盘（文件名含 uuid，避免重生成覆盖）。"""
        route = self._resolve_ark_route("image", model)
        upstream_model = route.upstream_model if route else ((model or "").strip() or self.settings.model_image)
        body: dict[str, Any] = {
            "model": upstream_model,
            "prompt": full_prompt,
            "size": size or self.settings.ark_image_size,
            "response_format": "url",
            "watermark": False,
        }
        from app.services.style_lock import seedream_ref_urls

        refs = seedream_ref_urls(*(ref_urls or []))
        if refs:
            body["image"] = refs if len(refs) > 1 else refs[0]

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                self._route_url("/images/generations", route),
                headers=self._route_headers(route),
                json=body,
            )
            if resp.status_code >= 400:
                _raise_seedream_http_error(resp.status_code, resp.text)
            data = resp.json()

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

        remote = self._extract_image_url(data)
        if not remote:
            raise RuntimeError(f"Seedream missing url: {json.dumps(data)[:500]}")

        dest_dir = storage.project_dir(project_id or 0)
        name = f"shot_{(shot_no or 0):03d}_{uuid.uuid4().hex[:12]}.png"
        dest = dest_dir / name
        await storage.download_to(remote, dest)
        return ImageResult(
            local_url=storage.publish_local(dest),
            remote_url=remote,
            total_tokens=int(usage_parsed.get("total_tokens") or 0),
            prompt_tokens=int(usage_parsed.get("prompt_tokens") or 0),
            completion_tokens=int(usage_parsed.get("completion_tokens") or 0),
            raw_usage=raw_usage,
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
    def _seedance_duration(duration: int | float) -> int:
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
        prompt_as_json: bool = True,
        return_last_frame: bool = True,
        generate_audio: bool = False,
    ) -> str:
        if self.mock:
            digest = hashlib.md5(f"{image_url}:{prompt}".encode()).hexdigest()[:10]
            return f"mock-task-{digest}"

        # Seedance needs a publicly reachable https image (data URI often rejected / odd errors)
        image_ref = await self._resolve_image_ref(image_url, prefer_https=True)
        # Prefer plain timed script for Seedance 2.5; JSON caption kept as fallback
        plain = (prompt or "").strip() or "画面轻微动态，保持主体外形稳定"
        text = plain if not prompt_as_json else self._seedance_prompt_text(prompt)
        # If prompt looks like manju-style script, always send plain text
        if "@duration:" in plain or "00:" in plain or plain.startswith("【"):
            text = plain
            prompt_as_json = False
        # 有目标画幅时用 reference_image + ratio（可强制 9:16）。
        # 纯 first_frame 禁止传 ratio，且实测即使静帧竖屏也可能吐横屏。
        image_role, target_ratio = resolve_seedance_i2v_image_role(ratio)
        content: list[dict[str, Any]] = [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": image_ref},
                "role": image_role,
            },
        ]
        route = self._resolve_ark_route("video", self.settings.model_video)
        video_model = route.upstream_model if route else self.settings.model_video
        body: dict[str, Any] = {
            "model": video_model,
            "content": content,
            "duration": self._seedance_duration(duration),
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

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self._route_url("/contents/generations/tasks", route),
                headers=self._route_headers(route),
                json=body,
            )
            if resp.status_code >= 400 and prompt_as_json:
                # Fallback: plain text prompt
                body["content"][0]["text"] = plain
                resp = await client.post(
                    self._route_url("/contents/generations/tasks", route),
                    headers=self._route_headers(route),
                    json=body,
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
                        resp = await client.post(
                            self._route_url("/contents/generations/tasks", route),
                            headers=self._route_headers(route),
                            json=body,
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
                    resp = await client.post(
                        self._route_url("/contents/generations/tasks", route),
                        headers=self._route_headers(route),
                        json=body,
                    )
            if resp.status_code >= 400 and not target_ratio:
                # 无目标画幅时的兼容回退；有竖屏目标时禁止 adaptive，避免再次出横屏
                body["content"][1].pop("role", None)
                body["ratio"] = "adaptive"
                resp = await client.post(
                    self._route_url("/contents/generations/tasks", route),
                    headers=self._route_headers(route),
                    json=body,
                )
            if resp.status_code >= 400:
                raise RuntimeError(_format_seedance_create_error(resp.status_code, resp.text))
            data = resp.json()

        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise RuntimeError(f"Seedance missing task id: {data}")
        return str(task_id)

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
                copy["image_url"] = {
                    "url": await self._resolve_media_ref(str(raw_url), prefer_https=True)
                }
            elif item.get("type") == "audio_url":
                raw_url = (item.get("audio_url") or {}).get("url") or ""
                copy["audio_url"] = {
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
        payload["duration"] = self._seedance_duration(payload.get("duration", 8))
        route = self._resolve_ark_route("video", str(payload.get("model") or ""))

        logger.info(
            "Seedance multimodal create model=%s duration=%s items=%s",
            payload.get("model"),
            payload.get("duration"),
            len(payload.get("content") or []),
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                self._route_url("/contents/generations/tasks", route),
                headers=self._route_headers(route),
                json=payload,
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
                    resp = await client.post(
                        self._route_url("/contents/generations/tasks", route),
                        headers=self._route_headers(route),
                        json=payload,
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

        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise RuntimeError(f"Seedance missing task id: {data}")
        return str(task_id)

    async def gen_and_wait_seedance_body(
        self,
        body: dict[str, Any],
        *,
        project_id: int,
        shot_no: int,
        max_attempts: int = 2,
        content_labels: list[str] | None = None,
    ) -> tuple[str, str | None, TaskResult]:
        """创建 Seedance 多模态任务并等待完成；返回 (本地视频 URL, 可选本地尾帧 URL, 任务结果)。"""
        def _is_audio_download_error(err: Exception) -> bool:
            msg = str(err)
            return "audio_url" in msg and "resource download failed" in msg

        def _strip_reference_audio(src: dict[str, Any]) -> dict[str, Any] | None:
            content = src.get("content")
            if not isinstance(content, list):
                return None
            filtered: list[dict[str, Any]] = []
            removed = False
            for item in content:
                if not isinstance(item, dict):
                    filtered.append(item)
                    continue
                if item.get("type") == "audio_url" and item.get("role") == "reference_audio":
                    removed = True
                    continue
                if item.get("type") == "text":
                    text = str(item.get("text") or "")
                    cleaned_lines = [
                        line
                        for line in text.splitlines()
                        if "参考音频" not in line
                        and "角色音色" not in line
                        and "旁白音色" not in line
                    ]
                    filtered.append({**item, "text": "\n".join(cleaned_lines).strip()})
                    continue
                filtered.append(item)
            if not removed:
                return None
            return {**src, "content": filtered}

        last_err: Exception | None = None
        fallback_body = body
        audio_fallback_used = False
        for _attempt in range(max_attempts):
            try:
                task_id = await self.gen_video_seedance_body(
                    fallback_body,
                    project_id=project_id,
                    content_labels=content_labels,
                )
                return await self.wait_video_assets(
                    task_id, project_id=project_id, shot_no=shot_no
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if not audio_fallback_used and _is_audio_download_error(exc):
                    stripped = _strip_reference_audio(fallback_body)
                    if stripped:
                        logger.warning(
                            "Seedance reference_audio download failed; retry without audio refs project=%s shot=%s",
                            project_id,
                            shot_no,
                        )
                        fallback_body = stripped
                        audio_fallback_used = True
        raise RuntimeError(str(last_err) if last_err else "Seedance multimodal failed")

    async def poll_task(self, task_id: str) -> TaskResult:
        if self.mock or task_id.startswith("mock-task-"):
            return TaskResult(
                status="succeeded",
                url=f"/static/mock/video_{task_id[-8:]}.mp4",
                last_frame_url=f"/static/mock/last_{task_id[-8:]}.jpg",
            )

        deadline = time.monotonic() + self.settings.ark_video_poll_timeout
        async with httpx.AsyncClient(timeout=60.0) as client:
            while time.monotonic() < deadline:
                resp = await client.get(
                    self._url(f"/contents/generations/tasks/{task_id}"),
                    headers=self._headers(),
                )
                if resp.status_code >= 400:
                    return TaskResult(status="failed", error=resp.text[:500])
                data = resp.json()
                result = _build_task_result_from_payload(data)
                result.provider_task_id = task_id
                if result.status == "succeeded":
                    return result
                if result.status == "failed":
                    return result
                await asyncio.sleep(self.settings.ark_video_poll_interval)
        return TaskResult(status="failed", error="poll timeout", provider_task_id=task_id)

    async def fetch_task_once(self, task_id: str) -> TaskResult:
        """单次查询 Seedance 任务，不阻塞等待。"""
        if self.mock or task_id.startswith("mock-task-"):
            return TaskResult(
                status="succeeded",
                url=f"/static/mock/video_{task_id[-8:]}.mp4",
                last_frame_url=f"/static/mock/last_{task_id[-8:]}.jpg",
            )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._url(f"/contents/generations/tasks/{task_id}"),
                headers=self._headers(),
            )
        if resp.status_code >= 400:
            return TaskResult(status="failed", error=resp.text[:500], provider_task_id=task_id)
        result = _build_task_result_from_payload(resp.json())
        result.provider_task_id = task_id
        return result

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
            await storage.download_to(result.url, dest)
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
                    await storage.download_to(result.last_frame_url, frame_dest)
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
        video_local, _last, result = await self.wait_video_assets(
            task_id, project_id=project_id, shot_no=shot_no
        )
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
    ) -> tuple[str, TaskResult]:
        """Create Seedance i2v task and wait; retry on summary_caption / transient BodyFormat."""
        last_err: Exception | None = None
        for attempt in range(max_attempts):
            use_json = attempt != 1  # attempt0 json, attempt1 plain, attempt2 json again
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
                )
                return await self.wait_video(
                    task_id,
                    project_id=project_id,
                    shot_no=shot_no,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                msg = str(exc)
                retryable = any(
                    k in msg
                    for k in (
                        "summary_caption",
                        "BodyFormat",
                        "InvalidParameter",
                        "poll timeout",
                    )
                )
                logger.warning(
                    "Seedance attempt %s/%s shot=%s failed: %s",
                    attempt + 1,
                    max_attempts,
                    shot_no,
                    msg[:300],
                )
                if not retryable or attempt >= max_attempts - 1:
                    break
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(str(last_err) if last_err else "video generation failed")

    def _openspeech_configured(self) -> bool:
        """豆包 openspeech 是否已配置（新版 API Key 或旧版 AppId + AccessKey）。"""
        if (self.settings.volc_tts_api_key or "").strip():
            return True
        return bool(self.settings.volc_tts_app_id and self.settings.volc_tts_access_key)

    @staticmethod
    def _build_tts_additions(speaker: str, emotion_hint: str | None) -> str | None:
        """组装 openspeech additions（S_ 克隆 + 语气 context_texts）。"""
        additions: dict[str, Any] = {}
        if speaker.startswith("S_"):
            additions["model_type"] = 4
        hint = (emotion_hint or "").strip()
        if hint:
            additions["context_texts"] = [f"用「{hint}」的语气朗读"]
        if not additions:
            return None
        return json.dumps(additions, ensure_ascii=False)

    async def tts(
        self,
        text: str,
        voice: str,
        *,
        project_id: int | None = None,
        shot_no: int | None = None,
        duration_hint: float = 4.0,
        emotion_hint: str | None = None,
    ) -> str:
        voice_map = {
            "narrator_calm": "zh_female_cancan_uranus_bigtts",
            "warm_storyteller": "zh_female_tianmeixiaoyuan_uranus_bigtts",
            "teacher_clear": "zh_male_shaonianzixin_uranus_bigtts",
            "urban_editorial": "zh_female_shuangkuaisisi_uranus_bigtts",
            "retro_host": "zh_male_shaonianzixin_uranus_bigtts",
            "guqin_narrator": "zh_female_vv_uranus_bigtts",
        }
        speaker = (
            voice_map.get(voice, voice)
            or self.settings.volc_tts_speaker
            or "zh_female_cancan_uranus_bigtts"
        )
        clean = (text or "").strip() or "这一幕。"

        if self.mock:
            digest = hashlib.md5(f"{speaker}:{clean}".encode()).hexdigest()[:8]
            dest = Path(__file__).resolve().parents[2] / "static" / "mock" / f"audio_{digest}.mp3"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size < 1000:
                await self._tts_edge(clean, dest)
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

        # 1) 豆包 openspeech（X-Api-Key 或 AppId + AccessKey）
        if self._openspeech_configured():
            try:
                ok = await self._tts_openspeech(clean, speaker, dest, emotion_hint=emotion_hint)
                if ok:
                    url = await _accept_if_audible("openspeech")
                    if url:
                        return url
            except Exception as exc:  # noqa: BLE001
                logger.warning("openspeech TTS failed: %s", exc)

        # 2) edge-tts（无 openspeech 凭证时的主路径；有凭证时作兜底）
        try:
            await self._tts_edge(clean, dest, voice_hint=speaker)
            url = await _accept_if_audible("edge-tts")
            if url:
                logger.info("TTS edge-tts ok shot=%s bytes=%s", shot_no, dest.stat().st_size)
                return url
        except Exception as exc:  # noqa: BLE001
            logger.warning("edge-tts failed: %s", exc)

        # 3) 旧 Ark /audio/speech（多数账号 404，保留兼容）
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    self._url("/audio/speech"),
                    headers=self._headers(),
                    json={
                        "model": self.settings.model_audio,
                        "input": clean,
                        "voice": speaker,
                        "response_format": "mp3",
                    },
                )
                if resp.status_code < 400 and resp.content and len(resp.content) > 1000:
                    dest.write_bytes(resp.content)
                    url = await _accept_if_audible("ark-speech")
                    if url:
                        return url
                logger.warning("Ark TTS HTTP %s: %s", resp.status_code, (resp.text or "")[:300])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ark TTS failed: %s", exc)

        # 最后才静音（保证合成不中断）
        logger.error("TTS all providers failed; writing silence shot=%s", shot_no)
        await asyncio.to_thread(self._write_silence_mp3, dest, duration_hint)
        return storage.publish_local(dest)

    def _tts_resource_id(self, speaker: str) -> str:
        if speaker.startswith("S_"):
            return "seed-icl-2.0"
        if "_uranus_" in speaker or speaker.startswith("saturn_"):
            return self.settings.volc_tts_resource_id or "seed-tts-2.0"
        return "seed-tts-1.0"

    async def _tts_openspeech(
        self,
        text: str,
        speaker: str,
        dest: Path,
        *,
        emotion_hint: str | None = None,
    ) -> bool:
        resource = self._tts_resource_id(speaker)
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": resource,
        }
        api_key = (self.settings.volc_tts_api_key or "").strip()
        if api_key:
            headers["X-Api-Key"] = api_key
        else:
            headers["X-Api-App-Id"] = self.settings.volc_tts_app_id
            headers["X-Api-Access-Key"] = self.settings.volc_tts_access_key
        body: dict[str, Any] = {
            "user": {"uid": "framecut"},
            "req_params": {
                "text": text,
                "speaker": speaker,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }
        additions = self._build_tts_additions(speaker, emotion_hint)
        if additions:
            body["req_params"]["additions"] = additions

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(self.settings.volc_tts_url, headers=headers, json=body)
            if resp.status_code >= 400:
                logger.warning("openspeech HTTP %s: %s", resp.status_code, resp.text[:400])
                return False
            audio = self._parse_openspeech_ndjson(resp.content)
            if not audio:
                logger.warning("openspeech empty audio body")
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(audio)
            return True

    @staticmethod
    def _parse_openspeech_ndjson(raw: bytes) -> bytes:
        chunks: list[bytes] = []
        text = raw.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = obj.get("code")
            if code == 0 and obj.get("data"):
                chunks.append(base64.b64decode(obj["data"]))
            elif code in {20000000, 20000001}:
                break
            elif code not in (None, 0):
                logger.warning("openspeech line error: %s", line[:300])
        return b"".join(chunks)

    async def _tts_edge(self, text: str, dest: Path, voice_hint: str = "") -> None:
        import edge_tts

        # Map rough gender from hint → Edge neural voice
        female = "zh-CN-XiaoxiaoNeural"
        male = "zh-CN-YunxiNeural"
        voice = male if "male" in (voice_hint or "").lower() or "男" in voice_hint else female
        dest.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(dest))

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
                public = storage.republish_url(raw, sync=True)
                if public and str(public).startswith("https://"):
                    return str(public)
                raise RuntimeError(
                    "Seedance 需要公网可访问的图片 URL（请启用 OSS 并确保参考图已上传），"
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
    ) -> StoryboardResult:
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
    ) -> StoryboardResult:
        raw = (content or "").strip()
        if not raw:
            raise RuntimeError("分镜 JSON 为空，无法解析")
        try:
            data = _extract_json(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"分镜 JSON 解析失败：{exc}") from exc
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
            text = str(item.get("text") or item.get("audio_text") or f"镜头{i}")
            title = str(item.get("title") or item.get("overlay_title") or "").strip()
            subtitle = str(item.get("subtitle") or item.get("overlay_subtitle") or "").strip()
            title = _normalize_overlay_title(title, text, i)
            subtitle = _normalize_overlay_subtitle(subtitle, text)
            img = str(item.get("img_prompt") or f"{text}")
            camera = str(item.get("camera", "缓慢横移"))
            bgm = str(item.get("bgm") or item.get("bgm_mood") or bgm_lock or "平稳")
            if not bgm_lock:
                bgm_lock = bgm
            beats = segplan.parse_beats_from_llm_shot(item, narration_fallback=text)
            script = segplan.build_segment_script(beats, bgm_mood=bgm_lock or bgm, max_total=hi)
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
            bgm_lock=bgm_lock or segplan.infer_bgm_mood(style_prefix),
        )

    async def expand_content(self, topic: str, mode: str = "theme") -> dict[str, str]:
        """Expand a short topic into title + theme brief or full narration script."""
        topic = (topic or "").strip() or "人工智能如何改变日常生活"
        mode = "script" if mode == "script" else "theme"
        if self.mock:
            return self._mock_expand_content(topic, mode)

        if mode == "script":
            system = (
                "你是科普短视频文案作者。根据用户主题写一篇可直接用于旁白的完整口播文案。"
                "只输出严格 JSON：{\"title\":\"作品名\",\"content\":\"完整文案\"}。"
                "title：8-18 字，吸引人、无标点堆砌。"
                "content：300-700 字，口语化，分 4-8 个自然段，有开场钩子、知识点、收尾；"
                "不要 markdown、不要分镜编号、不要标题行。"
            )
        else:
            system = (
                "你是科普短视频选题策划。把用户输入扩写成一句清晰具体的创作主题。"
                "只输出严格 JSON：{\"title\":\"作品名\",\"content\":\"主题句\"}。"
                "title：8-18 字。"
                "content：一句话主题，40-90 字，写清受众与要讲清的核心知识点；不要换行。"
            )
        content = await chat_completions(
            system,
            f"主题/素材：{topic}",
            temperature=0.6,
            max_tokens=4096,
            timeout=90.0,
        )
        return self._parse_expand_content(content or "{}", topic, mode)

    def _mock_expand_content(self, topic: str, mode: str) -> dict[str, str]:
        short = topic[:18].rstrip("？?。.!！") or "科普短片"
        title = short if len(short) >= 4 else f"{short}的科普"
        if mode == "script":
            content = (
                f"你有没有想过：{topic.rstrip('？?')}？\n\n"
                f"今天我们用三分钟，把这件事讲清楚。"
                f"先从生活里最常见的现象说起，再拆开背后的原理，最后给你一个好记的结论。\n\n"
                f"很多人第一反应会想当然，但真正关键在于因果链条，而不是表象。"
                f"弄懂这一点，你就能解释身边更多类似的问题。\n\n"
                f"记住：观察现象、追问机制、再用例子验证。"
                f"下一次再遇到{short}相关话题，你也能自信地讲给别人听。"
            )
        else:
            content = (
                f"{topic.rstrip('？?')}：面向普通观众，用生活例子讲清核心原理与常见误区。"
            )[:100]
        return {"title": title[:24], "content": content}

    def _parse_expand_content(self, raw: str, topic: str, mode: str) -> dict[str, str]:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}", text)
            if not m:
                return self._mock_expand_content(topic, mode)
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return self._mock_expand_content(topic, mode)
        title = str(data.get("title") or "").strip() or topic[:18]
        content = str(data.get("content") or "").strip()
        if not content:
            return self._mock_expand_content(topic, mode)
        if mode == "theme":
            content = content.replace("\n", " ").strip()[:100]
        else:
            content = content[:8000]
        return {"title": title[:24], "content": content}


_gateway: ArkGateway | None = None


def get_ark() -> ArkGateway:
    global _gateway
    if _gateway is None:
        _gateway = ArkGateway()
    return _gateway


def reset_ark() -> None:
    global _gateway
    _gateway = None
