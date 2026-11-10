"""市场双语增量结构与历史分类回填，不修改内容版本、签署原件或财务表。"""
import json

from sqlalchemy import inspect, text

from .categories import DEFAULT_CATEGORIES, legacy_entry

CONTENT_TABLES = ("marketplace_works", "marketplace_series", "marketplace_recruits")
ADDITIONS = {
    **{name: {"category_code": "VARCHAR(80)"} for name in CONTENT_TABLES},
    "marketplace_category_config": {"items": "JSON NOT NULL DEFAULT '[]'"},
    "marketplace_notifications": {"template_code": "VARCHAR(100) NOT NULL DEFAULT ''", "message_params": "JSON NOT NULL DEFAULT '{}'"},
    "marketplace_support": {"name_en": "VARCHAR(160) NOT NULL DEFAULT ''", "hours_en": "VARCHAR(200) NOT NULL DEFAULT ''"},
}


def ensure_locale_columns(connection) -> None:
    """给已经存在的市场表补上双语列和分类索引。缺表时跳过，不回填历史分类。"""
    inspector = inspect(connection)
    available = set(inspector.get_table_names())
    for table, definitions in ADDITIONS.items():
        if table not in available:
            continue
        columns = {row["name"] for row in inspector.get_columns(table)}
        for name, definition in definitions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        if table in CONTENT_TABLES:
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_category_code ON {table} (category_code)"))


def check_schema(connection) -> list[str]:
    """只读检查双语依赖列与分类索引。"""
    inspector = inspect(connection)
    available = set(inspector.get_table_names())
    missing = []
    for table, definitions in ADDITIONS.items():
        if table not in available:
            missing.append(table)
            continue
        columns = {row["name"] for row in inspector.get_columns(table)}
        missing.extend(f"{table}.{name}" for name in definitions if name not in columns)
        if table in CONTENT_TABLES and "category_code" in columns:
            if not any(index.get("column_names") == ["category_code"] for index in inspector.get_indexes(table)):
                missing.append(f"{table}:category_code_index")
    return missing


def category_report(connection) -> dict:
    """只报告分类与计数，不读取标题、签署内容、账户或秘密。"""
    report = {}
    available = set(inspect(connection).get_table_names())
    for table in CONTENT_TABLES:
        if table in available:
            report[table] = [dict(row) for row in connection.execute(text(f"SELECT category, count(*) AS count FROM {table} GROUP BY category ORDER BY category")).mappings()]
    return report


def apply_schema(connection) -> dict:
    """事务内执行可重复的增量DDL及分类回填，绝不改写审核与发布版本。"""
    available = set(inspect(connection).get_table_names())
    if not set(ADDITIONS).issubset(available):
        raise RuntimeError("请先初始化原数字资产市场，再执行双语迁移。")
    connection.execute(text("SELECT pg_advisory_xact_lock(18427, 73103)"))
    for table, definitions in ADDITIONS.items():
        for name, definition in definitions.items():
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {definition}"))
        if table in CONTENT_TABLES:
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_category_code ON {table} (category_code)"))
    row = connection.execute(text("SELECT names, items FROM marketplace_category_config WHERE id=1 FOR UPDATE")).mappings().first()
    names = row["names"] if row else DEFAULT_CATEGORIES
    configured = list(row["items"] or []) if row else []
    if not configured:
        configured = [legacy_entry(name) for name in names]
    aliases = {name: entry["code"] for entry in configured for name in [entry["name_zh"], *entry.get("aliases", [])]}
    report = category_report(connection)
    for rows in report.values():
        for record in rows:
            name = record["category"]
            if name not in aliases:
                entry = legacy_entry(name, False)
                configured.append(entry)
                aliases[name] = entry["code"]
    if row:
        connection.execute(text("UPDATE marketplace_category_config SET items=CAST(:items AS JSON) WHERE id=1"), {"items": json.dumps(configured, ensure_ascii=False)})
    else:
        connection.execute(text("INSERT INTO marketplace_category_config(id,version,names,items) VALUES(1,0,CAST(:names AS JSON),CAST(:items AS JSON))"),
                           {"names": json.dumps(names, ensure_ascii=False), "items": json.dumps(configured, ensure_ascii=False)})
    for table in CONTENT_TABLES:
        for name, code in aliases.items():
            connection.execute(text(f"UPDATE {table} SET category_code=:code WHERE category=:name AND category_code IS NULL"), {"code": code, "name": name})
    missing = check_schema(connection)
    if missing:
        raise RuntimeError("双语结构检查失败：" + ", ".join(missing))
    return {"categories": len(configured), "missing_english": [entry["name_zh"] for entry in configured if not entry.get("name_en")], "content": report}
