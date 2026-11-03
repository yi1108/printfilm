"""播放URL承载访问凭证，普通访问日志只记录脱敏后的路径。"""
import logging
import re

_PLAYBACK = re.compile(r"(/api/marketplace/app/v1/playback-sessions/)[^/?\s]+")


def safe_request_path(value: str) -> str:
    """隐藏会话令牌及所有查询参数，不影响实际HTTP请求。"""
    return _PLAYBACK.sub(r"\1[redacted]", value.split("?", 1)[0])


class PlaybackAccessFilter(logging.Filter):
    """Uvicorn在格式化前传入五元组，替换其中的URL字段。"""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and "/api/marketplace/app/v1/playback-sessions/" in args[2]:
                args[2] = safe_request_path(args[2])
                record.args = tuple(args)
        return True


def install_access_filter() -> None:
    """重复应用装载不叠加过滤器；无需修改原日志配置。"""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, PlaybackAccessFilter) for item in access.filters):
        access.addFilter(PlaybackAccessFilter())
