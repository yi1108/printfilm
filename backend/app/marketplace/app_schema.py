"""App 独立新增表迁移与只读检查，不修改 AI 或历史市场数据。"""
from sqlalchemy import inspect, text

from .models import MarketBase


# All App content, playback, social and financial tables share one
# transaction-scoped lock.  Keeping the lock here also protects the explicit
# migration script, so startup and manual recovery cannot race each other.
APP_SCHEMA_LOCK = (18427, 73104)


def acquire_schema_lock(connection) -> None:
    """Serialize additive App DDL on PostgreSQL; remain usable with SQLite tests."""
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {"namespace": APP_SCHEMA_LOCK[0], "key": APP_SCHEMA_LOCK[1]},
        )


def register_models():
    """显式注册全部 App 模型，避免运行时导入次序遗漏表。"""
    from . import app_models, app_media_models, apple_models, app_social_models, app_engagement_models, curation_models
    modules = {app_models.__name__, app_media_models.__name__, apple_models.__name__, app_social_models.__name__, app_engagement_models.__name__, curation_models.__name__}
    names = {mapper.local_table.name for mapper in MarketBase.registry.mappers if mapper.class_.__module__ in modules}
    return [table for table in MarketBase.metadata.sorted_tables if table.name in names]


def legacy_marketplace_tables():
    """普通市场启动只建原有业务表，App及财务表必须经过显式增量迁移。"""
    app_names = {table.name for table in register_models()}
    return [table for table in MarketBase.metadata.sorted_tables if table.name not in app_names]


def check_schema(connection) -> list[str]:
    """检查表、列和唯一性索引，成功健康检查不能代替此检查。"""
    tables = register_models()
    inspector = inspect(connection)
    available = set(inspector.get_table_names())
    missing = []
    for table in tables:
        if table.name not in available:
            missing.append(table.name)
            continue
        columns = {row["name"] for row in inspector.get_columns(table.name)}
        missing.extend(f"{table.name}.{column.name}" for column in table.columns if column.name not in columns)
        unique = {tuple(row["column_names"]) for row in inspector.get_unique_constraints(table.name)}
        indexes = {row["name"]: row for row in inspector.get_indexes(table.name)}
        from sqlalchemy import UniqueConstraint
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint) and tuple(column.name for column in constraint.columns) not in unique:
                missing.append(f"{table.name}:unique({','.join(column.name for column in constraint.columns)})")
        for index in table.indexes:
            actual = indexes.get(index.name)
            if not actual:
                missing.append(f"{table.name}:index:{index.name}")
                continue
            if bool(actual.get("unique")) != bool(index.unique) or actual.get("column_names") != [column.name for column in index.columns]:
                missing.append(f"{table.name}:index-definition:{index.name}")
            expected_where = index.dialect_options["postgresql"].get("where")
            if expected_where is not None and connection.dialect.name == "postgresql":
                # PostgreSQL会加括号和类型转换，此处只接受本模块的active=true活动权益谓词。
                actual_where = str(actual.get("dialect_options", {}).get("postgresql_where", "")).lower()
                normalized = "".join(actual_where.replace("(", "").replace(")", "").split())
                if str(expected_where) == "active = true" and normalized not in ("active=true", "activeistrue", "active"):
                    missing.append(f"{table.name}:index-predicate:{index.name}")
    return missing


def apply_schema(connection) -> None:
    """显式创建新表及共同充值订单引用列，不回填或猜测历史商品映射。"""
    acquire_schema_lock(connection)
    tables = register_models()
    available = set(inspect(connection).get_table_names())
    required = {"marketplace_assets", "marketplace_publications", "marketplace_content_orders", "marketplace_entitlements", "marketplace_revenue_ledger"}
    if not required.issubset(available):
        raise RuntimeError("请先初始化原数字资产市场表，再执行 App 增量迁移。")
    for table in tables:
        table.create(connection, checkfirst=True)
    patches = {
        "marketplace_app_content_stats": {"share_count": "BIGINT NOT NULL DEFAULT 0"},
        "marketplace_apple_products": {
            "sku_id": "VARCHAR(64) NOT NULL DEFAULT ''",
            "sku_snapshot": "JSON NOT NULL DEFAULT '{}'",
            "expected_prices": "JSON NOT NULL DEFAULT '{}'",
        },
        "marketplace_apple_transactions": {"recharge_order_id": "INTEGER",
            "payment_amount_minor": "BIGINT", "apple_price_milliunits": "BIGINT",
            "storefront": "VARCHAR(8)", "fx_snapshot": "JSON NOT NULL DEFAULT '{}'",
            "valuation_status": "VARCHAR(24) NOT NULL DEFAULT 'valued'"},
        "marketplace_apple_purchase_intents": {
            "recharge_order_id": "INTEGER",
            "fulfilled_transaction_id": "VARCHAR(100)",
        },
    }
    for table_name, definitions in patches.items():
        columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
        for column_name, definition in definitions.items():
            if column_name not in columns:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
    for table in tables:
        for index in table.indexes:
            index.create(connection, checkfirst=True)
    missing = check_schema(connection)
    if missing:
        raise RuntimeError("App结构检查未通过：" + ", ".join(missing))
