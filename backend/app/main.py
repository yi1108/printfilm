from pathlib import Path
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api import auth, billing, capabilities, creation, projects, tasks, templates, tools
from app.api import teams, team_billing, team_content, team_edit_locks
from app.api.admin import router as admin_router
from app.api.drama import router as drama_router
from app.config import get_settings
from app.database import AsyncSessionLocal, engine, init_db
from app.logging_setup import configure_logging
from app.models import Template, User
from app.openapi_docs import API_DESCRIPTION, OPENAPI_TAGS, build_openapi
from app.startup_database_retry import run_database_startup_steps
from app.services.tasks.runtime import runtime_summary, start_task_runtime, stop_task_runtime
from app.services.templates_seed import TEMPLATES

settings = get_settings()
# 业务日志 INFO；DEBUG=true 不再把根日志打成 DEBUG（避免 SQL 驱动刷屏）
configure_logging(level="INFO", sql_echo=settings.sql_echo)
logger = logging.getLogger("app.http")

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    summary="AI 视频创作平台接口",
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={"docExpansion": "none", "filter": True, "displayRequestDuration": True},
)


def chinese_openapi() -> dict:
    """为 Swagger、ReDoc 和 OpenAPI JSON 提供统一的中文元数据。"""
    return build_openapi(app)


app.openapi = chinese_openapi


@app.middleware("http")
async def media_price_context(request: Request, call_next):
    from app.services.media_models.prices import expected_price_version
    from fastapi.responses import JSONResponse
    raw = request.headers.get("X-Media-Price-Version")
    if raw is not None and (not raw.isdigit() or len(raw) > 18):
        return JSONResponse(status_code=422, content={"detail": "无效的媒体价格版本"})
    token = expected_price_version.set(int(raw) if raw is not None else None)
    try:
        return await call_next(request)
    finally:
        expected_price_version.reset(token)


from app.services.media_models import MediaValidationError


