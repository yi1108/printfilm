"""双语展示不改变分类关联、金额、用户原文、发布版本或签署原件。"""
import asyncio
import hashlib
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import httpx
import pytest
from sqlalchemy import select, text

from app.marketplace.locale import current_locale, negotiate_language
from app.marketplace.locale_middleware import MarketplaceLocaleMiddleware
from app.marketplace.locale_messages import error_message
from app.marketplace.models import CategoryConfig, Notification, Support, Work
from app.marketplace.notification_locale import encode, render, review_notice
from app.marketplace.categories import category_fields, merge_config, legacy_entry
from test_marketplace import ctx, work_body, asset, rights


@pytest.mark.parametrize('header,expected', [(None,'zh'), ('fr','zh'), ('en-US','en'), ('en;q=0,zh-CN;q=0.7','zh'), ('zh;q=.2,en-US;q=.9','en'), ('en;q=oops','zh')])
def test_language_negotiation(header, expected):
    assert negotiate_language(header) == expected


async def test_concurrent_locale_and_response_contract():
    app = FastAPI()
    app.add_middleware(MarketplaceLocaleMiddleware)
    @app.get('/api/marketplace/example')
    async def example():
        before = current_locale.get()
        await asyncio.sleep(.005)
        assert current_locale.get() == before
        return {'content_type': 'work', 'sale_type': 'free', 'access_mode': 'free', 'title': '我的中文标题', 'reason': '请保留这个人工理由', 'price_fen': 158, 'publication_id': 20}
    @app.get('/api/marketplace/error')
    async def failure():
        raise HTTPException(503, {'code': 'MARKETPLACE_STORAGE_UNAVAILABLE', 'message': '文件服务暂未配置或不可用'})
    @app.get('/api/marketplace/notify')
    async def callback():
        return PlainTextResponse('success')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        zh, en = await asyncio.gather(client.get('/api/marketplace/example', headers={'Accept-Language':'zh-CN'}), client.get('/api/marketplace/example', headers={'Accept-Language':'en-US'}))
        assert zh.headers['content-language'] == 'zh-CN' and en.headers['content-language'] == 'en'
        assert 'Accept-Language' in en.headers['vary']
        assert en.json()['content_type_label'] == 'Video'
        assert en.json()['sale_type_label'] == 'Free to watch'
        for key in ('content_type','sale_type','access_mode','title','reason','price_fen','publication_id'):
            assert zh.json()[key] == en.json()[key]
        failed = await client.get('/api/marketplace/error', headers={'Accept-Language':'en'})
        assert failed.status_code == 503 and failed.json()['detail']['code'] == 'MARKETPLACE_STORAGE_UNAVAILABLE'
        assert failed.json()['detail']['message'].startswith('File services')
        assert (await client.get('/api/marketplace/notify')).text == 'success'
    assert current_locale.get() == 'zh'


async def test_category_rename_disable_and_language_stable(ctx):
    created = await ctx.client.post('/api/marketplace/works', json={**work_body(), 'category_code': 'short_film', 'category': '广告'})
    assert created.status_code == 200, created.text
    work = created.json()
    assert work['category'] == '短片' and work['category_code'] == 'short_film'
    english = await ctx.client.get(f"/api/marketplace/works/{work['id']}", headers={'Accept-Language': 'en-US'})
    assert english.json()['category_label'] == 'Short Film'
    ctx.user = ctx.admin
    current = (await ctx.client.get('/api/admin/marketplace/categories')).json()
    items = [{key: item[key] for key in ('code','name_zh','name_en','enabled')} for item in current['items']]
    entry = next(item for item in items if item['code'] == 'short_film')
    entry.update(name_zh='创意短片', name_en='Creative Film', enabled=False)
    saved = await ctx.client.put('/api/admin/marketplace/categories', json={'version': current['version'], 'items': items})
    assert saved.status_code == 200, saved.text
    ctx.user = ctx.owner
    update = await ctx.client.put(f"/api/marketplace/works/{work['id']}", json={**work_body(), 'category_code': 'short_film', 'version': work['version']})
    assert update.status_code == 200, update.text
    assert update.json()['category'] == '短片' and update.json()['category_label'] == '创意短片'
    rejected = await ctx.client.post('/api/marketplace/works', json={**work_body(), 'category_code': 'short_film'})
    assert rejected.status_code == 400
    assert next(item for item in saved.json()['items'] if item['code']=='short_film')['aliases'] == ['短片','创意短片']


async def test_filters_code_precedence_and_legacy_alias(ctx):
    video = await asset(ctx)
    await rights(ctx, video, full=True)
    work = Work(owner_id=ctx.owner.id, **{**work_body(video), 'category':'短片', 'category_code':'short_film', 'sale_type':'free'}, audit_status='approved', listed=True)
    ctx.db.add(work); await ctx.db.flush()
    ctx.user = None
    for query in ('category=短片', 'category_code=short_film', 'category=广告&category_code=short_film'):
        zh = await ctx.client.get('/api/marketplace/works?' + query)
        en = await ctx.client.get('/api/marketplace/works?' + query, headers={'Accept-Language':'en'})
        assert [item['id'] for item in zh.json()['items']] == [work.id]
        assert [item['id'] for item in en.json()['items']] == [work.id]


