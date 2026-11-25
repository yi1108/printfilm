# -*- coding: utf-8 -*-
"""A3 安全加固回归：支付回调幂等、IDOR、令牌解析、签名常量时间比较。"""
from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import billing as billing_api
from app.api import tools as tools_api
from app.deps import _user_from_bearer
from app.models import Order, User, WalletLedger
from app.services import epay

from tests.conftest import make_user


class _FakeNotifyRequest:
    """模拟易支付回调的 POST 表单请求。"""

    def __init__(self, params: dict[str, str]) -> None:
        self.method = "POST"
        self._params = params
        self.query_params: dict[str, str] = {}

    async def form(self) -> dict[str, str]:
        return self._params


async def _make_pending_order(db: AsyncSession, user: User) -> Order:
    """构造一笔 1 元待支付订单。"""
    order = Order(
        out_trade_no=f"TEST{uuid.uuid4().hex[:16]}",
        user_id=user.id,
        sku_id="test_100",
        amount_fen=100,
        credit_fen=100,
        pay_type="alipay",
        status="pending",
    )
    db.add(order)
    await db.flush()
    return order


async def test_epay_notify_duplicate_callback_credits_once(
    db_session: AsyncSession, monkeypatch,
) -> None:
    """易支付重复回调只入账一次（行锁 + paid 幂等返回）。"""
    user = await make_user(db_session, balance_fen=0)
    order = await _make_pending_order(db_session, user)
    params = {
        "trade_status": "TRADE_SUCCESS",
        "out_trade_no": order.out_trade_no,
        "trade_no": "upstream-t-1",
        "money": "1.00",
        "sign": "x",
    }

    from app.config import get_settings
    from app.marketplace.android_epay_models import AndroidEpayCheckout, EpayReceipt
    from app.services.billing.epay_fulfillment import fulfill
    monkeypatch.setattr(get_settings(), "epay_key", "test-epay-key")
    connection = await db_session.connection()
    for table in (AndroidEpayCheckout.__table__, EpayReceipt.__table__):
        await connection.run_sync(lambda sync, table=table: table.create(sync, checkfirst=True))
    params["sign"] = epay._sign_pairs(params, "test-epay-key")
    resp1 = await fulfill(db_session, params)
    resp2 = await fulfill(db_session, params)

    assert resp1.body == b"success"
    assert resp2.body == b"success"
    topup_count = (
        await db_session.execute(
            select(func.count())
            .select_from(WalletLedger)
            .where(
                WalletLedger.user_id == user.id,
                WalletLedger.kind == "topup",
                WalletLedger.ref_id == order.out_trade_no,
            )
        )
    ).scalar_one()
    assert topup_count == 1
    await db_session.refresh(user)
    assert user.balance_fen == 100


def test_epay_notify_source_locks_order_row() -> None:
    """源码守卫：回调必须用 SELECT ... FOR UPDATE 锁订单行，防并发双入账。"""
    from app.services.billing.epay_fulfillment import fulfill
    assert "with_for_update" in inspect.getsource(fulfill)


def test_epay_verify_constant_time_signature() -> None:
    """正确签名通过、篡改签名拒绝；比较走 hmac.compare_digest。"""
    key = "unit-key"
    params = {"a": "1", "b": "2"}
    sign = epay._sign_pairs(params, key)
    fake_settings = SimpleNamespace(epay_key=key)
    forged = sign[:-1] + ("0" if sign[-1] != "0" else "1")
    with patch.object(epay, "get_settings", return_value=fake_settings):
        assert epay.verify({**params, "sign": sign}) is True
        assert epay.verify({**params, "sign": forged}) is False
        assert epay.verify({**params, "sign": ""}) is False
    assert "compare_digest" in inspect.getsource(epay.verify)


async def test_tools_get_task_404_without_local_row(db_session: AsyncSession) -> None:
    """/api/tools/tasks 本地无归属记录时不得代理查询上游。"""
    user = await make_user(db_session)
    poll = AsyncMock()
    with patch.object(tools_api, "poll_video_task", poll):
        with pytest.raises(HTTPException) as exc:
            await tools_api.get_tool_task("stranger-task", db=db_session, user=user)
    assert exc.value.status_code == 404
    poll.assert_not_called()


async def test_bearer_rejects_non_numeric_jwt_sub(db_session: AsyncSession) -> None:
    """JWT sub 非数字时返回匿名 None，不抛 ValueError。"""
    with patch("app.deps.decode_token", return_value="not-an-int"):
        assert await _user_from_bearer(db_session, "fake.jwt.token") is None
