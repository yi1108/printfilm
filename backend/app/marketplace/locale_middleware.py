"""仅市场 JSON 展示层本地化；媒体流、签名文件和支付通知原文不改写。"""
import json

from .locale import current_locale, negotiate_language, presentation_fields
from .locale_messages import translate_message, error_message


def present(value):
    if isinstance(value, list):
        return [present(item) for item in value]
    if not isinstance(value, dict):
        return value
    # 不递归改变用户填写的材料、快照及授权条款。
    result = {key: (item if key in {"details", "snapshot", "rights_snapshot", "template", "message_params"} else present(item)) for key, item in value.items()}
    kind = result.get("content_type") or result.get("kind") or result.get("target_type")
    presentation_fields(result, kind if kind in {"work", "series", "series_episode", "recruit"} else None)
    for key in ("error", "preview_error", "playback_error", "unavailable_reason", "restricted_reason"):
        if isinstance(result.get(key), str) and result[key]:
            result[key] = translate_message(result[key], safe_fallback=True)
    return result


class MarketplaceLocaleMiddleware:
    """ContextVar 在每个请求结束时复位，不共享全局语言状态。"""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"].startswith(("/api/marketplace/", "/api/admin/marketplace/", "/api/billing/apple/")) or scope["path"] in {"/api/billing/wallet", "/api/billing/skus", "/api/billing/orders"}):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        locale = "zh" if scope["path"].startswith("/api/admin/") else negotiate_language(headers.get(b"accept-language", b"").decode("latin1"))
        token = current_locale.set(locale)
        start, chunks, transform = None, [], False

        async def localized_send(message):
            nonlocal start, transform
            if message["type"] == "http.response.start":
                start = {**message, "headers": list(message.get("headers", []))}
                content_type = next((v for k, v in start["headers"] if k.lower() == b"content-type"), b"")
                transform = content_type.startswith(b"application/json")
                if transform:
                    vary = next((v.decode("latin1") for k, v in start["headers"] if k.lower() == b"vary"), "")
                    names = [name.strip() for name in vary.split(",") if name.strip()]
                    if not any(name.lower() == "accept-language" for name in names):
                        names.append("Accept-Language")
                    start["headers"] = [(k, v) for k, v in start["headers"] if k.lower() not in {b"content-language", b"vary", b"content-length"}]
                    start["headers"] += [(b"content-language", b"en" if locale == "en" else b"zh-CN"), (b"vary", ", ".join(names).encode("latin1"))]
                    return
                await send(start)
            elif message["type"] == "http.response.body" and transform:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                raw = b"".join(chunks)
                payload = json.loads(raw)
                if start["status"] >= 400 and isinstance(payload, dict) and "detail" in payload:
                    payload["detail"], payload["error"] = error_message(payload["detail"], start["status"])
                else:
                    payload = present(payload)
                raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
                start["headers"].append((b"content-length", str(len(raw)).encode()))
                await send(start)
                await send({"type": "http.response.body", "body": raw})
            else:
                await send(message)
        try:
            await self.app(scope, receive, localized_send)
        finally:
            current_locale.reset(token)


def install_locale(app):
    """完整市场或独立 App 挂载均只安装一次。"""
    if not getattr(app.state, "marketplace_locale_installed", False):
        app.add_middleware(MarketplaceLocaleMiddleware)
        app.state.marketplace_locale_installed = True
