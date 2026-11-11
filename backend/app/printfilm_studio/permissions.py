"""Shared project permission entry point for the new workspace."""

from app.services.drama.access import get_owned_drama_project, require_drama_project_access

__all__ = ["get_owned_drama_project", "require_drama_project_access"]
