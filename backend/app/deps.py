from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.auth import decode_token, get_user_by_id

security = HTTPBearer(auto_error=False)


from app.database import get_db
from app.models import User
from app.services.api_keys import API_KEY_PREFIX, user_from_api_key
from app.services.auth import decode_token, get_user_by_id

security = HTTPBearer(auto_error=False)


async def _user_from_bearer(db: AsyncSession, token: str) -> User | None:
    if token.startswith(API_KEY_PREFIX):
        return await user_from_api_key(db, token)
    sub = decode_token(token)
    if not sub:
        return None
    return await get_user_by_id(db, int(sub))


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    user = await _user_from_bearer(db, creds.credentials)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    return user


async def get_api_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> User:
    """对外 API：支持 JWT 或 pf_live_ API Key（Bearer / X-Api-Key）。"""
    token = (x_api_key or "").strip()
    if not token and creds:
        token = creds.credentials
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 API Key")
    user = await _user_from_bearer(db, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key 无效或已撤销")
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    # Require role=admin for /api/admin routes
    if (user.role or "user") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user
