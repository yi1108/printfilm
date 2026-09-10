"""分镜脚本内 @duration 标签解析（与前端 episodeFragmentDuration 一致）。"""

from __future__ import annotations

import re

FRAGMENT_CONTENT_DURATION_MAX = 30
SEEDANCE_DURATION_MIN = 4

DURATION_MENTION_TOKEN_PATTERN = re.compile(r"@duration:(\d+)")


# 统计 content 中时长标签合计秒数
def sum_fragment_content_duration_seconds(content: str) -> int:
    total = 0
    for match in DURATION_MENTION_TOKEN_PATTERN.finditer(content or ""):
        seconds = int(match.group(1))
        if seconds > 0:
            total += seconds
    return total


# 将秒数格式化为 MM:SS 时间戳
def format_duration_timestamp(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# 将 @duration 标签替换为渐进时间区间
def replace_duration_mentions_with_time_ranges(content: str) -> str:
    elapsed_seconds = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal elapsed_seconds
        seconds = int(match.group(1))
        if seconds <= 0:
            return " "
        range_start = elapsed_seconds
        elapsed_seconds += seconds
        return (
            f"{format_duration_timestamp(range_start)}-{format_duration_timestamp(elapsed_seconds)}"
        )

    return DURATION_MENTION_TOKEN_PATTERN.sub(replace, content or "")


# 解析提交 Seedance 的 duration；无标签时用 fallback
def resolve_seedance_duration_from_content(content: str | None, fallback: int = 8) -> int:
    total = sum_fragment_content_duration_seconds(content or "")
    if total <= 0:
        return max(SEEDANCE_DURATION_MIN, min(int(fallback), FRAGMENT_CONTENT_DURATION_MAX))
    return max(SEEDANCE_DURATION_MIN, min(total, FRAGMENT_CONTENT_DURATION_MAX))
