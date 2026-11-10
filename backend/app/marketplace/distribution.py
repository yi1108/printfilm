"""App 投放范围只用于内容查询，不参与语言、支付及历史权益。"""
from typing import Literal

from sqlalchemy import cast, or_
from sqlalchemy.dialects.postgresql import JSONB

AppEdition = Literal["domestic", "international"]


def edition_filter(model, edition: AppEdition | None):
    if edition is None:
        return True
    # 独立免费作品两版公开；平台投放系列的免费集继承系列范围。
    return or_(model.sale_type != "platform_unlock",
               cast(model.app_editions, JSONB).contains([edition]))


def keep_editions(body, values):
    """旧客户端更新不传字段时，不能把国际版设置覆盖回国内版。"""
    if "app_editions" not in body.model_fields_set:
        values.pop("app_editions", None)
    return values
