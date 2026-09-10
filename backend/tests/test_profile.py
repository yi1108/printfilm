"""账号资料：昵称 / 邮箱 / 手机号规范化。"""

from app.services.profile import normalize_phone, prepare_profile_update, ProfileError
import pytest


def test_normalize_phone_strips_and_drops_plus86():
    assert normalize_phone(" 138 0013 8000 ") == "13800138000"
    assert normalize_phone("+86-138-0013-8000") == "13800138000"
    assert normalize_phone("8613800138000") == "13800138000"
    assert normalize_phone("") == ""
    assert normalize_phone("  ") == ""
    assert normalize_phone(None) == ""


def test_prepare_profile_update_accepts_record_only_phone():
    out = prepare_profile_update(
        nickname=" 阿强 ",
        email=" Demo@Example.com ",
        phone="13800138000",
    )
    assert out["nickname"] == "阿强"
    assert out["email"] == "demo@example.com"
    assert out["phone"] == "13800138000"


def test_prepare_profile_update_allows_empty_phone():
    out = prepare_profile_update(nickname="创作者", email="a@b.com", phone="")
    assert out["phone"] == ""


def test_prepare_profile_update_rejects_bad_phone():
    with pytest.raises(ProfileError, match="手机号"):
        prepare_profile_update(nickname="创作者", email="a@b.com", phone="abc")


def test_prepare_profile_update_rejects_blank_nickname():
    with pytest.raises(ProfileError, match="用户名"):
        prepare_profile_update(nickname="  ", email="a@b.com", phone="")
