"""Normalize and validate self-serve account profile fields."""

from __future__ import annotations

import re

from pydantic import EmailStr, TypeAdapter, ValidationError

_EMAIL = TypeAdapter(EmailStr)
_PHONE_KEEP = re.compile(r"[^\d+]")


class ProfileError(ValueError):
    """用户可见的资料校验错误。"""


def normalize_phone(raw: str | None) -> str:
    """去掉空格/横线，+86 / 86 前缀收成 11 位国内号；空则表示未绑定。"""
    if raw is None:
        return ""
    compact = _PHONE_KEEP.sub("", raw.strip())
    if not compact:
        return ""
    if compact.startswith("+86"):
        compact = compact[3:]
    elif compact.startswith("86") and len(compact) >= 13:
        compact = compact[2:]
    return compact


def prepare_profile_update(*, nickname: str, email: str, phone: str | None) -> dict[str, str]:
    """校验并规范化用户名、邮箱、手机号（手机号只记录，不验证码）。"""
    name = (nickname or "").strip()
    if not name:
        raise ProfileError("用户名不能为空")
    if len(name) > 64:
        raise ProfileError("用户名不能超过 64 个字符")

    raw_email = (email or "").strip()
    try:
        parsed_email = str(_EMAIL.validate_python(raw_email)).lower()
    except ValidationError as exc:
        raise ProfileError("邮箱格式不正确") from exc

    raw_phone = (phone or "").strip()
    if raw_phone and re.search(r"[A-Za-z]", raw_phone):
        raise ProfileError("手机号格式不正确")
    normalized_phone = normalize_phone(raw_phone)
    if normalized_phone and (
        not normalized_phone.isdigit() or not (8 <= len(normalized_phone) <= 15)
    ):
        raise ProfileError("手机号格式不正确")

    return {"nickname": name, "email": parsed_email, "phone": normalized_phone}
