"""统一应用日志：可读业务日志，默认不刷 SQL DEBUG。"""

from __future__ import annotations

import logging
import sys

_configured = False


def configure_logging(*, level: str = "INFO", sql_echo: bool = False) -> None:
    # 配置根日志；可重复调用以刷新级别（reload 后仍可生效）
    global _configured

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)

    # 根级别用 INFO：DEBUG=true 也不刷第三方库
    root.setLevel(logging.INFO)
    logging.getLogger("app").setLevel(getattr(logging, level.upper(), logging.INFO))

    # SQLAlchemy 驱动默认关闭
    for name in (
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "sqlalchemy.dialects",
        "asyncpg",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    if sql_echo:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # 其他噪音
    for name in ("uvicorn.access", "httpx", "httpcore", "celery", "asyncio", "multipart"):
        logging.getLogger(name).setLevel(
            logging.INFO if name == "uvicorn.access" else logging.WARNING
        )
    logging.getLogger("celery").setLevel(logging.INFO)

    if not _configured:
        logging.getLogger("app").info(
            "日志已配置 app_level=%s sql_echo=%s（已关闭 SQL DEBUG）",
            level,
            sql_echo,
        )
    _configured = True
