"""统一钱包只能显式迁移，启动和读取接口均不创建财务表。"""
from sqlalchemy import inspect

from app.models_wallet import WalletBase


def register_models():
    """财务对账模型与核心来源模型一起由显式脚本管理。"""
    import app.models_wallet  # noqa: F401
    try:
        import app.models_wallet_finance  # noqa: F401
    except ModuleNotFoundError as error:
        if error.name != "app.models_wallet_finance":
            raise


def check_schema(connection):
    """只读检查新增表、列和唯一约束，不修改数据库。"""
    register_models()
    inspector = inspect(connection)
    schema = (connection.get_execution_options().get("schema_translate_map") or {}).get(None)
    missing = []
    for table in WalletBase.metadata.sorted_tables:
        if not inspector.has_table(table.name, schema=schema):
            missing.append(table.name)
            continue
        actual = {column["name"] for column in inspector.get_columns(table.name, schema=schema)}
        missing.extend(f"{table.name}.{column.name}" for column in table.columns if column.name not in actual)
        unique = {tuple(row["column_names"]) for row in inspector.get_unique_constraints(table.name, schema=schema)}
        checks = {row["name"] for row in inspector.get_check_constraints(table.name, schema=schema)}
        for constraint in table.constraints:
            if constraint.__class__.__name__ == "UniqueConstraint":
                names = tuple(column.name for column in constraint.columns)
                if names not in unique:
                    missing.append(f"{table.name}.unique({','.join(names)})")
            elif constraint.__class__.__name__ == "CheckConstraint" and constraint.name not in checks:
                missing.append(f"{table.name}.check({constraint.name})")
    return missing


def apply_schema(connection):
    """仅新增独立表，不自动创建历史来源或合并余额。"""
    register_models()
    WalletBase.metadata.create_all(connection)
    missing = check_schema(connection)
    if missing:
        raise RuntimeError("统一钱包结构未就绪：" + ", ".join(missing))
