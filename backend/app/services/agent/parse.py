"""解析 Cursor 风格 SKILL.md：YAML 头 + markdown 正文。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# SLUG_PATTERN 合法短名
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n([\s\S]*?)\n---\s*\n?", re.MULTILINE)
TASK_ALIASES = {
    "shot_plan": "shot_plan",
    "shot-plan": "shot_plan",
    "规划镜头": "shot_plan",
    "分镜": "shot_plan",
    "video_prompt": "video_prompt",
    "video-prompt": "video_prompt",
    "生视频": "video_prompt",
    "all": "all",
    "*": "all",
}


class SkillParseError(ValueError):
    """Skill markdown 无法解析。"""


def slugify_skill_name(raw: str) -> str:
    # 英文名收成连字符；中文名用 hash，避免都变成 untitled-skill
    text = (raw or "").strip().lower()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:64]
    if ascii_part and SLUG_PATTERN.match(ascii_part):
        return ascii_part
    digest = hashlib.sha1((raw or "").encode("utf-8")).hexdigest()[:10]
    return f"skill-{digest}"


def normalize_tasks(raw: Any) -> list[str]:
    # 任务标签归一：缺省规划镜头
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in re.split(r"[,，|/]", raw) if part.strip()]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = TASK_ALIASES.get(item.lower(), TASK_ALIASES.get(item, "shot_plan"))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out or ["shot_plan"]


def _parse_simple_yaml(block: str) -> dict[str, Any]:
    # 只解析本系统需要的标量/列表/折叠字符串，避免引入 PyYAML
    data: dict[str, Any] = {}
    folded_key: str | None = None
    folded_lines: list[str] = []
    list_key: str | None = None

    def flush_folded() -> None:
        nonlocal folded_key, folded_lines
        if folded_key:
            data[folded_key] = " ".join(part for part in folded_lines if part)
            folded_key = None
            folded_lines = []

    for raw in (block or "").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if folded_key and (raw.startswith("  ") or raw.startswith("\t")):
            folded_lines.append(line.strip())
            continue
        if list_key and re.match(r"^\s+-\s+", line):
            item = re.sub(r"^\s+-\s+", "", line).strip().strip("\"'")
            bucket = data.setdefault(list_key, [])
            if isinstance(bucket, list):
                bucket.append(item)
            continue
        flush_folded()
        list_key = None
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value in {"|", ">", ">-", "|-"}:
            folded_key = key
            folded_lines = []
            continue
        if value == "":
            list_key = key
            data[key] = []
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [part.strip().strip("\"'") for part in inner.split(",") if part.strip()]
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            data[key] = value[1:-1]
            continue
        data[key] = value
    flush_folded()
    return data


def parse_skill_markdown(markdown: str) -> dict[str, Any]:
    """把 SKILL.md 拆成 slug/name/description/tasks/body。"""
    text = (markdown or "").replace("\r\n", "\n").strip()
    if not text:
        raise SkillParseError("Skill 内容为空")
    meta: dict[str, Any] = {}
    body = text
    matched = FRONTMATTER_PATTERN.match(text)
    if matched:
        meta = _parse_simple_yaml(matched.group(1))
        body = text[matched.end() :].strip()
    name = str(meta.get("name") or "").strip()
    slug = slugify_skill_name(name or "untitled-skill")
    if not SLUG_PATTERN.match(slug):
        raise SkillParseError("Skill 名称只能用小写字母、数字和连字符")
    description = str(meta.get("description") or "").strip()
    if len(description) > 1024:
        description = description[:1024]
    if not body:
        raise SkillParseError("Skill 正文不能为空")
    return {
        "slug": slug,
        "name": name or slug,
        "description": description,
        "tasks": normalize_tasks(meta.get("tasks")),
        "body": body,
    }
