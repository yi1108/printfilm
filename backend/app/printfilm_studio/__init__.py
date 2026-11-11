"""Printfilm Studio canvas and agent integration."""

from app.config import get_settings


def ensure_enabled() -> None:
    """Fail closed while the feature is not enabled for the deployment."""
    from fastapi import HTTPException

    if not get_settings().printfilm_studio_enabled:
        raise HTTPException(status_code=404, detail="Printfilm Studio 功能未启用")