def test_notification_preserves_title_and_manual_reason():
    message = review_notice('作品', '不翻译《标题》', 'rejected', '请修改第三个镜头', '')
    code, params = encode(message)
    token = current_locale.set('en')
    try:
        output = render(SimpleNamespace(message=str(message), template_code=code, message_params=params))
        assert 'did not pass review' in output['message']
        assert '不翻译《标题》' in output['message'] and '请修改第三个镜头' in output['message']
        old = render(SimpleNamespace(message='旧消息不能猜测翻译', template_code='', message_params={}))
        assert old['historical'] and old['message'] == '旧消息不能猜测翻译'
        _, error = error_message('第12集版权授权已过期', 400)
        assert error['message'] == 'Rights authorization for episode 12 has expired.'
    finally:
        current_locale.reset(token)


def test_error_templates_keep_stable_codes_and_dynamic_details():
    token = current_locale.set('en')
    try:
        _, first = error_message('第1集版权授权已过期', 400)
        _, second = error_message('第12集版权授权已过期', 400)
        assert first['code'] == second['code']
        assert first['params'] == {'0': '1'} and second['params'] == {'0': '12'}
        _, changed = error_message('MARKETPLACE_SOURCE_CHANGED:源视频发生变化，请重新选择', 409)
        assert changed['code'] == 'MARKETPLACE_SOURCE_CHANGED'
        assert 'MARKETPLACE_' not in changed['message']
    finally:
        current_locale.reset(token)


async def test_support_and_authorization_reference(ctx):
    qr = await asset(ctx)
    support = Support(id=1, name='客服中文', name_en='Support', hours='工作日', hours_en='Weekdays (UTC+8)', wechat='unchanged', qr_asset_id=qr.id, enabled=True)
    ctx.db.add(support); await ctx.db.flush()
    response = await ctx.client.get('/api/marketplace/support', headers={'Accept-Language':'en'})
    assert response.json()['name'] == 'Support' and response.json()['wechat'] == 'unchanged'
    from app.marketplace.letter_template import archived_text, VERSION
    from app.marketplace.letter_reference import reading_reference
    before = hashlib.sha256(archived_text().encode()).hexdigest()
    zh = (await ctx.client.get('/api/marketplace/authorization')).json()
    en = (await ctx.client.get('/api/marketplace/authorization', headers={'Accept-Language':'en'})).json()
    assert zh['template'] == en['template']
    assert en['reading_reference']['version'] == VERSION
    assert 'Article 17' in en['reading_reference']['body']
    assert reading_reference('unknown-version') is None
    assert hashlib.sha256(archived_text().encode()).hexdigest() == before


def test_history_custom_categories_and_alias_conflicts():
    old = legacy_entry('历史自定义')
    assert not old['name_en']
    assert old['code'] == legacy_entry('历史自定义')['code']
    changed = merge_config([old], [{**old, 'name_zh':'新名称', 'name_en':'New name'}], None)
    assert changed[0]['code'] == old['code'] and '历史自定义' in changed[0]['aliases']
    with pytest.raises(HTTPException):
        merge_config(changed, [*changed, {'code':'another', 'name_zh':'历史自定义', 'name_en':'Other', 'enabled':True}], None)


async def test_existing_works_table_gains_category_code_without_rewriting_rows(ctx):
    """旧作品表缺分类编码时只补列，不改标题、版本和审核状态。"""
    from app.marketplace.locale_schema import ensure_locale_columns
    work = Work(owner_id=ctx.owner.id, title="保留历史标题", category="已移除分类", category_code="keep_me", price_fen=0, version=17, audit_status="approved")
    ctx.db.add(work)
    await ctx.db.flush()
    connection = await ctx.db.connection()
    await connection.execute(text("ALTER TABLE marketplace_works DROP COLUMN category_code"))
    await connection.run_sync(ensure_locale_columns)
    row = (await ctx.db.execute(text("SELECT category_code, version, title, audit_status FROM marketplace_works WHERE id=:id"), {"id": work.id})).mappings().one()
    assert row["category_code"] is None
    assert row["version"] == 17 and row["title"] == "保留历史标题" and row["audit_status"] == "approved"


async def test_locale_migration_is_repeatable_and_preserves_versions(ctx):
    from app.marketplace.locale_schema import apply_schema, check_schema
    config = CategoryConfig(id=1, version=8, names=['短片'], items=[])
    work = Work(owner_id=ctx.owner.id, title='保留历史标题', category='已移除分类', category_code=None, price_fen=0, version=17, audit_status='approved')
    ctx.db.add_all([config, work]); await ctx.db.flush()
    connection = await ctx.db.connection()
    first = await connection.run_sync(apply_schema)
    second = await connection.run_sync(apply_schema)
    assert first == second and not await connection.run_sync(check_schema)
    row = (await ctx.db.execute(text('SELECT category,category_code,version,title,audit_status FROM marketplace_works WHERE id=:id'), {'id':work.id})).mappings().one()
    assert row['category'] == '已移除分类' and row['category_code'].startswith('custom_')
    assert row['version'] == 17 and row['title']=='保留历史标题' and row['audit_status']=='approved'
    stored = (await ctx.db.execute(text('SELECT version,items FROM marketplace_category_config WHERE id=1'))).mappings().one()
    assert stored['version'] == 8
    historical = next(item for item in stored['items'] if item['code']==row['category_code'])
    assert not historical['enabled'] and not historical['name_en']
