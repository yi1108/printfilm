"""Payment evidence and order-origin safety. No live payment provider is contacted."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import select, func
from app.config import get_settings
from app.models import Order, WalletLedger
from app.models_teams import Team
from app.models_wallet import WalletFundingLot
from app.marketplace.android_epay_models import AndroidEpayCheckout, EpayReceipt
from app.services import epay
from app.services.billing import android_epay as service
from app.services.billing.epay_fulfillment import fulfill
from app.api.billing import CreateOrderBody
from test_unified_wallet_core import wallet_ctx

@pytest.fixture
async def ctx(wallet_ctx, monkeypatch):
    ctx=wallet_ctx
    async with ctx.factory().bind.begin() as connection:
        for table in (Team.__table__, Order.__table__, AndroidEpayCheckout.__table__, EpayReceipt.__table__):
            await connection.run_sync(lambda sync, table=table: table.create(sync, checkfirst=True))
    cfg=get_settings()
    for key,value in dict(android_epay_enabled=True, android_epay_alipay_enabled=True,
        android_epay_wxpay_enabled=True, android_epay_package_name="com.test.domestic",
        android_epay_sha256_fingerprints=":".join(["AA"]*32),
        android_epay_return_base_url="https://www.example.com", android_epay_checkout_hosts="",
        android_epay_app_scheme="printfilm", epay_api_url="https://pay.example.com",
        epay_pid="merchant-1", epay_key="test-signing-key", wallet_environment="Production").items():
        monkeypatch.setattr(cfg,key,value)
    ctx.provider=AsyncMock(return_value={"payurl":"https://pay.example.com/cashier/test"})
    monkeypatch.setattr(epay,"create_mapi_payment",ctx.provider)
    return ctx

def body(key="android-checkout-001"):
    return CreateOrderBody(client="android",app_edition="domestic",sku_id="topup_10",
        pay_type="alipay",idempotency_key=key)

def request():
    return Request({"type":"http","headers":[(b"x-app-edition",b"domestic"),
        (b"x-app-package-name",b"com.test.domestic")]})

async def create(ctx,key="android-checkout-001"):
    return await service.create_checkout(ctx.db,ctx.user.id,body(key),request(),"127.0.0.1")

def proof(number,trade="gateway-trade-001",**changes):
    params=dict(out_trade_no=number,trade_no=trade,pid="merchant-1",type="alipay",
        money="100.00",trade_status="TRADE_SUCCESS")
    params.update(changes)
    params["sign"]=epay._sign_pairs(params,"test-signing-key")
    return params

@pytest.mark.asyncio
async def test_snapshot_source_and_retries(ctx):
    first=await create(ctx)
    assert first["payment_client"]=="android_domestic" and first["credit_fen"]==10000
    assert first["environment"]=="Production"
    assert (await create(ctx))["out_trade_no"]==first["out_trade_no"]
    assert ctx.provider.await_count==1
    assert ctx.provider.call_args.kwargs["device"]=="jump"
    with pytest.raises(HTTPException):
        changed=body();changed.sku_id="topup_49"
        await service.create_checkout(ctx.db,ctx.user.id,changed,request(),"127.0.0.1")
    await ctx.db.rollback()
    row=await ctx.db.scalar(select(AndroidEpayCheckout))
    assert row.signing_secret.startswith("enc:")
    assert "signing_secret" not in first

@pytest.mark.asyncio
async def test_order_queries_support_legacy_android_epay_snapshot(ctx):
    import httpx
    from fastapi import FastAPI
    from app.api.billing import router
    from app.database import get_db
    from app.deps import get_current_user

    result = await create(ctx)
    number = result["out_trade_no"]
    order = await ctx.db.scalar(select(Order).where(Order.out_trade_no == number))
    assert order.payment_exchange_rate == "1"
    order.payment_exchange_rate = None
    await ctx.db.commit()

    async def database():
        yield ctx.db

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: ctx.user
    path = "/api/billing/orders"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        detail = await client.get(f"{path}/{number}")
        assert detail.status_code == 200, detail.text
        listing = await client.get(path)
        assert listing.status_code == 200, listing.text
        for item in (detail.json(), listing.json()["orders"][0]):
            assert item["status"] == "pending"
            assert item["payment_client"] == "android_domestic"
            assert item["payment_currency"] == "cny"
            assert item["payment_amount_minor"] == 10000
            assert item["payment_exchange_rate"] == "1"

        assert order.payment_exchange_rate is None
        assert (await fulfill(ctx.db, proof(number))).body == b"success"
        assert order.payment_exchange_rate == "1"
        paid = await client.get(f"{path}/{number}")
        assert paid.status_code == 200, paid.text
        assert paid.json()["status"] == "paid"


@pytest.mark.asyncio
async def test_parallel_callbacks_credit_once_and_source_is_separate(ctx):
    result=await create(ctx)
    async def notify():
        async with ctx.factory() as db:
            return (await fulfill(db,proof(result["out_trade_no"]))).body
    assert await asyncio.gather(notify(),notify(),notify())==[b"success"]*3
    async with ctx.factory() as db:
        lots=list((await db.scalars(select(WalletFundingLot))).all())
        assert len(lots)==1 and lots[0].source_type=="android_epay_order"
        assert lots[0].total_units==10000 and lots[0].total_amount_fen==10000
        assert await db.scalar(select(func.count()).select_from(EpayReceipt))==1

@pytest.mark.asyncio
@pytest.mark.parametrize("changes",[
    {"pid":"wrong"}, {"type":"wxpay"},{"money":"1.00"},{"money":"1e2"},
    {"money":"NaN"},{"money":"100.001"},{"trade_no":""},{"sign":"invalid"},
])
async def test_invalid_evidence_never_credits(ctx,changes):
    result=await create(ctx)
    params=proof(result["out_trade_no"],**{k:v for k,v in changes.items() if k!="sign"})
    if "sign" in changes: params["sign"]=changes["sign"]
    assert (await fulfill(ctx.db,params)).status_code>=400
    await ctx.db.rollback()
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot))==0

@pytest.mark.asyncio
async def test_trade_reuse_rejected_across_orders_and_clients(ctx):
    first=await create(ctx)
    assert (await fulfill(ctx.db,proof(first["out_trade_no"]))).body==b"success"
    second=await create(ctx,"android-checkout-002")
    assert (await fulfill(ctx.db,proof(second["out_trade_no"]))).status_code==409
    await ctx.db.refresh(ctx.user)
    order=Order(out_trade_no="WEB-test",user_id=ctx.user.id,sku_id="topup_10",
        amount_fen=10000,credit_fen=10000,pay_type="alipay",payment_client="web",status="pending")
    ctx.db.add(order);await ctx.db.commit()
    assert (await fulfill(ctx.db,proof("WEB-test"))).status_code==409
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot))==1

@pytest.mark.asyncio
async def test_timeout_retry_never_recreates_supplier_order(ctx):
    ctx.provider.side_effect=TimeoutError()
    with pytest.raises(HTTPException) as error:
        await create(ctx)
    assert error.value.status_code==503
    second=await create(ctx)
    assert second["checkout_status"]=="uncertain" and second["checkout_url"] is None
    assert ctx.provider.await_count==1
    assert (await fulfill(ctx.db,proof(second["out_trade_no"]))).body==b"success"

@pytest.mark.asyncio
async def test_late_payment_honored_after_close_and_new_purchase_disabled(ctx,monkeypatch):
    result=await create(ctx)
    order=await ctx.db.scalar(select(Order))
    order.status="closed";await ctx.db.commit()
    monkeypatch.setattr(get_settings(),"android_epay_enabled",False)
    assert (await fulfill(ctx.db,proof(result["out_trade_no"]))).body==b"success"
    assert (await create(ctx))["status"]=="paid"

@pytest.mark.asyncio
async def test_fulfillment_failure_rolls_back_payment(ctx,monkeypatch):
    result=await create(ctx)
    from app.services import billing
    monkeypatch.setattr(billing,"credit_topup",AsyncMock(side_effect=RuntimeError("simulated")))
    with pytest.raises(RuntimeError):
        await fulfill(ctx.db,proof(result["out_trade_no"]))
    await ctx.db.rollback()
    assert (await ctx.db.scalar(select(Order))).status=="pending"
    assert await ctx.db.scalar(select(func.count()).select_from(EpayReceipt))==0

@pytest.mark.asyncio
async def test_callback_before_cashier_response(ctx):
    async def supplier(**kwargs):
        async with ctx.factory() as db:
            assert (await fulfill(db,proof(kwargs["out_trade_no"]))).body==b"success"
        return {"payurl":"https://pay.example.com/cashier/test"}
    ctx.provider.side_effect=supplier
    result=await create(ctx)
    assert result["status"]=="paid" and result["checkout_url"] is None

def test_cashier_url_rejects_unsafe_destinations():
    from app.services.billing.android_epay_config import checkout_url
    cfg=NS(epay_api_url="https://pay.example.com",android_epay_checkout_hosts="")
    for value in ("http://pay.example.com/a","https://pay.example.com.evil/a","javascript:alert(1)",
                  "https://user@pay.example.com/a","https://pay.example.com:444/a"):
        with pytest.raises(ValueError):checkout_url(value,cfg)

@pytest.mark.asyncio
async def test_concurrent_create_uses_one_supplier_intent(ctx):
    user_id=ctx.user.id
    async def start():
        async with ctx.factory() as db:
            return await service.create_checkout(db,user_id,body(),request(),"127.0.0.1")
    results=await asyncio.gather(start(),start(),start())
    assert len({r["out_trade_no"] for r in results})==1
    assert ctx.provider.await_count==1

@pytest.mark.asyncio
async def test_rotation_uses_frozen_signing_key(ctx,monkeypatch):
    result=await create(ctx)
    monkeypatch.setattr(get_settings(),"epay_key","rotated")
    monkeypatch.setattr(get_settings(),"epay_pid","new-merchant")
    assert (await fulfill(ctx.db,proof(result["out_trade_no"]))).body==b"success"

@pytest.mark.asyncio
async def test_wrong_owner_cannot_read_order(ctx):
    from fastapi import FastAPI
    import httpx
    from app.api.billing import router
    from app.database import get_db
    from app.deps import get_current_user
    result=await create(ctx)
    app=FastAPI();app.include_router(router,prefix="/api")
    async def database(): yield ctx.db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[get_current_user]=lambda:NS(id=ctx.user.id+100000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://test") as client:
        assert (await client.get("/api/billing/orders/"+result["out_trade_no"])).status_code==404

@pytest.mark.asyncio
async def test_notify_duplicate_parameters_are_rejected(monkeypatch):
    from app.api.billing import epay_notify
    from app.marketplace import app_bootstrap
    monkeypatch.setattr(app_bootstrap,"require_schema",AsyncMock())
    req=Request({"type":"http","method":"GET","query_string":b"money=100&money=1",
                 "headers":[],"path":"/api/billing/epay/notify"})
    assert (await epay_notify(req,db=None)).status_code==400

@pytest.mark.asyncio
async def test_payment_association_survives_new_purchase_shutdown(ctx,monkeypatch):
    from app.marketplace.app_sharing import android_association
    from app.marketplace.app_settings import get_app_settings
    import json
    monkeypatch.setattr(get_settings(),"android_epay_enabled",False)
    config=get_app_settings()
    monkeypatch.setattr(config,"share_android_package_name","com.test.international")
    monkeypatch.setattr(config,"share_android_sha256_fingerprints",":".join(["BB"]*32))
    response=await android_association()
    packages={entry["target"]["package_name"] for entry in json.loads(response.body)}
    assert packages=={"com.test.domestic","com.test.international"}

@pytest.mark.asyncio
async def test_order_origin_additive_migration_preserves_history(wallet_ctx):
    from sqlalchemy import text
    from app.payment_schema import apply_payment_schema_patches, assert_payment_schema_ready
    async with wallet_ctx.factory().bind.begin() as conn:
        schema = conn.sync_connection.get_execution_options()["schema_translate_map"][None]
        import re
        assert re.fullmatch(r"wallet_core_[a-f0-9]{32}", schema)
        await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        assert await conn.scalar(text("SELECT current_schema()")) == schema
        await conn.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, status VARCHAR(16), amount_fen INTEGER)"))
        await conn.execute(text("INSERT INTO orders VALUES (1, 'paid', 12345)"))
        await apply_payment_schema_patches(conn)
        await apply_payment_schema_patches(conn)
        await assert_payment_schema_ready(conn)
        assert (await conn.execute(text("SELECT status,amount_fen,payment_client FROM orders"))).one()==("paid",12345,None)

@pytest.mark.asyncio
async def test_web_payment_without_any_app_return_configuration(ctx,monkeypatch):
    cfg=get_settings()
    for field in ("android_epay_package_name","android_epay_sha256_fingerprints",
                  "android_epay_app_scheme","android_epay_return_base_url"):
        monkeypatch.setattr(cfg,field,"")
    monkeypatch.setattr(cfg,"public_base_url","https://www.example.com")
    from app.services.billing.android_epay_config import readiness
    assert readiness()["available"]
    result=await create(ctx)
    assert result["payurl"]==result["checkout_url"]
    assert ctx.provider.call_args.kwargs["return_url"].startswith("https://www.example.com/payments/return?")
    assert (await fulfill(ctx.db,proof(result["out_trade_no"]))).body==b"success"
    from app.api.android_epay import return_config
    import json
    assert json.loads((await return_config()).body)["return_mode"]=="manual"

@pytest.mark.asyncio
async def test_optional_return_settings_change_does_not_break_idempotency(ctx,monkeypatch):
    first=await create(ctx)
    monkeypatch.setattr(get_settings(),"android_epay_package_name","")
    monkeypatch.setattr(get_settings(),"android_epay_sha256_fingerprints","")
    assert (await create(ctx))["out_trade_no"]==first["out_trade_no"]
    assert ctx.provider.await_count==1

@pytest.mark.asyncio
async def test_existing_order_list_filters_origin(ctx):
    from app.marketplace.unified_admin import records
    await create(ctx)
    for index,(pay_type,client) in enumerate((("alipay",None),("apple_iap",None),("google_play",None))):
        ctx.db.add(Order(out_trade_no=f"legacy-{index}",user_id=ctx.user.id,sku_id="topup_10",
            amount_fen=10000,credit_fen=10000,pay_type=pay_type,payment_client=client,status="pending"))
    await ctx.db.commit()
    for source in ("web","android_domestic","ios","android_international"):
        result=await records(ctx.db,"recharge-orders","Production",1,20,payment_client_filter=source)
        assert result["meta"]["total"]==1
        assert result["items"][0]["payment_client"]==source

def test_scheme_without_package_or_certificate_is_valid():
    from app.services.billing.android_epay_config import validate
    result=validate({"android_epay_enabled":False,"android_epay_app_scheme":"myapp"})
    assert result["android_epay_app_scheme"]=="myapp"
    assert result["android_epay_package_name"]==""

def test_admin_flat_payment_config_uses_deployment_public_url(monkeypatch):
    from app.services.billing.android_epay_config import validate, readiness
    cfg=get_settings()
    monkeypatch.setattr(cfg,"public_base_url","https://www.example.com")
    value=dict(android_epay_enabled=True,android_epay_alipay_enabled=True,
        epay_pid="merchant",epay_key="key",epay_api_url="https://pay.example.com",
        android_epay_return_base_url="")
    # This is the admin flat dictionary: public_base_url is not an editable field.
    assert "public_base_url" not in value
    assert validate(value)["android_epay_enabled"]

def test_invalid_payment_origin_reports_payment_field(monkeypatch):
    from app.services.billing.android_epay_config import payment_return_origin, validate
    monkeypatch.setattr(get_settings(),"public_base_url","http://127.0.0.1:8000")
    with pytest.raises(ValueError,match="支付返回站点留空") as error:
        payment_return_origin({})
    assert "分享" not in str(error.value)
    assert payment_return_origin({"android_epay_return_base_url":"https://www.example.com"})=="https://www.example.com"
    with pytest.raises(ValueError,match="支付返回站点必须") as error:
        validate({"android_epay_return_base_url":"https://www.example.com/payments/return"})
    assert "分享" not in str(error.value)
