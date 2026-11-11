"""Legacy image delivery must carry the facts required by per-image price rules."""
import json

import pytest

from app.config import get_settings
from app.services.ark import ImageResult
from app.services.billing.context import billing_scope
from app.services.billing.pricing import charge_fen_for_usage
from app.services.billing.settlement import freeze_for_task, settle_task
from app.services.drama.billing_util import record_seedream_image_usage
from app.services.tokenfree_pricing import (
    charge_fen_official_image, parse_pricing_payload, set_cached_rates,
)
from tests.conftest import make_task, make_user


@pytest.fixture
def image_rate(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'billing_usd_cny', 7.0)
    monkeypatch.setattr(settings, 'billing_enabled', True)
    monkeypatch.setattr(settings, 'unified_wallet_enabled', False)
    monkeypatch.setattr(settings, 'model_image', 'gpt-image-2')
    set_cached_rates(parse_pricing_payload({'data': [{
        'model_name': 'gpt-image-2.5', 'quota_type': 0,
        'model_ratio': 37.5, 'completion_ratio': 2, 'model_price': 0,
        'billing_mode': 'tiered_expr',
        'billing_expr': 'u("resolution") == "2K" ? tier("2K", u("image_count") * 0.075) : tier("1K", u("image_count") * 0.045)',
    }]}, settings))
    yield settings
    set_cached_rates(None)


@pytest.mark.parametrize('size, expected', [('1K', 32), ('2K', 53), ('2k', 53)])
def test_image_quote_and_usage_agree_without_provider_tokens(image_rate, size, expected):
    assert charge_fen_official_image(image_rate, model='gpt-image-2.5', size=size) == expected
    raw = {'size': size, 'usage': {'image_count': 1}}
    assert charge_fen_for_usage(0, 'seedream', raw_usage=raw,
        settings=image_rate, model='gpt-image-2.5')[:2] == (expected, expected)
    # Legacy records lacking quantity must still use the same per-image fallback.
    assert charge_fen_for_usage(0, 'seedream', raw_usage={'size': size, 'usage': {}},
        settings=image_rate, model='gpt-image-2.5')[:2] == (expected, expected)


@pytest.mark.asyncio
async def test_empty_provider_usage_deducts_wallet_once(db_session, image_rate):
    user = await make_user(db_session, balance_fen=1000)
    task = await make_task(db_session, user, domain='studio', task_type='tool_image')
    task.payload = {'model_id': 'gpt-image-2.5', 'resolution': '2K'}
    task.billing_snapshot = {'mode': 'legacy'}
    await db_session.commit()
    assert await freeze_for_task(db_session, task) == 53
    async with billing_scope(task.id):
        event = await record_seedream_image_usage(db_session, user_id=user.id,
            model='gpt-image-2.5', domain='studio',
            image_result=ImageResult(local_url='/static/test-delivery.png', raw_usage={}),
            extra_raw={'tool_id': 't2i', 'size': '2K'})
    assert json.loads(event.raw_usage_json)['usage']['image_count'] == 1
    assert event.charge_fen == 53
    task.status = 'succeeded'
    await db_session.commit()
    outcome = await settle_task(db_session, task.id)
    await db_session.commit()
    await db_session.refresh(user)
    assert outcome['charged'] == 53
    assert user.balance_fen == 947
    assert user.frozen_fen == 0
    assert event.settled is True
    await settle_task(db_session, task.id)
    await db_session.commit()
    await db_session.refresh(user)
    assert user.balance_fen == 947
