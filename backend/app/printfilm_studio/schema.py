"""Additive PostgreSQL schema for deployments with bootstrap disabled."""

from sqlalchemy import text


async def apply_printfilm_studio_schema_patches(conn) -> None:
    """Create Printfilm Studio tables without touching legacy canvas data."""
    # 允许部署脚本独立调用：注册 ORM 外键目标，避免 WorkflowRun 建表时无法推导字段类型。
    import app.models  # noqa: F401
    import app.models_drama  # noqa: F401
    import app.models_teams  # noqa: F401

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS printfilm_studio_canvas_documents (
            id VARCHAR(36) PRIMARY KEY,
            project_id BIGINT NOT NULL UNIQUE REFERENCES drama_projects(id) ON DELETE CASCADE,
            team_id BIGINT REFERENCES teams(id),
            document JSONB NOT NULL DEFAULT '{}'::jsonb,
            document_version INTEGER NOT NULL DEFAULT 1,
            created_by BIGINT NOT NULL REFERENCES users(id),
            updated_by BIGINT NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS printfilm_studio_agent_sessions (
            id VARCHAR(36) PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES drama_projects(id) ON DELETE CASCADE,
            team_id BIGINT REFERENCES teams(id),
            user_id BIGINT NOT NULL REFERENCES users(id),
            title VARCHAR(200) NOT NULL DEFAULT 'Printfilm Studio 会话',
            model_id VARCHAR(128),
            status VARCHAR(32) NOT NULL DEFAULT 'idle',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS printfilm_studio_agent_messages (
            id VARCHAR(36) PRIMARY KEY,
            session_id VARCHAR(36) NOT NULL REFERENCES printfilm_studio_agent_sessions(id) ON DELETE CASCADE,
            role VARCHAR(32) NOT NULL,
            content JSONB NOT NULL,
            sequence INTEGER NOT NULL,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_printfilm_studio_canvas_team_id ON printfilm_studio_canvas_documents(team_id)",
        "CREATE INDEX IF NOT EXISTS ix_printfilm_studio_canvas_updated_at ON printfilm_studio_canvas_documents(updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_printfilm_studio_agent_sessions_project_id ON printfilm_studio_agent_sessions(project_id)",
        "CREATE INDEX IF NOT EXISTS ix_printfilm_studio_agent_sessions_team_id ON printfilm_studio_agent_sessions(team_id)",
        "CREATE INDEX IF NOT EXISTS ix_printfilm_studio_agent_messages_session_id ON printfilm_studio_agent_messages(session_id)",
    ):
        await conn.execute(text(statement))
    # Additive tables only: existing sessions and legacy canvas data are untouched.
    from app.models_printfilm_studio import PrintfilmStudioAgentRun, PrintfilmStudioAgentEvent, PrintfilmStudioRecipe, PrintfilmStudioWorkflowRun
    for model in (PrintfilmStudioAgentRun, PrintfilmStudioAgentEvent, PrintfilmStudioRecipe, PrintfilmStudioWorkflowRun):
        await conn.run_sync(lambda sync_conn, table=model.__table__: table.create(sync_conn, checkfirst=True))
    from app.printfilm_studio.sharing import CanvasMember, CanvasInvitation
    for model in (CanvasMember, CanvasInvitation):
        await conn.run_sync(lambda sync_conn, table=model.__table__: table.create(sync_conn, checkfirst=True))
