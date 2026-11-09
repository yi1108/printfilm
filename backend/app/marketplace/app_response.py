"""App JSON 时间契约：数据库 UTC，展示时间统一北京时间，精确到秒。"""
from datetime import datetime, timedelta, timezone
import re

from fastapi.responses import JSONResponse

BEIJING = timezone(timedelta(hours=8))
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$")


def app_times(value, key=""):
    if isinstance(value, dict):
        return {name: app_times(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [app_times(item, key) for item in value]
    # Only structured timestamp fields: never rewrite user text, cursors or tokens.
    if key.endswith("_at") and isinstance(value, str) and ISO_DATETIME.fullmatch(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    return value


class AppJSONResponse(JSONResponse):
    def render(self, content):
        return super().render(app_times(content))
