from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas_api import ApiKeyCreateRequest, ApiKeyCreatedOut, ApiKeyOut
from app.services import api_keys

router = APIRouter(prefix="/user/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ApiKeyOut]:
    rows = await api_keys.list_api_keys(db, user.id)
    return [ApiKeyOut.model_validate(row) for row in rows]


@router.post("", response_model=ApiKeyCreatedOut)
async def create_key(
    body: ApiKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiKeyCreatedOut:
    row, raw = await api_keys.create_api_key(db, user, body.name)
    await db.commit()
    await db.refresh(row)
    out = ApiKeyOut.model_validate(row)
    return ApiKeyCreatedOut(**out.model_dump(), secret=raw)


@router.delete("/{key_id}")
async def revoke_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ok = await api_keys.revoke_api_key(db, user.id, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key 不存在或已撤销")
    await db.commit()
    return {"ok": True}
