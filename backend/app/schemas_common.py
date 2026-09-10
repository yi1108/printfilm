"""Shared Pydantic primitives used across schema modules."""

from pydantic import BaseModel


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
