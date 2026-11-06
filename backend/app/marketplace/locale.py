"""市场请求语言隔离；语言不参与身份、定价和媒体权限判断。"""
from contextvars import ContextVar
from fastapi import Header

current_locale: ContextVar[str] = ContextVar("marketplace_locale", default="zh")


def locale_header(accept_language: str | None = Header(default=None, description="Display language: zh-CN or en-US (quality weights supported). Defaults to Chinese. Business codes, amounts and user content are unchanged.")):
    """在 OpenAPI 声明统一语言头；请求语言由中间件隔离。"""
    return accept_language


def negotiate_language(header: str | None) -> str:
    """按 Accept-Language 权重选择简体中文或英文，不支持时保持中文兼容。"""
    candidates = []
    for index, part in enumerate((header or "").split(",")):
        pieces = part.strip().lower().split(";")
        language = pieces[0].split("-")[0]
        try:
            quality = next((float(piece.strip()[2:]) for piece in pieces[1:] if piece.strip().startswith("q=")), 1.0)
        except ValueError:
            continue
        if language in ("zh", "en") and 0 < quality <= 1:
            candidates.append((quality, -index, language))
    return max(candidates)[2] if candidates else "zh"


def localized(zh: str, en: str) -> str:
    """仅选择已维护的系统译文，不翻译用户原文。"""
    return en if current_locale.get() == "en" else zh


LABELS = {
    "content_type": {"work": ("单视频", "Video"), "series": ("短剧系列", "Series"), "series_episode": ("分集", "Episode"), "recruit": ("招募", "Creative brief")},
    "sale_type": {"free": ("免费公开", "Free to watch"), "copyright_contact": ("版权出售收益", "Copyright sales"), "platform_unlock": ("平台投放收益", "Platform earnings")},
    "access_mode": {"free": ("免费完整观看", "Free full playback"), "preview": ("短试看", "Preview"), "entitled": ("已解锁", "Unlocked")},
    "status": {"draft": ("草稿", "Draft"), "pending": ("待处理", "Pending"), "approved": ("已通过", "Approved"), "rejected": ("已驳回", "Rejected"), "processing": ("处理中", "Processing"), "running": ("处理中", "Processing"), "done": ("已完成", "Ready"), "ready": ("已就绪", "Ready"), "failed": ("失败", "Failed"), "cancelled": ("已取消", "Cancelled"), "none": ("无需处理", "Not required"), "missing": ("尚未准备", "Not ready"), "paid": ("已支付", "Paid"), "active": ("有效", "Active"), "inactive": ("已停用", "Inactive"), "preview_failed": ("短试看生成失败", "Preview failed")},
}


def label(group: str, value: str | None) -> str:
    """固定枚举代码与可本地化标签分离，未知状态使用可读兜底。"""
    pair = LABELS.get(group, {}).get(value or "")
    return localized(*pair) if pair else localized("状态待确认", "Status unavailable")


def presentation_fields(payload: dict, kind: str | None = None) -> dict:
    """只添加显示字段，保留现有业务枚举和价格值。"""
    if kind:
        payload["content_type_label"] = label("content_type", kind)
    for field in ("sale_type", "access_mode"):
        if field in payload:
            payload[field + "_label"] = label(field, payload[field])
    for field in ("audit_status", "playback_status", "preview_status", "media_status"):
        if field in payload:
            payload[field + "_label"] = localized("待审核", "Awaiting review") if field == "audit_status" and payload[field] == "pending" else label("status", payload[field])
    return payload
