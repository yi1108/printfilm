"""Seedance i2v 图片角色：有目标画幅时用 reference_image 以便传 ratio。"""

from __future__ import annotations


# 解析 i2v 图片 role 与是否附带 ratio
def resolve_seedance_i2v_image_role(ratio: str | None) -> tuple[str, str | None]:
    target = (ratio or "").strip() or None
    if target:
        return "reference_image", target
    return "first_frame", None
