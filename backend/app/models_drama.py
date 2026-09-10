"""Drama module ORM models (table prefix drama_)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DramaProject(Base):
    # One drama series owned by a PRINTFILM user
    __tablename__ = "drama_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="未命名漫剧")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assets: Mapped[list["DramaAsset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    episodes: Mapped[list["DramaEpisode"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    script: Mapped["DramaScript | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )


class DramaScript(Base):
    # Outline summary + per-episode body JSON
    __tablename__ = "drama_scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="剧本")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    episode_content: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("drama_projects.id", ondelete="CASCADE"), unique=True, index=True
    )
    episode_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped["DramaProject"] = relationship(back_populates="script")


class DramaAsset(Base):
    # Character / scene / prop / material / canvas node
    __tablename__ = "drama_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), default="none")
    asset_type: Mapped[str] = mapped_column(String(32), default="image")
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cover: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    derive_id: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("drama_projects.id", ondelete="CASCADE"), index=True
    )

    project: Mapped["DramaProject"] = relationship(back_populates="assets")
    asset_episodes: Mapped[list["DramaAssetEpisode"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    fragment_refs: Mapped[list["DramaFragmentAssetRef"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class DramaEpisode(Base):
    # One episode within a drama project
    __tablename__ = "drama_episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("drama_projects.id", ondelete="CASCADE"), index=True
    )

    project: Mapped["DramaProject"] = relationship(back_populates="episodes")
    asset_episodes: Mapped[list["DramaAssetEpisode"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    fragments: Mapped[list["DramaEpisodeFragment"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )


class DramaEpisodeFragment(Base):
    # Storyboard beat within an episode
    __tablename__ = "drama_episode_fragments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("drama_episodes.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="")
    cover: Mapped[str] = mapped_column(String(1024), default="")
    video: Mapped[str] = mapped_column(String(1024), default="")
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    episode: Mapped["DramaEpisode"] = relationship(back_populates="fragments")
    asset_references: Mapped[list["DramaFragmentAssetRef"]] = relationship(
        back_populates="fragment", cascade="all, delete-orphan"
    )


class DramaFragmentAssetRef(Base):
    # Fragment ↔ asset reference
    __tablename__ = "drama_fragment_asset_refs"
    __table_args__ = (UniqueConstraint("fragment_id", "asset_id", name="uq_drama_frag_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fragment_id: Mapped[int] = mapped_column(
        ForeignKey("drama_episode_fragments.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("drama_assets.id", ondelete="CASCADE"), index=True
    )

    fragment: Mapped["DramaEpisodeFragment"] = relationship(back_populates="asset_references")
    asset: Mapped["DramaAsset"] = relationship(back_populates="fragment_refs")


class DramaAssetEpisode(Base):
    # Asset ↔ episode many-to-many
    __tablename__ = "drama_asset_episodes"
    __table_args__ = (UniqueConstraint("asset_id", "episode_id", name="uq_drama_asset_episode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("drama_assets.id", ondelete="CASCADE"), index=True
    )
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("drama_episodes.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    asset: Mapped["DramaAsset"] = relationship(back_populates="asset_episodes")
    episode: Mapped["DramaEpisode"] = relationship(back_populates="asset_episodes")
