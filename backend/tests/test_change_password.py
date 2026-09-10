"""修改密码：bcrypt 校验与哈希。"""

from app.services.auth import hash_password, verify_password


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("old-pass-123")
    assert verify_password("old-pass-123", hashed)
    assert not verify_password("wrong", hashed)


def test_new_password_hash_differs_from_old():
    old_hash = hash_password("same-plain")
    new_hash = hash_password("same-plain")
    assert old_hash != new_hash
    assert verify_password("same-plain", new_hash)
