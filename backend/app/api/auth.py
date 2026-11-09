from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User, WalletLedger
from app.schemas import (
    ChangePasswordRequest,
    CloseAccountRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.services import storage
from app.services.account_closure import close_account
from app.services.auth import (
    create_access_token,
    get_user_by_email,
    hash_password,
    verify_password,
)
from app.services.password_reset import (
    InvalidTokenError,
    RedisUnavailableError,
    apply_password_reset,
    request_password_reset,
)
from app.services.profile import ProfileError, prepare_profile_update

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post(
    "/register",
    response_model=TokenResponse,
    summary="注册账号",
    description="使用邮箱、密码和昵称注册账号，按系统配置初始化额度及注册赠送余额，成功后返回访问令牌。已注册邮箱返回 400。",
    response_description="注册成功的访问令牌",
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=400, detail="邮箱已注册")
    grant = int(settings.billing_signup_grant_fen or 0)
    user = User(
        email=body.email.lower(),
        nickname=body.nickname,
        hashed_password=hash_password(body.password),
        quota_left=settings.new_user_quota,
        balance_fen=grant,
        plan="free",
    )
    db.add(user)
    await db.flush()
    if grant > 0:
        db.add(
            WalletLedger(
                user_id=user.id,
                delta_fen=grant,
                balance_after=grant,
                kind="grant",
                ref_type="signup",
                ref_id=str(user.id),
                note="signup_grant",
            )
        )
    await db.commit()
    await db.refresh(user)
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="邮箱密码登录",
    description="验证邮箱和密码并签发访问令牌；邮箱或密码错误返回 401。",
    response_description="登录成功的访问令牌",
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await get_user_by_email(db, body.email.lower())
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post(
    "/close-account",
    summary="永久注销当前账号",
    description="需要登录并校验当前密码及确认词 DELETE；存在名下团队或未完成任务时返回 409。成功后立即匿名化资料并使现有令牌失效。",
    response_description="账号注销结果",
)
async def close_current_account(
    body: CloseAccountRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """仅编排当前用户的账号注销，安全检查和持久化由领域服务执行。"""
    return await close_account(
        db,
        user=user,
        password=body.password,
        confirmation=body.confirmation,
    )


@router.get(
    "/me",
    response_model=UserOut,
    summary="获取当前用户资料",
    description="需要登录，返回当前用户的账号资料、套餐、额度及余额信息。",
    response_description="当前用户资料",
)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post(
    "/change-password",
    summary="修改登录密码",
    description="需要登录并校验当前密码；新密码不能与当前密码相同，成功后返回 ok。",
    response_description="密码修改结果",
)
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """需要登录并校验当前密码；新密码不能与当前密码相同，成功后返回 ok。"""
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.post(
    "/forgot-password",
    summary="申请重置密码",
    description="向指定邮箱发送密码重置邮件。接口统一返回提示以避免泄露账号是否存在；重置服务不可用时返回 503。",
    response_description="密码重置申请结果",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """向指定邮箱发送密码重置邮件。接口统一返回提示以避免泄露账号是否存在；重置服务不可用时返回 503。"""
    try:
        return await request_password_reset(db, str(body.email))
    except RedisUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/reset-password",
    summary="通过令牌重置密码",
    description="使用邮件中的一次性令牌设置新密码；令牌无效返回 400，重置服务不可用返回 503。",
    response_description="密码重置结果",
)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """使用邮件中的一次性令牌设置新密码；令牌无效返回 400，重置服务不可用返回 503。"""
    try:
        await apply_password_reset(db, token=body.token, new_password=body.new_password)
    except RedisUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.patch(
    "/me",
    response_model=UserOut,
    summary="更新当前用户资料",
    description="需要登录，更新昵称、登录邮箱和联系手机号。手机号仅保存，不发送验证码；邮箱被占用或资料无效时返回 400。",
    response_description="更新后的用户资料",
)
async def update_me(
    body: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """需要登录，更新昵称、登录邮箱和联系手机号。手机号仅保存，不发送验证码；邮箱被占用或资料无效时返回 400。"""
    try:
        fields = prepare_profile_update(
            nickname=body.nickname,
            email=body.email,
            phone=body.phone,
        )
    except ProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if fields["email"] != user.email:
        taken = await get_user_by_email(db, fields["email"])
        if taken and taken.id != user.id:
            raise HTTPException(status_code=400, detail="该邮箱已被使用")

    user.nickname = fields["nickname"]
    user.email = fields["email"]
    user.phone = fields["phone"]
    await db.commit()
    await db.refresh(user)
    return user


@router.post(
    "/avatar",
    response_model=UserOut,
    summary="上传用户头像",
    description=(
        "需要登录，通过 multipart/form-data 上传或替换头像。"
        "支持 JPG、PNG、WebP、GIF，文件不能为空且最大 5 MB。"
    ),
    response_description="包含新头像地址的用户资料",
)
async def upload_avatar(
    file: UploadFile = File(..., description="头像文件，支持 JPG、PNG、WebP、GIF，最大 5 MB"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """需要登录，通过 multipart/form-data 上传或替换头像。支持 JPG、PNG、WebP、GIF，文件不能为空且最大 5 MB。"""
    content_type = (file.content_type or "").lower()
    allowed = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = allowed.get(content_type)
    if not ext:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            ext = ".jpg" if suffix == ".jpeg" else suffix
        else:
            raise HTTPException(status_code=400, detail="仅支持 JPG / PNG / WebP / GIF")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="头像不能超过 5MB")

    dest = storage.user_dir(user.id) / f"avatar{ext}"
    dest.write_bytes(raw)
    user.avatar_url = storage.publish_local(dest)
    await db.commit()
    await db.refresh(user)
    return user
