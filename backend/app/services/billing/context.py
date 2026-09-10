# -*- coding: utf-8 -*-
"""任务计费上下文：当前 task_run_id。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

_current_task_run_id: ContextVar[int | None] = ContextVar("billing_task_run_id", default=None)


def get_current_task_run_id() -> int | None:
    return _current_task_run_id.get()


def set_current_task_run_id(task_run_id: int | None) -> None:
    _current_task_run_id.set(task_run_id)


@asynccontextmanager
async def billing_scope(task_run_id: int | None) -> AsyncIterator[None]:
    token = _current_task_run_id.set(task_run_id)
    try:
        yield
    finally:
        _current_task_run_id.reset(token)
