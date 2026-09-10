"""Seedance i2v：有目标画幅时用 reference_image + ratio。"""

from app.services.drama.seedance_i2v_role import resolve_seedance_i2v_image_role


# 有 ratio 时不得走 first_frame（禁止传 ratio，且可能吐横屏）
def test_i2v_role_with_target_ratio() -> None:
    role, sent = resolve_seedance_i2v_image_role("9:16")
    assert role == "reference_image"
    assert sent == "9:16"


# 无 ratio 时保持 first_frame 兼容
def test_i2v_role_without_ratio() -> None:
    role, sent = resolve_seedance_i2v_image_role(None)
    assert role == "first_frame"
    assert sent is None
    role2, sent2 = resolve_seedance_i2v_image_role("  ")
    assert role2 == "first_frame"
    assert sent2 is None
