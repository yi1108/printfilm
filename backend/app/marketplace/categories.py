"""分类使用稳定代码；旧名称只作为兼容值和历史别名。"""
import hashlib

from sqlalchemy import and_, or_

from .locale import current_locale
from .models import CategoryConfig
from .service import fail

BUILTINS = {
    "短片": ("short_film", "Short Film"), "短剧": ("short_drama", "Short Drama"),
    "广告": ("advertising", "Advertising"), "动画": ("animation", "Animation"),
    "文旅": ("culture_travel", "Culture & Travel"), "科普": ("science", "Science"), "其他": ("other", "Other"),
}
DEFAULT_CATEGORIES = ["短片", "广告", "动画", "文旅", "科普", "其他"]


def legacy_entry(name: str, enabled: bool = True) -> dict:
    """历史自定义分类确定性编号，重复迁移不新建第二个分类。"""
    code, english = BUILTINS.get(name, ("custom_" + hashlib.sha256(name.encode()).hexdigest()[:24], ""))
    return {"code": code, "name_zh": name, "name_en": english, "enabled": enabled, "aliases": [name]}


def entries(item) -> list[dict]:
    """兼容尚未保存双语配置的旧分类列表。"""
    if item and item.items:
        return [dict(entry) for entry in item.items]
    return [legacy_entry(name) for name in (item.names if item else DEFAULT_CATEGORIES)]


def display_entry(entry: dict) -> dict:
    """缺译的历史分类保留原名，并返回补齐提示。"""
    label = (entry.get("name_en") or entry["name_zh"]) if current_locale.get() == "en" else entry["name_zh"]
    return {**entry, "label": label, "translation_missing": not bool(entry.get("name_en"))}


async def category_config(db, *, include_disabled: bool = False):
    """旧 names 保留中文兼容值，items 提供固定代码及双语展示。"""
    item = await db.get(CategoryConfig, 1)
    configured = entries(item)
    return {"version": item.version if item else 0,
            "names": [entry["name_zh"] for entry in configured if entry.get("enabled", True)],
            "items": [display_entry(entry) for entry in configured if include_disabled or entry.get("enabled", True)]}


async def resolve_category(db, name: str, code: str | None = None, previous=None, previous_code=None) -> tuple[str, str]:
    """代码优先；停用分类只允许原内容继续保留，不能被新内容选择。"""
    configured = entries(await db.get(CategoryConfig, 1))
    match = next((entry for entry in configured if entry["code"] == code), None) if code else next(
        (entry for entry in configured if name in [entry["name_zh"], *entry.get("aliases", [])]), None)
    if match:
        unchanged = previous_code == match["code"] or (not previous_code and previous in [match["name_zh"], *match.get("aliases", [])])
        if not match.get("enabled", True) and not unchanged:
            fail("该作品分类未启用，请刷新后选择管理员配置的分类")
        return (previous if unchanged and previous else match["name_zh"]), match["code"]
    if not code and name == previous:
        return name, previous_code or legacy_entry(name)["code"]
    fail("该作品分类未启用，请刷新后选择管理员配置的分类")


async def validate_category(db, name, previous=None):
    """保留旧内部调用兼容；新增写入统一通过 normalize_category_input。"""
    await resolve_category(db, name, previous=previous)


async def normalize_category_input(db, body, previous=None):
    """规范化请求分类，确保所有草稿写入持久化代码。"""
    body.category, body.category_code = await resolve_category(db, body.category, body.category_code,
        getattr(previous, "category", None), getattr(previous, "category_code", None))


async def category_filter(db, model, name: str = "", code: str = ""):
    """代码筛选兼容未回填的旧行；旧名称筛选同时匹配改名前别名。"""
    configured = entries(await db.get(CategoryConfig, 1))
    match = next((entry for entry in configured if entry["code"] == code), None) if code else next(
        (entry for entry in configured if name in [entry["name_zh"], *entry.get("aliases", [])]), None)
    if match:
        return or_(model.category_code == match["code"], and_(model.category_code.is_(None), model.category.in_([match["name_zh"], *match.get("aliases", [])])))
    return model.category_code == code if code else model.category == name


async def category_fields(db, record) -> dict:
    """序列化阶段添加标签，不覆盖旧 category 或不可变发布内容。"""
    configured = entries(await db.get(CategoryConfig, 1))
    code, name = getattr(record, "category_code", None), record.category
    match = next((entry for entry in configured if entry["code"] == code), None) if code else next(
        (entry for entry in configured if name in [entry["name_zh"], *entry.get("aliases", [])]), None)
    entry = display_entry(match or legacy_entry(name, False))
    return {"category_code": entry["code"], "category_label": entry["label"],
            "category_labels": {"zh": entry["name_zh"], "en": entry["name_en"] or entry["name_zh"]}}


def merge_config(previous: list[dict], submitted: list[dict] | None, names: list[str] | None) -> list[dict]:
    """保存时保留历史别名与停用项；旧管理客户端不会删除既有英文名称。"""
    by_code = {entry["code"]: entry for entry in previous}
    result = []
    for entry in submitted if submitted is not None else [legacy_entry(name) for name in names or []]:
        old = by_code.get(entry["code"])
        if submitted is None:
            old = next((row for row in previous if entry["name_zh"] in [row["name_zh"], *row.get("aliases", [])]), None)
            if old:
                entry = {**old, "enabled": True}
        if not old and not entry.get("name_en") and submitted is not None:
            fail("新分类必须填写中文和英文名称")
        if old and old.get("name_en") and not entry.get("name_en"):
            fail("已有英文分类名称不能清空")
        aliases = list(dict.fromkeys([*(old or {}).get("aliases", []), *(([old["name_zh"]]) if old else []), entry["name_zh"]]))
        result.append({**entry, "aliases": aliases})
    present = {entry["code"] for entry in result}
    result.extend({**entry, "enabled": False} for entry in previous if entry["code"] not in present)
    owners = {}
    for entry in result:
        for name in entry["aliases"]:
            if name in owners and owners[name] != entry["code"]:
                fail("分类名称与历史分类重复，请使用其他名称")
            owners[name] = entry["code"]
    return result
