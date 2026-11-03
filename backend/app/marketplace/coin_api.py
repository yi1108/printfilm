"""App 钱包、扣币解锁和个人内容屏蔽接口。"""
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models import User, WalletLedger
from app.services.billing import wallet
from .app_models import AuthorBlock, CoinUnlock
from .coin_service import app_fail, funds_call, unlock_publication
from .dependencies import Actor, DB

router = APIRouter()


class UnlockInput(BaseModel):
    """价格由用户确认但必须与服务器冻结版本一致。"""
    model_config = ConfigDict(extra="forbid")
    publication_id: int = Field(gt=0)
    expected_coins: int = Field(gt=0, strict=True)
    idempotency_key: str = Field(min_length=8, max_length=128)


def current_environment() -> str:
    """客户端不得通过参数切换钱包环境。"""
    from .app_settings import get_app_settings
    return get_app_settings().apple_environment


def require_new_unlock() -> None:
    """暂停新业务不阻断已有充值确认、钱包查询及权益播放。"""
    from .app_settings import is_app_enabled
    from .config import is_marketplace_enabled
    if not is_app_enabled() or not is_marketplace_enabled():
        app_fail("MARKETPLACE_APP_UNAVAILABLE", "App内容服务暂未开放。", 503)


@router.get("/me/wallet", response_model=dict)
async def wallet_info(db: DB, user: Actor):
    """读取与 Web 相同的平台余额，兼容币字段只是单位别名。"""
    environment = current_environment()
    state = await funds_call(wallet.snapshot(db, user.id, environment))
    from .locale import localized
    return {**state, "balance_coins": state["balance_fen"], "frozen_coins": state["frozen_fen"],
            "debt_coins": state["debt_fen"], "spendable_coins": state["spendable_fen"],
            "coin_name": localized("平台余额", "Platform balance"), "coins_per_yuan": 100, "wallet_type": "platform_balance"}


@router.get("/me/wallet/entries", response_model=dict)
async def wallet_entries(db: DB, user: Actor, cursor: int | None = Query(None, gt=0), page_size: int = Query(20, ge=1, le=50)):
    """Web充值、Apple充值和AI消费读取同一历史，不再读取旧币流水。"""
    await funds_call(wallet.snapshot(db, user.id, current_environment()))
    query = select(WalletLedger).where(WalletLedger.user_id == user.id)
    if cursor:
        query = query.where(WalletLedger.id < cursor)
    rows = list((await db.execute(query.order_by(WalletLedger.id.desc()).limit(page_size+1))).scalars())
    return {"items": [{"id": row.id, "kind": row.kind, "coins_delta": row.delta_fen,
            "delta_fen": row.delta_fen, "balance_after": row.balance_after, "created_at": row.created_at}
            for row in rows[:page_size]], "next_cursor": rows[page_size-1].id if len(rows) > page_size else None, "has_more": len(rows) > page_size}


@router.post("/unlocks", response_model=dict)
async def unlock(body: UnlockInput, db: DB, user: Actor):
    """只有 App 播放文件已就绪的当前可售版本才允许扣币。"""
    require_new_unlock()
    from .app_media_models import AppMedia
    from .models import Publication
    from .coin_service import has_access
    environment = current_environment()
    if not await has_access(db, user.id, body.publication_id, environment):
        publication = await db.get(Publication, body.publication_id)
        if not publication:
            app_fail("MARKETPLACE_CONTENT_CHANGED", "该发布版本已不可购买，请刷新后确认。", 409)
        from .app_access import current_content
        _, _, _, visible_publication, free = await current_content(db, publication.content_type, publication.content_id, user.id)
        if free or not visible_publication or visible_publication.id != publication.id:
            app_fail("MARKETPLACE_CONTENT_CHANGED", "内容版本或收费方式已变化，请刷新后确认。", 409)
        ready = bool(publication and (await db.execute(select(AppMedia.id).where(
            AppMedia.content_type == publication.content_type, AppMedia.content_id == publication.content_id,
            AppMedia.version == publication.version, AppMedia.asset_id == publication.asset_id,
            AppMedia.variant == "full", AppMedia.status == "done"))).scalar_one_or_none())
        if not ready:
            app_fail("MARKETPLACE_EPISODE_NOT_READY", "App完整播放版本尚未就绪，请稍后重试。", 409)
    result = await unlock_publication(db, user.id, environment, body.publication_id, body.expected_coins, body.idempotency_key)
    await db.commit()
    return result


@router.get("/me/unlock-orders", response_model=dict)
async def unlock_orders(db: DB, user: Actor, cursor: int | None = Query(None, gt=0), page_size: int = Query(20, ge=1, le=50)):
    """保留撤销的购买历史，界面按有效权益决定能否播放。"""
    query = select(CoinUnlock).where(CoinUnlock.user_id == user.id, CoinUnlock.environment == current_environment())
    if cursor:
        query = query.where(CoinUnlock.id < cursor)
    rows = list((await db.execute(query.order_by(CoinUnlock.id.desc()).limit(page_size+1))).scalars())
    from .coin_service import unlock_data
    return {"items": [unlock_data(row) for row in rows[:page_size]], "next_cursor": rows[page_size-1].id if len(rows) > page_size else None, "has_more": len(rows) > page_size}


@router.get("/me/author-blocks", response_model=dict)
async def author_blocks(db: DB, user: Actor, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50)):
    """屏蔽列表不泄露作者邮箱或其他私人资料。"""
    from sqlalchemy import func
    query = select(AuthorBlock, User.nickname).join(User, User.id == AuthorBlock.author_id).where(AuthorBlock.user_id == user.id)
    rows = (await db.execute(query.order_by(AuthorBlock.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    total = (await db.execute(select(func.count()).select_from(AuthorBlock).where(AuthorBlock.user_id == user.id))).scalar_one()
    return {"items": [{"author_id": row.author_id, "author": name, "created_at": row.created_at} for row, name in rows], "meta": {"page": page, "page_size": page_size, "total": total}}


@router.put("/me/author-blocks/{author_id}", response_model=dict)
async def block_author(author_id: int, db: DB, user: Actor):
    """屏蔽只影响个人发现，不能撤回已购内容。"""
    if author_id == user.id or not await db.get(User, author_id):
        app_fail("MARKETPLACE_AUTHOR_INVALID", "作者不存在或不能屏蔽自己。")
    await db.execute(insert(AuthorBlock).values(user_id=user.id, author_id=author_id).on_conflict_do_nothing(index_elements=["user_id", "author_id"]))
    await db.commit()
    return {"blocked": True}


@router.delete("/me/author-blocks/{author_id}", response_model=dict)
async def unblock_author(author_id: int, db: DB, user: Actor):
    """取消屏蔽是幂等操作。"""
    from sqlalchemy import delete
    await db.execute(delete(AuthorBlock).where(AuthorBlock.user_id == user.id, AuthorBlock.author_id == author_id))
    await db.commit()
    return {"blocked": False}


from .schemas import ReportInput


@router.post("/reports", response_model=dict)
async def report_content(body: ReportInput, db: DB, user: Actor):
    """App举报复用原私有证据与管理员处理流程。"""
    if body.target_type not in ("work", "series_episode"):
        app_fail("MARKETPLACE_REPORT_TARGET_INVALID", "请选择作品或具体分集进行举报。")
    from .workspace import report
    return await report(body, db, user)