@app.exception_handler(MediaValidationError)
async def media_validation_error(_request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": [{"loc": ["body", exc.field], "msg": str(exc), "type": "media_parameter"}]})

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
# Allow LAN devices (phone/tablet) hitting Vite on private IPs
_LAN_ORIGIN_RE = (
    r"https?://("
    r"localhost|127\.0\.0\.1|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_origin_regex=_LAN_ORIGIN_RE,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # 业务可读请求日志（跳过静态资源；高频轮询默认不打）
    path = request.url.path
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if path.startswith("/static"):
        return response
    # 高频轮询：成功且较快时静默，避免淹没业务日志
    is_poll = (
        path.endswith("/generate_status")
        or (request.method == "GET" and path.startswith("/api/drama/scripts/"))
        or (request.method == "GET" and path.startswith("/api/drama/assets"))
        or (request.method == "GET" and path.startswith("/api/projects/") and path.count("/") == 3)
        or (request.method == "GET" and "/api/tools/tasks/" in path)
    )
    msg = f"{request.method} {path} → {response.status_code} ({elapsed_ms:.0f}ms)"
    if response.status_code >= 400:
        logger.warning(msg)
    elif elapsed_ms >= 3000:
        logger.warning("SLOW %s", msg)
    elif is_poll and elapsed_ms < 800:
        return response
    else:
        logger.info(msg)
    return response

static_dir = Path(__file__).resolve().parent.parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
(static_dir / "templates").mkdir(exist_ok=True)
(static_dir / "mock").mkdir(exist_ok=True)
(static_dir / "generated").mkdir(exist_ok=True)
(static_dir / "site").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(auth.router, prefix="/api")
app.include_router(capabilities.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(creation.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(drama_router, prefix="/api")
app.include_router(teams.router, prefix="/api")
app.include_router(teams.invitation_router, prefix="/api")
app.include_router(team_billing.router, prefix="/api")
app.include_router(team_content.router, prefix="/api")
app.include_router(team_content.personal_router, prefix="/api")
app.include_router(team_edit_locks.router, prefix="/api")
app.include_router(admin_router, prefix="/api")

# 下游扩展仅注册独立路由和初始化，不改变原发布、生成及存储逻辑。
from app.marketplace.bootstrap import install as install_marketplace
install_marketplace(app)


async def _load_startup_model_settings() -> None:
    async with AsyncSessionLocal() as db:
        from app.services.model_settings import load_model_settings_cache

        await load_model_settings_cache(db)


@app.on_event("startup")
async def on_startup() -> None:
    database_steps = (_load_startup_model_settings,)
    if settings.database_bootstrap_enabled:
        database_steps = (
            init_db,
            _apply_schema_patches,
            _load_startup_model_settings,
            seed_templates,
            bootstrap_admins,
            seed_agent_skills,
        )
    else:
        logger.info("Database bootstrap disabled; loading model settings from the existing database")
    await run_database_startup_steps(
        database_steps,
        dispose=engine.dispose,
    )
    try:
        from app.services import oss as oss_svc

        oss_svc.ensure_browser_cors()
    except Exception:  # noqa: BLE001
        pass
    await start_task_runtime()
    from app.marketplace.bootstrap import apply_marketplace_switch
    # 补列完成后再按系统设置建市场表并启动 Worker。关闭时不建表。
    await apply_marketplace_switch()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Release Postgres pool on uvicorn worker exit."""
    from app.database import dispose_engine

    from app.marketplace.runtime import stop_marketplace_runtime
    await stop_marketplace_runtime()
    await stop_task_runtime()
    await dispose_engine()


async def _pg_columns(conn, table: str) -> set[str]:
    """读取 information_schema 列名。"""
    result = await conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    return {row[0] for row in result.fetchall()}


async def _apply_schema_patches(engine_override: AsyncEngine | None = None) -> None:
    """Lightweight additive migrations（仅 PostgreSQL）。"""
    target_engine = engine_override if engine_override is not None else engine
    async with target_engine.begin() as conn:
        # 现有 SQLite 测试库由 create_all 建表；以下补列只适用于 PostgreSQL。
        if conn.dialect.name != "postgresql":
            return
        from app.team_schema import apply_team_schema_patches

        await apply_team_schema_patches(conn)
        from app.media_schema import apply_media_schema_patches
        await apply_media_schema_patches(conn)
        from app.payment_schema import apply_payment_schema_patches
        await apply_payment_schema_patches(conn)
        scols = await _pg_columns(conn, "shots")
        if "segment_script" not in scols:
            await conn.execute(text("ALTER TABLE shots ADD COLUMN segment_script TEXT DEFAULT ''"))
        if "last_frame_url" not in scols:
            await conn.execute(text("ALTER TABLE shots ADD COLUMN last_frame_url VARCHAR(1024)"))
        if "video_skip_reason" not in scols:
            await conn.execute(text("ALTER TABLE shots ADD COLUMN video_skip_reason VARCHAR(32)"))

        pcols = await _pg_columns(conn, "projects")
        if "pipeline_mode" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN pipeline_mode VARCHAR(32) DEFAULT 'full'"))
        if "creation_session_id" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN creation_session_id INTEGER"))
        if "target_duration_sec" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN target_duration_sec INTEGER DEFAULT 60"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_projects_creation_session_id ON projects (creation_session_id)"))
        if "output_ratio" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN output_ratio VARCHAR(16) DEFAULT ''"))
        if "voice_id" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN voice_id VARCHAR(128) DEFAULT ''"))
        if "character_bible" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN character_bible TEXT DEFAULT ''"))
        if "bgm_lock" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN bgm_lock TEXT DEFAULT ''"))
        if "subtitle_preset" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN subtitle_preset VARCHAR(32) DEFAULT ''"))
        if "style_prompt" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN style_prompt TEXT DEFAULT ''"))
        if "character_prompt" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN character_prompt TEXT DEFAULT ''"))
        if "extra_prompt" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN extra_prompt TEXT DEFAULT ''"))
        if "image_model" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN image_model VARCHAR(64) DEFAULT ''"))
        if "video_model" not in pcols:
            await conn.execute(text("ALTER TABLE projects ADD COLUMN video_model VARCHAR(64) DEFAULT ''"))

        # User billing columns
        ucols = await _pg_columns(conn, "users")
        # 早期库可能无 create_all 后缺此列（模型有、补丁曾遗漏）
        if "quota_left" not in ucols:
            await conn.execute(text("ALTER TABLE users ADD COLUMN quota_left INTEGER DEFAULT 5"))
        if "balance_fen" not in ucols:
            await conn.execute(text("ALTER TABLE users ADD COLUMN balance_fen INTEGER DEFAULT 0"))
        if "frozen_fen" not in ucols:
            await conn.execute(text("ALTER TABLE users ADD COLUMN frozen_fen INTEGER DEFAULT 0"))
        if "plan" not in ucols:
            await conn.execute(text("ALTER TABLE users ADD COLUMN plan VARCHAR(32) DEFAULT 'free'"))
        if "role" not in ucols:
            await conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user'"))
        if "avatar_url" not in ucols:
            await conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512) DEFAULT ''"))
        if "phone" not in ucols:
            await conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(32) DEFAULT ''"))
        if "billing_alert_last_milestone_fen" not in ucols:
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN billing_alert_last_milestone_fen INTEGER DEFAULT 0")
            )

        # UsageEvent.drama_project_id for drama module billing
        uecols = await _pg_columns(conn, "usage_events")
        if "drama_project_id" not in uecols:
            await conn.execute(text("ALTER TABLE usage_events ADD COLUMN drama_project_id INTEGER"))
        if "task_run_id" not in uecols:
            await conn.execute(text("ALTER TABLE usage_events ADD COLUMN task_run_id INTEGER"))
        if "domain" not in uecols:
            await conn.execute(text("ALTER TABLE usage_events ADD COLUMN domain VARCHAR(32)"))
        if "capability" not in uecols:
            await conn.execute(text("ALTER TABLE usage_events ADD COLUMN capability VARCHAR(16)"))

        # Task platform additive columns
        trcols = await _pg_columns(conn, "task_runs")
        if "queue_type" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN queue_type VARCHAR(16) NOT NULL DEFAULT 'text'"))
            await conn.execute(text("""
                UPDATE task_runs SET queue_type = CASE
                    WHEN task_type = 'project_pipeline' AND payload->>'phase' = 'assets' THEN 'image'
                    WHEN task_type = 'project_pipeline' AND payload->>'phase' IN ('videos', 'compose', 'produce') THEN 'video'
                    WHEN task_type LIKE '%video%' OR task_type IN ('v1_seedance', 'project_compose_only') THEN 'video'
                    WHEN task_type LIKE '%image%' THEN 'image'
                    ELSE 'text' END
            """))
        if "provider_name" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN provider_name VARCHAR(64)"))
        if "provider_status" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN provider_status VARCHAR(32)"))
        if "dedupe_key" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN dedupe_key VARCHAR(128)"))
        if "batch_key" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN batch_key VARCHAR(128)"))
        if "current_step_key" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN current_step_key VARCHAR(64)"))
        if "current_step_status" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN current_step_status VARCHAR(32)"))
        if "scheduled_at" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN scheduled_at TIMESTAMP"))
        if "next_action_at" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN next_action_at TIMESTAMP"))
        if "lease_token" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN lease_token VARCHAR(64)"))
        if "lease_until" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN lease_until TIMESTAMP"))
        if "billing_estimate_fen" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN billing_estimate_fen INTEGER DEFAULT 0"))
        if "billing_charged_fen" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN billing_charged_fen INTEGER DEFAULT 0"))
        if "billing_refunded_fen" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN billing_refunded_fen INTEGER DEFAULT 0"))
        if "billing_status" not in trcols:
            await conn.execute(text("ALTER TABLE task_runs ADD COLUMN billing_status VARCHAR(16) DEFAULT 'none'"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_runs_queue_due ON task_runs (queue_type, status, next_action_at, priority, id)"))

        # Drop leftover worker-era columns that block the new task platform.
        legacy_task_run_cols = (
            "execution_phase",
            "queue_name",
            "worker_task_id",
            "group_key",
            "next_poll_at",
            "lease_owner",
            "lease_expires_at",
            "attempt_count",
            "attempt_limit",
        )
        for col in legacy_task_run_cols:
            if col not in trcols:
                continue
            await conn.execute(text(f"DROP INDEX IF EXISTS ix_task_runs_{col}"))
            await conn.execute(text(f"ALTER TABLE task_runs DROP COLUMN {col}"))

        # Marketplace additive columns. The marketplace bootstrap creates new tables;
        # these columns keep existing work drafts compatible with the new sale modes.
        mcols = await _pg_columns(conn, "marketplace_works")
        if mcols:
            if "sale_type" not in mcols:
                await conn.execute(text("ALTER TABLE marketplace_works ADD COLUMN sale_type VARCHAR(24) DEFAULT 'copyright_contact'"))
            if "unlock_price_fen" not in mcols:
                await conn.execute(text("ALTER TABLE marketplace_works ADD COLUMN unlock_price_fen BIGINT DEFAULT 0"))
            if "share_bps" not in mcols:
                await conn.execute(text("ALTER TABLE marketplace_works ADD COLUMN share_bps INTEGER"))
            if "deleted_at" not in mcols:
                await conn.execute(text("ALTER TABLE marketplace_works ADD COLUMN deleted_at TIMESTAMPTZ"))

        # The marketplace tables are intentionally created from their own metadata,
        # but create_all() does not alter tables from an earlier deployment.  Keep
        # upgrades additive and idempotent so a server can be restarted against an
        # existing database without a manual migration step.  Defaults make these
        # additions safe for historical rows; newly written records still use the
        # ORM defaults and publication snapshots remain immutable.
        marketplace_columns: dict[str, dict[str, str]] = {
            "marketplace_series": {
                "sale_type": "VARCHAR(24) DEFAULT 'copyright_contact'",
                "copyright_price_fen": "BIGINT DEFAULT 0",
                "share_bps": "INTEGER",
                "free_episode_count": "INTEGER NOT NULL DEFAULT 0",
                "deleted_at": "TIMESTAMPTZ",
            },
            "marketplace_series_episodes": {
                "source": "VARCHAR(30) NOT NULL DEFAULT 'external'",
                "preview_status": "VARCHAR(24) DEFAULT 'none'",
                "preview_key": "VARCHAR(512)",
                "preview_attempts": "INTEGER DEFAULT 0",
                "playback_status": "VARCHAR(24) DEFAULT 'none'",
                "playback_manifest_key": "VARCHAR(512)",
                "playback_attempts": "INTEGER DEFAULT 0",
            },
            "marketplace_publications": {
                "preview_key": "VARCHAR(512)",
                "preview_status": "VARCHAR(24) DEFAULT 'pending'",
                "preview_attempts": "INTEGER DEFAULT 0",
                "preview_error": "TEXT DEFAULT ''",
                "playback_manifest_key": "VARCHAR(512)",
                "playback_status": "VARCHAR(24) DEFAULT 'pending'",
                "playback_attempts": "INTEGER DEFAULT 0",
                "playback_error": "TEXT DEFAULT ''",
            },
        }
        for table, additions in marketplace_columns.items():
            columns = await _pg_columns(conn, table)
            # A missing table is expected on a first boot before marketplace's
            # startup handler runs create_all(); simply let that handler create it.
            if not columns:
                continue
            for column, definition in additions.items():
                if column not in columns:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


async def bootstrap_admins() -> None:
    # Promote matching emails to admin (does not create users)
    raw = (settings.admin_bootstrap_emails or "").strip()
    if not raw:
        return
    emails = [e.strip().lower() for e in raw.split(",") if e.strip()]
    if not emails:
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email.in_(emails)))
        users = list(result.scalars().all())
        changed = False
        for user in users:
            if (user.role or "user") != "admin":
                user.role = "admin"
                changed = True
        if changed:
            await db.commit()


async def seed_agent_skills() -> None:
    """启动时把内置导演 Skill 同步进数据库。"""
    from app.services.agent.store import seed_builtin_skills

    async with AsyncSessionLocal() as db:
        await seed_builtin_skills(db)


def _publish_template_cover(cover: str, log: logging.Logger) -> str:
    """把 /static 封面发到 OSS；失败则仍返回原路径。"""
    from app.services import storage

    if not cover.startswith("/static/"):
        return cover
    local = storage.STATIC_ROOT / cover.removeprefix("/static/")
    if not local.is_file():
        log.warning("template cover missing on disk: %s", local)
        return cover
    try:
        return storage.publish_local(local, sync=True)
    except Exception:  # noqa: BLE001
        log.exception("template cover OSS publish failed: %s", local)
        return cover


async def seed_templates() -> None:
    """只插入缺失的内置模板；已有记录以管理后台为准，启动不再覆盖文案与配置。"""
    log = logging.getLogger("app.seed")
    async with AsyncSessionLocal() as db:
        for item in TEMPLATES:
            data = dict(item)
            existing = await db.get(Template, data["id"])
            cover = (data.get("preview_cover") or "").strip()
            if existing:
                # 已有模板不覆盖后台配置；仅当封面仍是本地路径时按库内路径补发 OSS
                current = (existing.preview_cover or "").strip()
                if not current.startswith(("http://", "https://")):
                    published = _publish_template_cover(current or cover, log)
                    if published.startswith(("http://", "https://")) and published != current:
                        existing.preview_cover = published
                continue
            data["preview_cover"] = _publish_template_cover(cover, log)
            db.add(Template(**data))
        await db.commit()


@app.get(
    "/api/health",
    tags=["系统状态"],
    summary="查看服务健康摘要",
    description="无需登录。返回应用名称、模型配置摘要、数据库连接池和任务运行时状态；ok 表示任务运行时是否健康。此接口不会执行数据库业务读写或模型调用，不能代替业务接口验收。",
    response_description="应用配置与任务运行时健康摘要，即使 ok 为 false 仍返回 HTTP 200。",
)
async def health() -> dict:
    from app.config import reload_settings

    s = reload_settings()
    from app.database import pool_status

    runtime = runtime_summary()
    runtime_ok = bool(runtime.get("healthy"))
    return {
        "ok": runtime_ok,
        "ark_mock": s.ark_mock,
        "db_pool": pool_status(),
        "task_runtime": runtime,
        "models": {
            "llm": s.model_llm,
            "image": s.model_image,
            "video": s.model_video,
            "audio": s.model_audio,
        },
        "quality": {
            "image_size": s.ark_image_size,
            "video_resolution": s.ark_video_resolution,
        },
        "app": s.app_name,
    }
