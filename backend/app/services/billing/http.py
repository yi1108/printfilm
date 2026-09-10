# -*- coding: utf-8 -*-
"""计费相关 HTTP 异常映射。"""
from __future__ import annotations

from fastapi import HTTPException


def http_exception_for_value_error(exc: ValueError) -> HTTPException:
    """余额不足 → 402，其余 ValueError → 400。"""
    detail = str(exc)
    status = 402 if detail.startswith("余额不足") else 400
    return HTTPException(status_code=status, detail=detail)
