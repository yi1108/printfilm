"""维护的系统译文；不自动翻译用户内容或暴露底层异常。"""
import hashlib
import json
from pathlib import Path
import re

from .locale import current_locale, localized

CATALOG = json.loads(Path(__file__).with_name("locale_messages.json").read_text(encoding="utf-8"))


def _patterns():
    result = []
    for source, target in CATALOG.items():
        if "{0}" not in source:
            continue
        indexes, parts = [], []
        for part in re.split(r"(\{\d+\})", source):
            if re.fullmatch(r"\{\d+\}", part):
                indexes.append(int(part[1:-1])); parts.append("(.*?)")
            else:
                parts.append(re.escape(part))
        result.append((source, target, re.compile("^" + "".join(parts) + "$", re.DOTALL), indexes))
    return result


PATTERNS = _patterns()


def message_template(message):
    if message in CATALOG:
        return message, CATALOG[message], {}
    for source, target, pattern, indexes in PATTERNS:
        match = pattern.fullmatch(message)
        if match:
            return source, target, {str(index): match.group(i + 1) for i, index in enumerate(indexes)}
    return None, None, {}


def translate_message(message: str, *, safe_fallback=False) -> str:
    if current_locale.get() != "en" or not message:
        return message
    # 持久化任务错误可能带业务码前缀；展示仍由稳定业务码与模板决定。
    message = re.sub(r"^MARKETPLACE_[A-Z_]+\s*[:：]\s*", "", message)
    source, target, values = message_template(message)
    if source:
        return re.sub(r"\{(\d+)\}", lambda item: values.get(item[1], item[0]), target)
    if safe_fallback:
        return "This operation could not be completed. Refresh and try again, or contact support."
    return message


def error_message(detail, status):
    """保留旧 detail 形状，补充稳定代码供新客户端判断。"""
    raw = detail.get("message", "") if isinstance(detail, dict) else detail if isinstance(detail, str) else ""
    code = detail.get("code") if isinstance(detail, dict) else None
    match = re.match(r"^(MARKETPLACE_[A-Z_]+)\s*[:：]?\s*(.*)$", raw, re.DOTALL)
    if match:
        code, raw = code or match[1], match[2]
    source, _, params = message_template(raw)
    code = code or ("MARKETPLACE_VALIDATION_ERROR" if isinstance(detail, list) else
                    "MARKETPLACE_MESSAGE_" + hashlib.sha256(source.encode()).hexdigest()[:12].upper() if source else f"MARKETPLACE_REQUEST_{status}")
    defaults = {401: ("请登录后继续", "Please sign in to continue."), 403: ("无权执行此操作", "You do not have permission to perform this action."), 404: ("内容不存在或不可访问", "This content does not exist or is unavailable."), 409: ("内容状态已变化，请刷新后重试", "The content has changed. Refresh and try again."), 422: ("请检查填写内容", "Please check the form fields."), 503: ("服务暂不可用，请稍后重试", "This service is temporarily unavailable. Please try again later.")}
    fallback = localized(*defaults.get(status, ("暂时无法完成操作", "This operation could not be completed. Please try again.")))
    message = translate_message(raw) if raw else fallback
    if current_locale.get() == "en" and re.search(r"[\u3400-\u9fff]", message) and message == raw:
        message = fallback
    if isinstance(detail, dict):
        detail = {**detail, "message": message}
    elif isinstance(detail, list):
        detail = [{**row, "msg": translate_message(row.get("msg", "").removeprefix("Value error, "), safe_fallback=True)} for row in detail]
    elif current_locale.get() == "en":
        detail = message
    return detail, {"code": code, "message": message, "params": params}
